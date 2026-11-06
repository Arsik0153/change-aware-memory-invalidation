"""Bind independent results and resource checks into compact readonly handoff facts."""

import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def main():
    audit = read(HERE / "independent-v1/report.json")
    resources = read(HERE / "frozen-resources/report.json")
    root_analysis = ROOT / "runs/opencode-development-v6-final-analysis-20261106/report.json"
    reaggregation = HERE / "frozen-reaggregation/report.json"
    assert root_analysis.read_bytes() == reaggregation.read_bytes()
    for row in resources["trials"]:
        independent = next(value for value in audit["trial_rows"] if value["id"] == row["id"])
        assert math.isclose(
            row["container_cpu_seconds"], independent["container_cpu_seconds"], abs_tol=1e-8
        )
        assert (
            row["maximum_container_peak_bytes"]
            == independent["maximum_container_peak_bytes_nonadditive"]
        )
        assert (
            row["persistent_memory_bytes_after"]
            == independent["persistent_memory_logical_bytes_after"]
        )
    visible, wire = read(HERE / "visible-costs.json"), read(HERE / "wire-accounting.json")
    pairs = audit["paired_token_comparisons"]
    next_target = {
        "proposal": "New generic lossless readable compact model-facing projection, identical for static/CAMI; no ranking/limits/catalog/predicate change.",
        "data_support": "Current model-visible memory JSON includes36,128nonliteral bytes across CAMI12calls, plus1,826escape expansion and96literal quote delimiters. Repeated source/subject/format structure is observable, not all safely removable.",
        "preserve": [
            "Every displayed prefix character, truncation flag, exact subject and origin source/span mapping",
            "Trust/current-availability labels and withheld identity/action",
            "Shared ranking/origin-record byte budget and full preprojection payload/receipt evidence",
            "Both memory arms same model-facing format, no per-task rewriting",
        ],
        "bounded_next_unit": "Prototype and offline byte-account a reversible readable projection against the already collected development packets; prove exact prefix/metadata/receipt recovery including physical newlines, Unicode, decorators, control/backtick text and withholding. Freeze a separately versioned protocol before any new model comparison.",
        "not_established": "Bytes are not provider tokens or subscription bills; no causal claim that JSON structure caused v6 token losses or that changing format will improve quality/efficiency. Do not silently retrofit v6 or rewrite Rust.",
        "secondary_observation": "Large parameterized local test failure outputs are another visible context source. Any summary-first native test output change must be shared across all arms, preserve complete diagnostics separately and use a distinct prospective protocol.",
    }
    facts = {
        "status": "closed_readonly_independent_audit",
        "study_sha256": audit["study_sha256"],
        "exact_frozen_analysis_report_sha256": sha(root_analysis),
        "frozen_analysis_commit": "fa415f0c85d51c886f8f509d26241cb8a836634c",
        "frozen_analysis_runtime_pins_sha256": sha(HERE / "frozen-analysis-pins.json"),
        "frozen_reaggregation_byte_identical": True,
        "frozen_resource_report_sha256": sha(HERE / "frozen-resources/report.json"),
        "terminal_trials": 36,
        "artifact_hashes_verified": 8130,
        "operational_quality_pass": 36,
        "tier": {
            "requested": "priority",
            "reasoning": "high",
            "all36effective_configs_valid": True,
            "assistant_response_observations": 469,
            "all_provider_reported": "default",
            "scope": audit["tier_scope"],
            "wire_request_observed_trials": sum(
                value["requested_priority_wire_observed"] is True for value in audit["trial_rows"]
            ),
        },
        "wall_primary_disqualified_whole_cohort": True,
        "timing_caveat_trial_ids_retained": audit["affected_trial_ids_retained"],
        "timing_caveats_sha256": audit["timing_caveats_sha256"],
        "timing_evidence": audit["timing_evidence"],
        "token_wins": {
            comparator: sum(
                value["token_strictly_lower"]
                for value in pairs
                if value["comparator"] == comparator
            )
            for comparator in ["plain", "static"]
        },
        "required_paired_token_wins": 6,
        "observed_paired_token_wins": sum(value["token_strictly_lower"] for value in pairs),
        "same_metric_all_six_met": False,
        "primary_superiority": "not_established",
        "excluded_trials": [],
        "historical_pooling": False,
        "normalized_provider_token_fields": {
            arm: values["tokens_total"] for arm, values in audit["arm_summaries"].items()
        },
        "token_work_blocks": {
            arm: values["token_work_blocks"] for arm, values in audit["arm_summaries"].items()
        },
        "cost_resource_summaries_descriptive": audit["arm_summaries"],
        "visible_cost_totals": visible["arm_totals"],
        "precise_memory_json_byte_partition": wire["arm_totals"],
        "same_file_read_scope": "Path overlap and literal overlap after removing native line numbers/joining visible lines withLF; not raw-source equivalence, necessary-read redundancy or causal reliance.",
        "native_debug_outputs": wire["native_shell_output"],
        "next_bounded_target": next_target,
        "model_calls": 0,
        "heldout_access": False,
        "source_changes": False,
        "commits": 0,
    }
    (HERE / "summary.json").write_text(json.dumps(facts, sort_keys=True, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": facts["status"],
                "frozen_analysis_sha256": facts["exact_frozen_analysis_report_sha256"],
                "token_wins": facts["token_wins"],
                "wall_disqualified": True,
            }
        )
    )


if __name__ == "__main__":
    main()
