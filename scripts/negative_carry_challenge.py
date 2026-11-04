"""Build only authored Git histories and execute actual sequential research policies."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
import subprocess
import time

from cami.artifacts import digest
from cami.index import IndexConfig, build_index, compare_indexes, signature
from cami.models import Anchor, Claim, Equals, MemoryState, PolicyConfig, Provenance, RepoLocation, Selection, Subject
from cami.policies import SelectionContext, advance_state, select_claims
from cami.repository import MAX_FILE_BYTES, read_snapshot
from cami.validation import ValidationContext, validate_claim
from scripts.real_structural_replay_support import load_reference, reference_claim
from blob_negative_carry import select_blob_negative_carry
from negative_carry import select_negative_carry
from negative_carry_witness import SCOPE, bind_context, mint_witness

VARIANTS = ("production", "signature_witness", "module_blob_witness")


def git(repo, *args):
    return subprocess.check_output(["git", "--no-replace-objects", "--no-optional-locks", "-C", str(repo), *args],
                                   stderr=subprocess.DEVNULL, timeout=60)


@dataclass(frozen=True)
class History:
    id: str
    parent: object
    parent_index: object
    initial_claim: Claim
    provenance: Provenance
    context: object
    parent_result: object
    frames: tuple[dict, ...]
    root: Path
    output: Path


def prepare_histories(plan, output, root, setup_costs=None):
    import ast
    reference = load_reference(root / "scripts/structural_checker_v2.py")
    histories = []
    for case in plan["histories"]:
        repo = output / "git-fixtures" / case["id"]
        repo.mkdir(parents=True)
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "Authored negative carry fixture")
        git(repo, "config", "user.email", "fixture@example.invalid")
        path = repo / "pkg/f.py"
        path.parent.mkdir()
        path.write_text(case["initial_source"])
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "authored initial mismatch")
        repo_location = RepoLocation(repo_id=case["id"], path=str(repo))
        config = IndexConfig()
        limit = case.get("max_file_bytes", MAX_FILE_BYTES)
        parent = read_snapshot(repo_location, git(repo, "rev-parse", "HEAD").decode().strip(), max_file_bytes=limit)
        cache = {}
        parent_index = build_index(parent, config, cache)
        context_start, context_cpu = time.perf_counter_ns(), time.process_time_ns()
        context = bind_context(repo_location, config, run_binding=digest(plan), max_file_bytes=limit)
        if setup_costs is not None:
            setup_costs.append({"history": case["id"], "phase": "candidate_only_context_binding",
                               "wall_ns": time.perf_counter_ns() - context_start,
                               "cpu_ns": time.process_time_ns() - context_cpu})
        claim = Claim(claim_id=case["id"], repo_id=case["id"], origin_commit=parent.revision,
            kind="signature_equals", text="Exact authored normalized function signature.", scope=SCOPE,
            subject=Subject(path="pkg/f.py", qualname="f", node_kind="function"),
            predicate=Equals(type="signature_equals", expected_signature=signature(ast.parse("def f(x=1): pass").body[0])))
        provenance = Provenance(claim_id=claim.claim_id, scenario_id="authored_challenge",
            known_incomplete=case.get("known_incomplete", False), anchors=(Anchor(scope="symbol", path="pkg/f.py", qualname="f",
                observed_commit=parent.revision, content_hash=parent.by_path()["pkg/f.py"].content_hash, origin="static"),))
        parent_result = validate_claim(claim, ValidationContext(parent, parent_index, provenance, root, output))
        if (parent_result.verdict, parent_result.reason) != ("contradicted", "predicate_mismatch"):
            raise ValueError("authored case must begin with actual signature mismatch")
        before, old_index, current_claim, current_context = parent, parent_index, claim, context
        frames = []
        for number, operation in enumerate(case["steps"]):
            kind = operation["operation"]
            if kind == "source":
                if path.is_symlink():
                    path.unlink()
                path.parent.mkdir(exist_ok=True)
                path.write_text(operation["source"])
            elif kind == "other_file":
                (repo / "other.txt").write_text(str(number))
            elif kind == "symlink_same_blob":
                content = path.read_text()
                path.unlink()
                path.symlink_to(content)
            elif kind == "delete":
                path.unlink()
            elif kind == "ancestor_symlink":
                path.parent.rmdir()
                path.parent.symlink_to("elsewhere")
            elif kind == "executable":
                path.chmod(0o755)
            elif kind != "noop":
                raise ValueError("unrecognized authored operation")
            if "expected_source" in operation:
                current_claim = current_claim.model_copy(update={"predicate": Equals(type="signature_equals",
                    expected_signature=signature(ast.parse(operation["expected_source"]).body[0]))})
            if "scope" in operation:
                current_claim = current_claim.model_copy(update={"scope": operation["scope"]})
            if "context" in operation:
                update = dict(operation["context"])
                if "source_roots" in update:
                    update["source_roots"] = tuple(update["source_roots"])
                current_context = replace(current_context, **update)
            config = IndexConfig(current_context.source_roots, current_context.build_graph)
            git(repo, "add", "-A")
            git(repo, "commit", "--allow-empty", "-qm", "authored challenge transition")
            snapshot = read_snapshot(repo_location, git(repo, "rev-parse", "HEAD").decode().strip(),
                                     max_file_bytes=current_context.max_file_bytes)
            index = build_index(snapshot, config, cache)
            fresh_index = build_index(snapshot, config)
            if index != fresh_index:
                raise ValueError("warm/fresh authored index mismatch")
            changes = compare_indexes(old_index, index, before, snapshot)
            fresh = validate_claim(current_claim, ValidationContext(snapshot, index, provenance, root, output))
            ref = reference_claim(repo, snapshot.revision, current_claim,
                output / "reference-packets" / case["id"] / str(number), reference)
            if fresh.verdict != operation["expected_production"] or ref["verdict"] != operation["expected_reference"]:
                raise ValueError(f"authored expected result mismatch in {case['id']} step {number}: {fresh.verdict}, {ref['verdict']}")
            frames.append({"before": before, "after": snapshot, "old_index": old_index, "new_index": index,
                           "changes": changes, "claim": current_claim, "context": current_context,
                           "fresh": fresh, "reference": ref, "operation": operation, "step": number})
            before, old_index = snapshot, index
        histories.append(History(case["id"], parent, parent_index, claim, provenance, context, parent_result,
                                 tuple(frames), root, output))
    return tuple(histories)


def run_history(history, variant, *, capture=False):
    initial = history.parent_result
    previous = MemoryState(claim_id=history.initial_claim.claim_id, revision=history.parent.revision,
        state="stale", available=False, basis="validated", last_checked_commit=initial.commit,
        last_supported_commit=None, last_verdict=initial.verdict, current_provenance=history.provenance,
        withheld_reason=initial.reason)
    counts = {"actual_validation_calls": 0, "original_selected": 0, "effective_selected": 0,
              "eligibility_attempts": 0, "suppressed": 0, "witness_mint_attempts": 0}
    witness = None
    if variant != "production":
        counts["witness_mint_attempts"] += 1
        witness = mint_witness(history.initial_claim, history.provenance, initial, history.parent,
                               history.parent_index, history.context)
    rows = []
    for frame in history.frames:
        claim, context = frame["claim"], frame["context"]
        policy = PolicyConfig(id=frame["operation"].get("policy", "symbol_validate"))
        original, = select_claims(SelectionContext(frame["after"].revision, (claim,), (history.provenance,),
            (previous,), frame["changes"], protocol_version="1.1"), policy)
        effective, audit = original, None
        if variant != "production" and policy.id == "symbol_validate":
            counts["eligibility_attempts"] += 1
            arguments = (claim, history.provenance, previous, original, frame["before"], frame["after"])
            if variant == "signature_witness":
                audit = select_negative_carry(*arguments, frame["old_index"], frame["new_index"], witness=witness, context=context)
            elif variant == "module_blob_witness":
                audit = select_blob_negative_carry(*arguments, witness=witness, context=context)
            else:
                raise ValueError("unknown research variant")
            effective = audit.effective
            counts["suppressed"] += audit.suppressed
        counts["original_selected"] += original.selected
        counts["effective_selected"] += effective.selected
        prior_witness = witness
        result = None
        if effective.selected and policy.id.endswith("_validate"):
            result = validate_claim(claim, ValidationContext(frame["after"], frame["new_index"],
                                    history.provenance, history.root, history.output))
            counts["actual_validation_calls"] += 1
            if variant != "production":
                counts["witness_mint_attempts"] += 1
                witness = mint_witness(claim, history.provenance, result, frame["after"], frame["new_index"], context)
        state = advance_state(previous, effective, policy, result, True)
        if capture:
            fresh = frame["fresh"]
            fresh_selection = Selection(claim_id=claim.claim_id, commit=frame["after"].revision, selected=True, reasons=("full_comparison",))
            fresh_state = advance_state(previous, fresh_selection, PolicyConfig(id="symbol_validate"), fresh, True)
            fields = ("state", "available", "last_verdict", "withheld_reason")
            if policy.id != "keep_all" and any(getattr(state, field) != getattr(fresh_state, field) for field in fields):
                raise ValueError(f"fresh-production endpoint mismatch: {history.id} {variant} {frame['step']}")
            if audit and audit.suppressed and (fresh.verdict, fresh.reason) != ("contradicted", "predicate_mismatch"):
                raise ValueError("suppressed step failed exact negative-result preservation")
            rows.append({"history": history.id, "variant": variant, "step": frame["step"], "policy": policy.id,
                         "claim_hash": digest(claim), "claim": claim.model_dump(mode="json"),
                         "provenance": history.provenance.model_dump(mode="json", by_alias=True),
                         "context": asdict(context), "prior_witness": witness_record(prior_witness),
                         "current_witness": witness_record(witness),
                         "original_selection": original.model_dump(mode="json"), "effective_selection": effective.model_dump(mode="json"),
                         "suppressed": audit.suppressed if audit else False, "audit_reason": audit.reason if audit else None,
                         "previous_state": previous.model_dump(mode="json"), "state": state.model_dump(mode="json"),
                         "validation": result.model_dump(mode="json") if result else None,
                         "fresh": fresh.model_dump(mode="json"), "reference": frame["reference"]})
        previous = state
    endpoint = (previous.state, previous.available, previous.last_verdict, previous.withheld_reason, previous.last_checked_commit)
    return {"endpoint": endpoint, "counts": counts, "rows": rows}


def witness_record(witness):
    if witness is None:
        return None
    return {**asdict(witness), "signature": witness.signature.model_dump(mode="json")}
