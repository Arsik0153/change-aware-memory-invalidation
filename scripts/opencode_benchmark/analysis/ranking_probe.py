"""One prospective ranking-only development block; no population superiority claim."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from aggregate_metrics import metric
from aggregate_study import V7_STUDY_ID, admit_study_cohort, read, sha, trial_row, trial_tier, write
from format_probe import read_projection

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "controller"))
from study_schema import RANKING_DESIGN, ranking_conditions, plan, validate_design  # noqa: E402
from study_runtime import validate_memory_command, validate_ranking_trace  # noqa: E402

RULES = {
    "design": RANKING_DESIGN,
    "maximum_model_sessions": 12,
    "repetitions": 1,
    "conditions": ranking_conditions(),
    "primary_comparison": ["cami_identifier", "cami_lexical"],
    "direction_rule": "Strictly lower total noncached normalized token work AND native read result text bytes over four stages; all twelve operational/quality/telemetry gates pass and provider tier is uniform and complete.",
    "plain_role": "Descriptive context only; not a primary superiority comparison.",
    "read_schema": "opencode-native-read-text/2",
    "read_scope": "UTF8 text in completed native read content plus error.message in exact {type,message} error objects, before redaction. Excludes error type labels, wrappers, shell reads and wire bytes. Unsupported/pending/running/incomplete evidence is unknown, never zero.",
    "token_scope": "Normalized input+cache.write+output+reasoning once per session; cache.read separately retained. Not billed currency.",
    "stopping_rule": "Exactly one scheduled block. Preserve all failures. No retries, replacement sessions, extensions, old-block pooling or heldout calls.",
    "scope": "Exploratory dependent A,A,B,B sequence on two development tasks, selected after offline diagnosis. No independent replication or population superiority inference.",
    "wall_eligibility": "Descriptive only; host quietness not independently established.",
}


def summarize(rows):
    blocks = []
    for condition in ranking_conditions():
        members = [r for r in rows if r["condition"] == condition["id"]]
        blocks.append({**condition, "trials": [r["id"] for r in members],
            "quality_complete": len(members) == 4 and all(r["quality_eligible"] for r in members),
            "token_work": metric(members, "token_work", "tokens_complete"),
            "native_read_bytes": metric(members, "native_read_bytes", "native_reads_complete"),
            "charged_wall": metric(members, "charged_wall_seconds", "wall_complete")})
    tiers = sorted({v for r in rows for v in r["service_tier"]["provider_reported_values"]})
    uniform = len(rows) == 12 and len(tiers) == 1 and all(
        r["service_tier"]["provider_reported_complete"] for r in rows)
    eligible = uniform and len(rows) == 12 and all(
        r["quality_eligible"] and r["tokens_complete"] and r["wall_complete"]
        and r["native_reads_complete"] and r["ranking_verified"]
        and r["service_tier"]["configuration_valid"] for r in rows)
    lookup = {b["id"]: b for b in blocks}
    comparison = {}
    for name in ("token_work", "native_read_bytes"):
        candidate = lookup["cami_identifier"][name]["total"]
        baseline = lookup["cami_lexical"][name]["total"]
        comparison[name] = {"candidate": candidate, "baseline": baseline,
            "strictly_lower": candidate < baseline if candidate is not None and baseline is not None else None}
    supported = eligible and all(v["strictly_lower"] is True for v in comparison.values())
    return {"planned_trials": 12, "terminal_trials": sum(r["terminal_present"] for r in rows),
        "eligible": eligible, "direction_supported": supported,
        "conclusion": "descriptive_direction_supported" if supported else "negative_or_inconclusive",
        "superiority_claim": None, "blocks": blocks, "primary_comparison": comparison,
        "provider_reported_tiers": tiers, "uniform_complete_tier": uniform,
        "wall_comparison_eligible": False, "rules": RULES}


def aggregate(root):
    study = read(root / "frozen-study.json")
    validate_design(study)
    if study.get("design") != RANKING_DESIGN or study.get("service_tier") != "priority":
        raise ValueError("requires registered priority ranking development design")
    # Reuse source-origin cohort validation only, not any historical success rules/results.
    admit_study_cohort(V7_STUDY_ID, study)
    if study.get("execution_authorized") is not True or study.get("model") != "openai/gpt-6.1-sol#high":
        raise ValueError("model identity or authorization differs")
    protocol = read(root / "protocol.json")
    if sha(root / "protocol.json") != study.get("protocol_sha256") or protocol.get("rules") != RULES:
        raise ValueError("frozen ranking protocol differs")
    binding = read(root / "run.json")
    if binding.get("mode") != "model" or binding.get("study_sha256") != sha(root / "frozen-study.json"):
        raise ValueError("frozen model-run binding changed")
    schedule = plan(study)
    if read(root / "plan.json").get("trials") != schedule or protocol.get("schedule") != schedule:
        raise ValueError("frozen schedule changed")
    if {p.name for p in (root / "trials").iterdir()} - {r["id"] for r in schedule}:
        raise ValueError("unplanned trial evidence present")
    rows = []
    for trial in schedule:
        directory = root / "trials" / trial["id"]
        row = trial_row(directory, trial)
        row["service_tier"] = trial_tier(directory, row)
        row.update(ranking_verified=False, native_read_bytes=None, native_reads_complete=False)
        projection = directory / "session/evidence/native-read-bytes.json"
        if row["terminal_present"] and projection.is_file():
            manifest = read(directory / "session/manifest.json")
            if manifest.get("artifact_hashes", {}).get("evidence/native-read-bytes.json") != sha(projection):
                raise ValueError("native read projection is not session-hashed")
            receipt = read(projection)
            if receipt.get("schema") != RULES["read_schema"]:
                raise ValueError("prospective ranking study requires native read v2")
            observed = read_projection(read(directory / "session/evidence/messages.json"), receipt)
            row.update(native_read_bytes=observed["bytes"], native_reads_complete=observed["complete"], native_reads=observed)
        if row["terminal_present"] and row["session_status"] == "passed":
            manifest = read(directory / "session/manifest.json")
            policy = trial["ranking_policy"]
            if manifest.get("memory_ranking_policy") != policy:
                raise ValueError("recorded ranking policy differs")
            config = read(directory / "session/effective-input-config.json")
            validate_memory_command(config, trial["arm"], trial["response_format"], policy)
            trace = directory / "session/evidence/memory-backend-trace.jsonl"
            events = [json.loads(line) for line in trace.read_text().splitlines()] if trace.is_file() else []
            validate_ranking_trace(events, trial["arm"], policy)
            # A trial without memory use cannot establish the ranking intervention.
            format_evidence = read(directory / "memory-response-format.json")
            row["ranking_verified"] = trial["arm"] == "plain" or (
                format_evidence.get("status") == "matched"
                and any(e.get("event") == "memory_lookup" and e.get("error") is None for e in events))
        rows.append(row)
    return {"schema_version": 1, "study_sha256": binding["study_sha256"],
            "summary": summarize(rows), "trials": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    write(args.out, aggregate(args.run.resolve()))


if __name__ == "__main__":
    main()
