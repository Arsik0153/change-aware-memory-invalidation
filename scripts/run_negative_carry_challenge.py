#!/usr/bin/env python3
"""Sealed authored challenge and complete-maintenance benchmark; no corpus reader."""
# ruff: noqa: E402
from __future__ import annotations

import argparse
import cProfile
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import pstats
import statistics
import sys
import time

STAGE = Path(__file__).resolve().parent
ROOT = next(parent for parent in STAGE.parents if (parent / "src/cami").is_dir())
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(STAGE))

from cami.artifacts import file_hash, read_json, reserve, within, write_json, write_jsonl
from scripts.verify_cami import source_snapshot
from negative_carry_challenge import VARIANTS, prepare_histories, run_history


def preflight(path):
    plan = read_json(path)
    if plan.get("schema_version") != 1 or plan.get("status") != "sealed":
        raise ValueError("requires a newly sealed authored challenge protocol")
    if (path.parent / plan["root"]).resolve() != ROOT:
        raise ValueError("challenge workspace root mismatch")
    seal = read_json(within(ROOT, plan["seal_path"]))
    if seal["protocol_sha256"] != file_hash(path):
        raise ValueError("challenge protocol hash mismatch")
    for name, expected in seal["files"].items():
        if file_hash(within(ROOT, name)) != expected:
            raise ValueError(f"challenge seal mismatch: {name}")
    runtime_names = ("run_negative_carry_challenge.py", "negative_carry_challenge.py", "negative_carry.py",
                     "negative_carry_witness.py", "blob_negative_carry.py")
    required = [str((STAGE / name).relative_to(ROOT)) for name in runtime_names]
    test_path = plan["test_path"]
    if Path(test_path).name not in {"test_negative_carry.py", "test_negative_structural_carry.py"}:
        raise ValueError("challenge must bind its authored test module")
    required += [test_path, "pyproject.toml", ".python-version", "uv.lock"]
    required += [str(path.relative_to(ROOT)) for path in (ROOT / "src/cami").rglob("*.py")]
    required += ["scripts/verify_cami.py", "scripts/real_structural_replay_support.py", "scripts/structural_checker_v2.py"]
    if not set(required) <= set(plan["implementation_paths"]) or not set(plan["implementation_paths"]) <= set(seal["files"]):
        raise ValueError("challenge implementation/reference inventory is incomplete")
    if plan["variants"] != list(VARIANTS) or plan["paired_repetitions"] < 21:
        raise ValueError("requires all three variants and at least 21 paired repetitions")
    if plan["histories_per_block"] < 1 or plan["warmup_blocks"] < 1 or plan["profile_history_pack_repetitions"] < 1:
        raise ValueError("requires fixed positive warmup/block sizes")
    import re
    ids = [case["id"] for case in plan["histories"]]
    if len(ids) != len(set(ids)) or any(re.fullmatch(r"[a-z0-9_]+", value) is None for value in ids):
        raise ValueError("requires safe unique authored history identifiers")
    return plan, seal


def run_block(histories, variant, repetitions):
    counts, endpoints = {}, {}
    for _ in range(repetitions):
        for history in histories:
            result = run_history(history, variant)
            endpoints[history.id] = result["endpoint"]
            for key, value in result["counts"].items():
                counts[key] = counts.get(key, 0) + value
    return {"counts": counts, "endpoints": endpoints}


def check_block(result, expected, repetitions):
    if result["endpoints"] != expected["endpoints"]:
        raise ValueError("timed maintenance endpoint changed")
    if result["counts"] != {key: value * repetitions for key, value in expected["counts"].items()}:
        raise ValueError("timed actual work counters changed")


def now():
    return datetime.now(timezone.utc).isoformat()


