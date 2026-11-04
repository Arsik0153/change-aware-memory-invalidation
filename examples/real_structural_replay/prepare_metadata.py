"""Prepare a development replay proposal from parent artifacts and Git metadata only."""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parent
ROOT = BASE.parent.parent
READY = ROOT / "runs/main-restored-20261029/ready"
PILOT = ROOT / "examples/ai_review_pilot"
GROUPS = ("click-1c2fc1b0152f", "click-1e53748f80eb", "click-8c7491d9b0d7")
BOUNDARY = "934813e4d421071a1b3db3973c02fe2721359a6e"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def read(path: Path):
    return json.loads(path.read_bytes())


def rows(path: Path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def write_rows(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(canonical(value) + b"\n" for value in values))


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def build() -> None:
    if any(path.name != "prepare_metadata.py" for path in BASE.iterdir()):
        raise RuntimeError("Keep the existing planning output unchanged")
    inputs = {}

    def note(path: Path):
        inputs[relative(path)] = sha(path.read_bytes())

    dataset_path = READY / "dataset.json"
    note(dataset_path)
    dataset = read(dataset_path)
    click = next(repo for repo in dataset["repositories"] if repo["repo_id"] == "click")
    repo = Path(click["path"])
    git_commands = []

    def git(*arguments: str, allow_failure: bool = False) -> str:
        git_commands.append(list(arguments))
        process = subprocess.run(
            ["git", "--no-replace-objects", "--no-optional-locks", "-c", "core.fsmonitor=false",
             "-C", str(repo), *arguments], capture_output=True, text=True,
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"},
            timeout=60,
        )
        if process.returncode and not allow_failure:
            raise RuntimeError(process.stderr.strip())
        return process.stdout.strip()

    head = git("rev-parse", "--verify", "HEAD^{commit}")
    if head != BOUNDARY:
        raise RuntimeError("Local Click boundary changed before proposal creation")
    symbolic_head = git("symbolic-ref", "-q", "HEAD", allow_failure=True) or None
    branch_refs = git("for-each-ref", "--format=%(refname) %(objectname)",
                      "refs/heads/main", "refs/remotes/origin/main",
                      "refs/heads/master", "refs/remotes/origin/master")
    tag = git("rev-parse", "--verify", "refs/tags/8.1.8^{commit}")
    first_parent = git("rev-list", "--first-parent", "--reverse", head).splitlines()
    if len(set(first_parent)) != len(first_parent):
        raise RuntimeError("Nonunique first-parent boundary history")

    def commit(commit_id: str) -> dict:
        data = git("show", "-s", "--format=%H%x09%P%x09%cI", commit_id).split("\t")
        if len(data) != 3:
            raise RuntimeError("Unexpected commit metadata format")
        return {"commit": data[0], "parents": data[1].split(), "committer_timestamp": data[2]}

    case_map_path = PILOT / "private/case_map.json"
    note(case_map_path)
    # This is the preparation origin map, not an AI review answer or an outcome.
    originals = {row["original_candidate_id"]: row for row in read(case_map_path)
                 if row["origin_class"] == "authentic_parent_claim"}
    runs = {row["run_id"]: row for row in dataset["runs"]}
    cohort, original_provenance, symbol_provenance, file_provenance, incomplete_provenance = [], [], [], [], []
    trajectories, original_files, parent_sources = [], [], {}
    candidate_population = []
    for group in GROUPS:
        metadata = runs[group]
        if metadata["split"] != "development":
            raise RuntimeError("Selected group is not development")
        config_path = READY / metadata["config_path"]
        config = read(config_path)
        if config["repo"]["repo_id"] != "click" or config["split"] != "development":
            raise RuntimeError("Selected configuration is not development Click")
        if config["repo"]["path"] != str(repo) or config["repo"]["source_roots"] != click["source_roots"]:
            raise RuntimeError("Repository identity/source-root mismatch")
        if len(config["child_commits"]) != 1:
            raise RuntimeError("Original metadata is not a one-child pair")
        parent, original_child = config["parent_commit"], config["child_commits"][0]
        original_pair = [commit(parent), commit(original_child)]
        if original_pair[1]["parents"] != [parent]:
            raise RuntimeError("Original child is not the unique single-parent successor")
        proposed = []
        reasons = []
        if parent not in first_parent:
            reasons.append("parent_not_on_frozen_boundary_first_parent_path")
        else:
            index = first_parent.index(parent)
            proposed = [commit(child) for child in first_parent[index + 1:index + 13]]
            if len(proposed) != 12:
                reasons.append("fewer_than_12_first_parent_successors")
            if not proposed or proposed[0]["commit"] != original_child:
                reasons.append("original_child_not_immediate_first_parent_successor")
            previous = parent
            for child in proposed:
                if child["parents"] != [previous]:
                    reasons.append("multi_parent_or_nonlinear_successor")
                previous = child["commit"]
        chosen = original_pair[1:] if reasons else proposed
        trajectories.append({
            "group_id": group, "dataset_run_metadata": metadata,
            "config_sha256": sha(config_path.read_bytes()), "config_path": relative(config_path),
            "split": "development", "repo_id": "click", "source_roots": config["repo"]["source_roots"],
            "parent": original_pair[0], "original_child": original_pair[1],
            "explored_first_12_successors_metadata": proposed,
            "selection_mode": "original_one_child_fallback" if reasons else "12_single_parent_successors",
            "fallback_reasons": sorted(set(reasons)), "frozen_children": chosen,
        })
        claims_path = config_path.parent / config["claims_path"]
        provenance_path = config_path.parent / config["provenance_path"]
        for path in (config_path, claims_path, provenance_path):
            note(path)
        archive_paths = {}
        for name, path in (("config.json", config_path), ("claims_all_original_candidates.jsonl", claims_path),
                           ("provenance_all_original_candidates.jsonl", provenance_path)):
            target = BASE / "original_inputs" / group / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
            archive_paths[name] = target.relative_to(BASE).as_posix()
        claims = [claim for claim in rows(claims_path)
                  if claim["kind"] in {"symbol_exists", "signature_equals"}]
        if Counter(claim["kind"] for claim in claims) != {"symbol_exists": 4, "signature_equals": 4}:
            raise RuntimeError("Expected eight authentic structural parent claims")
        provenance_by_claim = {row["claim_id"]: row for row in rows(provenance_path)}
        selected_ids = {claim["claim_id"] for claim in claims}
        selected_raw_lines = [line for line in claims_path.read_bytes().splitlines(keepends=True)
                              if json.loads(line)["claim_id"] in selected_ids]
        selected_claims_path = BASE / "groups" / group / "claims.jsonl"
        selected_claims_path.parent.mkdir(parents=True, exist_ok=True)
        selected_claims_path.write_bytes(b"".join(selected_raw_lines))
        original_files.append({"group_id": group, "config": relative(config_path),
                               "claims": relative(claims_path), "provenance": relative(provenance_path),
                               "copied_original_inputs": archive_paths,
                               "selected_immutable_claim_rows": selected_claims_path.relative_to(BASE).as_posix(),
                               "selected_claim_rows_sha256": sha(selected_claims_path.read_bytes()),
                               "original_config_preview": config["preview"],
                               "original_config_protocol_version": config["protocol_version"],
                               "original_config_policy": config["policy"]})
        for claim in sorted(claims, key=lambda row: row["claim_id"]):
            identity = claim["claim_id"]
            origin = originals[identity]
            if claim != origin["original_claim"] or sha(canonical(claim)) != origin["original_claim_sha256"]:
                raise RuntimeError("Authentic claim differs from sealed parent pilot")
            if claim["origin_commit"] != parent:
                raise RuntimeError("Claim origin differs from trajectory parent")
            source_origin = origin["source_origin"]
            source_path = ROOT / "runs/parent-review-20261104" / source_origin["package_evidence_path"]
            note(source_path)
            source = source_path.read_bytes()
            if sha(source) != source_origin["source_sha256"]:
                raise RuntimeError("Immutable parent source hash mismatch")
            blob = f"blob {len(source)}\0".encode() + source
            if hashlib.sha1(blob).hexdigest() != source_origin["git_blob_object_id"]:
                raise RuntimeError("Original parent Git blob identity mismatch")
            copied_source = BASE / "parent_sources" / group / claim["subject"]["path"]
            copied_source.parent.mkdir(parents=True, exist_ok=True)
            copied_source.write_bytes(source)
            # Parent-only anchor extraction. No predicate comparison or label is made.
            tree = ast.parse(source.decode("utf-8"), filename=claim["subject"]["path"])
            definitions = [node for node in tree.body
                           if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and node.name == claim["subject"]["qualname"]]
            if len(definitions) != 1:
                raise RuntimeError("Cannot derive the proposed exact-subject parent anchor")
            node = definitions[0]
            symbol_hash = sha(ast.dump(node, include_attributes=False).encode())
            anchor_base = {"path": claim["subject"]["path"], "observed_commit": parent, "origin": "static"}
            symbol_anchor = {**anchor_base, "qualname": claim["subject"]["qualname"], "scope": "symbol",
                             "content_hash": symbol_hash, "start_line": node.lineno, "end_line": node.end_lineno}
            file_anchor = {**anchor_base, "scope": "file", "content_hash": sha(source),
                           "start_line": 1, "end_line": len(source.splitlines())}
            new_base = {"schema_version": 1, "claim_id": identity, "dependencies": []}
            symbol_provenance.append({**new_base, "scenario_id": "research_symbol_anchor_v1",
                                      "anchors": [symbol_anchor], "known_incomplete": False, "unresolved_reasons": []})
            file_provenance.append({**new_base, "scenario_id": "research_file_anchor_v1",
                                    "anchors": [file_anchor], "known_incomplete": False, "unresolved_reasons": []})
            incomplete_provenance.append({**new_base, "scenario_id": "research_known_incomplete_v1",
                                          "anchors": [symbol_anchor], "known_incomplete": True,
                                          "unresolved_reasons": ["Deliberately conservative research baseline; original provenance remains unchanged."]})
            original_row = provenance_by_claim[identity]
            original_provenance.append(original_row)
            cohort.append({"group_id": group, "claim": claim, "claim_sha256": sha(canonical(claim)),
                           "original_provenance_row_sha256": sha(canonical(original_row)),
                           "parent_source_sha256": sha(source), "parent_git_blob_object_id": source_origin["git_blob_object_id"],
                           "symbol_ast_sha256": symbol_hash, "source_evidence_path": relative(source_path),
                           "copied_parent_source_path": copied_source.relative_to(BASE).as_posix(),
                           "split": "development", "ai_confirmation_binding": "Coordinator must bind existing sealed parent-only AI records before final freeze; not read here."})
            parent_sources[(group, claim["subject"]["path"])] = {
                **source_origin, "copied_parent_source_path": copied_source.relative_to(BASE).as_posix()}
            for child in chosen:
                candidate_population.append({"group_id": group, "claim_id": identity,
                                             "parent_commit": parent, "child_commit": child["commit"],
                                             "split": "development"})

    if len(cohort) != 24 or len(candidate_population) != 112:
        raise RuntimeError("The metadata-derived fixed population differs from the intended 24 claims and 112 observations")
    implementation_paths = [
        ROOT / "scripts/structural_checker_v2.py", ROOT / "src/cami/index.py",
        ROOT / "src/cami/validation.py", ROOT / "src/cami/policies.py",
        ROOT / "src/cami/repository.py", ROOT / "src/cami/models.py",
    ]
    for path in implementation_paths:
        note(path)
    boundary = {"frozen_commit": head, "symbolic_HEAD": symbolic_head,
                "main_master_refs": branch_refs.splitlines(), "tag_8.1.8_commit": tag,
                "interpretation": "Detached local HEAD at 8.1.8 is the explicit upper boundary; no main branch is claimed.",
                "shallow_repository": git("rev-parse", "--is-shallow-repository") == "true",
                "object_format": git("rev-parse", "--show-object-format")}
    write(BASE / "metadata_manifest.json", {
        "status": "proposed_before_any_child_source_access", "repo": click, "boundary": boundary,
        "group_ids": list(GROUPS), "trajectories": trajectories,
        "development_only_evidence": "All selected dataset runs and selected original configs declare development and repo_id=click.",
        "original_files": original_files, "original_parent_sources": list(parent_sources.values()),
        "git_metadata_commands": git_commands, "git_fetch_performed": False,
        "child_blob_tree_or_diff_read": False, "child_results_read": False,
        "original_AI_reviews_read": False, "parent_reference_labels_computed": False,
        "parent_source_access": "Only existing immutable parent-review module bytes were hashed and parsed for anchor derivation.",
        "parent_anchor_python_version": sys.version.split()[0], "input_sha256": inputs,
    })
    write(BASE / "cohort.json", cohort)
    write_rows(BASE / "candidate_population.jsonl", candidate_population)
    write_rows(BASE / "original_provenance_unchanged.jsonl", original_provenance)
    write_rows(BASE / "research_provenance/symbol_anchor.jsonl", symbol_provenance)
    write_rows(BASE / "research_provenance/file_anchor.jsonl", file_provenance)
    write_rows(BASE / "research_provenance/known_incomplete.jsonl", incomplete_provenance)
    protocol = {
        "protocol_id": "real-click-structural-replay-development-v1", "status": "draft_awaiting_root_implementation_and_pre_access_seal",
        "evaluation_eligible": False, "dataset_kind": "real_repository_research_replay",
        "split": "development", "repo_id": "click", "boundary_commit": head,
        "candidate_claims": 24, "candidate_claim_child_observations_per_variant": 112,
        "variants": [
            {"id": "symbol_anchor", "policy": {"id": "symbol_validate", "dependency_depth": 1}, "provenance": "research_provenance/symbol_anchor.jsonl"},
            {"id": "file_anchor", "policy": {"id": "file_validate", "dependency_depth": 1}, "provenance": "research_provenance/file_anchor.jsonl"},
            {"id": "known_incomplete", "policy": {"id": "symbol_validate", "dependency_depth": 1}, "provenance": "research_provenance/known_incomplete.jsonl"},
            {"id": "all_validate", "policy": {"id": "all_validate", "dependency_depth": 1}, "provenance": "research_provenance/symbol_anchor.jsonl"},
        ],
        "production_protocol_version": "1.1",
        "trajectory_selection": {
            "rule": "From each fixed parent, take the first 12 successors on the frozen detached-HEAD first-parent path only if all are single-parent successors and the first equals the original configured child. Otherwise use the entire original one-child pair.",
            "no_skipping_or_repair": "Do not skip merges, gaps, unsupported sources, or inconvenient outcomes. No fetching or alternative branch choice.",
            "bindings": "metadata_manifest.json records every explored successor, parent list, chosen child ID and fallback reason.",
            "chosen_child_counts": {row["group_id"]: len(row["frozen_children"]) for row in trajectories},
        },
        "access_scope": {
            "current": "Planning only. No child source, tree listing, diff or outcome has been read by this planner.",
            "future_authorization": "Only after root seals this new protocol, complete implementation, exact child IDs and input hashes may its research runner read the three recorded parent snapshots and IDs in frozen_children for each trajectory.",
            "separation": "This new experiment alone supersedes parent-only access for its chosen development snapshots. Rejected explored successors, side parents, old AI pilot, old main protocol, held-out Requests/pytest and other child snapshots remain outside scope.",
            "no_production_admission": "Use production library functions in a separate research replay. Do not create receipts or admission records, edit original configs, unpreview old runs, or run main evaluation.",
        },
        "parent_eligibility_check": {
            "fixed_population": "Keep all 24 authentic claims and all 112 candidate observations in the preparation/report inventory. No replacements.",
            "requirements": "Existing sealed AI-pilot confirmations must bind the same 24 original claim hashes. Independent v2 reference must separately return supported on the exact parent source. AI agreement is not truth or a human review.",
            "excluded_parents": "Reference contradicted, uncertain or missing confirmation excludes that claim from replay scoring, while retaining its record and exclusion reason. Never fill an exclusion with a different claim.",
            "initial_state": "Run the actual full production structural validator on eligible parent claims to initialize each variant's state. Do not initialize availability from AI agreement or from the independent reference verdict.",
            "terminology": "This is an internal research eligibility check, not CAMI admission, annotation labels, parent receipts or human double-review.",
        },
        "new_provenance": {
            "derivation": "Parse each full immutable parent module, identify the exact direct subject definition, derive its AST hash and range, and separately retain the full-file byte hash and range. Hashes are evidence identity, not independent truth labels.",
            "originals": "Original claims, source bytes, configs, known_incomplete flags and unresolved remarks remain unchanged. original_provenance_unchanged.jsonl is a separate record of the original rows.",
            "symbol_assumption": "Symbol-only research support with known_incomplete=false is a deliberate experimental input assumption. Full-module binding facts may fall outside that anchor. The replay tests this assumption against v2; it is not certified provenance completeness.",
            "file_assumption": "The full module is the proposed bounded syntactic evidence scope. This does not certify original provenance completeness or runtime behavior.",
            "known_incomplete_baseline": "A separately derived symbol-anchor input sets known_incomplete=true and a research reason. It does not rewrite or close any original remark.",
            "dependencies": "No dependencies are asserted for these bounded syntactic claims. Dynamic runtime meaning is outside scope.",
        },
        "reference_and_replay": {
            "reference": "Freeze scripts/structural_checker_v2.py and its rubric/tests before child access. Derive independent reference verdicts on every scored child snapshot; disclose shared CPython ast and its version.",
            "production": "Use real production snapshot/index/change computation, full structural validation, select_claims and advance_state. Preserve all selection reasons, validation verdicts and state fields per step and variant.",
            "no_reference_leakage": "Independent reference results never determine which claims production selects or what state production carries. The all_validate variant supplies a full-production comparison.",
            "cost": "Count logical selected child validations per variant and actual executions separately. If full-validation results are shared, consume them in a selected policy only when that policy selects the claim. Parent initialization and independent reference work are separate costs.",
            "limits": "No network, LLM calls, behavior probes, package execution, fabricated human reviews or claims of parser independence.",
        },
        "metrics": {
            "candidate_denominator": "112 frozen claim-child records per variant: 8,96,8 by the three ordered groups. Retain excluded-parent records separately.",
            "scored_denominator": "For each group and variant, eligible parent claim count times its fixed child count. Report exclusions and reference uncertainty; do not silently change the candidate denominator.",
            "false_available_count": "Count production available=true only when independent v2 reference is contradicted.",
            "false_available_rates": "Report false-available count divided by reference-contradicted scored observations, and separately by all scored observations. Use null with a reason for a zero denominator.",
            "available_unknown": "Count and report available=true with reference uncertain separately. It is neither proven false availability nor proven correctness.",
            "withheld_supported": "Count unavailable production states on reference-supported observations separately from reference-unknown and parent exclusions.",
            "cost_metrics": "Selected logical validations, validation outcomes, carried states and actual executions. Report parent, index and reference costs separately. No wall-time speedup claim.",
            "group_reporting": "Report each group's child count and denominator, plus aggregate counts. These unequal trajectories and repeated modules are dependent observations; do not infer an independent-sample population error rate.",
        },
        "failure_rules": [
            "Stop on a seal, source hash, commit identity, chain, cohort or implementation mismatch. Do not reseal after looking at child outcomes.",
            "Record parse or unsupported-syntax uncertainty. Do not drop a difficult child, change a predicate or substitute a trajectory.",
            "If a semantic checker bug is found after execution, preserve this run and version. Use a separate protocol/reference version for a new run or disclosed sensitivity analysis.",
            "Zero contradicted reference observations yields no false-availability-rate estimate and no evidence of universal safety.",
        ],
        "must_be_bound_by_root_before_child_access": [
            "Exact sealed parent AI-confirmation artifact paths and hashes, without relabeling AI as human.",
            "Final replay runner and analyzer source hashes, tests, reference v2 source/rubric/test hashes and production implementation hashes.",
            "A final immutable hash inventory of this cohort, all trajectory metadata, all four variant inputs and the final protocol.",
        ],
    }
    write(BASE / "proposed_protocol.json", protocol)
    write(BASE / "planning_hashes.json", {
        path.relative_to(BASE).as_posix(): sha(path.read_bytes())
        for path in sorted(BASE.rglob("*")) if path.is_file()
    })


if __name__ == "__main__":
    build()
