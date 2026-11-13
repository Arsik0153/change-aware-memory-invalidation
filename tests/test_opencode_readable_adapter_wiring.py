"""Authored adapter/configuration controls; no model, Docker, auth or network."""

from __future__ import annotations

import argparse
import copy
import io
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/opencode"))
sys.path.insert(0, str(ROOT / "scripts/opencode_benchmark/harness"))
import container_session as session  # noqa: E402
import memory_adapter as adapter  # noqa: E402
from compact_response import FORMAT as COMPACT_FORMAT, compact_result  # noqa: E402
from memory_backend import canonical, digest  # noqa: E402
from readable_response import FORMAT, readable_result  # noqa: E402


def literal_value(arm):
    subject = {
        "language": "python", "path": "src/authored.py",
        "qualname": "example", "node_kind": "function",
    }
    source = {"path": subject["path"], "sha256": "a" * 64, "size": 100}
    entry = {
        "id": "authored-literal",
        "payload": {
            "type": "source_excerpt_equals", "subject": subject,
            "origin_source": source, "origin_span": {"first_line": 2, "last_line": 4},
            "expected": {"format": "python.definition-prefix/1",
                         "text": 'def example():\r\n    return "π and ```"', "truncated": False},
        },
        "origin_source": source,
        "availability": "supported" if arm == "cami" else "unchecked_current",
        "label": "validated_literal_source" if arm == "cami" else "origin_literal_source_assertion",
    }
    if arm == "cami":
        entry["state_type"] = "carried"
    value = {
        "schema_version": 1, "backend": arm, "query": "authored query", "catalog_sha256": "b" * 64,
        "entries": [entry], "withheld": [], "matched_records": 7, "selected_records": 1,
        "truncated": True,
        "selection_budget": {"origin_record_bytes": 16384, "used_bytes": 1234,
                             "ranking_before_availability": True},
        "freshness": "verified_readset; refresh after edits" if arm == "cami" else "origin unchecked",
    }
    if arm == "cami":
        value.update(snapshot_id="c" * 64, memory_generation_id="d" * 64)
    return value


def mcp(value):
    return {"content": [{"type": "text", "text": canonical(value).decode()}], "isError": False}


def request(limit=3):
    return {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "memory_lookup", "arguments": {"query": "authored query", "limit": limit}}}


def make_server(tmp_path, monkeypatch, arm, mode="readable", case="literal"):
    value, calls = literal_value(arm), []
    if case == "note":
        value["entries"][0]["payload"] = {
            "type": "note", "subject": value["entries"][0]["payload"]["subject"],
            "text": "Authored manual assertion", "note_key": "authored-key", "sources": [],
        }
    elif case in {"empty", "withheld"}:
        if case == "withheld":
            value["withheld"] = [{"id": "authored-literal", "kind": "source_excerpt_equals",
                "subject": value["entries"][0]["payload"]["subject"],
                "reason": "contradicted", "required_action": "Do not use"}]
        value["entries"] = []

    class FakeBackend:
        def __init__(self, path, *, ranking_policy="lexical-overlap/1"):
            self.binding = {"repo": str(tmp_path / "repo"), "backend": arm,
                            "catalog_sha256": "b" * 64, "state_home": None}
            self.fail = case == "error"

        def lookup(self, query, limit):
            calls.append((query, limit))
            if self.fail:
                raise ValueError("Authored backend failure")
            return copy.deepcopy(value), {"selected_records": 1, "returned_records": len(value["entries"])}

    monkeypatch.setattr(adapter, "Backend", FakeBackend)
    trace = tmp_path / "trace.jsonl"
    server = adapter.Server(tmp_path / "binding", trace, response_format=mode)
    server.phase = "ready"
    return server, value, calls, trace


def assert_bound_result(result, audit):
    assert digest(audit["full_result"]) == audit["receipt_payload"]["full_result_sha256"]
    assert digest(result) == audit["model_result_sha256"]
    assert digest(audit["receipt_payload"]) == audit["receipt_sha256"]
    base = copy.deepcopy(result)
    text = result["content"][0]["text"]
    if audit["effective_format"] == FORMAT:
        start = text.index("```json\n") + len("```json\n")
        end = text.index("\n```", start)
        header = json.loads(text[start:end])
        assert header.pop("audit_receipt") == audit["receipt_sha256"]
        base["content"][0]["text"] = text[:start] + canonical(header).decode() + text[end:]
    else:
        value = json.loads(text)
        assert value.pop("audit_receipt") == audit["receipt_sha256"]
        base["content"][0]["text"] = canonical(value).decode()
    assert digest(base) == audit["receipt_payload"]["projection_result_sha256"]


