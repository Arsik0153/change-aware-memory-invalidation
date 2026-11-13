"""Post-hoc temporal source-prefix overlap, not an avoided-read estimate."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from aggregate_study import read, sha, verify_terminal, write
from format_probe import plan, read_projection, validate_design


def numbered_source(state):
    if state.get("status") != "completed":
        return None
    content = state.get("content")
    if not isinstance(content, list) or any(
        not isinstance(p, dict) or p.get("type") != "text" or not isinstance(p.get("text"), str)
        for p in content
    ):
        return None
    text = "\n".join(p["text"] for p in content)
    if "[REDACTED" in text:
        return None
    lines = [match.group(1) for line in text.splitlines()
             if (match := re.fullmatch(r"\d+: ?(.*)", line))]
    return "\n".join(lines) if lines else None


def prefix_present(prefix, source):
    if source is None or not prefix.strip() or "[REDACTED" in prefix:
        return None
    normalized = prefix.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return normalized in source


def analyze(root):
    study = read(root / "frozen-study.json")
    validate_design(study)
    if study.get("schema_version") != 3:
        raise ValueError("requires closed ranking cohort with original read counts")
    trials = []
    for expected in plan(study):
        directory = root / "trials" / expected["id"]
        terminal, terminal_sha, _ = verify_terminal(directory)
        if terminal["trial"] != expected:
            raise ValueError("terminal schedule differs")
        evidence = directory / "session/evidence"
        messages = read(evidence / "messages.json")
        receipt = read(evidence / "native-read-bytes.json")
        if not read_projection(messages, receipt)["complete"]:
            raise ValueError("original byte evidence incomplete")
        counts = {r["call_id"]: r["utf8_bytes"] for m in receipt["messages"] for r in m["reads"]}
        tools = [p for m in messages if m.get("type") == "assistant"
                 for p in m["content"] if p.get("type") == "tool"]
        memory_calls = [p for p in tools if p["name"].endswith("memory_lookup")]
        path = evidence / "memory-backend-trace.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        events = [e for e in events if e.get("event") == "memory_lookup"]
        if len(events) != len(memory_calls):
            raise ValueError("memory call/trace coverage differs")
        memories = []
        for call, event in zip(memory_calls, events):
            body = json.loads(event["response_audit"]["full_result"]["content"][0]["text"])
            if call["state"]["input"]["query"] != body["query"] or call["state"]["status"] != "completed":
                raise ValueError("memory query identity/completion differs")
            memories.extend({"entry": e, "completed": call["time"]["completed"]} for e in body["entries"])
        edits = [p["time"]["ran"] for p in tools if p["name"] in {"patch", "edit", "write"}]
        first_edit = min(edits) if edits else None
        reads = []
        for call in tools:
            if call["name"] != "read":
                continue
            state = call["state"]
            path = state.get("input", {}).get("path")
            available = [m["entry"] for m in memories if m["completed"] < call["time"]["ran"]
                         and path == "/workspace/" + m["entry"]["payload"]["subject"]["path"]]
            source = numbered_source(state)
            matched = [e for e in available if prefix_present(e["payload"]["expected"]["text"], source) is True]
            reads.append({"call_id": call["id"], "path": path, "original_bytes": counts[call["id"]],
                "same_file_prior_records": [e["id"] for e in available],
                "complete_prefix_matches": [e["id"] for e in matched],
                "matched_symbols": [e["payload"]["subject"]["qualname"] for e in matched],
                "source_comparable": source is not None,
                "before_first_explicit_edit": first_edit is not None and call["time"]["ran"] < first_edit})
        trials.append({"trial": expected, "terminal_sha256": terminal_sha,
            "returned_records": len(memories), "reads": reads,
            "tool_counts": dict(Counter(p["name"] for p in tools)),
            "assistant_messages": sum(m.get("type") == "assistant" for m in messages)})
    summary = {}
    for condition in study["conditions"]:
        members = [t for t in trials if t["trial"]["condition"] == condition["id"]]
        reads = [r for t in members for r in t["reads"]]
        summary[condition["id"]] = {
            "reads": len(reads), "returned_record_observations": sum(t["returned_records"] for t in members),
            "reads_of_previously_returned_files": sum(bool(r["same_file_prior_records"]) for r in reads),
            "reads_containing_a_complete_returned_prefix": sum(bool(r["complete_prefix_matches"]) for r in reads),
            "such_reads_before_first_explicit_edit": sum(bool(r["complete_prefix_matches"]) and r["before_first_explicit_edit"] for r in reads),
            "assistant_messages": sum(t["assistant_messages"] for t in members),
            "tool_counts": dict(sum((Counter(t["tool_counts"]) for t in members), Counter()))}
    return {"schema_version": 1, "study_sha256": sha(root / "frozen-study.json"),
        "scope": "Post-hoc exact logical-text prefix overlap in later reads of the same file. CRLF normalized and read line labels removed. Redacted/nontext reads unknown. A matching read may contain essential additional context. No avoided bytes, causal savings or sufficiency claim. Explicit-edit boundary excludes shell mutations and is not a source-consistency guarantee.",
        "summary": summary, "trials": trials}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    write(args.out, analyze(args.run.resolve()))


if __name__ == "__main__":
    main()
