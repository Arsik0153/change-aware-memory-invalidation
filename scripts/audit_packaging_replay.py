#!/usr/bin/env python3
"""Independent stdlib Packaging replay audit; no production/driver/reference imports."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys

from packaging_audit_common import (
    advance,
    canonical,
    dump,
    parse,
    require,
    rows,
    safe,
    sha,
    signature,
    unique_index,
)
from packaging_audit_inputs import Frozen, VARIANTS, checker_metadata, method, reviews
from packaging_audit_git import Project, parent_population
from packaging_audit_metrics import report as recomputed_report
from packaging_audit_syntax import changes as compare, index, production


def node(row):
    return row["path"], row.get("qualname")


def edge(row):
    return node(row["from"]), node(row["to"]), row["relation"], row["origin"]


def artifact_check(result, manifest):
    files = {
        str(p.relative_to(result))
        for p in result.rglob("*")
        if p.is_file() and p != result / "manifest.json"
    }
    require(files == set(manifest["artifact_hashes"]), "artifact exact file coverage")
    for name, expected in manifest["artifact_hashes"].items():
        require(
            sha(safe(result, name).read_bytes()) == expected, "artifact file hash mismatch: " + name
        )
    return files


def validation(actual, claim, commit, prov, blobs, indexed):
    require(actual is not None, "missing selected production validation")
    verdict, reason = production(claim, blobs, indexed)
    evidence = [commit + ":" + claim["subject"]["path"] + ":" + claim["subject"]["qualname"]]
    expected = {
        "schema_version": 1,
        "claim_id": claim["claim_id"],
        "commit": commit,
        "validator": "structural",
        "verdict": verdict,
        "reason": reason,
        "evidence": evidence,
        "input_hash": sha(
            canonical(
                {
                    "claim": claim,
                    "commit": commit,
                    "evidence": evidence,
                    "validator_version": "5",
                    "provenance": prov,
                }
            )
        ),
        "test_executions": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "logs": [],
        "cache_hit": False,
        "original_measurement": None,
    }
    require(
        set(actual) == set(expected) | {"duration_seconds", "cpu_seconds"},
        "exact validation schema",
    )
    for key, value in expected.items():
        require(
            canonical(actual[key]) == canonical(value),
            "independent production validation " + key + " mismatch for " + claim["claim_id"],
        )
    require(
        all(
            isinstance(actual[k], (float, int)) and math.isfinite(actual[k]) and actual[k] >= 0
            for k in ("duration_seconds", "cpu_seconds")
        ),
        "invalid validation costs",
    )


def selection(cid, commit, variant, prov, previous, changes, current_index, claim):
    reasons = []
    path, name = claim["subject"]["path"], claim["subject"]["qualname"]
    a = prov["anchors"][0]
    if variant == "all_validate":
        reasons.append("all_claims")
    else:
        if prov["known_incomplete"] or prov["unresolved_reasons"] or not prov["anchors"]:
            reasons.append("known_incomplete")
        limited = (
            current_index["limitations"] if variant == "file_anchor" else changes["limited_paths"]
        )
        if {path, a["path"]} & limited:
            reasons.append("analysis_limitation")
        if variant == "file_anchor":
            if path in changes["files"]:
                reasons.append("subject_file_changed")
            if a["path"] in changes["files"]:
                reasons.append("anchor_file_changed")
        else:
            if (path, name) in changes["symbols"]:
                reasons.append("subject_changed")
            if (a["path"], a.get("qualname")) in changes["symbols"]:
                reasons.append("symbol_or_dependency_changed")
    if not previous["available"]:
        reasons.append("previously_unavailable")
    return {
        "schema_version": 1,
        "claim_id": cid,
        "commit": commit,
        "selected": bool(reasons),
        "reasons": sorted(set(reasons)),
    }


def changes_check(raw, computed, transition, before, after):
    require(
        all(raw[k] == v for k, v in transition.items())
        and raw["before"] == before
        and raw["after"] == after,
        "change full topology/basis",
    )
    require(
        set(raw["files"]) == computed["files"] and len(raw["files"]) == len(computed["files"]),
        "changed files independently recomputed",
    )
    for key in ("symbols", "unresolved"):
        require(
            {node(x) for x in raw[key]} == computed[key] and len(raw[key]) == len(computed[key]),
            "independent " + key + " change metadata",
        )
    require(
        set(raw["limited_paths"]) == computed["limited_paths"]
        and raw["global_unresolved"] == computed["global_unresolved"],
        "independent limitation metadata",
    )
    require(
        {edge(x) for x in raw["edges"]} == computed["edges"]
        and len(raw["edges"]) == len(computed["edges"]),
        "independent import/call edge changes",
    )


def cohort_and_provenance(f):
    p = f.protocol
    cohort_rows = f.json(p["cohort_path"])
    cohort = unique_index(cohort_rows, lambda x: x["claim"]["claim_id"], "derived cohort")
    require(len(cohort) == 24, "24 new-derived cohort claims")
    claims = {}
    for g in p["groups"]:
        values = f.rows(g["claims_path"])
        require(len(values) == 8, "8 exact claims/group")
        for c in values:
            cid = c["claim_id"]
            require(cid not in claims and cid in cohort, "claim coverage/identity")
            row = cohort[cid]
            rank = row["function_rank"]
            suffix = "exists" if c["kind"] == "symbol_exists" else "signature"
            require(
                row["schema_version"] == 1
                and row["origin_kind"] == "new_derived_parent_claim"
                and row["original_candidate_id"] is None
                and row["split"] == "development"
                and row["claim"] == c
                and row["claim_sha256"] == sha(canonical(c))
                and row["group_id"] == g["group_id"]
                and c["repo_id"] == "packaging"
                and c["origin_commit"] == g["parent_commit"]
                and type(rank) is int
                and rank in range(4)
                and cid == f"{g['group_id']}-f{rank:02d}-{suffix}"
                and c["kind"] in {"symbol_exists", "signature_equals"}
                and c["subject"]["node_kind"] == "function"
                and c["subject"]["qualname"].isidentifier(),
                "exact new-derived claim identity/hash",
            )
            claims[cid] = c
    require(
        set(claims) == set(cohort) and set(p["provenance"]) == set(VARIANTS),
        "complete exact claim/provenance coverage",
    )
    prov = {}
    for v in VARIANTS:
        prov[v] = unique_index(
            f.rows(p["provenance"][v]), lambda x: x["claim_id"], "provenance claim"
        )
        require(set(prov[v]) == set(cohort), "all24 provenance rows pervariant")
        for cid, row in prov[v].items():
            require(
                row["dependencies"] == []
                and len(row["anchors"]) == 1
                and row["known_incomplete"] == (v == "known_incomplete")
                and bool(row["unresolved_reasons"]) == (v == "known_incomplete"),
                "dependency-free explicit provenance assumption",
            )
            a = row["anchors"][0]
            a.setdefault("qualname", None)
            a.setdefault("start_line", None)
            a.setdefault("end_line", None)
            scope = "file" if v == "file_anchor" else "symbol"
            expected = cohort[cid]
            require(
                a["scope"] == scope
                and a["path"] == claims[cid]["subject"]["path"]
                and a["qualname"]
                == (None if scope == "file" else claims[cid]["subject"]["qualname"])
                and a["observed_commit"] == claims[cid]["origin_commit"]
                and a["origin"] == "static"
                and a["content_hash"]
                == expected["parent_source_sha256" if scope == "file" else "symbol_ast_sha256"],
                "exact frozen provenance anchor",
            )
    return cohort, claims, prov


def audit(root, result, *, authored=False, repo_override=None):
    require(
        sys.implementation.name == "cpython" and sys.version_info[:2] == (3, 12),
        "shared pinned CPython3.12 required",
    )
    root, result = root.resolve(), result.resolve()
    manifest = parse((result / "manifest.json").read_bytes())
    require(
        manifest["status"] == "complete" and manifest["evaluation_eligible"] is False,
        "completed development-only result required",
    )
    files = artifact_check(result, manifest)
    f = Frozen(root, manifest, authored)
    p = f.protocol
    metadata, topology = method(f)
    require(
        parse((result / "topology.json").read_bytes()) == topology,
        "output topology exact frozen mapping",
    )
    cohort, claims, prov = cohort_and_provenance(f)
    decisions, confirmations = reviews(f, cohort)
    generation = f.json(p["parent_generation_manifest_path"])
    require(
        generation["status"] == "prepared_awaiting_packet_seal_and_independent_review"
        and generation["parent_only"] is True
        and generation["child_source_access"] is False
        and generation["reference_calls"] == generation["AI_reviews"] == 0
        and generation["candidate_claims"] == 24
        and generation["selected_function_occurrences"] == 12
        and generation["public_cases"] == 36
        and generation["authored_controls"] == 12,
        "reference-free parent generation boundary",
    )
    for name, expected in generation["artifact_hashes"].items():
        target = str(Path(p["parent_generation_manifest_path"]).parent / name)
        require(sha(f.read(target)) == expected, "complete parent-generation artifact binding")
    parents = rows(result / "parents.jsonl")
    obs = rows(result / "observations.jsonl")
    costs = rows(result / "costs.jsonl")
    pi = unique_index(parents, lambda x: (x["group_id"], x["claim"]["claim_id"]), "parent record")
    oi = unique_index(
        obs, lambda x: (x["group_id"], x["commit"], x["claim_id"], x["variant"]), "observation"
    )
    parent_keys = {
        (g["group_id"], c["claim_id"])
        for g in p["groups"]
        for c in claims.values()
        if c["origin_commit"] == g["parent_commit"]
    }
    expected_keys = {
        (gid, commit, cid, v)
        for gid, cid in parent_keys
        for g in p["groups"]
        if g["group_id"] == gid
        for commit in g["child_commits"]
        for v in VARIANTS
    }
    require(set(pi) == parent_keys and len(parents) == 24, "exact24 parent records")
    require(
        set(oi) == expected_keys and len(obs) == 2208, "exact2208 observations / four552 variants"
    )
    project = Project(root, p, metadata, repo_override)
    packets = {}
    snapshots = {}
    indices = {}
    populations = {}
    expected_files = {
        "topology.json",
        "parents.jsonl",
        "observations.jsonl",
        "costs.jsonl",
        "report.json",
    }
    checker = checker_metadata(f, manifest["python"].split()[0])
    expected_costs = []
    cost_seconds = {}
    expected_eligible = []
    exclusions = []
    for g in p["groups"]:
        gid = g["group_id"]
        group_claims = f.rows(g["claims_path"])
        previous = None
        for commit in [g["parent_commit"], *g["child_commits"]]:
            blobs = project.snapshot(commit)
            indexed = index(blobs)
            snapshots[commit] = blobs
            indices[commit] = indexed
            phase = "parent_snapshot_index" if previous is None else "child_snapshot_index_compare"
            expected_costs.append((phase, gid, commit, None, None))
            if previous is None:
                selected, population = parent_population(g, blobs, indexed, f)
                populations[gid] = population
                for c in group_claims:
                    row = cohort[c["claim_id"]]
                    rank, path, name, fn = selected[row["function_rank"]]
                    require(
                        c["subject"]["path"] == path
                        and c["subject"]["qualname"] == name
                        and row["rank_sha256"] == rank
                        and row["symbol_ast_sha256"] == sha(dump(fn).encode())
                        and row["parent_source_sha256"] == sha(blobs[path]["raw"])
                        and row["parent_git_blob_object_id"] == blobs[path]["oid"],
                        "complete parent ranking to exact cohort binding",
                    )
                    expected_pred = (
                        {"type": "symbol_exists", "expected": True}
                        if c["kind"] == "symbol_exists"
                        else {"type": "signature_equals", "expected_signature": signature(fn)}
                    )
                    require(
                        c["predicate"] == expected_pred, "parent-derived predicate/signature facts"
                    )
                    for v in VARIANTS:
                        a = prov[v][c["claim_id"]]["anchors"][0]
                        require(
                            (a["start_line"], a["end_line"])
                            == (
                                (1, len(blobs[path]["raw"].decode().splitlines()))
                                if v == "file_anchor"
                                else (fn.lineno, fn.end_lineno)
                            ),
                            "full module/symbol provenance range",
                        )
            else:
                change_path = "changes/" + gid + "/" + commit + ".json"
                expected_files.add(change_path)
                computed = compare(snapshots[previous], blobs, indices[previous], indexed)
                changes_check(
                    parse((result / change_path).read_bytes()),
                    computed,
                    topology[gid][commit],
                    previous,
                    commit,
                )
            for c in group_claims:
                cid = c["claim_id"]
                decision = project.packet(result, gid, commit, c, checker)
                packets[(gid, commit, cid)] = decision
                directory = result / "packets" / gid / commit / cid
                expected_files.update(
                    str(x.relative_to(result)) for x in directory.iterdir() if x.is_file()
                )
                expected_costs.append(
                    (
                        "parent_reference" if previous is None else "child_reference",
                        gid,
                        None if previous is None else commit,
                        cid,
                        None,
                    )
                )
                if previous is None:
                    parent = pi[(gid, cid)]
                    eligible = decisions[cid]["eligible"]
                    require(
                        parent["claim"] == c
                        and parent["claim_sha256"] == sha(canonical(c))
                        and parent["eligible"] == eligible
                        and parent["exclusion_reasons"] == decisions[cid]["exclusion_reasons"]
                        and parent["reference"] == decision
                        and parent["ai_confirmation"] == confirmations[cid],
                        "parent exact cohort/reference/AI eligibility binding",
                    )
                    require(
                        decision["verdict"] == decisions[cid]["reference_verdict"]
                        and decision.get("facts") == confirmations[cid]["reference"].get("facts"),
                        "fresh runtime parent vs sealed phase3 reference facts",
                    )
                    if eligible:
                        expected_eligible.append(cid)
                    else:
                        exclusions.append(
                            {"claim_id": cid, "reasons": decisions[cid]["exclusion_reasons"]}
                        )
            previous = commit
    require(
        len(snapshots) == 72 and files == expected_files,
        "exact72 snapshots and output artifact layout",
    )
    require(
        manifest["eligible_claims"] == expected_eligible
        and manifest["parent_exclusions"] == exclusions,
        "manifest exact parent eligibility/exclusions",
    )
    for g in p["groups"]:
        gid, parent_commit = g["group_id"], g["parent_commit"]
        for c in f.rows(g["claims_path"]):
            cid = c["claim_id"]
            parent = pi[(gid, cid)]
            eligible = decisions[cid]["eligible"]
            require(
                set(parent["variants"]) == (set(VARIANTS) if eligible else set()),
                "parent initialized variant coverage",
            )
            for v in VARIANTS:
                provenance = prov[v][cid]
                if eligible:
                    pr = parent["variants"][v]
                    require(pr["provenance"] == provenance, "parent normalized provenance")
                    validation(
                        pr["validation"],
                        c,
                        parent_commit,
                        provenance,
                        snapshots[parent_commit],
                        indices[parent_commit],
                    )
                    previous = {
                        "schema_version": 1,
                        "claim_id": cid,
                        "revision": parent_commit,
                        "state": "needs_validation",
                        "last_checked_commit": None,
                        "last_supported_commit": None,
                        "last_verdict": None,
                        "basis": "validated",
                        "current_provenance": provenance,
                        "available": False,
                        "withheld_reason": "parent_not_validated",
                    }
                    previous = advance(previous, parent_commit, True, pr["validation"])
                    require(
                        canonical(pr["state"]) == canonical(previous),
                        "parent state independently advanced",
                    )
                    expected_costs.append(("parent_production_validation", gid, None, cid, v))
                    cost_seconds[("parent_production_validation", gid, None, cid, v)] = pr[
                        "validation"
                    ]["duration_seconds"]
                before = parent_commit
                for commit in g["child_commits"]:
                    row = oi[(gid, commit, cid, v)]
                    require(
                        row["claim_kind"] == c["kind"]
                        and row["eligible"] == eligible
                        and row["reference"] == packets[(gid, commit, cid)]
                        and row["trajectory"] == topology[gid][commit],
                        "observation exact kind/eligibility/reference/topology",
                    )
                    if not eligible:
                        require(
                            row["selection"] is None
                            and row["validation"] is None
                            and row["state"] is None
                            and row["full_production_validation"] is None,
                            "excluded observation unscored/no validation/state",
                        )
                        continue
                    computed = compare(
                        snapshots[before], snapshots[commit], indices[before], indices[commit]
                    )
                    expected_selection = selection(
                        cid, commit, v, provenance, previous, computed, indices[commit], c
                    )
                    require(
                        row["provenance"] == provenance
                        and row["previous_state"] == previous
                        and canonical(row["selection"]) == canonical(expected_selection),
                        "independent previous state/provenance/selection",
                    )
                    if expected_selection["selected"]:
                        validation(
                            row["validation"],
                            c,
                            commit,
                            provenance,
                            snapshots[commit],
                            indices[commit],
                        )
                        key = ("child_production_validation", gid, commit, cid, v)
                        expected_costs.append(key)
                        cost_seconds[key] = row["validation"]["duration_seconds"]
                    else:
                        require(row["validation"] is None, "unselected validation must be absent")
                    previous = advance(
                        previous, commit, expected_selection["selected"], row["validation"]
                    )
                    require(
                        canonical(row["state"]) == canonical(previous),
                        "independent state/availability transition",
                    )
                    require(
                        row["full_production_validation"]
                        == oi[(gid, commit, cid, "all_validate")]["validation"],
                        "all_validate comparison identity",
                    )
                    before = commit
    actual_costs = []
    for row in costs:
        key = (
            row["phase"],
            row["group_id"],
            row.get("commit"),
            row.get("claim_id"),
            row.get("variant"),
        )
        actual_costs.append(key)
        require(
            isinstance(row["seconds"], (int, float))
            and math.isfinite(row["seconds"])
            and row["seconds"] >= 0,
            "finite nonnegative cost",
        )
        if "production_validation" in row["phase"]:
            require(
                row["actual_calls"] == 1
                and row.get("logical_calls", 1) == 1
                and row["seconds"] == cost_seconds[key],
                "exact actual/logical validation cost/duration",
            )
        elif "reference" in row["phase"]:
            require(row["reference_calls"] == 1, "reference call count")
            if row["phase"] == "child_reference":
                require(
                    row["scored"] == decisions[row["claim_id"]]["eligible"],
                    "reference scored/excluded status",
                )
        else:
            require(row["index_builds"] == 1, "shared index count")
    require(
        Counter(actual_costs) == Counter(expected_costs),
        "exact cost phase/group/commit/claim/variant multiplicities",
    )
    expected = recomputed_report(obs, parents, p, costs)
    require(
        canonical(parse((result / "report.json").read_bytes())) == canonical(expected),
        "full23/prefix12/group/kind/merge aggregate recomputation",
    )
    resource_check(manifest, p)
    return {
        "status": "pass",
        "audit_runtime_source_hashes": {
            name: sha((Path(__file__).resolve().parent / name).read_bytes())
            for name in (
                "audit_packaging_replay.py",
                "packaging_audit_common.py",
                "packaging_audit_inputs.py",
                "packaging_audit_git.py",
                "packaging_audit_syntax.py",
                "packaging_audit_metrics.py",
            )
        },
        "manifest_sha256": sha((result / "manifest.json").read_bytes()),
        "protocol_sha256": manifest["protocol_sha256"],
        "seal_sha256": sha(
            __import__("packaging_audit_common").git(
                root, "cat-file", "blob", f.commit + ":" + p["seal_path"]
            )
        ),
        "implementation_commit": f.commit,
        "artifact_files_checked": len(files),
        "sealed_files_checked": len(f.seal["files"]),
        "historical_source_files_checked": f.source_count,
        "production_Python_files_checked": 53,
        "production_unchanged_since": "700ebf2" if not authored else "authored infrastructure copy",
        "reference_v2_sha256": p["reference_sha256"],
        "historical_fallback_paths": f.historical,
        "authorized_snapshot_count": len(snapshots),
        "authorized_step_count": 69,
        "parent_records": len(parents),
        "observation_records": len(obs),
        "reference_packets_checked": len(packets),
        "AI_primary_contexts_checked": 6,
        "authored_controls_checked": 12,
        "parent_population_checks": populations,
        "actual_validation_calls_by_variant": {
            v: expected["full23"]["variants"][v]["actual_validation_calls"] for v in VARIANTS
        },
        "phase3_reference_calls": 36,
        "runtime_parent_reference_calls": 24,
        "runtime_child_reference_calls": 552,
        "all_phase_reference_calls": 612,
        "cost_rows_checked": len(costs),
        "source_access_log": project.log,
        "authorized_project_commit_ids": project.allowed,
        "recomputed_report": expected,
        "limits": [
            "Trust roots are independently pinned final protocol/seal plus local offline Git ODB, not cryptographic signatures.",
            "Shared CPython3.12 ast/dump; syntactic claims establish no runtime behavior or behavioral equivalence.",
            "Raw timing/call records reconcile exactly; past physical execution and elapsed time are not independently observed.",
            "24 claims are paired predicates on12 function occurrences across3 dependent histories;552 rows/variant are repeated observations.",
            "Prefix and merge/group/kind projections overlap; they provide no independent sample, causal merge effect, speedup or broader-project generalization.",
            "Review identity/context independence is declared; model weights/training independence and evidence reasoning truth are not established.",
        ],
    }


def resource_check(manifest, p):
    expected = ["after_global_preflight"]
    for g in p["groups"]:
        expected.extend(["before_parent:" + g["group_id"], "after_parent:" + g["group_id"]])
    for g in p["groups"]:
        for commit in g["child_commits"]:
            expected.extend(
                [
                    "before_child:" + g["group_id"] + ":" + commit,
                    "after_child:" + g["group_id"] + ":" + commit,
                ]
            )
    expected.append("final")
    checkpoints = manifest["resource_checkpoints"]
    require(
        [x["phase"] for x in checkpoints] == expected and len(checkpoints) == 146,
        "exact observed resource checkpoint coverage",
    )
    cpu = wall = -1
    for point in checkpoints:
        require(
            point["disk_scope"] == "repositories_and_output"
            and 0 <= point["disk_bytes"] <= 2 * 1024**3
            and cpu <= point["cpu_seconds"] <= 1200
            and wall <= point["wall_seconds"] <= 1800,
            "recorded observed resource caps/monotonic clocks",
        )
        cpu, wall = point["cpu_seconds"], point["wall_seconds"]
    require(
        manifest["resource_usage"] == checkpoints[-1]
        and manifest["disk_bytes_before"] == checkpoints[0]["disk_bytes"]
        and manifest["disk_bytes_after"] == checkpoints[-1]["disk_bytes"],
        "final resource accounting",
    )


def default_root():
    return next(
        (p for p in Path(__file__).resolve().parents if (p / "src/cami").is_dir()), Path.cwd()
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repo", type=Path)
    parser.add_argument(
        "--authored-fixture",
        action="store_true",
        help="Only for isolated authored fixture workspace carrying its explicit marker; bypasses real protocol SHA pins.",
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    try:
        result = audit(
            args.root, args.result, authored=args.authored_fixture, repo_override=args.repo
        )
    except Exception as error:
        (args.out / "report.json").write_text(
            json.dumps(
                {"status": "fail", "failure": type(error).__name__ + ": " + str(error)}, indent=2
            )
            + "\n"
        )
        raise
    (args.out / "report.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k
                not in {
                    "source_access_log",
                    "recomputed_report",
                    "parent_population_checks",
                    "limits",
                    "historical_fallback_paths",
                    "authorized_project_commit_ids",
                }
            }
        )
    )


if __name__ == "__main__":
    main()
