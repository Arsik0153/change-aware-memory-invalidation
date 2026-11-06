"""Reproduce sealed profile/quiet statistics from retained evidence, never lookups."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys
import tarfile

C2 = "runs/opencode-indexed-transition-candidate-20261106"
QUIET = "runs/opencode-quiet-lookup-confirmation-20261106"
BASE = "runs/opencode-lookup-profile-20261106"
C1 = "runs/opencode-membership-candidate-20261106"
VARIANTS = ["baseline", "candidate1", "candidate2"]
TRACE = [
    "selected_records",
    "returned_records",
    "withheld_records",
    "states_checked_type",
    "states_carried_type",
    "note_states",
]


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root):
    inventory = read(root / "PUBLICATION-MANIFEST.json")["files"]
    for name, row in inventory.items():
        p = root / name
        assert not Path(name).is_absolute() and ".." not in Path(name).parts
        assert not any(x.is_symlink() for x in [p, *p.parents])
        mode = p.lstat()
        assert stat.S_ISREG(mode.st_mode) and mode.st_nlink == 1
        assert (
            sha(p) == row["sha256"]
            and mode.st_size == row["bytes"]
            and stat.S_IMODE(mode.st_mode) == row["mode"]
        )
    return len(inventory)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prerequisite(path, out):
    assert sha(path) == "dad2a64d060cbd8144f78487711e88862b442670d34465d6a2e52731bf2ef435"
    out.mkdir()
    with tarfile.open(path, "r:gz") as archive:
        names = set()
        for m in archive.getmembers():
            assert m.name not in names and m.isfile() and not m.linkname
            names.add(m.name)
            parts = Path(m.name).parts
            assert not Path(m.name).is_absolute() and ".." not in parts
            assert not any(
                x in {".git", "workspace", "cami-state", "private-state", "server-private"}
                for x in parts
            )
            p = out / m.name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(archive.extractfile(m).read())
            p.chmod(m.mode)
    verify(out)


def semantic_proofs(root, old, comparison):
    proofs = []
    for repetition in range(1, 4):
        ns = f"r{repetition}-cami"
        vectors = {v: read(root / C2 / "semantic-vectors" / f"{v}-{ns}.json") for v in VARIANTS}
        assert (
            vectors["baseline"]["semantic_generations"]
            == vectors["candidate1"]["semantic_generations"]
            == vectors["candidate2"]["semantic_generations"]
        )
        for v, base in [
            ("baseline", old / BASE),
            ("candidate1", old / C1),
            ("candidate2", root / C2),
        ]:
            report = read(base / "profile-v1/report.json")
            checks = [
                h
                for name, h in report["artifact_hashes"].items()
                if name.startswith(ns + "/") and name.endswith("/memory.sqlite3")
            ]
            assert checks == [vectors[v]["sqlite_sha256"]]
        proofs.append(
            {
                "namespace": ns,
                "full329record_semantics_exact": True,
                "sqlite_sha256": {v: x["sqlite_sha256"] for v, x in vectors.items()},
                "generation_counts": [
                    {
                        "sequence": g["sequence"],
                        "records": len(g["records"]),
                        "states": g["state_counts"],
                        "verdicts": g["verdict_counts"],
                    }
                    for g in vectors["baseline"]["semantic_generations"]
                ],
            }
        )
    assert proofs == comparison["all329record_semantics_per_generation_exact"]


def profile_comparison(root, old):
    module = load_module("sealed_profile_focus", root / C2 / "compare_candidates.py")
    roots = {
        "baseline": old / BASE / "profile-v1",
        "candidate1": old / C1 / "profile-v1",
        "candidate2": root / C2 / "profile-v1",
    }
    reports = {v: read(p / "report.json") for v, p in roots.items()}
    rows = []
    for repetition in range(1, 4):
        ns = f"r{repetition}-cami"
        for group in [x for x in reports["candidate2"]["cases"] if x["namespace"] == ns]:
            label = group["case"]
            others = {
                v: next(x for x in r["cases"] if x["namespace"] == ns and x["case"] == label)
                for v, r in reports.items()
            }
            for call in group["report"]["cases"]:
                phase = call["label"]
                values = {}
                attributes = {}
                trace = {}
                for v, p in roots.items():
                    directory = p / ns / label
                    result = read(directory / (phase + "-mcp-result.json"))
                    assert result["isError"] is False
                    value = json.loads(result["content"][0]["text"])
                    assert value.pop("audit_receipt")
                    values[v] = value
                    attributes[v] = module.focus(directory / (phase + ".prof"))
                    events = [
                        x
                        for x in map(
                            json.loads, (directory / "backend-trace.jsonl").read_text().splitlines()
                        )
                        if x["event"] == "memory_lookup"
                    ]
                    phases = [x["label"] for x in others[v]["report"]["cases"]]
                    event = events[phases.index(phase)]
                    trace[v] = {k: event.get(k) for k in TRACE}
                assert values["baseline"] == values["candidate1"] == values["candidate2"]
                assert trace["baseline"] == trace["candidate1"] == trace["candidate2"]
                rows.append(
                    {
                        "namespace": ns,
                        "case": phase,
                        "portable_mcp_and_status_exact": True,
                        "checked_carried_trace_counts_exact": True,
                        "trace_counts": trace["candidate2"],
                        "attribution": attributes,
                    }
                )
    original = read(root / C2 / "comparison.json")
    assert rows == original["comparisons"] and len(rows) == 15
    changed = [x for x in rows if x["case"] == "changed-new-process"]
    keys = sorted({k for row in changed for a in row["attribution"].values() for k in a})
    stats = {
        v: {k: module.stats([row["attribution"][v].get(k, 0) for row in changed]) for k in keys}
        for v in VARIANTS
    }
    assert stats == original["changed_profile_attribution"]
    semantic_proofs(root, old, original)


def quiet_comparison(root, out):
    here = root / QUIET
    data = here / "quiet-v1"
    module = load_module("sealed_quiet_rules", here / "summarize_quiet.py")
    report, plan, original = (
        read(data / "report.json"),
        read(data / "plan.json"),
        read(here / "summary.json"),
    )
    sys.path.insert(0, str(root / "scripts/opencode_benchmark/analysis"))
    from classify_literal_calls import authenticate_response, canonical

    rows = []
    costs = []
    resources = []
    portable = {}
    receipts = []
    origins = []
    changed_inputs = []
    catalogs = []
    assert len(report["attempts"]) == 15 and not report["failures"]
    query_hash = hashlib.sha256(canonical(plan["query"])).hexdigest()
    for attempt in report["attempts"]:
        block, v = attempt["block"], attempt["variant"]
        ns = data / f"b{block}-{v}"
        assert attempt["status"] == "passed"
        origins.append(read(ns / "origin-reset.json")["canonical_files"])
        changed_inputs.append(read(ns / "changed-reset.json")["canonical_files"])
        catalogs.append((ns / "memory/prepared/catalog.json").read_bytes())
        construction = module.cgroup(ns / "preparation")
        resources.append({"block": block, "variant": v, "phase": "preparation", **construction})
        operation = read(ns / "preparation/preparation-operation.json")
        metrics = read(ns / "memory/prepared/construction-metrics.json")
        container_seconds = 0
        for entry in attempt["cases"]:
            directory = ns / entry["container_case"]
            container_seconds += entry["container_host_inclusive_seconds"]
            resource = read(directory / "container/report.json")
            assert resource["status"] == "passed" and resource["cleanup_passed"]
            resources.append(
                {
                    "block": block,
                    "variant": v,
                    "phase": entry["container_case"],
                    **module.cgroup(directory / "container"),
                }
            )
            events = [
                x
                for x in map(
                    json.loads, (directory / "backend-trace.jsonl").read_text().splitlines()
                )
                if x["event"] == "memory_lookup"
            ]
            for event, call in zip(events, entry["worker"]["cases"], strict=True):
                assert (
                    event["error"] is None
                    and event["backend"] == "cami"
                    and event["query_sha256"] == query_hash
                )
                response = read(directory / (call["label"] + "-mcp-result.json"))
                assert response["isError"] is False
                value = json.loads(response["content"][0]["text"])
                assert value.pop("audit_receipt")
                full, mode = authenticate_response(response["content"][0]["text"], event)
                assert mode == "compact_verified" and full["query"] == plan["query"]["query"]
                receipts.append(
                    {
                        "block": block,
                        "variant": v,
                        "case": call["label"],
                        "query_sha256": query_hash,
                        "receipt_sha256": event["response_audit"]["receipt_sha256"],
                    }
                )
                portable[(block, v, call["label"])] = value
                rows.append(
                    {
                        "block": block,
                        "variant": v,
                        "case": call["label"],
                        "dispatch_wall_seconds": call["dispatch_wall_seconds"],
                        "dispatch_cpu_self_and_completed_children_seconds": call[
                            "dispatch_cpu_self_and_completed_children_seconds"
                        ],
                        "backend_wall_seconds_nested": event["wall_seconds"],
                        "backend_cpu_seconds_nested": event[
                            "cpu_seconds_self_and_completed_children"
                        ],
                        **{k: event[k] for k in TRACE},
                    }
                )
        phase_fields = [
            "origin_materialization_host_seconds",
            "preparation_host_inclusive_seconds",
            "changed_source_update_host_seconds",
            "final_storage_observation_and_hashing_host_seconds",
        ]
        known = sum(attempt[k] for k in phase_fields) + container_seconds
        costs.append(
            {
                "block": block,
                "variant": v,
                **{
                    k: attempt[k]
                    for k in [
                        "host_variant_seconds_inclusive",
                        *phase_fields,
                        "final_owned_storage_bytes",
                        "final_memory_storage_bytes",
                    ]
                },
                "lookup_containers_host_seconds_inclusive": container_seconds,
                "other_host_orchestration_seconds_residual": attempt[
                    "host_variant_seconds_inclusive"
                ]
                - known,
                "seed_generation_process_seconds_nested": operation["commands"][0]["wall_seconds"],
                "adapter_prepare_process_seconds_nested": operation["commands"][1]["wall_seconds"],
                "adapter_function_seconds_nested": metrics["wall_seconds"],
                "catalog_capture_seconds_nested": metrics["catalog_capture"]["wall_seconds"],
                "registration_batch_seconds_nested": metrics["registration_batch"]["wall_seconds"],
                "preparation_cgroup_cpu_seconds": construction["cpu_seconds"],
            }
        )
    assert (
        rows == original["lookup_rows"]
        and costs == original["variant_cost_rows"]
        and resources == original["resources_per_container_nonadditive_peak"]
    )
    assert len(rows) == len(resources) == len(receipts) == 75
    for block in range(1, 6):
        vectors = {v: read(here / "semantic-vectors" / f"b{block}-{v}.json") for v in VARIANTS}
        assert (
            vectors["baseline"]["semantic_generations"]
            == vectors["candidate1"]["semantic_generations"]
            == vectors["candidate2"]["semantic_generations"]
        )
        for v, vector in vectors.items():
            attempt = next(
                x for x in report["attempts"] if x["block"] == block and x["variant"] == v
            )
            assert [
                h for n, h in attempt["artifact_hashes"].items() if n.endswith("/memory.sqlite3")
            ] == [vector["sqlite_sha256"]]
        for case in plan["cases"]:
            assert (
                portable[(block, "baseline", case)]
                == portable[(block, "candidate1", case)]
                == portable[(block, "candidate2", case)]
            )
    pairs = []
    for case in plan["cases"]:
        for before, after in [
            ("baseline", "candidate1"),
            ("baseline", "candidate2"),
            ("candidate1", "candidate2"),
        ]:
            for metric in plan["metrics"]:
                left = [
                    next(
                        x[metric]
                        for x in rows
                        if x["block"] == b and x["variant"] == before and x["case"] == case
                    )
                    for b in range(1, 6)
                ]
                right = [
                    next(
                        x[metric]
                        for x in rows
                        if x["block"] == b and x["variant"] == after and x["case"] == case
                    )
                    for b in range(1, 6)
                ]
                pairs.append(
                    {
                        "case": case,
                        "comparison": before + "_to_" + after,
                        "metric": metric,
                        **module.compare(left, right),
                    }
                )
    phases = []
    for before, after in [
        ("baseline", "candidate1"),
        ("baseline", "candidate2"),
        ("candidate1", "candidate2"),
    ]:
        for metric in [
            "preparation_host_inclusive_seconds",
            "preparation_cgroup_cpu_seconds",
            "host_variant_seconds_inclusive",
            "changed_source_update_host_seconds",
            "final_storage_observation_and_hashing_host_seconds",
        ]:
            left = [
                next(x[metric] for x in costs if x["block"] == b and x["variant"] == before)
                for b in range(1, 6)
            ]
            right = [
                next(x[metric] for x in costs if x["block"] == b and x["variant"] == after)
                for b in range(1, 6)
            ]
            phases.append(
                {
                    "comparison": before + "_to_" + after,
                    "metric": metric,
                    **module.compare(left, right),
                }
            )
    assert (
        pairs == original["all_case_comparisons"]
        and phases == original["separate_phase_comparisons"]
    )
    primary = [x for x in pairs if x["case"] == plan["primary_case"]]
    assert primary == original["primary_comparisons"]
    assert all(
        x["classification"] == "no_measurable_difference"
        for x in primary
        if x["comparison"].startswith("baseline_to_")
    )
    assert all(
        x["classification"] == "lower_time_for_candidate_in_this_microbenchmark"
        for x in primary
        if x["comparison"] == "candidate1_to_candidate2"
    )
    for filename, values in [
        ("lookup-samples.csv", rows),
        ("variant-costs.csv", costs),
        ("resources.csv", resources),
    ]:
        header = next(csv.reader(io.StringIO((here / filename).read_text())))
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=header)
        writer.writeheader()
        writer.writerows(values)
        assert buffer.getvalue().encode() == (here / filename).read_bytes()
        (out / filename).write_bytes(buffer.getvalue().encode())
    assert (
        all(x == origins[0] for x in origins)
        and all(x == changed_inputs[0] for x in changed_inputs)
        and all(x == catalogs[0] for x in catalogs)
    )
    extra = read(here / "additional-verification.json")
    assert receipts == extra["receipts"] and extra["full_compact_receipts_verified"] == 75
    return {
        "quiet_lookup_rows_exact": 75,
        "quiet_resource_rows_exact": 75,
        "quiet_all_case_comparisons_exact": True,
        "quiet_separate_phase_comparisons_exact": True,
        "quiet_three_csv_files_byte_exact": True,
        "quiet_compact_receipts_exact": 75,
        "quiet_semantic_namespaces_equal": 15,
        "primary_baseline_comparisons": "no_measurable_difference",
        "secondary_candidate1_to_candidate2_primary": "lower_time_for_candidate_in_this_microbenchmark",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.root.absolute(), args.out.absolute()
    assert not root.is_relative_to(out) and not out.is_relative_to(root)
    out.mkdir(exist_ok=False)
    count = verify(root)
    old = out / "prerequisite"
    prerequisite(root / "prerequisites/baseline-candidate1-public-profile-evidence.tar.gz", old)
    profile_comparison(root, old)
    quiet = quiet_comparison(root, out)
    report = {
        "status": "passed",
        "verified_supplement_files": count,
        "prerequisite_archive_exact": True,
        "candidate2_profile_comparisons_exact": 15,
        "profile_semantic_namespaces_equal": 9,
        **quiet,
        "model_calls": 0,
        "profile_or_timing_reruns": 0,
        "Docker_calls": 0,
        "network_calls": 0,
        "SQLite_bodies_read": False,
        "scope": "Retained hash-bound profiles/results/semantic exports/statistics only. Omitted workspace and DB bodies are not reconstructed or claimed verified. No model/end-to-end inference.",
    }
    (out / "verification.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
