"""Configured MCP stdio correctness probe; stdlib only, no model or task execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

# Isolated Python omits the script directory; only the read-only sibling is trusted.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from readable_receipts import verify_readable_result  # noqa: E402


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def validate_response(result, expected, backend, response_format, trace, arguments):
    if result.get("isError") is not False or len(result.get("content", [])) != 1:
        raise ValueError("MCP result failed or content differs")
    content = result["content"][0]
    if content.get("type") != "text":
        raise ValueError("MCP result is not text")
    if response_format == "readable":
        events = [row for row in trace if row.get("event") == "memory_lookup"]
        if (len(events) != 1 or events[0].get("query_sha256") != digest(arguments)
                or events[0].get("backend") != backend or events[0].get("error") is not None
                or events[0].get("response_format") != "readable"
                or events[0].get("response_bytes") != len(canonical(result))
                or events[0].get("requested_limit") != arguments.get("limit", 5)):
            raise ValueError("readable response/backend trace mismatch")
        value = verify_readable_result(result, events[0].get("response_audit"))
        if (value.get("query") != arguments.get("query")
                or events[0].get("catalog_sha256") != value.get("catalog_sha256")):
            raise ValueError("readable full result/query/catalog trace mismatch")
    else:
        value = json.loads(content["text"])
    if value.get("schema_version") != 1 or value.get("backend") != backend:
        raise ValueError("wire envelope/backend differs")
    marker = value.get("response_format")
    if (response_format == "compact" and marker != "research-memory-compact/1") or (
        response_format == "full" and marker is not None
    ):
        raise ValueError("actual MCP response format differs")
    entries = value.get("entries", [])
    if len(entries) != 1 or entries[0].get("id") != expected["id"] or value.get("withheld") != []:
        raise ValueError("origin lookup did not return exactly the selected literal")
    entry = entries[0]
    if entry.get("payload") != expected["payload"]:
        raise ValueError("literal tuple/source/span lost in MCP projection")
    label = "origin_literal_source_assertion" if backend == "static" else "validated_literal_source"
    availability = "unchecked_current" if backend == "static" else "supported"
    if entry.get("label") != label or entry.get("availability") != availability:
        raise ValueError("literal trust/status label differs")
    if response_format in ("full", "readable") and entry.get("origin_source") != expected["source"]:
        raise ValueError("full origin source differs")
    budget = value.get("selection_budget", {})
    if (
        budget.get("origin_record_bytes") != 16384
        or budget.get("used_bytes") != len(canonical(expected))
        or budget.get("ranking_before_availability") is not True
    ):
        raise ValueError("shared origin selection budget differs")
    events = [row for row in trace if row.get("event") == "memory_lookup"]
    if (
        len(events) != 1
        or events[0].get("query_sha256") != digest(arguments)
        or events[0].get("error") is not None
    ):
        raise ValueError("actual response/backend trace mismatch")
    event = events[0]
    if event.get("backend") != backend:
        raise ValueError("trace backend differs")
    if response_format == "compact":
        audit = event.get("response_audit", {})
        payload = audit.get("receipt_payload", {})
        if (
            event.get("response_format") != "compact"
            or audit.get("receipt_sha256") != digest(payload)
            or value.get("audit_receipt") != audit.get("receipt_sha256")
            or audit.get("model_result_sha256") != digest(result)
            or payload.get("full_result_sha256") != digest(audit.get("full_result"))
        ):
            raise ValueError("unscrubbed compact receipt binding differs")
        base = dict(value)
        base.pop("audit_receipt")
        projected = {
            "content": [{"type": "text", "text": canonical(base).decode()}],
            "isError": False,
        }
        if payload.get("projection_result_sha256") != digest(projected):
            raise ValueError("compact projection receipt differs")
    elif response_format == "full" and event.get("response_format") is not None:
        raise ValueError("full response has unexpected compact trace")
    return {
        "backend": backend,
        "format": response_format,
        "id": expected["id"],
        "label": label,
        "availability": availability,
        "result_sha256": digest(result),
        "query_sha256": digest(arguments),
        "receipt_verification": "exact_unscrubbed_bytes"
        if response_format in ("compact", "readable")
        else "not_applicable",
        "model_calls": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_bytes())
    report = {
        "status": "started",
        "model_calls": 0,
        "scope": "actual configured MCP stdio; no OpenCode model session",
    }
    try:
        server = config["server"]
        arguments = {"query": config["expected"]["id"], "limit": 1}
        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "literal-configured-correctness", "version": "1"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "memory_lookup", "arguments": arguments},
            },
        ]
        completed = subprocess.run(
            server["command"],
            input=b"".join(canonical(row) + b"\n" for row in requests),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=server["cwd"],
            env=dict(os.environ, **server["environment"]),
            timeout=120,
            check=False,
        )
        args.out.parent.joinpath("mcp.stdout.jsonl").write_bytes(completed.stdout)
        args.out.parent.joinpath("mcp.stderr.log").write_bytes(completed.stderr)
        if completed.returncode:
            raise ValueError("configured MCP process failed")
        responses = [json.loads(line) for line in completed.stdout.splitlines() if line]
        by_id = {row.get("id"): row for row in responses}
        if (
            len(responses) != 3
            or set(by_id) != {1, 2, 3}
            or any("error" in row for row in responses)
        ):
            raise ValueError("configured MCP protocol responses incomplete")
        if [tool["name"] for tool in by_id[2]["result"]["tools"]] != ["memory_lookup"]:
            raise ValueError("configured MCP tool catalog differs")
        trace = [
            json.loads(line)
            for line in Path("/state/evidence/memory-backend-trace.jsonl").read_bytes().splitlines()
        ]
        report.update(
            validate_response(
                by_id[3]["result"],
                config["expected"],
                config["backend"],
                config["format"],
                trace,
                arguments,
            )
        )
        report["status"] = "passed"
    except BaseException as error:
        report.update(status="failed", error=type(error).__name__ + ": " + str(error))
        raise
    finally:
        args.out.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
