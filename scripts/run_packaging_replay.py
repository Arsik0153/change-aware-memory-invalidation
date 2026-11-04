#!/usr/bin/env python3
"""Sealed new-derived Packaging replay; no original cohort or production changes."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import resource
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
from scripts.real_structural_replay_support import (
    VARIANTS,
    load_reference,
    reference_claim,
)
from packaging_replay_support import (
    load_inputs,
    preflight_topology,
    report_stratum,
    check,
    storage_bytes,
)


def now():
    return datetime.now(timezone.utc).isoformat()


def total_cpu():
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time() + children.ru_utime + children.ru_stime


class ObservedBudget:
    """Boundary observations, not preemptive timeouts; one operation may overshoot."""

    def __init__(self, output, groups, root, started_wall, started_cpu):
        self.output = output
        self.repositories = {within(root, group["repo_path"]) for group, _ in groups}
        check(
            not any(output.is_relative_to(repo) for repo in self.repositories),
            "output must be outside repository",
        )
        self.started_wall, self.started_cpu = started_wall, started_cpu

    def observe(self, phase):
        disk = storage_bytes(self.output) + sum(storage_bytes(repo) for repo in self.repositories)
        return {
            "phase": phase,
            "disk_bytes": disk,
            "disk_scope": "repositories_and_output",
            "cpu_seconds": total_cpu() - self.started_cpu,
            "wall_seconds": time.monotonic() - self.started_wall,
        }


def enforce_usage(usage):
    exceeded = [
        name
        for name, cap in (
            ("disk_bytes", 2 * 1024**3),
            ("cpu_seconds", 1200),
            ("wall_seconds", 1800),
        )
        if usage[name] > cap
    ]
    check(
        not exceeded,
        "observed replay resource ceiling exceeded at "
        + usage["phase"]
        + ": "
        + ", ".join(exceeded),
    )


def initial_state(claim, provenance, result):
    empty = MemoryState(
        claim_id=claim.claim_id,
        revision=claim.origin_commit,
        state="needs_validation",
        last_checked_commit=None,
        last_supported_commit=None,
        last_verdict=None,
        basis="validated",
        current_provenance=provenance,
        available=False,
        withheld_reason="parent_not_validated",
    )
    return advance_state(
        empty,
        Selection(
            claim_id=claim.claim_id,
            commit=claim.origin_commit,
            selected=True,
            reasons=("parent_initialization",),
        ),
        PolicyConfig(id="all_validate"),
        result,
        True,
    )


def execute(protocol_path, output):
    started_wall, started_cpu = time.monotonic(), total_cpu()
    protocol_path, output = protocol_path.resolve(), output.resolve()
    reserve(output)
    manifest = {
        "schema_version": 1,
        "status": "preflight",
        "evaluation_eligible": False,
        "started_at": now(),
        "protocol_path": str(protocol_path.resolve()),
        "source_before": source_snapshot(ROOT),
        "python": sys.version,
        "resource_limits": {
            "disk_bytes": 2 * 1024**3,
            "cpu_seconds": 1200,
            "wall_seconds": 1800,
            "cpu_scope": "self plus completed subprocess user/system CPU",
            "enforcement": "Observed at boundaries; no preemptive hard kill. A single operation may overshoot.",
        },
        "resource_checkpoints": [],
        "notes": [
            "Research replay only; no admission records or parent receipts.",
            "Full production indexes and AST cache are shared across variants.",
            "Every selected variant validation executes with its own provenance; no result caching.",
            "Independent reference shares CPython ast; source is never executed.",
            "Production read_snapshot reads complete allowlisted snapshots; roots constrain indexing/claims, not physical snapshot reads.",
            "No wall-time speedup estimate. Trajectory observations are dependent.",
        ],
    }
    write_json(output / "manifest.json", manifest)
    records, parents, costs = [], [], []
    budget = None

    def checkpoint(phase, enforce=True):
        usage = (
            budget.observe(phase)
            if budget
            else {
                "phase": phase,
                "disk_bytes": storage_bytes(output),
                "disk_scope": "output_only_before_protocol_preflight",
                "cpu_seconds": total_cpu() - started_cpu,
                "wall_seconds": time.monotonic() - started_wall,
            }
        )
        manifest["resource_usage"] = usage
        manifest["resource_checkpoints"].append(usage)
        if enforce:
            enforce_usage(usage)
        return usage

    try:
        if manifest["source_before"]["source_status"]:
            raise ValueError("implementation source working tree must be clean before replay")
        (
            protocol,
            root,
            seal,
            groups,
            cohort,
            confirmations,
            provenance,
            reference_path,
            metadata,
            decisions,
        ) = load_inputs(protocol_path)
        if root != ROOT:
            raise ValueError("protocol root must be the running implementation workspace")
        runner_name = str(Path(__file__).resolve().relative_to(root))
        if runner_name not in seal["files"] or runner_name not in protocol["implementation_paths"]:
            raise ValueError("running driver must be named and sealed")
        manifest.update(
            status="running",
            protocol_sha256=file_hash(protocol_path),
            seal=seal,
            protocol=protocol,
            parent_exclusions=[],
            eligible_claims=[],
        )
        write_json(output / "manifest.json", manifest)
        reference = load_reference(reference_path)
        # Metadata-only global preflight completes before every production/reference source read.
        topology = preflight_topology(protocol, metadata, groups, root)
        budget = ObservedBudget(output, groups, root, started_wall, started_cpu)
        manifest["disk_bytes_before"] = checkpoint("after_global_preflight")["disk_bytes"]
        write_json(output / "topology.json", topology)
        prepared = []
        # Initialize every parent before any group may read its first child.
        for group, claims in groups:
            group_id = group["group_id"]
            repo_path = within(root, group["repo_path"])
            parent, children = group["parent_commit"], tuple(group["child_commits"])
            repo = RepoLocation(
                repo_id=group["repo_id"],
                path=str(repo_path),
                source_roots=tuple(group["source_roots"]),
            )
            index_config = IndexConfig(repo.source_roots, True)
            cache = {}
            checkpoint("before_parent:" + group_id)
            tick = time.perf_counter()
            before = read_snapshot(repo, parent)
            old_index = build_index(before, index_config, cache)
            costs.append(
                {
                    "phase": "parent_snapshot_index",
                    "group_id": group_id,
                    "commit": parent,
                    "seconds": time.perf_counter() - tick,
                    "index_builds": 1,
                }
            )
            eligible = []
            previous = {variant: {} for variant in VARIANTS}
            for claim in claims:
                tick = time.perf_counter()
                decision = reference_claim(
                    repo_path,
                    parent,
                    claim,
                    output / "packets" / group_id / parent / claim.claim_id,
                    reference,
                )
                costs.append(
                    {
                        "phase": "parent_reference",
                        "group_id": group_id,
                        "claim_id": claim.claim_id,
                        "seconds": time.perf_counter() - tick,
                        "reference_calls": 1,
                    }
                )
                expected = cohort[claim.claim_id]
                if decision["source_sha256"] != expected["parent_source_sha256"]:
                    raise ValueError("parent subject source differs from frozen original cohort")
                if decision["git_oid"] != expected["parent_git_blob_object_id"]:
                    raise ValueError("parent Git subject identity differs from frozen cohort")
                confirmation = confirmations[claim.claim_id]
                sealed = decisions[claim.claim_id]
                check(
                    decision["verdict"] == sealed["reference_verdict"]
                    and decision.get("facts") == confirmation["reference"].get("facts"),
                    "fresh parent reference differs from sealed decision",
                )
                reasons = sealed["exclusion_reasons"]
                is_eligible = sealed["eligible"]
                parent_row = {
                    "group_id": group_id,
                    "claim": claim.model_dump(mode="json"),
                    "claim_sha256": digest(claim),
                    "eligible": is_eligible,
                    "exclusion_reasons": reasons,
                    "reference": decision,
                    "ai_confirmation": confirmation,
                    "variants": {},
                }
                if is_eligible:
                    eligible.append(claim)
                    manifest["eligible_claims"].append(claim.claim_id)
                    for variant in VARIANTS:
                        prov = provenance[variant][claim.claim_id]
                        result = validate_claim(
                            claim, ValidationContext(before, old_index, prov, root, output)
                        )
                        state = initial_state(claim, prov, result)
                        previous[variant][claim.claim_id] = state
                        parent_row["variants"][variant] = {
                            "provenance": prov.model_dump(mode="json", by_alias=True),
                            "validation": result.model_dump(mode="json"),
                            "state": state.model_dump(mode="json"),
                        }
                        costs.append(
                            {
                                "phase": "parent_production_validation",
                                "group_id": group_id,
                                "variant": variant,
                                "claim_id": claim.claim_id,
                                "actual_calls": 1,
                                "seconds": result.duration_seconds,
                            }
                        )
                else:
                    manifest["parent_exclusions"].append(
                        {"claim_id": claim.claim_id, "reasons": reasons}
                    )
                parents.append(parent_row)
                write_jsonl(output / "parents.jsonl", parents)
            check(len(eligible) >= 4, "runtime parent feasibility gate failed; no children read")
            checkpoint("after_parent:" + group_id)
            prepared.append(
                (group, claims, repo, index_config, cache, before, old_index, eligible, previous)
            )
        for (
            group,
            claims,
            repo,
            index_config,
            cache,
            before,
            old_index,
            eligible,
            previous,
        ) in prepared:
            group_id = group["group_id"]
            children = tuple(group["child_commits"])
            repo_path = Path(repo.path)
            claims_by_id = {claim.claim_id: claim for claim in eligible}
            for commit in children:
                checkpoint("before_child:" + group_id + ":" + commit)
                transition = topology[group_id][commit]
                if before.revision != transition["previous_commit"]:
                    raise ValueError("snapshot loop lost preceding first-parent state")
                tick = time.perf_counter()
                snap = read_snapshot(repo, commit)
                index = build_index(snap, index_config, cache)
                changes = compare_indexes(old_index, index, before, snap)
                costs.append(
                    {
                        "phase": "child_snapshot_index_compare",
                        "group_id": group_id,
                        "commit": commit,
                        "seconds": time.perf_counter() - tick,
                        "index_builds": 1,
                    }
                )
                step = []
                # Reference decisions are deliberately computed only after all policy transitions.
                for variant, policy_id in VARIANTS.items():
                    policy = PolicyConfig(id=policy_id, dependency_depth=1)
                    provs = tuple(provenance[variant][claim.claim_id] for claim in eligible)
                    states = tuple(previous[variant][claim.claim_id] for claim in eligible)
                    variant_changes = changes
                    if policy_id.startswith("file_"):
                        variant_changes = replace(
                            changes,
                            unresolved=index.unresolved,
                            limited_paths=frozenset(index.limitations()),
                            global_unresolved=index.global_unresolved,
                        )
                    decisions = select_claims(
                        SelectionContext(
                            commit, tuple(eligible), provs, states, variant_changes, (), "1.1"
                        ),
                        policy,
                    )
                    for old_state, selection in zip(states, decisions, strict=True):
                        claim = claims_by_id[selection.claim_id]
                        prov = provenance[variant][claim.claim_id]
                        result = (
                            validate_claim(
                                claim, ValidationContext(snap, index, prov, root, output)
                            )
                            if selection.selected
                            else None
                        )
                        state = advance_state(old_state, selection, policy, result, True)
                        previous[variant][claim.claim_id] = state
                        step.append(
                            {
                                "group_id": group_id,
                                "variant": variant,
                                "commit": commit,
                                "claim_id": claim.claim_id,
                                "claim_kind": claim.kind,
                                "eligible": True,
                                "provenance": prov.model_dump(mode="json", by_alias=True),
                                "previous_state": old_state.model_dump(mode="json"),
                                "selection": selection.model_dump(mode="json"),
                                "validation": result.model_dump(mode="json") if result else None,
                                "state": state.model_dump(mode="json"),
                            }
                        )
                        if result:
                            costs.append(
                                {
                                    "phase": "child_production_validation",
                                    "group_id": group_id,
                                    "variant": variant,
                                    "claim_id": claim.claim_id,
                                    "commit": commit,
                                    "logical_calls": 1,
                                    "actual_calls": 1,
                                    "seconds": result.duration_seconds,
                                }
                            )
                references = {}
                for claim in claims:
                    tick = time.perf_counter()
                    references[claim.claim_id] = reference_claim(
                        repo_path,
                        commit,
                        claim,
                        output / "packets" / group_id / commit / claim.claim_id,
                        reference,
                    )
                    costs.append(
                        {
                            "phase": "child_reference",
                            "group_id": group_id,
                            "commit": commit,
                            "claim_id": claim.claim_id,
                            "seconds": time.perf_counter() - tick,
                            "reference_calls": 1,
                            "scored": claim.claim_id in claims_by_id,
                        }
                    )
                    if claim.claim_id not in claims_by_id:
                        for variant in VARIANTS:
                            step.append(
                                {
                                    "group_id": group_id,
                                    "variant": variant,
                                    "commit": commit,
                                    "claim_id": claim.claim_id,
                                    "claim_kind": claim.kind,
                                    "eligible": False,
                                    "selection": None,
                                    "validation": None,
                                    "state": None,
                                }
                            )
                full = {
                    row["claim_id"]: row["validation"]
                    for row in step
                    if row["variant"] == "all_validate" and row["eligible"]
                }
                for row in step:
                    row["trajectory"] = transition
                    row["reference"] = references[row["claim_id"]]
                    row["full_production_validation"] = full.get(row["claim_id"])
                records.extend(step)
                write_jsonl(output / "observations.jsonl", records)
                write_jsonl(output / "costs.jsonl", costs)
                write_json(
                    output / "changes" / group_id / f"{commit}.json",
                    {
                        **transition,
                        "before": before.revision,
                        "after": commit,
                        "files": sorted(changes.files),
                        "symbols": [
                            node.model_dump(mode="json")
                            for node in sorted(changes.symbols, key=str)
                        ],
                        "limited_paths": sorted(changes.limited_paths),
                        "global_unresolved": changes.global_unresolved,
                        "unresolved": [
                            node.model_dump(mode="json")
                            for node in sorted(changes.unresolved, key=str)
                        ],
                        "edges": [
                            edge.model_dump(mode="json", by_alias=True) for edge in changes.edges
                        ],
                    },
                )
                checkpoint("after_child:" + group_id + ":" + commit)
                before, old_index = snap, index
        report = {
            "full23": report_stratum(records, groups),
            "prefix12": report_stratum(
                [row for row in records if row["trajectory"]["step"] <= 12], groups
            ),
            "topology_strata": {
                name: report_stratum(
                    [row for row in records if row["trajectory"]["is_merge"] == merge], groups
                )
                for name, merge in (("merge", True), ("nonmerge", False))
            },
        }
        report["parent_initialization"] = {
            variant: {
                "eligible_parent_claims": sum(row["eligible"] for row in parents),
                "supported": sum(
                    row["eligible"] and row["variants"][variant]["state"]["available"]
                    for row in parents
                ),
                "initially_withheld": sum(
                    row["eligible"] and not row["variants"][variant]["state"]["available"]
                    for row in parents
                ),
                "actual_validation_calls": sum(row["eligible"] for row in parents),
            }
            for variant in VARIANTS
        }
        report["separate_work"] = {
            "parent_reference_calls": sum(
                row.get("reference_calls", 0) for row in costs if row["phase"] == "parent_reference"
            ),
            "child_reference_calls": sum(
                row.get("reference_calls", 0) for row in costs if row["phase"] == "child_reference"
            ),
            "shared_index_builds": sum(row.get("index_builds", 0) for row in costs),
        }
        report["coverage_note"] = (
            "New-derived Packaging development claims; paired predicates and repeated functions/modules/parents remain dependent. Prefix12 is nested in full23; merge strata are descriptive, not causal. No Click overlap evaluation or speedup inference."
        )
        write_json(output / "report.json", report)
        for name, expected in seal["files"].items():
            if file_hash(within(root, name)) != expected:
                raise ValueError(f"sealed input changed during replay: {name}")

        manifest["source_after"] = source_snapshot(ROOT)
        manifest["source_snapshots_match"] = manifest["source_before"] == manifest["source_after"]
        if not manifest["source_snapshots_match"]:
            raise ValueError("implementation workspace changed during replay")
        artifact_hashes = {
            str(path.relative_to(output)): file_hash(path)
            for path in sorted(output.rglob("*"))
            if path.is_file() and path.name != "manifest.json"
        }
        manifest["disk_bytes_after"] = checkpoint("final")["disk_bytes"]
        manifest.update(status="complete", finished_at=now(), artifact_hashes=artifact_hashes)
    except BaseException as error:
        manifest.update(
            status="failed",
            finished_at=now(),
            failure=f"{type(error).__name__}: {error}",
            source_after=source_snapshot(ROOT),
        )
        write_jsonl(output / "observations.jsonl", records)
        write_jsonl(output / "parents.jsonl", parents)
        write_jsonl(output / "costs.jsonl", costs)
        try:
            checkpoint("failure", enforce=False)
        except OSError as usage_error:
            manifest["resource_usage_error"] = str(usage_error)
            manifest["resource_usage"] = {
                "phase": "failure",
                "cpu_seconds": total_cpu() - started_cpu,
                "wall_seconds": time.monotonic() - started_wall,
            }
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
