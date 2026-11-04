"""Sealed inputs, independent exact-path Git reference, and replay accounting."""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import re
import subprocess

from cami.artifacts import canonical, digest, file_hash, read_json, read_jsonl, within, write_bytes, write_json
from cami.models import Claim, Provenance

VARIANTS = {"symbol_anchor": "symbol_validate", "file_anchor": "file_validate",
            "known_incomplete": "symbol_validate", "all_validate": "all_validate"}


def sealed_inputs(protocol_path: Path):
    protocol = read_json(protocol_path)
    if (protocol.get("schema_version") != 1 or protocol.get("status") != "sealed"
            or protocol.get("production_protocol_version") != "1.1"
            or protocol.get("split") != "development"):
        raise ValueError("requires sealed development protocol schema 1 / production 1.1")
    root = (protocol_path.parent / protocol["root"]).resolve(strict=True)
    seal = read_json(within(root, protocol["seal_path"]))
    if seal.get("protocol_sha256") != file_hash(protocol_path):
        raise ValueError("protocol seal mismatch")
    inventory = seal["files"]
    for name, expected in inventory.items():
        if file_hash(within(root, name)) != expected:
            raise ValueError(f"sealed file mismatch: {name}")

    def require(name):
        path = within(root, name)
        relative = str(path.relative_to(root))
        if relative not in inventory:
            raise ValueError(f"unsealed input: {relative}")
        return path

    for path in (root / "src/cami").rglob("*.py"):
        require(str(path.relative_to(root)))
    require("scripts/verify_cami.py")
    for name in protocol["implementation_paths"]:
        require(name)
    for path in (Path(__file__).resolve(),):
        require(str(path.relative_to(root)))
    reference_path = require(protocol["reference_path"])
    cohort_rows = read_json(require(protocol["cohort_path"]))
    cohort = {row["claim"]["claim_id"]: row for row in cohort_rows}
    if len(cohort) != len(cohort_rows):
        raise ValueError("duplicate cohort claim")
    case_map = read_json(require(protocol["ai_case_map_path"]))
    public_cases = read_json(require(protocol["ai_public_cases_path"]))
    if len({case["id"] for case in public_cases}) != len(public_cases):
        raise ValueError("duplicate public AI case ID")
    public_by_id = {case["id"]: case for case in public_cases}
    authentic = {}
    for claim_id, row in cohort.items():
        if row.get("split") != "development":
            raise ValueError("cohort claim must be explicitly development split")
        matches = [case for case in case_map if case.get("origin_class") == "authentic_parent_claim"
                   and case.get("original_candidate_id") == claim_id]
        if len(matches) != 1:
            raise ValueError("requires one authentic AI case mapping per original claim")
        mapped = matches[0]
        if mapped.get("original_claim_sha256") != row["claim_sha256"] or mapped.get("original_claim") != row["claim"]:
            raise ValueError("authentic AI case original claim identity mismatch")
        case = public_by_id.get(mapped["id"])
        if case is None or any(case.get(field) != row["claim"][field]
                               for field in ("kind", "subject", "predicate", "text", "scope")):
            raise ValueError("authentic public AI case does not match exact original claim")
        if case.get("source_sha256") != row["parent_source_sha256"]:
            raise ValueError("authentic public AI case source mismatch")
        authentic[claim_id] = case["id"]
    confirmations = read_jsonl(require(protocol["confirmations_path"]))
    by_confirmation = {}
    for row in confirmations:
        claim_id = row["claim_id"]
        if claim_id in by_confirmation or claim_id not in cohort:
            raise ValueError("duplicate or unknown AI confirmation")
        if row["claim_sha256"] != cohort[claim_id]["claim_sha256"]:
            raise ValueError("AI confirmation original claim hash mismatch")
        if row.get("reviewer_kind") != "ai_reviewer":
            raise ValueError("AI confirmation must preserve reviewer kind")
        agents, eligible_reviews = set(), []
        for review in row["reviews"]:
            if review["item_id"] != authentic[claim_id]:
                raise ValueError("AI confirmation item does not match authentic original claim case")
            path = require(review["review_path"])
            if file_hash(path) != review["review_sha256"]:
                raise ValueError("AI review hash mismatch")
            raw = read_json(path)
            if raw.get("human") is not False or raw.get("reviewer_kind") != "ai_reviewer":
                raise ValueError("raw AI review identity mismatch")
            agent = raw.get("agent_task")
            if not isinstance(agent, str) or not agent or agent in agents:
                raise ValueError("AI reviews require distinct declared agent_task identities")
            agents.add(agent)
            matches = [item for item in raw["items"] if item.get("id") == review["item_id"]]
            if len(matches) != 1:
                raise ValueError("AI review item ID must occur exactly once")
            item = matches[0]
            if item["source_sha256"] != cohort[claim_id]["parent_source_sha256"]:
                raise ValueError("AI review source hash mismatch")
            eligible_reviews.append(item["verdict"] == "supported")
        by_confirmation[claim_id] = {**row, "eligible": len(agents) >= 2 and all(eligible_reviews)}
    provenance = {}
    if set(protocol["provenance"]) != set(VARIANTS):
        raise ValueError("requires exactly the four frozen provenance variants")
    for variant, path in protocol["provenance"].items():
        rows = tuple(Provenance.model_validate_json(canonical(row)) for row in read_jsonl(require(path)))
        if len(rows) != len(cohort) or {row.claim_id for row in rows} != set(cohort):
            raise ValueError("provenance must cover the entire fixed cohort exactly")
        if any(row.dependencies for row in rows):
            raise ValueError("this bounded syntactic replay requires dependency-free provenance")
        provenance[variant] = {row.claim_id: row for row in rows}
    groups, seen, group_ids = [], set(), set()
    for group in protocol["groups"]:
        if group["group_id"] in group_ids:
            raise ValueError("duplicate group")
        group_ids.add(group["group_id"])
        claims = tuple(Claim.model_validate_json(canonical(row)) for row in read_jsonl(require(group["claims_path"])))
        ids = [claim.claim_id for claim in claims]
        if len(ids) != len(set(ids)) or seen.intersection(ids):
            raise ValueError("duplicate replay claim")
        seen.update(ids)
        revisions = [group["parent_commit"], *group["child_commits"]]
        if not group["child_commits"] or len(revisions) != len(set(revisions)) or any(
                re.fullmatch(r"[0-9a-f]{40}", revision) is None for revision in revisions):
            raise ValueError("requires distinct exact frozen Git commit IDs")
        for claim in claims:
            row = cohort[claim.claim_id]
            if (row["group_id"] != group["group_id"] or digest(claim) != row["claim_sha256"]
                    or claim.model_dump(mode="json", by_alias=True) != row["claim"]
                    or claim.origin_commit != group["parent_commit"] or claim.repo_id != group["repo_id"]
                    or claim.kind not in {"symbol_exists", "signature_equals"}):
                raise ValueError("fixed original claim identity mismatch")
        for variant in VARIANTS:
            for claim in claims:
                prov = provenance[variant][claim.claim_id]
                scope = "file" if variant == "file_anchor" else "symbol"
                row = cohort[claim.claim_id]
                expected_hash = row["parent_source_sha256"] if scope == "file" else row["symbol_ast_sha256"]
                expected_qualname = None if scope == "file" else claim.subject.qualname
                if (prov.known_incomplete != (variant == "known_incomplete") or len(prov.anchors) != 1
                        or (variant != "known_incomplete" and prov.unresolved_reasons)
                        or any(anchor.observed_commit != group["parent_commit"] or anchor.scope != scope
                               or anchor.path != claim.subject.path or anchor.qualname != expected_qualname
                               or anchor.content_hash != expected_hash for anchor in prov.anchors)):
                    raise ValueError("variant provenance anchor or completeness assumption mismatch")
        groups.append((group, claims))
    if seen != set(cohort):
        raise ValueError("group claims must cover exactly the fixed cohort")
    if len(cohort) != protocol["candidate_claims"] or sum(
            len(claims) * len(group["child_commits"]) for group, claims in groups
    ) != protocol["candidate_claim_child_observations_per_variant"]:
        raise ValueError("frozen candidate denominators mismatch")
    return protocol, root, seal, groups, cohort, by_confirmation, provenance, reference_path


