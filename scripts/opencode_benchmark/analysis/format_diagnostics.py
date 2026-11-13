"""Post-hoc descriptive lookup/read diagnostics; never alter the frozen decision."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from aggregate_study import read, sha, verify_terminal, write
from format_probe import plan, validate_design


def analyze(root):
    study = read(root / "frozen-study.json")
    validate_design(study)
    if study.get("schema_version") != 2:
        raise ValueError("requires the five-condition development cohort")
    trials, groups = [], defaultdict(list)
    for expected in plan(study):
        directory = root / "trials" / expected["id"]
        terminal, terminal_sha, _ = verify_terminal(directory)
        if terminal["trial"] != expected:
            raise ValueError("trial differs from frozen schedule")
        messages = read(directory / "session/evidence/messages.json")
        trace = directory / "session/evidence/memory-backend-trace.jsonl"
        events = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
        lookups = [e for e in events if e.get("event") == "memory_lookup"]
        reads, query_limits = [], []
        for message in messages:
            if message.get("type") != "assistant":
                continue
            for part in message["content"]:
                if part.get("type") != "tool":
                    continue
                state = part["state"]
                if part.get("name") == "read":
                    reads.append({"status": state["status"], "path": state.get("input", {}).get("filePath"),
                                  "call_id": part["id"]})
                elif part.get("name", "").endswith("memory_lookup"):
                    query_limits.append({"status": state["status"], "input": state.get("input")})
        entries, withheld = [], []
        for event in lookups:
            full = event.get("response_audit", {}).get("full_result")
            if not isinstance(full, dict):
                raise ValueError("full memory receipt unavailable")
            body = json.loads(full["content"][0]["text"])
            for entry in body.get("entries", []):
                payload = entry["payload"]
                entries.append({"id": entry["id"], "subject": payload["subject"],
                                "truncated": payload["expected"]["truncated"]})
            withheld.extend(body.get("withheld", []))
        costs = terminal["costs"]
        row = {"trial": expected, "terminal_sha256": terminal_sha, "reads": reads,
            "memory_calls": query_limits, "returned_entries": entries, "withheld": withheld,
            "lookup_backend_wall_seconds": sum(e["wall_seconds"] for e in lookups),
            "memory_response_bytes": sum(e["response_bytes"] for e in lookups),
            "construction_host_wall_seconds": costs["construction_host_wall_seconds"],
            "session_host_wall_seconds": costs["session_host_wall_seconds"]}
        trials.append(row)
        groups[expected["condition"]].append(row)
    summary = {}
    for condition, rows in groups.items():
        calls = [c for r in rows for c in r["memory_calls"]]
        entries = [e for r in rows for e in r["returned_entries"]]
        reads = [call for r in rows for call in r["reads"]]
        wall = sum(r["lookup_backend_wall_seconds"] for r in rows)
        session = sum(r["session_host_wall_seconds"] for r in rows)
        summary[condition] = {"native_read_calls": len(reads),
            "native_read_states": dict(Counter(c["status"] for c in reads)),
            "native_read_paths": dict(Counter(c["path"] for c in reads)),
            "memory_calls": len(calls), "requested_limits": dict(Counter(str(c["input"].get("limit")) for c in calls)),
            "returned_record_observations": len(entries),
            "truncated_record_observations": sum(e["truncated"] for e in entries),
            "withheld_record_observations": sum(len(r["withheld"]) for r in rows),
            "memory_response_bytes": sum(r["memory_response_bytes"] for r in rows),
            "lookup_backend_wall_seconds": wall,
            "session_host_wall_seconds": session,
            "lookup_nested_fraction_of_session_wall": wall / session,
            "construction_host_wall_seconds": sum(r["construction_host_wall_seconds"] for r in rows)}
    return {"schema_version": 1, "study_sha256": sha(root / "frozen-study.json"),
        "scope": "Post-hoc descriptive diagnostics, not a new success rule or causal attribution. Repeated observations are dependent. Backend spans exclude RPC/trace append and are nested within session wall: never add them to charged totals. Native read counts do not recover original read bytes or identify avoidable reads.",
        "summary": summary, "trials": trials}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    write(args.out, analyze(args.run.resolve()))


if __name__ == "__main__":
    main()