def execute(protocol_path, output):
    protocol_path, output = protocol_path.resolve(), output.resolve()
    reserve(output)
    manifest = {"status": "running", "started_at": now(), "source_before": source_snapshot(ROOT),
                "python": sys.version, "platform": platform.platform(), "cpu_count": os.cpu_count(),
                "load_average_before": os.getloadavg(), "evaluation_eligible": False,
                "corpus_access": False, "source_execution": False, "network": False,
                "measured_region": "complete select+eligibility+witness+actual_validate+advance loop over authored histories",
                "excluded_setup": "Git authoring, production snapshot/index/compare, independent reference, output serialization",
                "error_count": 0, "inference": "authored workload only; limiter profile required before performance recommendation"}
    write_json(output / "manifest.json", manifest)
    try:
        if manifest["source_before"]["source_status"]:
            raise ValueError("commit implementation source before measurement")
        plan, seal = preflight(protocol_path)
        manifest.update(protocol=plan, seal=seal, protocol_sha256=file_hash(protocol_path))
        tick, cpu = time.perf_counter_ns(), time.process_time_ns()
        context_costs = []
        histories = prepare_histories(plan, output, ROOT, context_costs)
        setup = {"wall_ns": time.perf_counter_ns() - tick, "cpu_ns": time.process_time_ns() - cpu,
                 "histories": len(histories), "transitions": sum(len(history.frames) for history in histories),
                 "parent_actual_validation_calls": len(histories),
                 "fresh_comparison_calls": sum(len(history.frames) for history in histories),
                 "independent_reference_calls": sum(len(history.frames) for history in histories),
                 "candidate_only_context_binding": context_costs,
                 "candidate_context_binding_wall_ns": sum(cost["wall_ns"] for cost in context_costs),
                 "candidate_context_binding_cpu_ns": sum(cost["cpu_ns"] for cost in context_costs),
                 "cost_note": "Total setup includes candidate-only context identity creation; this overhead is not a baseline end-to-end saving."}
        rows, expected = [], {}
        for variant in VARIANTS:
            for history in histories:
                rows.extend(run_history(history, variant, capture=True)["rows"])
            expected[variant] = run_block(histories, variant, 1)
        write_jsonl(output / "correctness.jsonl", rows)
        write_json(output / "setup.json", setup)
        write_json(output / "expected-work.json", expected)
        size = plan["histories_per_block"]
        for _ in range(plan["warmup_blocks"]):
            for variant in VARIANTS:
                check_block(run_block(histories, variant, size), expected[variant], size)
        measurements = []
        for repetition in range(plan["paired_repetitions"]):
            offset = repetition % len(VARIANTS)
            order = list(VARIANTS[offset:] + VARIANTS[:offset])
            if repetition % 2:
                order.reverse()
            for order_position, variant in enumerate(order):
                wall_start, cpu_start = time.perf_counter_ns(), time.process_time_ns()
                result = run_block(histories, variant, size)
                cpu_ns, wall_ns = time.process_time_ns() - cpu_start, time.perf_counter_ns() - wall_start
                check_block(result, expected[variant], size)
                measurements.append({"repetition": repetition, "order_position": order_position,
                    "variant": variant, "wall_ns": wall_ns, "cpu_ns": cpu_ns, "history_pack_repetitions": size, "histories_in_pack": len(histories),
                    "actual_history_executions": size * len(histories),
                    "actual_transition_executions": size * sum(len(history.frames) for history in histories),
                    "counts": result["counts"]})
        write_jsonl(output / "timings.jsonl", measurements)
        # Profiling is a separate post-measurement phase; never mix these samples.
        profile_rows = []
        profile_size = plan["profile_history_pack_repetitions"]
        for variant in VARIANTS:
            profiler = cProfile.Profile()
            profiled_result = profiler.runcall(run_block, histories, variant, profile_size)
            check_block(profiled_result, expected[variant], profile_size)
            stats = pstats.Stats(profiler).strip_dirs()
            profile_path = output / "profiles" / f"{variant}.prof"
            profile_path.parent.mkdir(exist_ok=True)
            stats.dump_stats(str(profile_path))
            top = sorted(stats.stats.items(), key=lambda pair: pair[1][3], reverse=True)[:plan["profile_top_functions"]]
            functions = [{"function": f"{key[0]}:{key[1]}:{key[2]}", "primitive_calls": value[0],
                          "total_calls": value[1], "own_seconds": value[2], "cumulative_seconds": value[3]}
                         for key, value in top]
            record = {"phase": "separate_limiter_profile", "variant": variant,
                      "history_pack_repetitions": profile_size, "actual_history_executions": profile_size * len(histories),
                      "counts": profiled_result["counts"], "top_cumulative_functions": functions,
                      "included_in_timing_samples": False}
            profile_rows.append(record)
            write_json(output / "profiles" / f"{variant}.json", record)
        write_json(output / "profiling-work.json", profile_rows)
        summary = {"status": "measured_authored_workload", "error_count": 0,
                   "performance_recommendation": "inconclusive_until_separate_profile_and_variation_review",
                   "profile_work": [{"variant": row["variant"], "counts": row["counts"]} for row in profile_rows],
                   "variants": {}, "paired_deltas": {},
                   "cost_limit": "Setup/index/reference are excluded from maintenance timings and reported separately; these timings do not establish end-to-end corpus savings."}
        summary["minimum_block_ns"] = plan["minimum_block_ns"]
        summary["blocks_below_clock_noise_floor"] = sum(row["wall_ns"] < plan["minimum_block_ns"] for row in measurements)
        summary["candidate_only_context_binding_setup"] = context_costs
        for variant in VARIANTS:
            variant_rows = [row for row in measurements if row["variant"] == variant]
            summary["variants"][variant] = {unit: {"median": statistics.median([row[unit] for row in variant_rows]),
                "min": min(row[unit] for row in variant_rows), "max": max(row[unit] for row in variant_rows)}
                for unit in ("wall_ns", "cpu_ns")}
        for variant in VARIANTS[1:]:
            summary["paired_deltas"][variant] = []
            for number in range(plan["paired_repetitions"]):
                baseline = next(row for row in measurements if row["repetition"] == number and row["variant"] == "production")
                candidate = next(row for row in measurements if row["repetition"] == number and row["variant"] == variant)
                summary["paired_deltas"][variant].append({"repetition": number,
                    "candidate_minus_baseline_wall_ns": candidate["wall_ns"] - baseline["wall_ns"],
                    "candidate_minus_baseline_cpu_ns": candidate["cpu_ns"] - baseline["cpu_ns"]})
        write_json(output / "summary.json", summary)
        for name, expected_hash in seal["files"].items():
            if file_hash(within(ROOT, name)) != expected_hash:
                raise ValueError("challenge implementation changed during run")
        manifest["source_after"] = source_snapshot(ROOT)
        if manifest["source_before"] != manifest["source_after"]:
            raise ValueError("implementation source changed during run")
        manifest.update(status="complete", finished_at=now(), load_average_after=os.getloadavg())
    except BaseException as error:
        manifest.update(status="failed", error_count=1, failure=f"{type(error).__name__}: {error}",
                        finished_at=now(), source_after=source_snapshot(ROOT))
        write_json(output / "manifest.json", manifest)
        raise
    manifest["artifact_hashes"] = {str(path.relative_to(output)): file_hash(path) for path in output.rglob("*")
                                   if path.is_file() and path != output / "manifest.json" and ".git" not in path.parts}
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