def load_reference(path):
    spec = importlib.util.spec_from_file_location("sealed_replay_reference", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reference_git(repo: Path, *args: str):
    """Independent reader: no cami snapshot, index, Git helper or source execution."""
    result = subprocess.run(["git", "--no-replace-objects", "--no-optional-locks", "-c",
                             "core.fsmonitor=false", "-C", str(repo), *args],
                            capture_output=True, check=True, timeout=60,
                            env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"})
    return result.stdout


def reference_claim(repo, commit, claim, packet, reference):
    packet = packet.resolve()
    path = claim.subject.path
    raw_tree = reference_git(repo, "ls-tree", "-z", "--full-tree", commit, "--", ":(literal)" + path)
    write_bytes(packet / "git-ls-tree.raw", raw_tree)
    entries = [entry for entry in raw_tree.split(b"\0") if entry]
    result = {"id": claim.claim_id, "commit": commit, "path": path, "verdict": "uncertain",
              "reason": None, "git_mode": None, "git_oid": None, "source_sha256": None,
              "git_ls_tree_sha256": hashlib.sha256(raw_tree).hexdigest()}
    unsupported_ancestor = None
    if not entries:
        from pathlib import PurePosixPath
        for ancestor in reversed(PurePosixPath(path).parents):
            if str(ancestor) == ".":
                continue
            raw_ancestor = reference_git(repo, "ls-tree", "-z", "--full-tree", commit, "--", ":(literal)" + str(ancestor))
            write_bytes(packet / ("ancestor-" + hashlib.sha256(str(ancestor).encode()).hexdigest() + ".raw"), raw_ancestor)
            if raw_ancestor:
                info, found_path = raw_ancestor.rstrip(b"\0").split(b"\t", 1)
                mode, kind, oid = info.decode("ascii").split()
                if found_path == str(ancestor).encode() and (mode != "040000" or kind != "tree"):
                    unsupported_ancestor = {"path": str(ancestor), "git_mode": mode, "git_type": kind, "git_oid": oid}
                    break
    if unsupported_ancestor:
        result.update(reason="unsupported non-tree ancestor of exact subject path", evidence=[unsupported_ancestor])
    elif not entries:
        result.update(verdict="contradicted", reason="exact subject path absent from frozen Git tree",
                      evidence=[{"kind": "git_path_absence", "commit": commit, "path": path,
                                 "command": ["ls-tree", "-z", "--full-tree", commit, "--", ":(literal)" + path]}])
    elif len(entries) != 1 or entries[0].split(b"\t", 1)[1] != path.encode("utf-8"):
        result["reason"] = "unsupported non-exact Git path result"
    else:
        mode, kind, oid = entries[0].split(b"\t", 1)[0].decode("ascii").split()
        result.update(git_mode=mode, git_oid=oid, git_type=kind)
        if kind == "blob":
            raw = reference_git(repo, "show", "--no-ext-diff", "--no-textconv", f"{commit}:{path}")
            write_bytes(packet / "subject.raw", raw)
            result["source_sha256"] = hashlib.sha256(raw).hexdigest()
        if mode not in {"100644", "100755"} or kind != "blob":
            result["reason"] = "unsupported Git type or nonregular mode"
        else:
            case = {"id": claim.claim_id, "kind": claim.kind,
                    "subject": claim.subject.model_dump(mode="json"),
                    "predicate": claim.predicate.model_dump(mode="json"), "text": claim.text,
                    "scope": claim.scope, "source_path": "subject.raw", "source_sha256": result["source_sha256"]}
            write_json(packet / "case.json", case)
            result.update(reference.check_case(packet, case))
    write_json(packet / "decision.json", result)
    return result


def summarize(rows):
    scored = [row for row in rows if row["eligible"]]
    contradicted = sum(row["reference"]["verdict"] == "contradicted" for row in scored)
    false = sum(row["state"]["available"] and row["reference"]["verdict"] == "contradicted" for row in scored)
    return {"candidate_observations": len(rows), "scored_observations": len(scored),
            "excluded_parent_observations": len(rows) - len(scored),
            "candidate_reference_supported": sum(row["reference"]["verdict"] == "supported" for row in rows),
            "candidate_reference_contradicted": sum(row["reference"]["verdict"] == "contradicted" for row in rows),
            "candidate_reference_unknown": sum(row["reference"]["verdict"] == "uncertain" for row in rows),
            "reference_supported": sum(row["reference"]["verdict"] == "supported" for row in scored),
            "reference_contradicted": contradicted,
            "reference_unknown": sum(row["reference"]["verdict"] == "uncertain" for row in scored),
            "available": sum(row["state"]["available"] for row in scored),
            "false_available": false,
            "available_unknown": sum(row["state"]["available"] and row["reference"]["verdict"] == "uncertain" for row in scored),
            "withheld_supported": sum(not row["state"]["available"] and row["reference"]["verdict"] == "supported" for row in scored),
            "false_available_per_contradicted": false / contradicted if contradicted else None,
            "false_available_per_contradicted_null_reason": None if contradicted else "zero_reference_contradicted_observations",
            "false_available_per_scored": false / len(scored) if scored else None,
            "false_available_per_scored_null_reason": None if scored else "no_eligible_parent_claims",
            "selected_logical_validations": sum(row["selection"]["selected"] for row in scored),
            "actual_validation_calls": sum(row["validation"] is not None for row in scored),
            "carried_states": sum(not row["selection"]["selected"] for row in scored),
            "available_full_production_contradicted": sum(row["state"]["available"] and
                row.get("full_production_validation", {}).get("verdict") == "contradicted" for row in scored),
            "full_production_unknown": sum(row.get("full_production_validation", {}).get("verdict") ==
                "insufficient_evidence" for row in scored)}
