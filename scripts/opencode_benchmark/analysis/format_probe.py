"""Read-only analysis of the frozen, single-block format development experiment."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from aggregate_metrics import metric
from aggregate_study import (
    LITERAL_COMPACT_DEVELOPMENT_ID, admit_study_cohort, read, sha, trial_row, trial_tier, write,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "controller"))
from study_schema import FORMAT_DESIGN, format_conditions, plan, validate_design  # noqa: E402


def native_reads(messages):
    """Count returned native read text, never shell-inferred bytes or duplicated output."""
    total, calls, ids, errors = 0, 0, set(), []
    if not isinstance(messages, list) or not messages:
        return {"bytes": None, "calls": 0, "complete": False, "errors": ["messages unavailable"]}
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("content"), list):
            errors.append("malformed message content")
            continue
        for part in message["content"]:
            if not isinstance(part, dict):
                errors.append("malformed message part")
                continue
            if part.get("type") != "tool" or part.get("name") != "read":
                continue
            calls += 1
            if not isinstance(part.get("id"), str) or part["id"] in ids:
                errors.append("missing or duplicate read identity")
            ids.add(part.get("id") if isinstance(part.get("id"), str) else None)
            state = part.get("state", {})
            if not isinstance(state, dict) or state.get("status") != "completed":
                errors.append("native read not completed")
                continue
            content = state.get("content")
            if not isinstance(content, list) or any(
                not isinstance(p, dict) or p.get("type") != "text" or not isinstance(p.get("text"), str)
                for p in content
            ):
                errors.append("native read has unavailable or nontext result")
                continue
            text = "".join(p["text"] for p in content)
            if "[REDACTED" in text:
                errors.append("redacted read bytes cannot reconstruct original result")
            total += len(text.encode("utf-8"))
    return {"bytes": total if not errors else None, "observed_subtotal": total,
            "calls": calls, "complete": not errors, "errors": errors}


def summarize(rows):
    blocks = []
    for condition in format_conditions():
        members = [r for r in rows if r["condition"] == condition["id"]]
        blocks.append({**condition, "trials": [r["id"] for r in members],
            "quality_complete": len(members) == 4 and all(r["quality_eligible"] for r in members),
            "token_work": metric(members, "token_work", "tokens_complete"),
            "native_read_bytes": metric(members, "native_read_bytes", "native_reads_complete"),
            "charged_wall": metric(members, "charged_wall_seconds", "wall_complete")})
    eligible = len(rows) == 20 and all(
        r["quality_eligible"] and r["tokens_complete"] and r["wall_complete"]
        and r["native_reads_complete"] and r["service_tier"]["configuration_valid"]
        for r in rows)
    lookup = {b["id"]: b for b in blocks}
    pairs = []
    for backend in ("static", "cami"):
        pair = {"backend": backend}
        for name in ("token_work", "native_read_bytes"):
            compact = lookup[backend + "_compact"][name]["total"]
            readable = lookup[backend + "_readable"][name]["total"]
            pair[name] = {"compact": compact, "readable": readable,
                "strictly_lower": readable < compact if readable is not None and compact is not None else None}
        pairs.append(pair)
    supported = eligible and all(p[m]["strictly_lower"] is True for p in pairs
                                 for m in ("token_work", "native_read_bytes"))
    tiers = sorted({v for r in rows for v in r["service_tier"]["provider_reported_values"]})
    uniform_tier = len(rows) == 20 and len(tiers) == 1 and all(
        r["service_tier"]["provider_reported_complete"] for r in rows)
    return {"planned_trials": 20, "terminal_trials": sum(r["terminal_present"] for r in rows),
        "eligible": eligible, "direction_supported": supported,
        "conclusion": "descriptive_direction_supported" if supported else "negative_or_inconclusive",
        "superiority_claim": None, "blocks": blocks, "pairs": pairs,
        "provider_reported_tiers": tiers, "uniform_complete_tier": uniform_tier,
        "wall_comparison_eligible": False,
        "wall_note": "Host quietness is not independently established by these artifacts; wall totals descriptive only.",
        "scope": "One dependent four-stage sequence per condition on two development tasks; no heldout or population inference.",
        "read_scope": "UTF8 text returned by completed native read calls across the entire session; excludes shell reads, images and implied avoided reads. Missing, redacted or malformed evidence is incomplete.",
        "token_scope": "Normalized input+cache.write+output+reasoning once per session; cache.read retained separately. Not monetary billing."}


def aggregate(root):
    study = read(root / "frozen-study.json")
    validate_design(study)
    if study.get("design") != FORMAT_DESIGN or study.get("service_tier") != "priority":
        raise ValueError("requires the registered format-only priority development design")
    admit_study_cohort(LITERAL_COMPACT_DEVELOPMENT_ID, {k: v for k, v in study.items() if k != "service_tier"})
    if study.get("execution_authorized") is not True or study.get("model") != "openai/gpt-6.1-sol#high":
        raise ValueError("model identity or execution authorization differs")
    binding = read(root / "run.json")
    if binding.get("mode") != "model" or binding.get("study_sha256") != sha(root / "frozen-study.json"):
        raise ValueError("frozen model-run binding changed")
    schedule = plan(study)
    if read(root / "plan.json").get("trials") != schedule:
        raise ValueError("frozen schedule changed")
    unexpected = {p.name for p in (root / "trials").iterdir()} - {r["id"] for r in schedule}
    if unexpected:
        raise ValueError("unplanned trial evidence present")
    rows = []
    for trial in schedule:
        directory = root / "trials" / trial["id"]
        row = trial_row(directory, trial)
        row["service_tier"] = trial_tier(directory, row)
        source = directory / "session/evidence/messages.json"
        observed = native_reads(read(source) if row["terminal_present"] and source.is_file() else None)
        row.update(native_read_bytes=observed["bytes"], native_reads_complete=observed["complete"],
                   native_reads=observed)
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
