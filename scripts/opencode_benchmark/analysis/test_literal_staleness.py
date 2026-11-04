"""Authored offline tuples/receipts/terminal fixtures only; no core or models."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy
import sys
from types import ModuleType

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_literal_calls import COMPACT, canonical, classify, mcp, projection  # noqa: E402
from literal_reference import FORMAT, body, sha  # noqa: E402
from summarize_literal_staleness import load_controls, load_module, summarize  # noqa: E402

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "scripts/analyze_opencode_staleness.py").is_file())
CONTROLS = ROOT / "scripts/opencode_benchmark/analysis/summarize_terminal_staleness.py"
ANALYZER = ROOT / "scripts/analyze_opencode_staleness.py"


@pytest.fixture
def case(tmp_path):
    origin, current = tmp_path / "origin", tmp_path / "current"
    origin.mkdir()
    current.mkdir()
    raw = b"@(\n deco\n)\ndef a():\n    return 1\n"
    (origin / "m.py").write_bytes(raw)
    (current / "m.py").write_bytes(raw)
    result = body(origin, "m.py", "a")
    assert result.text == raw.decode() and result.first_line == 1
    source = {"path": "m.py", "sha256": sha(raw), "size": len(raw)}
    payload = {"type": "source_excerpt_equals", "subject": {"language": "python", "path": "m.py", "qualname": "a", "node_kind": "function"},
               "expected": {"format": FORMAT, "text": raw.decode(), "truncated": False},
               "origin_source": source, "origin_span": {"first_line": 1, "last_line": 5}}
    catalog = {"schema_version": 2, "source_roots": ["."], "excluded_paths": [], "records": [{"id": "a", "payload": payload, "source": source}]}
    analyzer = load_module("test_literal_old_normalizer", ANALYZER)
    return origin, current, catalog, analyzer


def wire(catalog, *, backend="static", withheld=False, compact=False):
    record = catalog["records"][0]
    arguments = {"query": "a", "limit": 1}
    value = {"schema_version": 1, "backend": backend, "query": "a", "catalog_sha256": sha(canonical(catalog)), "selected_records": 1,
             "entries": [] if withheld else [{"id": "a", "payload": record["payload"], "origin_source": record["source"]}],
             "withheld": [{"id": "a", "kind": "source_excerpt_equals", "subject": record["payload"]["subject"], "reason": "source_excerpt_mismatch", "required_action": "review_and_update_expectation"}] if withheld else []}
    full = mcp(canonical(value).decode())
    event = {"event": "memory_lookup", "backend": backend, "catalog_sha256": sha(canonical(catalog)), "query_sha256": sha(canonical(arguments)),
             "returned_records": len(value["entries"]), "withheld_records": len(value["withheld"]), "error": None}
    model = value
    if compact:
        model = projection(value)
        base = mcp(canonical(model).decode())
        receipt_payload = {"format": COMPACT, "full_result_sha256": sha(canonical(full)), "projection_result_sha256": sha(canonical(base))}
        receipt = sha(canonical(receipt_payload))
        model["audit_receipt"] = receipt
        event.update(response_format="compact", response_audit={"receipt_sha256": receipt, "receipt_payload": receipt_payload,
                     "full_result": full, "model_result_sha256": sha(canonical(mcp(canonical(model).decode())))})
    text = canonical(model).decode()
    event["response_bytes"] = len(canonical(mcp(text)))
    rows = [{"type": "tool_use", "part": {"id": "lookup", "tool": "research_memory_memory_lookup", "state": {"status": "completed", "input": arguments, "output": text, "time": {"start": 2, "end": 3}}}}]
    return rows, [event]


def assess(case, *, rows=None, events=None, **kwargs):
    origin, current, catalog, analyzer = case
    if rows is None:
        rows, events = wire(catalog, **kwargs)
    return classify(analyzer, rows, catalog, origin, current, kwargs.get("backend", "static"), events)


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
def test_reference_lexical_physical_decorator_newlines_and_unicode(tmp_path, ending):
    text = ('@(\n decorator\n)\ndef a():\n    return "π\u2028x"  # exact\n').replace("\n", ending)
    (tmp_path / "m.py").write_bytes(text.encode())
    result = body(tmp_path, "m.py", "a")
    assert result.status == "unique_definition" and result.text == text and result.first_line == 1 and not result.truncated


@pytest.mark.parametrize("compact", [False, True])
def test_full_and_compact_opening_line_edit_obsolete(case, compact):
    origin, current, _, _ = case
    (current / "m.py").write_bytes((origin / "m.py").read_bytes().replace(b"@(\n", b"@( # changed opening\n"))
    result = assess(case, compact=compact)
    assert result["unsupported_calls"] == 0
    assert result["records"][0]["assessment"] == "obsolete_literal_tuple"
    assert result["records"][0]["exposed_to_agent"] is True
    assert result["memory_calls"][0]["response_format"] == ("compact_verified" if compact else "full")


def test_flag_only_2401_to_2400_detected(tmp_path):
    origin, current = tmp_path / "origin", tmp_path / "current"
    origin.mkdir()
    current.mkdir()
    prefix, suffix = 'def a():\n    return "', '"\n'
    text = prefix + 'x' * (2401 - len(prefix) - len(suffix)) + suffix
    assert len(text) == 2401
    (origin / "m.py").write_bytes(text.encode())
    (current / "m.py").write_bytes(text[:-1].encode())
    old, new = body(origin, "m.py", "a"), body(current, "m.py", "a")
    assert old.text == new.text and old.truncated is True and new.truncated is False


def test_classifier_flag_only_edit_obsolete_even_when_text_equal(case):
    origin, current, catalog, _ = case
    prefix, suffix = 'def a():\n    return "', '"\n'
    text = prefix + 'x' * (2401 - len(prefix) - len(suffix)) + suffix
    (origin / "m.py").write_bytes(text.encode())
    (current / "m.py").write_bytes(text[:-1].encode())
    record = catalog["records"][0]
    source = {"path": "m.py", "sha256": sha(text.encode()), "size": len(text.encode())}
    record["source"] = source
    record["payload"].update(origin_source=source, origin_span={"first_line": 1, "last_line": 2}, expected={"format": FORMAT, "text": text[:2400], "truncated": True})
    result = assess(case)
    observed = result["records"][0]
    assert observed["assessment"] == "obsolete_literal_tuple"
    assert observed["origin_tuple"]["text"] == observed["current_tuple"]["text"]
    assert observed["origin_tuple"]["truncated"] is True and observed["current_tuple"]["truncated"] is False


@pytest.mark.parametrize("prefix", [b'\xef\xbb\xbf', b'# coding: latin-1\n'])
def test_strict_encoding_policy_explicit(tmp_path, prefix):
    (tmp_path / "m.py").write_bytes(prefix + b'def a(): pass\n')
    assert body(tmp_path, "m.py", "a").status == "unsupported_encoding"


def test_suffix_only_edit_same_truncated_tuple(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    text = 'def a():\n    return "' + 'x' * 2500 + '"\n'
    (first / "m.py").write_text(text)
    (second / "m.py").write_text(text[:-3] + 'y"\n')
    a, b = body(first, "m.py", "a"), body(second, "m.py", "a")
    assert a.expected() == b.expected() and a.source_sha256 != b.source_sha256


@pytest.mark.parametrize("withheld", [False, True])
def test_after_possible_write_both_channels_unknown(case, withheld):
    _, current, catalog, _ = case
    (current / "m.py").unlink()  # Must not substitute this canonical state after edits.
    rows, events = wire(catalog, withheld=withheld)
    rows.insert(0, {"type": "tool_use", "part": {"id": "shell", "tool": "shell", "state": {"time": {"start": 1}}}})
    result = assess(case, rows=rows, events=events)
    observation = result["records"][0]
    assert observation["assessment"] == "unknown_after_possible_write"
    assert "current_tuple" not in observation
    assert observation["exposed_to_agent"] is (not withheld)


@pytest.mark.parametrize("change,expected", [("delete", "origin_definition_absent"), ("parse", "unknown_current_source"), ("symlink", "unknown_current_source")])
def test_current_missing_parse_or_type_unknowns(case, tmp_path, change, expected):
    _, current, _, _ = case
    if change == "delete":
        (current / "m.py").unlink()
    elif change == "parse":
        (current / "m.py").write_text("def a(:\n")
    else:
        (current / "m.py").unlink()
        (current / "m.py").symlink_to(tmp_path / "missing")
    assert assess(case)["records"][0]["assessment"] == expected


@pytest.mark.parametrize("tamper", ["missing_audit", "full_digest", "model_digest", "receipt", "unknown_format"])
def test_compact_missing_redacted_or_tampered_evidence_unsupported(case, tamper):
    _, _, catalog, _ = case
    rows, events = wire(catalog, compact=True)
    if tamper == "missing_audit":
        del events[0]["response_audit"]
    elif tamper == "full_digest":
        events[0]["response_audit"]["full_result"]["content"][0]["text"] = "[REDACTED]"
    elif tamper == "model_digest":
        events[0]["response_audit"]["model_result_sha256"] = "0" * 64
    else:
        value = json.loads(rows[0]["part"]["state"]["output"])
        value["audit_receipt" if tamper == "receipt" else "response_format"] = "unknown"
        rows[0]["part"]["state"]["output"] = canonical(value).decode()
    result = assess(case, rows=rows, events=events)
    assert result["unsupported_calls"] == 1 and result["records"] == []
    assert result["memory_calls"][0]["reported_returned_ids"] == ["a"]


def test_missing_trace_limit_hash_and_duplicate_calls(case):
    _, _, catalog, analyzer = case
    rows, events = wire(catalog)
    assert assess(case, rows=rows, events=None)["unsupported_calls"] == 1
    changed = copy.deepcopy(events)
    changed[0]["query_sha256"] = sha(canonical({"query": "a", "limit": 2}))
    assert assess(case, rows=rows, events=changed)["unsupported_calls"] == 1
    with pytest.raises(ValueError, match="duplicate tool"):
        classify(analyzer, rows + rows, catalog, case[0], case[1], "static", events)


@pytest.mark.parametrize("problem", ["duplicate", "source", "null_channel"])
def test_full_response_invalid_selection_or_payload_unknown(case, problem):
    _, _, catalog, _ = case
    rows, events = wire(catalog)
    value = json.loads(rows[0]["part"]["state"]["output"])
    if problem == "duplicate":
        value["withheld"] = [{"id": "a"}]
        value["selected_records"] = 2
        events[0]["withheld_records"] = 1
    elif problem == "source":
        value["entries"][0]["origin_source"]["sha256"] = "0" * 64
    else:
        value["entries"] = None
    text = canonical(value).decode()
    rows[0]["part"]["state"]["output"] = text
    events[0]["response_bytes"] = len(canonical(mcp(text)))
    result = assess(case, rows=rows, events=events)
    assert result["unsupported_calls"] == 1 and result["records"] == []


def test_old_catalog_explicitly_rejected(case):
    _, _, catalog, _ = case
    changed = copy.deepcopy(catalog)
    changed["schema_version"] = 1
    with pytest.raises(ValueError, match="old notes use old analyzer"):
        classify(case[3], [], changed, case[0], case[1], "static", [])


def test_installed_compact_projector_real_format_authenticates_independently(case, monkeypatch):
    _, _, catalog, _ = case
    rows, events = wire(catalog)
    full = mcp(rows[0]["part"]["state"]["output"])
    utilities = ModuleType("memory_backend")
    utilities.canonical = canonical
    utilities.digest = lambda value: sha(canonical(value))
    monkeypatch.setitem(sys.modules, "memory_backend", utilities)
    projector = runpy.run_path(str(ROOT / "integrations/opencode/compact_response.py"))["compact_result"]
    actual, audit = projector(full)
    rows[0]["part"]["state"]["output"] = actual["content"][0]["text"]
    events[0].update(response_format="compact", response_audit=audit, response_bytes=len(canonical(actual)))
    result = assess(case, rows=rows, events=events)
    assert result["unsupported_calls"] == 0 and result["memory_calls"][0]["response_format"] == "compact_verified"


def test_legacy_ast_line_recipe_remains_distinct(case):
    origin, _, _, analyzer = case
    status, _, old = analyzer.body(origin, "m.py", "a")
    current = body(origin, "m.py", "a")
    assert status == "unique_definition" and old.startswith(" deco\n")
    assert current.text.startswith("@(\n") and old != current.text


def test_terminal_wrapper_preserves_plain_failed_and_missing_telemetry(case, tmp_path):
    origin, current, catalog, _ = case
    controls = load_controls(CONTROLS)
    run = tmp_path / "run"
    (run / "trials").mkdir(parents=True)
    sequence = ["task-a", "task-a", "task-b", "task-b"]
    def save(path, value):
        path.write_bytes(canonical(value) + b"\n")
    save(run / "frozen-study.json", {"bundle_kind": "development", "arms": ["plain", "static", "cami"], "normalized": {"sequence": sequence}})
    plan = [{"id": f"r{rep}-{arm}-s{stage}", "repetition": rep, "arm": arm, "stage": stage, "task": sequence[stage - 1]} for rep in range(1, 4) for arm in ("plain", "static", "cami") for stage in range(1, 5)]
    save(run / "plan.json", {"trials": plan})
    catalog_path = tmp_path / "catalog.json"
    save(catalog_path, catalog)
    catalog_hash = controls.sha(catalog_path)
    for trial in [p for p in plan if p["repetition"] == 1 and p["stage"] == 1]:
        directory = run / "trials" / trial["id"]
        (directory / "session/evidence").mkdir(parents=True)
        save(directory / "canonical-reset.json", {"canonical_files": controls.inventory(current)})
        save(directory / "memory-before.json", {"prepared/catalog.json": catalog_hash})
        if trial["arm"] == "plain":
            messages = []
        elif trial["arm"] == "static":
            rows, events = wire(catalog, backend="static")
            state = rows[0]["part"]["state"]
            messages = [{"id": "m1", "type": "assistant", "content": [{"id": "lookup", "type": "tool", "name": "memory_lookup", "time": {"created": 2, "completed": 3}, "state": {"status": "completed", "input": state["input"], "content": [{"type": "text", "text": state["output"]}]}}]}]
            (directory / "session/evidence/memory-backend-trace.jsonl").write_bytes(b"".join(canonical(e) + b"\n" for e in events))
        else:
            messages = None
        if messages is not None:
            save(directory / "session/evidence/messages.json", messages)
        artifacts = {name: value["sha256"] for name, value in controls.inventory(directory).items()}
        save(directory / "terminal.json", {"trial": trial, "status": "failed" if trial["arm"] == "cami" else "passed", "artifact_hashes": artifacts, "immutable_memory": {"prepared/catalog.json": catalog_hash}})
    result = summarize(run, catalog_path, origin, current, current, CONTROLS, ANALYZER)
    assert result["completed_trials"] == 3 and result["planned_trials"] == 36
    assert len(result["trials"]) == 3 and result["unassessed_trial_ids"] == ["r1-cami-s1"]
    assert result["trials"][0]["backend_crosscheck"]["status"] == "plain_no_external_memory_expected"
    assert result["trials"][1]["records"][0]["assessment"] == "same_literal_tuple"
    assert result["trials"][2]["terminal_status"] == "failed"
    assert result["unsupported_call_count_complete"] is False


@pytest.mark.parametrize("extra", [{"response_format": "future-format/2"}, {"response_audit": {}}, {"response_audit": None}])
def test_full_unknown_trace_format_or_audit_is_unsupported(case, extra):
    rows, events = wire(case[2])
    events[0].update(extra)
    result = assess(case, rows=rows, events=events)
    assert result["unsupported_calls"] == 1
    assert not result["records"]