@pytest.mark.parametrize("arm", ["static", "cami"])
@pytest.mark.parametrize("case,reason", [
    ("literal", None), ("note", "non_literal_or_mixed_records"),
    ("empty", "empty_entries"), ("withheld", "withheld_only"), ("error", "error_response"),
])
def test_readable_dispatch_records_requested_mode_and_exact_projection(tmp_path, monkeypatch, arm, case, reason):
    server, value, calls, trace = make_server(tmp_path, monkeypatch, arm, case=case)
    result = server.dispatch(request())
    record = json.loads(trace.read_text().splitlines()[-1])
    audit = record["response_audit"]
    assert calls == [("authored query", 3)]
    assert record["response_format"] == "readable"
    assert record["query_sha256"] == digest(request()["params"]["arguments"])
    assert record["requested_limit"] == 3
    assert record["response_bytes"] == len(canonical(result))
    assert record["backend"] == arm and record["catalog_sha256"] == "b" * 64
    assert audit["requested_format"] == FORMAT and audit["fallback_reason"] == reason
    assert audit["effective_format"] == (FORMAT if reason is None else COMPACT_FORMAT)
    assert audit["receipt_payload"]["format"] == audit["effective_format"]
    assert_bound_result(result, audit)
    if case != "error":
        assert audit["full_result"] == mcp(value)
        assert result == readable_result(mcp(value))[0]
    else:
        assert result["isError"] is True
        failed = json.loads(audit["full_result"]["content"][0]["text"])
        assert failed["entries"] == [] and failed["withheld"] == []
        assert failed["freshness"] == "unavailable; no historical result substituted"
        assert failed["error"]["code"] == "memory_lookup_failed"
        assert record["error"] == {"type": "ValueError", "message": "Authored backend failure"}
    if reason:
        expected, compact_audit = compact_result(audit["full_result"])
        assert canonical(result) == canonical(expected)
        assert all(audit[key] == val for key, val in compact_audit.items())


@pytest.mark.parametrize("arm", ["static", "cami"])
def test_readable_error_after_success_never_reuses_previous_result(tmp_path, monkeypatch, arm):
    server, _, calls, trace = make_server(tmp_path, monkeypatch, arm)
    first = server.dispatch(request())
    assert "def example" in first["content"][0]["text"]
    server.backend.fail = True
    result = server.dispatch(request())
    record = json.loads(trace.read_text().splitlines()[-1])
    assert result["isError"] and "def example" not in canonical(result).decode()
    assert "def example" not in canonical(record["response_audit"]["full_result"]).decode()
    assert calls == [("authored query", 3)] * 2
    assert record["response_format"] == "readable"
    assert record["response_audit"]["fallback_reason"] == "error_response"
    assert_bound_result(result, record["response_audit"])


@pytest.mark.parametrize("arm", ["static", "cami"])
@pytest.mark.parametrize("mode", ["full", "compact"])
def test_existing_response_bytes_and_audits_unchanged(tmp_path, monkeypatch, arm, mode):
    server, value, _, trace = make_server(tmp_path, monkeypatch, arm, mode)
    result = server.dispatch(request())
    record = json.loads(trace.read_text().splitlines()[-1])
    if mode == "full":
        assert canonical(result) == canonical(mcp(value))
        assert "response_format" not in record and "response_audit" not in record
    else:
        expected, audit = compact_result(mcp(value))
        assert canonical(result) == canonical(expected) and record["response_audit"] == audit
        assert record["response_format"] == "compact"


def test_readable_projection_and_storage_remain_inside_observed_span(tmp_path, monkeypatch):
    server, _, _, trace = make_server(tmp_path, monkeypatch, "static")
    events = []
    clock = iter([10.0, 11.0])
    monkeypatch.setattr(adapter.time, "perf_counter", lambda: events.append("wall") or next(clock))
    monkeypatch.setattr(adapter, "cpu", lambda: events.append("cpu") or 0.0)
    def project(result):
        events.append("project")
        return readable_result(result)
    monkeypatch.setattr(adapter, "readable_result", project)
    server.backend.binding["state_home"] = str(tmp_path / "state")
    monkeypatch.setattr(adapter, "storage", lambda path: events.append("storage") or 41)
    original_trace = adapter.trace
    def append(path, value):
        events.append("trace")
        original_trace(path, value)
    monkeypatch.setattr(adapter, "trace", append)
    server.dispatch(request())
    assert events == ["wall", "cpu", "project", "storage", "wall", "cpu", "trace"]
    record = json.loads(trace.read_text().splitlines()[-1])
    assert record["state_bytes"] == 41 and record["wall_seconds"] == 1.0


