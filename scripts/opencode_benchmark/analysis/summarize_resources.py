"""Secondary local resource accounting from hash-verified terminal artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from aggregate_metrics import ARMS, number
from aggregate_study import read, safe_path, sha, verify_terminal, write


def components(record):
    trial, costs = record["trial"], record.get("costs", {})
    construction_required = trial["arm"] != "plain" and trial["stage"] == 1
    construction = costs.get("construction_cgroup", {})
    session = costs.get("session_cgroup", {})
    construction_cpu = number(construction.get("cpu_seconds")) if construction_required else 0
    session_cpu = number(session.get("cpu_seconds"))
    peaks = [number(session.get("peak_memory_bytes"), integer=True)]
    if construction_required:
        peaks.append(number(construction.get("peak_memory_bytes"), integer=True))
    return {
        **trial,
        "construction_required": construction_required,
        "construction_cpu_seconds": construction_cpu,
        "session_cpu_seconds": session_cpu,
        "container_cpu_seconds": construction_cpu + session_cpu
        if construction_cpu is not None and session_cpu is not None else None,
        "maximum_container_peak_bytes": max(peaks) if all(v is not None for v in peaks) else None,
        "persistent_memory_bytes_after": number(record.get("memory_bytes_after"), integer=True),
        "controller_self_cpu_seconds": number(costs.get("controller_self_cpu_seconds")),
        "host_child_cpu_seconds": number(costs.get("host_child_cpu_seconds")),
    }


def combine(values, operation):
    known = [v for v in values if v is not None]
    return {
        "value": operation(known) if known and len(known) == len(values) else None,
        "observed_partial": operation(known) if known else None,
        "complete": bool(values) and len(known) == len(values),
        "known_observations": len(known),
        "expected_observations": len(values),
    }


def summarize(rows):
    blocks = []
    for repetition in range(1, 4):
        for arm in ARMS:
            selected = sorted(
                (r for r in rows if r["repetition"] == repetition and r["arm"] == arm),
                key=lambda r: r["stage"],
            )
            if [r["stage"] for r in selected] != [1, 2, 3, 4]:
                raise ValueError("secondary resource report requires all four terminal stages")
            blocks.append({
                "repetition": repetition, "arm": arm,
                "container_cpu_seconds": combine([r["container_cpu_seconds"] for r in selected], sum),
                "maximum_container_peak_bytes": combine([r["maximum_container_peak_bytes"] for r in selected], max),
                "maximum_observed_persistent_memory_bytes": combine([r["persistent_memory_bytes_after"] for r in selected], max),
                "final_persistent_memory_bytes": selected[-1]["persistent_memory_bytes_after"],
            })
    return blocks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--analysis-sha256", required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if sha(args.analysis) != args.analysis_sha256:
        raise ValueError("analysis digest differs")
    analysis = read(args.analysis)
    rows = []
    for expected in analysis["trials"]:
        if not expected["terminal_present"]:
            raise ValueError("all trials must be terminal before resource aggregation")
        directory = safe_path(args.run, "trials/" + expected["id"])
        terminal, terminal_sha, _ = verify_terminal(directory)
        if terminal_sha != expected["terminal_sha256"]:
            raise ValueError("terminal differs from admitted primary analysis")
        row = components(terminal)
        row["terminal_sha256"] = terminal_sha
        trace = directory / "session/evidence/memory-backend-trace.jsonl"
        row["published_backend_trace_bytes"] = trace.stat().st_size if trace.is_file() else None
        rows.append(row)
    report = {
        "schema_version": 1, "analysis_sha256": args.analysis_sha256,
        "study_sha256": analysis["study_sha256"], "trials": rows,
        "blocks": summarize(rows), "primary_superiority_override": False,
        "limits": [
            "Secondary descriptive resources; the frozen primary decision is unchanged.",
            "Container CPU sums construction and session deltas. Host controller/children remain separate: their scope includes evaluation and may overlap container work.",
            "Container memory peaks are maxima, never sums. They include charged cgroup memory, not only process RSS, and omit concurrent host/process peaks.",
            "Persistent-memory sizes are logical file bytes at observed stage boundaries. Their maximum is not a continuously sampled disk peak or byte-time rental cost.",
            "Published backend trace size is separate from the memory directory and may differ after redaction. It is not total private session/evaluation storage.",
            "Missing observations remain unknown, not zero. Construction CPU is zero only for stages with no construction operation.",
            "Remote inference CPU, memory, energy and actual subscription bills are unavailable.",
        ],
    }
    args.out.mkdir(parents=True, exist_ok=False)
    write(args.out / "report.json", report)


if __name__ == "__main__":
    main()
