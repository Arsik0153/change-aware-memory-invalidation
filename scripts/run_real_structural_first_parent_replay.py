#!/usr/bin/env python3
"""Separate sealed ordered-first-parent extension; original replay remains unchanged."""
# ruff: noqa: E402
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "src/cami").is_dir():
    ROOT = Path(__file__).resolve().parents[2]  # isolated staging directory
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cami.artifacts import digest, file_hash, reserve, within, write_json, write_jsonl
from cami.index import IndexConfig, build_index, compare_indexes
from cami.models import MemoryState, PolicyConfig, RepoLocation, Selection
from cami.policies import SelectionContext, advance_state, select_claims
from cami.repository import read_snapshot
from cami.validation import ValidationContext, validate_claim
from scripts.verify_cami import source_snapshot
from scripts.real_structural_replay_support import VARIANTS, load_reference, reference_claim, summarize
from real_structural_first_parent_support import extension_inputs, preflight_first_parent, compare_overlap, stratum_report


def now():
    return datetime.now(timezone.utc).isoformat()


def initial_state(claim, provenance, result):
    empty = MemoryState(claim_id=claim.claim_id, revision=claim.origin_commit,
                        state="needs_validation", last_checked_commit=None, last_supported_commit=None,
                        last_verdict=None, basis="validated", current_provenance=provenance,
                        available=False, withheld_reason="parent_not_validated")
    return advance_state(empty, Selection(claim_id=claim.claim_id, commit=claim.origin_commit,
                         selected=True, reasons=("parent_initialization",)),
                         PolicyConfig(id="all_validate"), result, True)


