"""Derive compact cost findings from read-only attribution output."""

from pathlib import Path
import hashlib
import json
import statistics

HERE = Path(__file__).resolve().parent
r = json.loads((HERE / "analysis-v2/report.json").read_bytes())
arms = r["arm_trial_summaries"]


def get(arm, key):
    return arms[arm][key]["sum"]


controlled = {
    arm: get(arm, "construction_seconds") + get(arm, "memory_tool_execution_union_seconds")
    for arm in ("plain", "static", "cami")
}
stages = {}
for stage in range(1, 5):
    stages[str(stage)] = {}
    for arm in ("static", "cami"):
        values = [
            t["memory_backend_nested"]["lookup_seconds"]
            for t in r["trials"]
            if t["arm"] == arm and t["stage"] == stage
        ]
        stages[str(stage)][arm] = {
            "samples": values,
            "median": statistics.median(values),
            "range": [min(values), max(values)],
        }
findings = {
    "scope": "Descriptive read-only diagnosis; all36 including original operational failure; no new benchmark/model.",
    "charged_wall_totals_seconds": {arm: get(arm, "charged_seconds") for arm in arms},
    "memory_construction_plus_api_memory_execution_seconds": controlled,
    "fixed_trace_elimination_fraction_cami": controlled["cami"] / get("cami", "charged_seconds"),
    "fixed_trace_elimination_bound_note": "Accounting only: eliminating both measured phases with all other events unchanged. Not a predicted optimization gain or model-response counterfactual.",
    "cami_minus_static_charged_total_seconds": get("cami", "charged_seconds")
    - get("static", "charged_seconds"),
    "cami_minus_static_measured_memory_phases_seconds": controlled["cami"] - controlled["static"],
    "cami_minus_static_non_tool_api_residual_seconds": get("cami", "non_tool_execution_seconds")
    - get("static", "non_tool_execution_seconds"),
    "cami_lookup_cpu_to_wall_ratio": get("cami", "backend_lookup_cpu_seconds")
    / get("cami", "backend_lookup_seconds"),
    "backend_lookup_by_stage_seconds": stages,
    "largest_measured_controllable_memory_scopes": [
        {
            "scope": "12 API memory executions, including backend refresh/import/serialization",
            "cami_seconds": get("cami", "memory_tool_execution_union_seconds"),
            "note": "Backend subspan17.428s,16.106CPU seconds; no separately timed observe/refresh.",
        },
        {
            "scope": "3 origin constructions",
            "cami_seconds": get("cami", "construction_seconds"),
            "note": "Nested adapter context capture3.987s and registration4.054s. Do not add these to construction again.",
        },
    ],
    "next_bounded_target": {
        "priority": "Attribute then reduce cold/new-process lookup/refresh overhead, especially changed canonical snapshot stage3.",
        "evidence": "This recurring scope exceeds total construction time. Stage3 med2.600s versus unchanged stage2 med1.036s; source refresh+origin verification are untimed subcomponents.",
        "optimization_hypothesis": "Avoid redundant operation-internal source/index/materialization/serialization work only after profiling identifies it; retain fresh final source guards, complete329-record catalog, selected-before-availability ranking, withholding and receipt checks.",
        "next_measurement": "Separately authorized no-model cProfile on fresh source/state copies: cold process, unchanged head and changed snapshot. Preparation separate; profile attribution timings are not benchmarks; quiet repeated unprofiled samples confirm later.",
    },
    "not_supported": [
        "Do not call the API residual pure model/provider wait.",
        "Do not attribute random generated patch size/tool sequence differences causally to CAMI.",
        "Do not interpret generation_changed=true as source changed: new Backend.last_generation startsNone each session.",
        "Do not interpret checked/carried state type counts as actual validator calls.",
        "No superiority claim: original1operational failure retained and third CAMI-static block delta reverses.",
    ],
    "report_sha256": hashlib.sha256((HERE / "analysis-v2/report.json").read_bytes()).hexdigest(),
}
(HERE / "findings.json").write_text(json.dumps(findings, indent=2, sort_keys=True) + "\n")
print(json.dumps(findings, indent=2))
