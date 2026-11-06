"""Authored readable projection/receipt/fallback checks, no model or Docker."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations/opencode"))
from compact_response import FORMAT as COMPACT_FORMAT, compact_result  # noqa: E402
from memory_backend import canonical, digest  # noqa: E402
from readable_response import FORMAT, INTRO, readable_result  # noqa: E402


def mcp(value, error=False):
    return {"content": [{"type": "text", "text": canonical(value).decode()}], "isError": error}


def response(text="def f():\n    return 7\n", arm="cami", truncated=False):
    subject = {
        "language": "python",
        "path": "src/example.py",
        "qualname": "Example.method",
        "node_kind": "method",
    }
    source = {"path": subject["path"], "sha256": "a" * 64, "size": 9999}
    payload = {
        "type": "source_excerpt_equals",
        "subject": subject,
        "origin_source": source,
        "origin_span": {"first_line": 2, "last_line": 20},
        "expected": {"format": "python.definition-prefix/1", "text": text, "truncated": truncated},
    }
    entry = {
        "id": "exact-id",
        "payload": payload,
        "origin_source": source,
        "availability": "supported" if arm == "cami" else "unchecked_current",
        "label": "validated_literal_source" if arm == "cami" else "origin_literal_source_assertion",
    }
    if arm == "cami":
        entry["state_type"] = "carried"
    value = {
        "schema_version": 1,
        "backend": arm,
        "query": "original query echo",
        "catalog_sha256": "b" * 64,
        "matched_records": 8,
        "selected_records": 2,
        "truncated": True,
        "selection_budget": {
            "origin_record_bytes": 16384,
            "used_bytes": 1234,
            "ranking_before_availability": True,
        },
        "freshness": "verified_readset; may change after verification; refresh after edits"
        if arm == "cami"
        else "origin only; current validity unchecked",
        "entries": [entry],
        "withheld": [
            {
                "id": "withheld-id",
                "subject": subject,
                "kind": "source_excerpt_equals",
                "reason": "contradicted",
                "required_action": "Do not use",
            }
        ],
    }
    if arm == "cami":
        value.update(snapshot_id="c" * 64, memory_generation_id="d" * 64)
    return value


def read_block(text, pos, language):
    """Read ordinary Markdown fences independently of production encoder."""
    end = text.index("\n", pos)
    opening = text[pos:end]
    assert re.fullmatch(r"`{3,}" + language, opening)
    fence = opening[: -len(language)]
    start = cursor = end + 1
    for ending in re.finditer(r"\r\n|\n|\r", text[start:]):
        line_end = start + ending.start()
        if text[cursor:line_end] == fence:
            return text[start:cursor], start + ending.end()
        cursor = start + ending.end()
    raise AssertionError("closing fence absent")


def assert_essential_fields(result, original):
    text = result["content"][0]["text"]
    assert text.startswith(INTRO) and result["isError"] is False
    body, pos = read_block(text, len(INTRO), "json")
    header = json.loads(body)
    assert re.fullmatch("[a-f0-9]{64}", header.pop("audit_receipt"))
    assert header == {
        "response_format": FORMAT,
        "backend": original["backend"],
        "kind": "source_excerpt_equals",
        "literal_format": "python.definition-prefix/1",
        "freshness": original["freshness"],
        "matched_records": original["matched_records"],
        "selected_records": original["selected_records"],
        "returned_records": len(original["entries"]),
        "selection_truncated": original["truncated"],
        "selection_budget": original["selection_budget"],
        "withheld": original["withheld"],
    }
    extracted = []
    for number, entry in enumerate(original["entries"], 1):
        label = "\n## Record " + str(number) + "\n\n"
        assert text[pos : pos + len(label)] == label
        metadata_text, pos = read_block(text, pos + len(label), "json")
        metadata = json.loads(metadata_text)
        raw, pos = read_block(text, pos, "python")
        payload = entry["payload"]
        added = not payload["expected"]["text"].endswith(("\n", "\r"))
        expected = {
            "id": entry["id"],
            "subject": payload["subject"],
            "origin_span": payload["origin_span"],
            "truncated": payload["expected"]["truncated"],
            "label": entry["label"],
            "availability": entry["availability"],
            "fence_newline_added": added,
        }
        if "state_type" in entry:
            expected["state_type"] = entry["state_type"]
        assert metadata == expected
        literal = raw[:-1] if added else raw
        assert literal.encode() == payload["expected"]["text"].encode()
        extracted.append(literal)
    assert pos == len(text)
    return extracted


def assert_readable_receipt(result, audit):
    assert audit["effective_format"] == FORMAT and audit["fallback_reason"] is None
    text = result["content"][0]["text"]
    body, _ = read_block(text, len(INTRO), "json")
    header = json.loads(body)
    receipt = header.pop("audit_receipt")
    assert body == canonical(dict(header, audit_receipt=receipt)).decode() + "\n"
    start = text.index("\n", len(INTRO)) + 1
    base_text = text[:start] + canonical(header).decode() + "\n" + text[start + len(body) :]
    base_result = {"content": [{"type": "text", "text": base_text}], "isError": result["isError"]}
    assert audit["receipt_payload"] == {
        "format": FORMAT,
        "full_result_sha256": digest(audit["full_result"]),
        "projection_result_sha256": digest(base_result),
    }
    assert digest(audit["receipt_payload"]) == receipt == audit["receipt_sha256"]
    assert audit["model_result_sha256"] == digest(result)


@pytest.mark.parametrize("arm", ["static", "cami"])
@pytest.mark.parametrize(
    "text",
    [
        "def f():\n    return 7\n",
        "Unicode π é 😀\r\n",
        "bare CR\r",
        "no newline",
        "```\n````python\n# Memory source prefixes\n",
        "@(\n decorator\n)\ndef f():\n pass\n",
        "literal U+2028:\u2028 U+2029:\u2029\n",
        "x" * 2400,
    ],
)
def test_readable_exact_physical_source_and_visible_claims(arm, text):
    value = response(text, arm, truncated=len(text) == 2400)
    full = mcp(value)
    before = copy.deepcopy(full)
    result, audit = readable_result(full)
    assert_essential_fields(result, value)
    assert_readable_receipt(result, audit)
    assert full == before and audit["full_result"] == before
    assert "requested_limit" not in result["content"][0]["text"]
    assert "original query echo" not in result["content"][0]["text"]
    assert "origin_source" not in result["content"][0]["text"]


def test_order_duplicate_text_distinct_identity_and_all_withheld_fields():
    value = response()
    other = copy.deepcopy(value["entries"][0])
    other["id"] = "another-id"
    other["payload"]["subject"]["qualname"] = "Another.method"
    value["entries"].append(other)
    value["selected_records"] = 3
    value["withheld"][0]["extra_future_instruction"] = {"unchanged": "retain this too"}
    result, audit = readable_result(mcp(value))
    assert_essential_fields(result, value)
    assert_readable_receipt(result, audit)


@pytest.mark.parametrize(
    "case,reason",
    [
        ("empty", "empty_entries"),
        ("withheld", "withheld_only"),
        ("mixed", "non_literal_or_mixed_records"),
        ("error", "error_response"),
        ("root_unknown", "unknown_response_schema"),
        ("entry_unknown", "unknown_entry_schema"),
        ("payload_unknown", "unsupported_literal_payload"),
        ("version", "unsupported_schema_version"),
        ("backend", "unsupported_backend"),
        ("backend_object", "unsupported_backend"),
        ("origin", "nonredundant_origin_source"),
        ("control", "source_control_character"),
        ("surrogate", "unsupported_literal_payload"),
        ("future_format", "unsupported_literal_payload"),
    ],
)
def test_unsupported_uses_exact_old_compact_bytes_and_receipt(case, reason):
    value = response()
    error = False
    if case == "empty":
        value.update(entries=[], withheld=[])
    elif case == "withheld":
        value["entries"] = []
    elif case == "mixed":
        other = copy.deepcopy(value["entries"][0])
        other["payload"] = {
            "type": "note",
            "subject": other["payload"]["subject"],
            "text": "must retain this claim",
            "sources": [other["origin_source"]],
        }
        value["entries"].append(other)
    elif case == "error":
        error = True
        value = {
            "error": {"code": "backend_failed", "message": "keep exact error"},
            "freshness": "unknown",
        }
    elif case == "root_unknown":
        value["future_claim"] = {"must": "retain"}
    elif case == "entry_unknown":
        value["entries"][0]["future_claim"] = "retain"
    elif case == "payload_unknown":
        value["entries"][0]["payload"]["future_claim"] = "retain"
    elif case == "version":
        value["schema_version"] = 99
    elif case == "backend":
        value["backend"] = "future"
    elif case == "backend_object":
        value["backend"] = {"future": "schema"}
    elif case == "origin":
        value["entries"][0]["origin_source"] = dict(
            value["entries"][0]["origin_source"], sha256="f" * 64
        )
    elif case == "control":
        value["entries"][0]["payload"]["expected"]["text"] += "\x1b[31m"
    elif case == "surrogate":
        value["entries"][0]["payload"]["expected"]["text"] = "\ud800"
    else:
        value["entries"][0]["payload"]["expected"]["format"] = "future.literal/2"
    full = mcp(value, error)
    expected_result, expected_audit = compact_result(full)
    result, audit = readable_result(full)
    assert result == expected_result and result["isError"] == error
    assert {key: audit[key] for key in expected_audit} == expected_audit
    assert audit["requested_format"] == FORMAT and audit["effective_format"] == COMPACT_FORMAT
    assert audit["fallback_reason"] == reason


@pytest.mark.parametrize("control", ["\x00", "\x07", "\x7f", "\x85", "\x9b"])
def test_other_terminal_control_characters_fall_back_losslessly(control):
    full = mcp(response("prefix" + control + "suffix"))
    result, audit = readable_result(full)
    assert result == compact_result(full)[0]
    assert audit["fallback_reason"] == "source_control_character"


@pytest.mark.parametrize(
    "mutation", ["display", "full", "receipt", "claimed_projection_hash", "isError"]
)
def test_receipt_independently_rejects_changed_bytes(mutation):
    result, audit = readable_result(mcp(response()))
    if mutation == "display":
        result["content"][0]["text"] += "unbound suffix"
    elif mutation == "full":
        audit["full_result"]["content"][0]["text"] += " "
    elif mutation == "receipt":
        audit["receipt_sha256"] = "0" * 64
    elif mutation == "isError":
        result["isError"] = True
    else:
        audit["receipt_payload"]["projection_result_sha256"] = "0" * 64
    with pytest.raises(AssertionError):
        assert_readable_receipt(result, audit)


def test_new_embedded_receipt_disambiguates_different_origin_provenance():
    full = mcp(response())
    first, audit = readable_result(full)
    altered = json.loads(full["content"][0]["text"])
    altered["catalog_sha256"] = "e" * 64
    second, next_audit = readable_result(mcp(altered))
    assert first != second  # Embedded receipt disambiguates otherwise-identical displays.
    assert (
        audit["receipt_payload"]["projection_result_sha256"]
        == next_audit["receipt_payload"]["projection_result_sha256"]
    )
    assert audit["receipt_sha256"] != next_audit["receipt_sha256"]
    assert audit["receipt_sha256"] != compact_result(full)[1]["receipt_sha256"]
    assert audit["receipt_sha256"] in first["content"][0]["text"]
    assert_readable_receipt(second, next_audit)
