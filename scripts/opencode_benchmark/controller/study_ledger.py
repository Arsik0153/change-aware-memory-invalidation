"""Immutable terminal trials and explicit incomplete-attempt recovery, never retries."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from study_common import file_hashes, read, verify_files, write


def complete(trial_dir, record):
    record["artifact_hashes"] = file_hashes(trial_dir)
    write(trial_dir / "terminal.json", record)
    return record


def terminals(output, planned, *, recover=False):
    records = {}
    trials = output / "trials"
    for trial in planned:
        directory = trials / trial["id"]
        if not directory.exists():
            continue
        terminal = directory / "terminal.json"
        if terminal.exists():
            record = read(terminal)
            if record["trial"] != trial:
                raise ValueError("terminal trial identity changed")
            verify_files(directory, record["artifact_hashes"])
            extras = (
                set(file_hashes(directory)) - set(record["artifact_hashes"]) - {"terminal.json"}
            )
            if extras:
                raise ValueError("unrecorded files appended to terminal evidence")
            records[trial["id"]] = record
        elif recover:
            records[trial["id"]] = complete(
                directory,
                {
                    "trial": trial,
                    "status": "abandoned",
                    "memory_usable": False,
                    "failure": "Incomplete prior attempt preserved; no retry permitted.",
                    "costs": {"complete": False},
                    "model_calls_unknown_after_interruption": True,
                },
            )
        else:
            raise ValueError("incomplete attempt requires explicit --resume; no retry")
    return records


def verify_binding(output, study_sha, execute):
    run = read(output / "run.json")
    if run["study_sha256"] != study_sha or run["mode"] != ("model" if execute else "plan"):
        raise ValueError("resume study/mode mismatch")
    if read(output / "frozen-study.json") != read(Path(run["study_path"])):
        raise ValueError("resumed frozen study bytes changed")


def next_trials(planned, records):
    for trial in planned:
        if trial["id"] not in records:
            yield trial


def summarize(records, *, planned_trials=36):
    groups = defaultdict(list)
    for row in records.values():
        trial = row["trial"]
        groups[(trial["repetition"], trial.get("condition", trial["arm"]))].append(row)
    blocks = []
    for (rep, arm), rows in sorted(groups.items()):
        costs = [r.get("costs", {}) for r in rows]
        blocks.append(
            {
                "repetition": rep,
                "arm": rows[0]["trial"]["arm"],
                **({"condition": arm} if "condition" in rows[0]["trial"] else {}),
                "terminal_stages": len(rows),
                "four_stage_complete": len(rows) == 4 and all(c.get("complete") for c in costs),
                "passed_stages": sum(r["status"] == "passed" for r in rows),
                "quality_passed_stages": sum(r.get("quality") == "pass" for r in rows),
                "operational_passed_stages": sum(
                    r.get("operational_status") == "passed" for r in rows
                ),
                "memory_construction_host_wall_seconds": sum(
                    c.get("construction_host_wall_seconds", 0) for c in costs
                ),
                "session_host_wall_seconds": sum(
                    c.get("session_host_wall_seconds", 0) for c in costs
                ),
                "charged_host_wall_seconds": sum(
                    c.get("charged_host_wall_seconds", 0) for c in costs
                ),
                "infrastructure_host_wall_seconds": sum(
                    c.get("infrastructure_host_wall_seconds", 0) for c in costs
                ),
                "session_tokens": [r.get("usage", {}).get("session_tokens") for r in rows],
                "failures": [r["trial"]["id"] for r in rows if r["status"] != "passed"],
            }
        )
    return {
        "terminal_trials": len(records),
        "planned_trials": planned_trials,
        "blocks": blocks,
        "speedup_claim": None,
        "scope": ("two fixed tasks; one exploratory block, no superiority claim"
                  if planned_trials == 20 else "two fixed tasks; dependent repeats within three blocks"),
        "cost_accounting": "Construction includes generation and preparation once per memory arm. Session inclusive harness elapsed includes startup/auth/cleanup; authentication separately reported as infrastructure but not silently subtracted. Nested phase metrics are not added to inclusive totals. Canonical fixture export and fixed-test grading are separate infrastructure.",
    }