def execute(protocol_path, output):
    protocol_path, output = protocol_path.resolve(), output.resolve()
    reserve(output)
    manifest = {"schema_version": 1, "status": "preflight", "evaluation_eligible": False,
                "started_at": now(), "protocol_path": str(protocol_path.resolve()),
                "source_before": source_snapshot(ROOT), "python": sys.version,
                "notes": ["Research replay only; no admission records or parent receipts.",
                          "Full production indexes and AST cache are shared across variants.",
                          "Every selected variant validation executes with its own provenance; no result caching.",
                          "Independent reference shares CPython ast; source is never executed.",
                          "No wall-time speedup estimate. Trajectory observations are dependent."]}
    write_json(output / "manifest.json", manifest)
    records, parents, costs = [], [], []
    try:
        if manifest["source_before"]["source_status"]:
            raise ValueError("implementation source working tree must be clean before replay")
        inputs, metadata, old_protocol, old_rows, old_parents = extension_inputs(protocol_path)
        protocol, root, seal, groups, cohort, confirmations, provenance, reference_path = inputs
        if root != ROOT:
            raise ValueError("protocol root must be the running implementation workspace")
        runner_name = str(Path(__file__).resolve().relative_to(root))
        if runner_name not in seal["files"] or runner_name not in protocol["implementation_paths"]:
            raise ValueError("running driver must be named and sealed")
        manifest.update(status="running", protocol_sha256=file_hash(protocol_path), seal=seal,
                        protocol=protocol, parent_exclusions=[], eligible_claims=[])
        write_json(output / "manifest.json", manifest)
        reference = load_reference(reference_path)
        # Metadata-only global preflight completes before every production/reference source read.
        topology = preflight_first_parent(protocol, metadata, old_protocol, groups, root)
        write_json(output / "topology.json", topology)
        for group, claims in groups:
            group_id = group["group_id"]
            repo_path = within(root, group["repo_path"])
            parent, children = group["parent_commit"], tuple(group["child_commits"])
            repo = RepoLocation(repo_id=group["repo_id"], path=str(repo_path), source_roots=tuple(group["source_roots"]))
            index_config = IndexConfig(repo.source_roots, True)
            cache = {}
            tick = time.perf_counter()
            before = read_snapshot(repo, parent)
            old_index = build_index(before, index_config, cache)
            costs.append({"phase": "parent_snapshot_index", "group_id": group_id, "commit": parent,
                          "seconds": time.perf_counter() - tick, "index_builds": 1})
            eligible = []
            previous = {variant: {} for variant in VARIANTS}
            for claim in claims:
                tick = time.perf_counter()
                decision = reference_claim(repo_path, parent, claim,
                    output / "packets" / group_id / parent / claim.claim_id, reference)
                costs.append({"phase": "parent_reference", "group_id": group_id, "claim_id": claim.claim_id,
                              "seconds": time.perf_counter() - tick, "reference_calls": 1})
                expected = cohort[claim.claim_id]
                if decision["source_sha256"] != expected["parent_source_sha256"]:
                    raise ValueError("parent subject source differs from frozen original cohort")
                if decision["git_oid"] != expected["parent_git_blob_object_id"]:
                    raise ValueError("parent Git subject identity differs from frozen cohort")
                confirmation = confirmations.get(claim.claim_id)
                reasons = []
                if decision["verdict"] != "supported":
                    reasons.append("parent_reference_" + decision["verdict"])
                if confirmation is None or not confirmation.get("eligible", False):
                    reasons.append("missing_or_unsupported_sealed_ai_confirmation")
                is_eligible = not reasons
                parent_row = {"group_id": group_id, "claim": claim.model_dump(mode="json"),
                              "claim_sha256": digest(claim), "eligible": is_eligible,
                              "exclusion_reasons": reasons, "reference": decision,
                              "ai_confirmation": confirmation, "variants": {}}
                if is_eligible:
                    eligible.append(claim)
                    manifest["eligible_claims"].append(claim.claim_id)
                    for variant in VARIANTS:
                        prov = provenance[variant][claim.claim_id]
                        result = validate_claim(claim, ValidationContext(before, old_index, prov, root, output))
                        state = initial_state(claim, prov, result)
                        previous[variant][claim.claim_id] = state
                        parent_row["variants"][variant] = {"provenance": prov.model_dump(mode="json", by_alias=True),
                            "validation": result.model_dump(mode="json"), "state": state.model_dump(mode="json")}
                        costs.append({"phase": "parent_production_validation", "group_id": group_id,
                                      "variant": variant, "claim_id": claim.claim_id, "actual_calls": 1,
                                      "seconds": result.duration_seconds})
                else:
                    manifest["parent_exclusions"].append({"claim_id": claim.claim_id, "reasons": reasons})
                parents.append(parent_row)
                write_jsonl(output / "parents.jsonl", parents)
            claims_by_id = {claim.claim_id: claim for claim in eligible}
            for commit in children:
                transition = topology[group_id][commit]
                if before.revision != transition["previous_commit"]:
                    raise ValueError("snapshot loop lost preceding first-parent state")
                tick = time.perf_counter()
                snap = read_snapshot(repo, commit)
                index = build_index(snap, index_config, cache)
                changes = compare_indexes(old_index, index, before, snap)
                costs.append({"phase": "child_snapshot_index_compare", "group_id": group_id, "commit": commit,
                              "seconds": time.perf_counter() - tick, "index_builds": 1})
                step = []
                # Reference decisions are deliberately computed only after all policy transitions.
                for variant, policy_id in VARIANTS.items():
                    policy = PolicyConfig(id=policy_id, dependency_depth=1)
                    provs = tuple(provenance[variant][claim.claim_id] for claim in eligible)
                    states = tuple(previous[variant][claim.claim_id] for claim in eligible)
                    variant_changes = changes
                    if policy_id.startswith("file_"):
                        variant_changes = replace(changes, unresolved=index.unresolved,
                            limited_paths=frozenset(index.limitations()), global_unresolved=index.global_unresolved)
                    decisions = select_claims(SelectionContext(commit, tuple(eligible), provs, states,
                                               variant_changes, (), "1.1"), policy)
                    for old_state, selection in zip(states, decisions, strict=True):
                        claim = claims_by_id[selection.claim_id]
                        prov = provenance[variant][claim.claim_id]
                        result = validate_claim(claim, ValidationContext(snap, index, prov, root, output)) if selection.selected else None
                        state = advance_state(old_state, selection, policy, result, True)
                        previous[variant][claim.claim_id] = state
                        step.append({"group_id": group_id, "variant": variant, "commit": commit,
                                     "claim_id": claim.claim_id, "eligible": True,
                                     "provenance": prov.model_dump(mode="json", by_alias=True),
                                     "previous_state": old_state.model_dump(mode="json"),
                                     "selection": selection.model_dump(mode="json"),
                                     "validation": result.model_dump(mode="json") if result else None,
                                     "state": state.model_dump(mode="json")})
                        if result:
                            costs.append({"phase": "child_production_validation", "group_id": group_id,
                                          "variant": variant, "claim_id": claim.claim_id, "commit": commit,
                                          "logical_calls": 1, "actual_calls": 1, "seconds": result.duration_seconds})
                references = {}
                for claim in claims:
                    tick = time.perf_counter()
                    references[claim.claim_id] = reference_claim(repo_path, commit, claim,
                        output / "packets" / group_id / commit / claim.claim_id, reference)
                    costs.append({"phase": "child_reference", "group_id": group_id, "commit": commit,
                                  "claim_id": claim.claim_id, "seconds": time.perf_counter() - tick,
                                  "reference_calls": 1, "scored": claim.claim_id in claims_by_id})
                    if claim.claim_id not in claims_by_id:
                        for variant in VARIANTS:
                            step.append({"group_id": group_id, "variant": variant, "commit": commit,
                                         "claim_id": claim.claim_id, "eligible": False,
                                         "selection": None, "validation": None, "state": None})
                full = {row["claim_id"]: row["validation"] for row in step
                        if row["variant"] == "all_validate" and row["eligible"]}
                for row in step:
                    row["trajectory"] = transition
                    row["reference"] = references[row["claim_id"]]
                    row["full_production_validation"] = full.get(row["claim_id"])
                records.extend(step)
                write_jsonl(output / "observations.jsonl", records)
                write_jsonl(output / "costs.jsonl", costs)
                write_json(output / "changes" / group_id / f"{commit}.json", {
                    **transition, "before": before.revision, "after": commit, "files": sorted(changes.files),
                    "symbols": [node.model_dump(mode="json") for node in sorted(changes.symbols, key=str)],
                    "limited_paths": sorted(changes.limited_paths), "global_unresolved": changes.global_unresolved,
                    "unresolved": [node.model_dump(mode="json") for node in sorted(changes.unresolved, key=str)],
                    "edges": [edge.model_dump(mode="json", by_alias=True) for edge in changes.edges]})
                before, old_index = snap, index
        report = {"variants": {variant: summarize([row for row in records if row["variant"] == variant]) for variant in VARIANTS},
                  "groups": {group["group_id"]: {"child_count": len(group["child_commits"]),
                      "candidate_claims": len(claims), "variants": {variant: summarize([row for row in records
                          if row["group_id"] == group["group_id"] and row["variant"] == variant]) for variant in VARIANTS}}
                      for group, claims in groups}}
        report["parent_initialization"] = {variant: {
            "eligible_parent_claims": sum(row["eligible"] for row in parents),
            "supported": sum(row["eligible"] and row["variants"][variant]["state"]["available"] for row in parents),
            "initially_withheld": sum(row["eligible"] and not row["variants"][variant]["state"]["available"] for row in parents),
            "actual_validation_calls": sum(row["eligible"] for row in parents)} for variant in VARIANTS}
        report["separate_work"] = {"parent_reference_calls": sum(row.get("reference_calls", 0) for row in costs if row["phase"] == "parent_reference"),
            "child_reference_calls": sum(row.get("reference_calls", 0) for row in costs if row["phase"] == "child_reference"),
            "shared_index_builds": sum(row.get("index_builds", 0) for row in costs)}
        report["primary_new_coverage"] = stratum_report([row for row in records if row["trajectory"]["coverage_stratum"] == "new_added"], groups)
        report["old_overlap"] = stratum_report([row for row in records if row["trajectory"]["coverage_stratum"] == "old_overlap"], groups)
        report["topology_strata"] = {name: stratum_report([row for row in records if row["trajectory"]["is_merge"] == merge], groups)
                                     for name, merge in (("merge", True), ("nonmerge", False))}
        report["coverage_note"] = "Added transitions are outcome-informed development coverage; old overlap is repeated evidence. Merge strata are descriptive, not causal."
        overlap = compare_overlap(records, parents, old_rows, old_parents, output)
        report["overlap_check"] = {field: overlap[field] for field in ("status", "observation_count", "parent_count")}
        write_json(output / "report.json", report)
        for name, expected in seal["files"].items():
            if file_hash(within(root, name)) != expected:
                raise ValueError(f"sealed input changed during replay: {name}")
        manifest["source_after"] = source_snapshot(ROOT)
        manifest["source_snapshots_match"] = manifest["source_before"] == manifest["source_after"]
        if not manifest["source_snapshots_match"]:
            raise ValueError("implementation workspace changed during replay")
        manifest.update(status="complete", finished_at=now(), artifact_hashes={str(path.relative_to(output)): file_hash(path)
            for path in sorted(output.rglob("*")) if path.is_file() and path.name != "manifest.json"})
    except BaseException as error:
        manifest.update(status="failed", finished_at=now(), failure=f"{type(error).__name__}: {error}",
                        source_after=source_snapshot(ROOT))
        write_jsonl(output / "observations.jsonl", records)
        write_jsonl(output / "parents.jsonl", parents)
        write_jsonl(output / "costs.jsonl", costs)
        write_json(output / "manifest.json", manifest)
        raise
    write_json(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    execute(args.protocol, args.out)


if __name__ == "__main__":
    main()
