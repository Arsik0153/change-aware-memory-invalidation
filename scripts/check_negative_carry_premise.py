"""Check whether the measured negative-carry bookkeeping paid for itself."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import pstats


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def function_cost(path, filename, function):
    matches = [(key, value) for key, value in pstats.Stats(str(path)).stats.items()
               if key[0] == filename and key[2] == function]
    if len(matches) != 1:
        raise ValueError(f"requires one profile function: {filename}:{function}")
    key, (primitive, calls, own, cumulative, _) = matches[0]
    return {"function": list(key), "primitive_calls": primitive, "total_calls": calls,
            "own_seconds": own, "cumulative_seconds": cumulative}


def run(source: Path, out: Path):
    manifest = json.loads((source / "manifest.json").read_bytes())
    if manifest["status"] != "complete" or manifest["source_before"] != manifest["source_after"]:
        raise ValueError("requires completed measurement with stable sources")
    inputs = ["summary.json", "expected-work.json", "profiles/production.prof",
              "profiles/registered_inputs.prof", "profiles/production.json", "profiles/registered_inputs.json"]
    for name in inputs:
        if sha(source / name) != manifest["artifact_hashes"][name]:
            raise ValueError(f"measurement artifact hash mismatch: {name}")
    for variant in ("production", "registered_inputs"):
        profile = json.loads((source / "profiles" / f"{variant}.json").read_bytes())
        if profile["included_in_timing_samples"] is not False or profile["history_pack_repetitions"] != 1:
            raise ValueError("requires separately instrumented single-pack profiles")
    summary = json.loads((source / "summary.json").read_bytes())
    work = json.loads((source / "expected-work.json").read_bytes())
    comparisons = {}
    for variant, rows in summary["paired_deltas"].items():
        comparisons[variant] = {"pairs": len(rows), "fewer_validation_calls":
            work[variant]["counts"]["actual_validation_calls"] < work["production"]["counts"]["actual_validation_calls"],
            "positive_cpu_pairs": sum(r["candidate_minus_baseline_cpu_ns"] > 0 for r in rows),
            "positive_wall_pairs": sum(r["candidate_minus_baseline_wall_ns"] > 0 for r in rows)}
    slower = all(x["fewer_validation_calls"] and x["pairs"] == manifest["protocol"]["paired_repetitions"]
                 and x["positive_cpu_pairs"] == x["positive_wall_pairs"] == x["pairs"]
                 for x in comparisons.values())
    baseline_validation = function_cost(source / "profiles/production.prof", "validation.py", "validate_claim")
    registration = function_cost(source / "profiles/registered_inputs.prof", "registered_negative_carry.py", "register")
    ingress = function_cost(source / "profiles/registered_inputs.prof", "registered_negative_carry.py", "initialize_checked_negative")
    report = {"status": "premise_rejected_for_measured_implementations" if slower else "premise_not_rejected",
        "premise": "On this fixed short-history workload, avoiding repeated cheap structural validation pays for the correctness bookkeeping required by these negative-carry implementations.",
        "paired_observation": comparisons, "separate_profile": {
            "all_baseline_validation": baseline_validation, "registered_input_registration": registration,
            "registered_actual_result_ingress": ingress,
            "registration_exceeds_all_baseline_validation": registration["cumulative_seconds"] > baseline_validation["cumulative_seconds"]},
        "decision": "Retain ordinary production retry; stop adding variants that assume this workload's validation savings pay for their lifecycle bookkeeping.",
        "limits": ["This is a diagnostic of three measured implementations on the same 17 authored histories, not an impossibility theorem for negative caching.",
                   "Instrumented single-pack profile intervals are not unprofiled CPU samples or a causal counterfactual speedup estimate.",
                   "Registration contains nested cloning and immutability work; these cumulative times must not be added again to their children.",
                   "Longer histories, larger indexes or a different validator would be new workload conditions requiring new evidence."],
        "sources": {name: sha(source / name) for name in ["manifest.json", *inputs]},
        "script_sha256": sha(Path(__file__))}
    with out.open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.source, args.out)
    print(report["status"])
