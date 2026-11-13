"""Readable controller/preflight controls; authored data, no Docker/model/network."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import types

import pytest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "harness")]
import literal_stdio_worker as worker  # noqa: E402
import memory_format_evidence as observer  # noqa: E402
import study_common as common  # noqa: E402
import study_ledger as ledger  # noqa: E402
import study_schema as schema  # noqa: E402
import verify_literal_containers as preflight  # noqa: E402
from readable_receipts import COMPACT, READABLE, verify_readable_result  # noqa: E402
from test_readable_receipts import fixture, mcp, readable_result  # noqa: E402


def packet(arm="cami", case="literal", text="def f():\r\n    return 'π ```'", query=None):
    value = fixture(text, arm)
    if case == "note":
        value["entries"][0]["payload"] = {
            "type": "note", "subject": value["entries"][0]["payload"]["subject"],
            "text": "Authored manual note", "note_key": "authored-key", "sources": [],
        }
    elif case in ("empty", "withheld"):
        value["entries"] = []
        if case == "empty":
            value["withheld"] = []
    elif case == "error":
        value = {"schema_version": 1, "entries": [], "withheld": [],
                 "error": {"code": "memory_lookup_failed", "type": "ValueError", "message": "Unavailable"},
                 "freshness": "unavailable; no historical result substituted"}
    if case != "error":
        value["query"] = query or value["query"]
    arguments = {"query": query or value.get("query", "query echo"), "limit": 3}
    result, audit = readable_result(mcp(value, case == "error"))
    event = {"event": "memory_lookup", "backend": arm, "query_sha256": observer.digest(arguments),
             "response_format": "readable", "response_audit": audit,
             "response_bytes": len(worker.canonical(result)), "requested_limit": 3,
             "catalog_sha256": value.get("catalog_sha256"),
             "error": {"type": "ValueError"} if case == "error" else None}
    part = {"id": "call-1", "type": "tool", "name": "research_memory_memory_lookup",
            "state": {"status": "completed", "input": arguments, "content": copy.deepcopy(result["content"])}}
    return [{"type": "assistant", "content": [part]}], [event], result


@pytest.mark.parametrize("arm", ["static", "cami"])
@pytest.mark.parametrize("case", ["literal", "note", "empty", "withheld", "error"])
def test_readable_observer_handles_readable_and_explicit_compact_fallbacks(arm, case):
    messages, events, _ = packet(arm, case)
    observed = observer.inspect_format(messages, events, arm, "readable")
    assert observed["status"] == "matched" and observed["completed_observations"] == 1
    assert observed["requested_format"] == "readable"
    assert observed["observations"][0]["format"] == "readable"
    assert observed["observations"][0]["effective_format"] == (READABLE if case == "literal" else COMPACT)
    assert "metadata_binding_only" in observed["receipt_verification"]


def test_mixed_fallbacks_repeated_queries_join_receipt_multisets_without_order():
    messages, events, _ = packet(case="literal")
    for index, case in enumerate(("note", "withheld", "literal"), 2):
        more, trace, _ = packet(case=case)
        more[0]["content"][0]["id"] = "call-" + str(index)
        messages[0]["content"].extend(more[0]["content"])
        events.extend(trace)
    before = copy.deepcopy((messages, events))
    observed = observer.inspect_format(messages, list(reversed(events)), "cami", "readable")
    assert observed["status"] == "matched" and observed["completed_observations"] == 4
    assert (messages, events) == before
    assert observer.inspect_format(messages, events[1:], "cami", "readable")["status"] == "unsupported_or_mismatch"


@pytest.mark.parametrize("arm,expected", [("plain", "not_applicable"), ("static", "not_observed"), ("cami", "not_observed")])
def test_readable_no_observations_remain_explicit(arm, expected):
    assert observer.inspect_format([], [], arm, "readable")["status"] == expected


@pytest.mark.parametrize("fault", [
    "wrongarm", "missingbackend", "unrecognizederror", "errorwithentries", "errorfreshness",
    "requestedcompact", "badauditmode", "fallbackreason", "badreceipt", "badquery",
    "duplicatecall", "extrastringpart", "truncated", "nontext", "nonstring", "malformedheader",
    "missingtrace", "extratrace", "plaingroup", "fullinstead",
])
def test_readable_observer_rejects_mismatches_and_malformed_metadata(fault):
    messages, events, _ = packet(case="error" if fault in {
        "unrecognizederror", "errorwithentries", "errorfreshness"} else "literal")
    part, event = messages[0]["content"][0], events[0]
    if fault == "wrongarm":
        messages, _, _ = packet("static")
    elif fault == "missingbackend":
        messages, events, _ = packet(case="note")
        value = json.loads(messages[0]["content"][0]["state"]["content"][0]["text"])
        value.pop("backend")
        messages[0]["content"][0]["state"]["content"][0]["text"] = json.dumps(value)
    elif fault in {"unrecognizederror", "errorwithentries", "errorfreshness"}:
        value = json.loads(part["state"]["content"][0]["text"])
        if fault == "unrecognizederror":
            value["error"]["code"] = "unknown"
        elif fault == "errorwithentries":
            value["entries"] = [{"id": "old"}]
        else:
            value["freshness"] = "historical"
        part["state"]["content"][0]["text"] = json.dumps(value)
    elif fault == "requestedcompact":
        event["response_format"] = "compact"
    elif fault == "badauditmode":
        event["response_audit"]["requested_format"] = COMPACT
    elif fault == "fallbackreason":
        event["response_audit"]["fallback_reason"] = "made_up"
    elif fault == "badreceipt":
        event["response_audit"]["receipt_sha256"] = "0" * 64
    elif fault == "badquery":
        event["query_sha256"] = observer.digest({"query": "other", "limit": 3})
    elif fault == "duplicatecall":
        messages[0]["content"].append(copy.deepcopy(part))
    elif fault == "extrastringpart":
        part["state"]["content"].append({"type": "text", "text": "extra"})
    elif fault == "truncated":
        part["state"]["metadata"] = {"truncated": True}
    elif fault == "nontext":
        part["state"]["content"][0]["type"] = "image"
    elif fault == "nonstring":
        part["state"]["content"][0]["text"] = []
    elif fault == "malformedheader":
        part["state"]["content"][0]["text"] = part["state"]["content"][0]["text"].replace('"backend":', '"extra":1,"backend":', 1)
    elif fault == "missingtrace":
        events = []
    elif fault == "extratrace":
        events.append(copy.deepcopy(event))
    elif fault == "fullinstead":
        part["state"]["content"] = copy.deepcopy(event["response_audit"]["full_result"]["content"])
    arm = "plain" if fault == "plaingroup" else "cami"
    assert observer.inspect_format(messages, events, arm, "readable")["status"] == "unsupported_or_mismatch"


def test_readable_scrubbed_source_stays_metadata_only_and_exact_verifier_rejects():
    messages, events, result = packet(text="def f():\n    return 'private@example.test'\n")
    scrubbed = result["content"][0]["text"].replace("private@example.test", "[REDACTED_EMAIL]")
    messages[0]["content"][0]["state"]["content"][0]["text"] = scrubbed
    observed = observer.inspect_format(messages, events, "cami", "readable")
    assert observed["status"] == "matched"
    assert "original full/projected/model bytes not checked" in observed["receipt_verification"]
    changed = copy.deepcopy(result)
    changed["content"][0]["text"] = scrubbed
    with pytest.raises(ValueError, match="source"):
        verify_readable_result(changed, events[0]["response_audit"])


def worker_case(arm="cami", source="def f():\r\n    return 'π ```'"):
    value = fixture(source, arm)
    entry = value["entries"][0]
    expected = {"id": entry["id"], "payload": entry["payload"], "source": entry["origin_source"]}
    arguments = {"query": expected["id"], "limit": 1}
    value.update(query=expected["id"], withheld=[], matched_records=1, selected_records=1, truncated=False)
    value["selection_budget"]["used_bytes"] = len(worker.canonical(expected))
    result, audit = readable_result(mcp(value))
    event = {"event": "memory_lookup", "backend": arm, "query_sha256": worker.digest(arguments),
             "response_format": "readable", "response_audit": audit, "error": None,
             "response_bytes": len(worker.canonical(result)), "requested_limit": 1,
             "catalog_sha256": value["catalog_sha256"]}
    return [result, expected, arm, "readable", [event], arguments]


@pytest.mark.parametrize("arm", ["static", "cami"])
@pytest.mark.parametrize("source", ["def f():\n    return 7\n", "CRLF\r\nlast", "CR\r", "π no newline", "```\n````python\n", "control\x01"])
def test_stdio_readable_exact_source_and_safe_compact_fallback(arm, source):
    args = worker_case(arm, source)
    before = copy.deepcopy(args)
    report = worker.validate_response(*args)
    assert report["format"] == "readable" and report["receipt_verification"] == "exact_unscrubbed_bytes"
    assert args == before


@pytest.mark.parametrize("fault", [
    "source", "suffix", "auditextra", "modelextra", "audithash", "bytes", "query", "limit",
    "catalog", "backend", "requestedmode", "missingtrace", "duplicatetrace", "originalsource",
])
def test_stdio_readable_rejects_byte_and_backend_trace_mismatches(fault):
    args = worker_case()
    event = args[4][0]
    if fault == "source":
        args[0]["content"][0]["text"] = args[0]["content"][0]["text"].replace("return 'π ```'", "return 'changed'")
    elif fault == "suffix":
        args[0]["content"][0]["text"] += "extra"
    elif fault == "auditextra":
        event["response_audit"]["unknown"] = True
    elif fault == "modelextra":
        args[0]["unknown"] = True
    elif fault == "audithash":
        event["response_audit"]["model_result_sha256"] = "0" * 64
    elif fault == "bytes":
        event["response_bytes"] += 1
    elif fault == "query":
        args[5]["query"] = "different"
    elif fault == "limit":
        event["requested_limit"] = 2
    elif fault == "catalog":
        event["catalog_sha256"] = "0" * 64
    elif fault == "backend":
        event["backend"] = "static"
    elif fault == "requestedmode":
        event["response_format"] = "compact"
    elif fault == "missingtrace":
        args[4] = []
    elif fault == "duplicatetrace":
        args[4].append(copy.deepcopy(event))
    elif fault == "originalsource":
        args[1] = copy.deepcopy(args[1])
        args[1]["source"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        worker.validate_response(*args)


def test_readable_controller_helper_is_required_pinned_and_immutable(tmp_path):
    for path in HERE.glob("*.py"):
        shutil.copyfile(path, tmp_path / path.name)
    pins = schema.controller_files(tmp_path)
    assert pins["readable_receipts.py"] == common.digest(HERE / "readable_receipts.py")
    common.verify_files(tmp_path, pins)
    helper = tmp_path / "readable_receipts.py"
    helper.write_text(helper.read_text() + "\n# Authored tamper\n")
    with pytest.raises(ValueError, match="sealed file mismatch"):
        common.verify_files(tmp_path, pins)
    helper.unlink()
    with pytest.raises(ValueError, match="required controller/helper"):
        schema.controller_files(tmp_path)


def test_isolated_stdio_worker_imports_only_the_trusted_sibling(tmp_path):
    trusted, untrusted = tmp_path / "trusted", tmp_path / "untrusted"
    trusted.mkdir()
    untrusted.mkdir()
    for name in ("literal_stdio_worker.py", "readable_receipts.py"):
        shutil.copyfile(HERE / name, trusted / name)
    (untrusted / "readable_receipts.py").write_text("raise RuntimeError('untrusted working directory helper')\n")
    completed = subprocess.run([sys.executable, "-I", str(trusted / "literal_stdio_worker.py"), "--help"],
                               cwd=untrusted, capture_output=True, check=False)
    assert completed.returncode == 0 and b"--config" in completed.stdout and not completed.stderr


def test_resume_rejects_readable_format_changes_without_any_execution(tmp_path):
    study = {"memory_response_format": "readable"}
    common.write(tmp_path / "study.json", study)
    common.write(tmp_path / "frozen-study.json", study)
    common.write(tmp_path / "run.json", {"study_sha256": common.digest(tmp_path / "study.json"),
                                        "mode": "plan", "study_path": str(tmp_path / "study.json")})
    ledger.verify_binding(tmp_path, common.digest(tmp_path / "study.json"), False)
    original = common.digest(tmp_path / "study.json")
    (tmp_path / "study.json").write_text(json.dumps({"memory_response_format": "compact"}))
    with pytest.raises(ValueError, match="resumed frozen study bytes changed"):
        ledger.verify_binding(tmp_path, original, False)


def test_preflight_plans_all_six_cases_without_writes(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["verify_literal_containers.py"])
    preflight.main()
    plan = json.loads(capsys.readouterr().out)
    assert plan["cases"] == [arm + "/" + mode for arm in ("static", "cami")
                             for mode in ("full", "compact", "readable")]
    assert plan["writes"] is False and plan["model_calls"] == 0


@pytest.mark.parametrize("policy", ["lexical-overlap/1", "identifier-mentions/1"])
def test_preflight_mounts_pinned_worker_and_helper_readonly_for_all_six_cases(tmp_path, monkeypatch, policy):
    import container_session as harness
    from study_runtime import validate_ranking_trace

    controller = tmp_path / "installed-controller"
    controller.mkdir()
    for name in ("literal_stdio_worker.py", "readable_receipts.py"):
        shutil.copyfile(HERE / name, controller / name)
    original_sources = common.file_hashes(controller)
    record = worker_case()[1]
    study = {"pins": {"controller": {"root": str(controller)}}, "harness": harness.__file__,
             "normalized": {"tasks": [{"archive": "authored.tar", "archive_sha256": "a" * 64}],
                            "seed": "authored-seed.json"}, "bundle_path": str(tmp_path),
             "cami_source": str(tmp_path / "source"), "adapter": str(tmp_path / "adapter")}
    study_path = tmp_path / "study.json"
    common.write(study_path, study)
    common.write(tmp_path / "authored-seed.json", {"authored": True})
    validations, calls = [], []
    def validate(value, execute=False):
        validations.append(execute)
        assert common.file_hashes(controller) == original_sources
    def namespace(arm, study_sha):
        arm.mkdir()
        (arm / "workspace").mkdir()
        (arm / "memory").mkdir()
    def prepare(study, workspace, memory, output, backend):
        (memory / "prepared").mkdir()
        (memory / "prepared/catalog.json").write_bytes(worker.canonical({"records": [record]}))
        return {"status": "passed", "authored": True}
    def container(study, mounts, argv, output, timeout):
        calls.append((mounts, argv))
        assert argv[:3] == ["python", "-I", "/opt/literal_stdio_worker.py"]
        assert (controller / "literal_stdio_worker.py", "/opt/literal_stdio_worker.py", True) in mounts
        assert (controller / "readable_receipts.py", "/opt/readable_receipts.py", True) in mounts
        case = next(source for source, target, _ in mounts if target == "/check")
        config = common.read(case / "config.json")
        mode = config["format"]
        command = config["server"]["command"]
        if mode == "full":
            assert "--response-format" not in command
        else:
            assert command[command.index("--response-format") + 1] == mode
        assert ("--ranking-policy" in command) == (policy != "lexical-overlap/1")
        if "--ranking-policy" in command:
            assert command[-2:] == ["--ranking-policy", policy]
        events = [{"event": event, "ranking_policy": policy} for event in ("server_start", "memory_lookup")]
        (case / "evidence/memory-backend-trace.jsonl").write_text("\n".join(json.dumps(e) for e in events))
        common.write(case / "result.json", {"status": "passed", "format": mode})
        return {"status": "passed"}
    fake_modules = {
        "study_schema": types.SimpleNamespace(validate=validate),
        "study_common": types.SimpleNamespace(**{name: getattr(common, name) for name in (
            "read", "write", "digest", "file_hashes")}, chown=lambda path: None),
        "study_workspace": types.SimpleNamespace(create_namespace=namespace, reset=lambda *args: {}),
        "study_runtime": types.SimpleNamespace(origin_memory=prepare, container=container, validate_ranking_trace=validate_ranking_trace),
        "memory_seed_schema": types.SimpleNamespace(policy_for=lambda value: {"schema_version": 2},
                                                   literal_catalog=lambda value: {"records": [record]}),
        "container_session": harness,
    }
    for name, module in fake_modules.items():
        if name != "container_session":
            module.__file__ = str(controller / (name + ".py"))
    monkeypatch.setattr(preflight.importlib, "import_module", lambda name: fake_modules[name])
    report = preflight.execute(study_path, controller, tmp_path / "output", ranking_policy=policy)
    assert report["status"] == "passed" and report["actual_configured_stdio_cases"] == 6
    assert len(calls) == 6 and validations == [False, False]
    assert common.file_hashes(controller) == original_sources