def test_readable_failed_audit_append_does_not_return_response(tmp_path, monkeypatch):
    server, _, _, _ = make_server(tmp_path, monkeypatch, "static")
    def fail(*args):
        raise OSError("Authored audit append failure")
    monkeypatch.setattr(adapter, "trace", fail)
    with pytest.raises(OSError, match="audit append failure"):
        server.dispatch(request())


def test_readable_stdio_keeps_only_jsonrpc_on_stdout(tmp_path, monkeypatch):
    _, _, _, _ = make_server(tmp_path, monkeypatch, "static")
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "clientInfo": {}, "capabilities": {}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"}, request(),
    ]
    incoming = io.BytesIO(b"".join(canonical(row) + b"\n" for row in messages))
    outgoing = io.BytesIO()
    adapter.serve(tmp_path / "binding", tmp_path / "stdio-trace", incoming, outgoing,
                  response_format="readable")
    replies = [json.loads(line) for line in outgoing.getvalue().splitlines()]
    assert [row["id"] for row in replies] == [1, 2]
    assert replies[-1]["result"]["content"][0]["text"].startswith("# Memory source prefixes\n")


@pytest.mark.parametrize("mode", [None, "full", "compact", "readable"])
def test_adapter_cli_accepts_optin_and_preserves_default(tmp_path, monkeypatch, mode):
    seen = []
    monkeypatch.setattr(adapter, "serve", lambda *args, **kwargs: seen.append(kwargs))
    argv = ["memory_adapter.py", "serve", "--binding", str(tmp_path / "binding"),
            "--trace", str(tmp_path / "trace")]
    if mode:
        argv += ["--response-format", mode]
    monkeypatch.setattr(sys, "argv", argv)
    assert adapter.main() == 0 and seen == [{"response_format": mode or "full", "ranking_policy": "lexical-overlap/1"}]


def test_adapter_rejects_unknown_format_before_backend_construction(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "Backend", lambda path: pytest.fail("backend constructed"))
    with pytest.raises(ValueError, match="response format"):
        adapter.Server(tmp_path / "binding", tmp_path / "trace", response_format="unknown")
    monkeypatch.setattr(sys, "argv", ["memory_adapter.py", "serve", "--binding", "binding",
                                    "--trace", "trace", "--response-format", "unknown"])
    with pytest.raises(SystemExit) as exc:
        adapter.main()
    assert exc.value.code == 2


@pytest.mark.parametrize("arm", ["plain", "static", "cami"])
@pytest.mark.parametrize("tier", [None, "auto", "priority"])
def test_harness_formats_change_only_memory_command(arm, tier):
    full = session.configuration(arm, "authored/binding.json", service_tier=tier)
    assert session.configuration(arm, "authored/binding.json", "full", tier) == full
    assert full["model"] == "openai/gpt-6.1-sol#high"
    if tier:
        assert full["providers"]["openai"]["models"]["gpt-6.1-sol"]["settings"] == {"serviceTier": tier}
    for mode in ("compact", "readable"):
        actual = session.configuration(arm, "authored/binding.json", mode, tier)
        if arm != "plain":
            command = actual["mcp"]["servers"]["research_memory"]["command"]
            assert command[-2:] == ["--response-format", mode]
            del command[-2:]
        else:
            assert "mcp" not in actual
        assert canonical(actual) == canonical(full)


@pytest.mark.parametrize("arm", ["plain", "static", "cami"])
def test_harness_configuration_rejects_unknown_format(arm):
    with pytest.raises(ValueError, match="unsupported memory response format"):
        session.configuration(arm, "authored/binding.json", "unknown")


@pytest.mark.parametrize("mode", [None, "full", "compact", "readable", "unknown"])
def test_harness_cli_format_validation_stops_before_any_execution(monkeypatch, mode):
    seen = []
    parse = argparse.ArgumentParser.parse_args
    class Parsed(Exception):
        pass
    def capture(parser, *args, **kwargs):
        seen.append(parse(parser, *args, **kwargs))
        raise Parsed
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", capture)
    argv = ["container_session.py", "--workspace", "workspace", "--state-dir", "state",
            "--memory-dir", "memory", "--arm", "plain", "--out", "out"]
    if mode:
        argv += ["--memory-response-format", mode]
    monkeypatch.setattr(sys, "argv", argv)
    if mode == "unknown":
        with pytest.raises(SystemExit) as exc:
            session.main()
        assert exc.value.code == 2 and seen == []
    else:
        with pytest.raises(Parsed):
            session.main()
        assert seen[0].memory_response_format == (mode or "full")
