"""Assess visible origin-note exposure before any possibly mutating agent tool.

This does not infer that the model relied on a note, or that changed code implies
false behavior. Later lookups require a contemporaneous source observation.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath


READ_ONLY = {"read", "grep", "glob", "list", "ls", "todoread", "todowrite"}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def memory_tool(name: str) -> bool:
    return name == "memory_lookup" or name.endswith("_memory_lookup")


def message_rows(messages: list[dict]) -> list[dict]:
    """Normalize aggregated OpenCode v2 API messages to the CLI tool shape."""
    rows = []
    for message in messages:
        if message.get("type") == "shell":
            rows.append({"type": "tool_use", "part": {
                "id": message["id"], "tool": "shell",
                "state": {"status": message.get("status"), "time": {
                    "start": message.get("time", {}).get("created"),
                    "end": message.get("time", {}).get("completed")}}}})
        if message.get("type") != "assistant":
            continue
        for part in message.get("content", []):
            if part.get("type") != "tool":
                continue
            state = dict(part["state"])
            state["time"] = {"start": part.get("time", {}).get("created"),
                             "end": part.get("time", {}).get("completed")}
            if memory_tool(part["name"]) and state["status"] == "completed":
                content = state.get("content", [])
                if len(content) != 1 or content[0].get("type") != "text":
                    raise ValueError("memory response must contain one complete text payload")
                if state.get("metadata", {}).get("truncated"):
                    raise ValueError("truncated memory response cannot authenticate exposure")
                state["output"] = content[0]["text"]
            rows.append({"type": "tool_use", "part": {
                "id": part["id"], "tool": part["name"], "state": state}})
    return rows


def body(repo: Path, relative: str, qualname: str) -> tuple[str, str | None, str | None]:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or str(path) != relative:
        raise ValueError("noncanonical source path")
    source = repo / relative
    if any(p.is_symlink() for p in [source, *source.parents] if p.is_relative_to(repo)):
        return "unavailable_symlink", None, None
    if not source.exists():
        return "absent_path", None, None
    if not source.is_file() or source.stat().st_size > 2 * 1024**2:
        return "unavailable_source", None, None
    raw = source.read_bytes()
    try:
        tree, text = ast.parse(raw), raw.decode("utf-8")
    except (SyntaxError, UnicodeError):
        return "unavailable_parse", sha(raw), None
    matches = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == qualname:
            matches.append(node)
        elif isinstance(node, ast.ClassDef):
            matches.extend(member for member in node.body
                           if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and node.name + "." + member.name == qualname)
    if len(matches) != 1:
        if not matches and any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                               and node.name == qualname.rsplit(".", 1)[-1]
                               for node in ast.walk(tree)):
            return "unavailable_non_direct_definition", sha(raw), None
        return "absent_definition" if not matches else "ambiguous_definition", sha(raw), None
    node = matches[0]
    first = min([node.lineno] + [d.lineno for d in node.decorator_list])
    excerpt = "".join(text.splitlines(keepends=True)[first - 1:node.end_lineno])[:2400]
    return "unique_definition", sha(raw), excerpt


def analyze(rows: list[dict], catalog: dict, origin: Path, current: Path) -> dict:
    records = {r["id"]: r for r in catalog["records"]}
    if len(records) != len(catalog["records"]):
        raise ValueError("duplicate catalog IDs")
    calls = {}
    for row in rows:
        if row.get("type") == "tool_use":
            part = row["part"]
            calls[part["id"]] = part
    potential_writes = [p for p in calls.values()
                        if p["tool"] not in READ_ONLY and not memory_tool(p["tool"])]
    output = []
    call_reports = []
    for call in calls.values():
        if not memory_tool(call["tool"]):
            continue
        state = call["state"]
        end = state.get("time", {}).get("end")
        unknown_time = end is None or any(p.get("state", {}).get("time", {}).get("start") is None
                                         for p in potential_writes)
        prior_write = unknown_time or any(p["state"]["time"]["start"] <= end for p in potential_writes)
        report = {"call_id": call["id"], "source_assessable": not prior_write,
                  "reason": "no_prior_or_overlapping_potential_write" if not prior_write else "possible_write_or_missing_timestamps"}
        call_reports.append(report)
        if state.get("status") != "completed":
            report["tool_status"] = state.get("status")
            continue
        payload = json.loads(state["output"])
        if payload.get("error"):
            report.update(source_assessable=False, reason="memory_tool_error", error=payload["error"])
            continue
        if payload.get("catalog_sha256") != sha(canonical(catalog)):
            raise ValueError("tool response is not bound to the frozen catalog")
        report["returned_records"] = len(payload["entries"])
        report["withheld_records"] = len(payload["withheld"])
        for entry in payload["entries"]:
            record = records[entry["id"]]
            if record["payload"] != entry["payload"] or record["source"] != entry["origin_source"]:
                raise ValueError("returned origin payload differs from frozen catalog")
            row = {"call_id": call["id"], "record_id": entry["id"], "assessment": "unknown_after_possible_write"}
            output.append(row)
            if prior_write:
                continue
            if record["payload"]["type"] != "note":
                row["assessment"] = "not_a_source_note"
                continue
            subject = record["payload"]["subject"]
            old_status, old_hash, old_excerpt = body(origin, subject["path"], subject["qualname"])
            if old_status != "unique_definition" or old_hash != record["source"]["sha256"]:
                raise ValueError("origin fixture does not authenticate the source note")
            if old_excerpt not in record["payload"]["text"]:
                raise ValueError("note is not the declared origin-source excerpt")
            status, current_hash, excerpt = body(current, subject["path"], subject["qualname"])
            row.update(current_definition_status=status, origin_file_sha256=old_hash,
                       current_file_sha256=current_hash,
                       source_file_changed=current_hash != old_hash if current_hash else None)
            if status == "unique_definition":
                row.update(assessment="same_literal_excerpt" if excerpt == old_excerpt else "obsolete_literal_excerpt",
                           origin_excerpt_sha256=sha(old_excerpt.encode()), current_excerpt_sha256=sha(excerpt.encode()))
            elif status in {"absent_path", "absent_definition"}:
                row["assessment"] = "origin_definition_absent"
            else:
                row["assessment"] = "unknown_current_source"
    return {"scope": "Origin-memory exposure before any possible agent write; literal source comparison, not behavioral truth or causal reliance.",
            "stale_reliance": "not inferred; requires evidence-backed review of visible actions/final statements",
            "memory_calls": call_reports, "records": output,
            "counts": {"memory_calls": len(call_reports), "returned_records": len(output),
                       "source_file_changed": sum(r.get("source_file_changed") is True for r in output),
                       "obsolete_literal_excerpt": sum(r["assessment"] == "obsolete_literal_excerpt" for r in output),
                       "origin_definition_absent": sum(r["assessment"] == "origin_definition_absent" for r in output),
                       "unassessed_records": sum(r["assessment"].startswith("unknown") or r["assessment"] == "not_a_source_note" for r in output)},
            "limitations": ["Shell and unknown tools conservatively count as potentially mutating, even when they might only read.",
                            "Changed-file exposure does not imply the selected function or any behavioral claim became false.",
                            "Plain mode has no external-memory exposure; this does not prove it never uses stale model knowledge."]}


def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--trace", type=Path, help="CLI JSONL tool events")
    source.add_argument("--messages", type=Path, help="Complete aggregated v2 API message array")
    for name in ["catalog", "origin", "current", "out"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.messages:
        messages = json.loads(args.messages.read_text())
        if not isinstance(messages, list):
            raise ValueError("expected complete aggregated message array, not a paginated API envelope")
        rows = message_rows(messages)
    else:
        rows = [json.loads(line) for line in args.trace.read_text().splitlines() if line.strip()]
    result = analyze(rows, json.loads(args.catalog.read_text()), args.origin.resolve(), args.current.resolve())
    args.out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
