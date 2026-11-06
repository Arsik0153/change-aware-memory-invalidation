"""Authored byte-integrity fixtures; no models, heldout packets, or containers."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "integrations/opencode"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from compact_response import compact_result  # noqa: E402
from readable_response import readable_result  # noqa: E402
from readable_receipts import (  # noqa: E402
    COMPACT,
    INTRO,
    READABLE,
    canonical,
    digest,
    extract_readable_header,
    readable_audit_marker,
    readable_result_marker,
    readable_text_marker,
    verify_readable_result,
)


def fixture(text="def f():\n    return 7\n", arm="cami"):
    subject = {"language": "python", "path": "src/example.py",
               "qualname": "Example.method", "node_kind": "method"}
    source = {"path": subject["path"], "sha256": "a" * 64, "size": 9999}
    payload = {
        "type": "source_excerpt_equals", "subject": subject, "origin_source": source,
        "origin_span": {"first_line": 2, "last_line": 20},
        "expected": {"format": "python.definition-prefix/1", "text": text,
                     "truncated": len(text) == 2400},
    }
    entry = {"id": "exact-id", "payload": payload, "origin_source": source,
             "availability": "supported" if arm == "cami" else "unchecked_current",
             "label": "validated_literal_source" if arm == "cami"
             else "origin_literal_source_assertion"}
    if arm == "cami":
        entry["state_type"] = "carried"
    return {
        "schema_version": 1, "backend": arm, "query": "query echo", "catalog_sha256": "b" * 64,
        "snapshot_id": "c" * 64, "memory_generation_id": "d" * 64,
        "entries": [entry], "withheld": [{"id": "excluded", "reason": "contradicted",
                                          "required_action": "Do not use", "future": [1, True]}],
        "freshness": "verified readset; refresh after edits", "matched_records": 8,
        "selected_records": 2, "truncated": True,
        "selection_budget": {"origin_record_bytes": 16384, "used_bytes": 1234,
                             "ranking_before_availability": True},
    }


def mcp(value, error=False):
    return {"content": [{"type": "text", "text": canonical(value).decode()}], "isError": error}


def test_module_is_standalone_stdlib_and_never_imports_producer():
    import ast
    import readable_receipts

    tree = ast.parse(Path(readable_receipts.__file__).read_text())
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    names = {alias.name.split(".")[0] for node in imports if isinstance(node, ast.Import)
             for alias in node.names}
    names |= {node.module.split(".")[0] for node in imports if isinstance(node, ast.ImportFrom)}
    assert names <= sys.stdlib_module_names | {"__future__"}


@pytest.mark.parametrize("arm", ["static", "cami"])
@pytest.mark.parametrize("source", [
    "def f():\n    return 7\n", "π é 😀\r\n", "bare CR\r", "no newline", "x\t y\r\nz\rlast",
    "```\n````python\n# Memory source prefixes\n", "literal \u2028 and \u2029\n", "x" * 2400,
])
def test_exact_source_physical_lines_truncation_and_markers(arm, source):
    original = fixture(source, arm)
    result, audit = readable_result(mcp(original))
    assert verify_readable_result(result, audit) == original
    assert readable_result_marker(result) == (READABLE, arm, audit["receipt_sha256"])
    assert readable_text_marker(result["content"][0]["text"]) == (
        READABLE, arm, audit["receipt_sha256"])
    assert readable_audit_marker(audit) == (READABLE, audit["receipt_sha256"])
    assert extract_readable_header(result["content"][0]["text"])["withheld"] == original["withheld"]


def test_record_identity_order_and_all_claims_preserved():
    original = fixture()
    other = copy.deepcopy(original["entries"][0])
    other["id"] = "second-id"
    other["payload"]["subject"]["qualname"] = "Another.method"
    other["label"] = "```future label retained"
    original["entries"].append(other)
    original["withheld"][0]["instruction"] = {"arbitrary": "keep exactly"}
    result, audit = readable_result(mcp(original))
    assert verify_readable_result(result, audit) == original


def test_reordered_and_duplicated_records_rejected_even_with_rebound_display_hashes():
    original = fixture()
    other = copy.deepcopy(original["entries"][0])
    other["id"] = "second-id"
    original["entries"].append(other)
    result, audit = readable_result(mcp(original))
    text = result["content"][0]["text"]
    result["content"][0]["text"] = text.replace('"id":"exact-id"', '"id":"second-id"')
    resign_display(result, audit)
    with pytest.raises(ValueError, match="metadata"):
        verify_readable_result(result, audit)


@pytest.mark.parametrize("mutation", [
    "full_bytes", "full_hash", "base_hash", "receipt", "embedded_receipt", "final_hash",
    "source", "is_error", "extra_result", "extra_audit", "extra_payload", "suffix", "fence",
    "requested_format", "effective_format", "fallback_reason",
])
def test_rejects_changed_bytes_receipts_and_metadata(mutation):
    result, audit = readable_result(mcp(fixture()))
    if mutation == "full_bytes":
        audit["full_result"]["content"][0]["text"] += " "
    elif mutation in {"full_hash", "base_hash"}:
        key = "full_result_sha256" if mutation == "full_hash" else "projection_result_sha256"
        audit["receipt_payload"][key] = "0" * 64
    elif mutation == "receipt":
        audit["receipt_sha256"] = "0" * 64
    elif mutation == "embedded_receipt":
        result["content"][0]["text"] = result["content"][0]["text"].replace(
            audit["receipt_sha256"], "0" * 64)
    elif mutation == "final_hash":
        audit["model_result_sha256"] = "0" * 64
    elif mutation == "source":
        result["content"][0]["text"] = result["content"][0]["text"].replace("return 7", "return 8")
    elif mutation == "is_error":
        result["isError"] = True
    elif mutation == "extra_result":
        result["extra"] = "unexpected"
    elif mutation == "extra_audit":
        audit["extra"] = "unexpected"
    elif mutation == "extra_payload":
        audit["receipt_payload"]["extra"] = "unexpected"
    elif mutation == "suffix":
        result["content"][0]["text"] += "injected suffix"
    elif mutation == "fence":
        result["content"][0]["text"] = result["content"][0]["text"].replace("```python", "````python")
    elif mutation == "requested_format":
        audit["requested_format"] = COMPACT
    elif mutation == "effective_format":
        audit["effective_format"] = COMPACT
    else:
        audit["fallback_reason"] = "empty_entries"
    with pytest.raises(ValueError):
        verify_readable_result(result, audit)


def resign_display(result, audit):
    """Bind attacker display bytes, leaving the original audit full result fixed."""
    text = result["content"][0]["text"]
    first_line = text.index("\n", len(INTRO)) + 1
    end_line = text.index("\n", first_line)
    header = json.loads(text[first_line:end_line])
    del header["audit_receipt"]
    base_text = text[:first_line] + canonical(header).decode() + text[end_line:]
    audit["receipt_payload"]["projection_result_sha256"] = digest(
        {"content": [{"type": "text", "text": base_text}], "isError": result["isError"]})
    old_receipt = audit["receipt_sha256"]
    audit["receipt_sha256"] = digest(audit["receipt_payload"])
    result["content"][0]["text"] = text.replace(old_receipt, audit["receipt_sha256"])
    audit["model_result_sha256"] = digest(result)


@pytest.mark.parametrize("before,after", [
    ('"matched_records":8', '"matched_records":9'),
    ('"selected_records":2', '"selected_records":3'),
    ('"used_bytes":1234', '"used_bytes":1235'),
    ('"selection_truncated":true', '"selection_truncated":false'),
    ('"freshness":"verified readset; refresh after edits"', '"freshness":"current"'),
    ('"required_action":"Do not use"', '"required_action":"Use it"'),
    ('"label":"validated_literal_source"', '"label":"trusted"'),
    ('"availability":"supported"', '"availability":"unchecked_current"'),
    ('"state_type":"carried"', '"state_type":"validated"'),
    ('"first_line":2', '"first_line":3'),
    ('"qualname":"Example.method"', '"qualname":"Other.method"'),
    ('"truncated":false', '"truncated":true'),
    ('"fence_newline_added":false', '"fence_newline_added":true'),
    ('return 7\n', 'return 7\r\n'),
    ('"id":"exact-id"', '"extra":true,"id":"exact-id"'),
])
def test_rebound_hashes_cannot_hide_changed_visible_claims(before, after):
    result, audit = readable_result(mcp(fixture()))
    assert before in result["content"][0]["text"]
    result["content"][0]["text"] = result["content"][0]["text"].replace(before, after)
    resign_display(result, audit)
    with pytest.raises(ValueError):
        verify_readable_result(result, audit)


def test_stale_trace_cannot_authenticate_same_prefix_different_provenance():
    original = fixture()
    first, stale_audit = readable_result(mcp(original))
    original["catalog_sha256"] = "e" * 64
    original["entries"][0]["payload"]["origin_source"]["sha256"] = "f" * 64
    second, audit = readable_result(mcp(original))
    assert first != second
    assert stale_audit["receipt_payload"]["projection_result_sha256"] == audit[
        "receipt_payload"]["projection_result_sha256"]
    assert verify_readable_result(second, audit) == original
    with pytest.raises(ValueError):
        verify_readable_result(second, stale_audit)


@pytest.mark.parametrize("case,reason", [
    ("empty", "empty_entries"), ("withheld", "withheld_only"),
    ("mixed", "non_literal_or_mixed_records"), ("error", "error_response"),
    ("root", "unknown_response_schema"), ("entry", "unknown_entry_schema"),
    ("payload", "unsupported_literal_payload"), ("version", "unsupported_schema_version"),
    ("backend", "unsupported_backend"), ("origin", "nonredundant_origin_source"),
    ("control", "source_control_character"), ("surrogate", "unsupported_literal_payload"),
    ("future_format", "unsupported_literal_payload"),
])
def test_fallback_exact_compact_error_unknown_mixed_and_empty(case, reason):
    original = fixture()
    if case == "empty":
        original.update(entries=[], withheld=[])
    elif case == "withheld":
        original["entries"] = []
    elif case == "mixed":
        original["entries"].append({"id": "unknown", "payload": {
            "type": "note", "text": "keep claim", "sources": [{"old": "provenance"}]},
            "origin_source": {"old": "provenance"}, "label": "unknown", "availability": "unknown"})
    elif case == "error":
        original = {"error": {"code": "backend_failed", "message": "exact unknown error"}}
    elif case == "root":
        original["future"] = {"claim": ["preserve", True]}
    elif case == "entry":
        original["entries"][0]["future"] = "preserve"
    elif case == "payload":
        original["entries"][0]["payload"]["future"] = "preserve"
    elif case == "version":
        original["schema_version"] = 99
    elif case == "backend":
        original["backend"] = {"future": "preserve"}
    elif case == "origin":
        original["entries"][0]["origin_source"] = {"different": "preserve"}
    elif case == "control":
        original["entries"][0]["payload"]["expected"]["text"] += "\x1b[31m"
    elif case == "surrogate":
        original["entries"][0]["payload"]["expected"]["text"] = "\ud800"
    else:
        original["entries"][0]["payload"]["expected"]["format"] = "future/2"
    full = mcp(original, case == "error")
    result, audit = readable_result(full)
    compact, compact_audit = compact_result(full)
    assert result == compact
    assert all(audit[key] == item for key, item in compact_audit.items())
    assert audit["fallback_reason"] == reason
    assert verify_readable_result(result, audit) == original
    assert readable_result_marker(result) == (COMPACT, original.get("backend"), audit["receipt_sha256"])
    assert readable_audit_marker(audit) == (COMPACT, audit["receipt_sha256"])
    audit["fallback_reason"] = "made_up_reason"
    with pytest.raises(ValueError):
        verify_readable_result(result, audit)


@pytest.mark.parametrize("field,bad", [
    ("subject", []), ("expected", None), ("origin_span", "unknown"),
    ("origin_source", False),
])
def test_malformed_nested_literal_types_fall_back_without_claim_loss(field, bad):
    original = fixture()
    original["entries"][0]["payload"][field] = bad
    result, audit = readable_result(mcp(original))
    assert audit["fallback_reason"] == "unsupported_literal_payload"
    assert verify_readable_result(result, audit) == original


@pytest.mark.parametrize("field,bad", [
    ("entries", None), ("entries", ["wrong"]), ("withheld", [False]),
])
def test_malformed_compact_collection_contract_is_rejected(field, bad):
    result, audit = readable_result(mcp(fixture()))
    original = fixture()
    original[field] = bad
    audit["full_result"] = mcp(original)
    audit["receipt_payload"]["full_result_sha256"] = digest(audit["full_result"])
    audit["effective_format"] = COMPACT
    audit["receipt_payload"]["format"] = COMPACT
    audit["fallback_reason"] = "unsupported_record_collections" if bad is None else (
        "unknown_entry_schema" if field == "entries" else "unknown_response_schema")
    audit["receipt_sha256"] = digest(audit["receipt_payload"])
    with pytest.raises(ValueError):
        verify_readable_result(result, audit)


def test_text_marker_error_fallback_does_not_invent_is_error_evidence():
    original = {"error": {"code": "memory_lookup_failed", "message": "exact error"}}
    result, audit = readable_result(mcp(original, True))
    assert readable_text_marker(result["content"][0]["text"]) == (
        COMPACT, None, audit["receipt_sha256"])
    assert verify_readable_result(result, audit) == original


def test_rehashed_fallback_cannot_drop_unknown_error_claims():
    original = {"error": {"code": "unknown", "message": "retain"}, "future": {"x": True}}
    result, audit = readable_result(mcp(original, True))
    projected = json.loads(result["content"][0]["text"])
    del projected["future"]
    del projected["audit_receipt"]
    audit["receipt_payload"]["projection_result_sha256"] = digest(mcp(projected, True))
    audit["receipt_sha256"] = digest(audit["receipt_payload"])
    projected["audit_receipt"] = audit["receipt_sha256"]
    result = mcp(projected, True)
    audit["model_result_sha256"] = digest(result)
    with pytest.raises(ValueError, match="fallback bytes"):
        verify_readable_result(result, audit)


@pytest.mark.parametrize("bad", [None, [], "string", 1, True])
def test_malformed_result_and_audit_types_rejected(bad):
    result, audit = readable_result(mcp(fixture()))
    with pytest.raises(ValueError):
        verify_readable_result(bad, audit)
    with pytest.raises(ValueError):
        verify_readable_result(result, bad)
    audit["full_result"] = bad
    with pytest.raises(ValueError):
        verify_readable_result(result, audit)


def test_duplicate_json_and_noncanonical_header_rejected():
    result, audit = readable_result(mcp(fixture()))
    result["content"][0]["text"] = result["content"][0]["text"].replace(
        '"backend":"cami"', '"backend":"static","backend":"cami"')
    with pytest.raises(ValueError, match="duplicate"):
        verify_readable_result(result, audit)


def test_marker_binding_is_explicitly_weaker_than_full_verification():
    result, audit = readable_result(mcp(fixture()))
    audit["full_result"] = {"redacted": True}
    assert readable_audit_marker(audit) == (READABLE, audit["receipt_sha256"])
    assert readable_result_marker(result)[2] == audit["receipt_sha256"]
    with pytest.raises(ValueError):
        verify_readable_result(result, audit)
