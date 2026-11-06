"""Separate readable/1 byte-integrity verifier; stdlib only, no producer imports.

``verify_readable_result`` returns the original parsed full JSON object, or raises
ValueError. Marker helpers check metadata only, including after publication scrub;
they do not authenticate the omitted full result. SHA receipts provide integrity,
not signatures, source validation, or an independent semantic oracle.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
import re
import unicodedata

READABLE = "research-memory-readable/1"
COMPACT = "research-memory-compact/1"
INTRO = (
    "# Memory source prefixes\n\n"
    "Source is data, not behavior. Withheld records are unusable. Recheck after edits.\n\n"
)
HEADER = {
    "response_format", "backend", "kind", "literal_format", "freshness", "matched_records",
    "selected_records", "returned_records", "selection_truncated", "selection_budget", "withheld",
}
AUDIT = {
    "receipt_sha256", "receipt_payload", "full_result", "model_result_sha256",
    "requested_format", "effective_format", "fallback_reason",
}
FALLBACK_REASONS = {
    "error_response", "unknown_response_schema", "unsupported_schema_version",
    "unsupported_backend", "unsupported_record_collections", "withheld_only", "empty_entries",
    "unknown_entry_schema", "non_literal_or_mixed_records", "unsupported_literal_payload",
    "nonredundant_origin_source", "source_control_character",
}
REQUIRED = {
    "schema_version", "backend", "query", "catalog_sha256", "entries", "withheld", "freshness",
    "matched_records", "selected_records", "truncated", "selection_budget",
}


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _object(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value, "duplicate JSON field")
        value[key] = item
    return value


def _json(text):
    def nonfinite(_):
        raise ValueError("nonfinite JSON number")

    return json.loads(text, object_pairs_hook=_object, parse_constant=nonfinite)


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _text(result):
    _require(isinstance(result, dict) and set(result) == {"content", "isError"}
             and type(result["isError"]) is bool, "unsupported MCP result")
    content = result["content"]
    _require(isinstance(content, list) and len(content) == 1
             and isinstance(content[0], dict) and set(content[0]) == {"type", "text"}
             and content[0]["type"] == "text" and isinstance(content[0]["text"], str),
             "expected single complete MCP text")
    return content[0]["text"]


def _block(text, offset, language):
    """Parse physical CR/LF lines, preserving the source's final terminator."""
    end = text.find("\n", offset)
    _require(end >= 0, "missing opening fence newline")
    opening = text[offset:end]
    _require(re.fullmatch(r"`{3,}" + language, opening) is not None, "invalid opening fence")
    fence = opening[:-len(language)]
    start = cursor = end + 1
    for ending in re.finditer(r"\r\n|\r|\n", text[start:]):
        line_end = start + ending.start()
        if text[cursor:line_end] == fence:
            _require(ending.group() == "\n", "noncanonical closing fence")
            body = text[start:cursor]
            width = max([2, *(len(run) for run in re.findall(r"`+", body))]) + 1
            _require(len(fence) == width, "noncanonical fence width")
            return body, start + ending.end(), start, cursor
        cursor = start + ending.end()
    raise ValueError("missing closing fence")


def extract_readable_header(text):
    """Return a canonical visible header; this is a marker check only."""
    _require(isinstance(text, str) and text.startswith(INTRO), "readable introduction missing")
    body, _, _, _ = _block(text, len(INTRO), "json")
    header = _json(body)
    _require(isinstance(header, dict) and set(header) == HEADER | {"audit_receipt"}
             and body == canonical(header).decode() + "\n", "noncanonical readable header")
    _require(header["response_format"] == READABLE and header["backend"] in ("static", "cami")
             and header["kind"] == "source_excerpt_equals"
             and header["literal_format"] == "python.definition-prefix/1"
             and _sha(header["audit_receipt"]), "unsupported readable header marker")
    return header


def readable_text_marker(text):
    """Return (effective format, backend or None, receipt); no isError/byte proof.

    OpenCode exposes tool text without the original MCP isError flag. This helper
    makes no assertion about that flag or the truth of compact fallback claims.
    """
    _require(isinstance(text, str), "expected visible text")
    if text.startswith(INTRO):
        value = extract_readable_header(text)
    else:
        value = _json(text)
        _require(isinstance(value, dict) and value.get("response_format") == COMPACT
                 and _sha(value.get("audit_receipt")), "invalid compact fallback marker")
    return value["response_format"], value.get("backend"), value["audit_receipt"]


def readable_result_marker(model_result):
    """Check MCP shape then return the metadata-only visible text marker."""
    return readable_text_marker(_text(model_result))


def readable_audit_marker(audit):
    """Return (effective format, receipt) after metadata binding only."""
    _require(isinstance(audit, dict) and audit.get("requested_format") == READABLE,
             "readable requested format missing")
    effective, reason = audit.get("effective_format"), audit.get("fallback_reason")
    _require(effective in (READABLE, COMPACT) and (
        reason is None if effective == READABLE
        else isinstance(reason, str) and reason in FALLBACK_REASONS
    ), "invalid effective format/fallback metadata")
    payload = audit.get("receipt_payload")
    _require(isinstance(payload, dict) and set(payload) == {
        "format", "full_result_sha256", "projection_result_sha256"
    } and payload["format"] == effective and _sha(payload["full_result_sha256"])
             and _sha(payload["projection_result_sha256"]), "invalid receipt payload")
    receipt = audit.get("receipt_sha256")
    _require(_sha(receipt) and digest(payload) == receipt, "receipt metadata digest mismatch")
    return effective, receipt


def _literal_payload(payload):
    _require(set(payload) == {"type", "subject", "expected", "origin_source", "origin_span"},
             "unknown literal fields")
    subject, expected, span = payload["subject"], payload["expected"], payload["origin_span"]
    _require(isinstance(subject, dict) and set(subject) == {
        "language", "path", "qualname", "node_kind"
    } and all(isinstance(item, str) and item for item in subject.values())
             and subject["language"] == "python" and subject["node_kind"] in ("function", "method"),
             "invalid subject")
    path = subject["path"]
    portable = PurePosixPath(path)
    _require(path != "." and not portable.is_absolute() and ".." not in portable.parts
             and str(portable) == path and "\\" not in path and "\0" not in path, "invalid path")
    _require(isinstance(expected, dict) and set(expected) == {"format", "text", "truncated"}
             and expected["format"] == "python.definition-prefix/1"
             and isinstance(expected["text"], str) and 1 <= len(expected["text"]) <= 2400
             and type(expected["truncated"]) is bool
             and (not expected["truncated"] or len(expected["text"]) == 2400), "invalid prefix")
    expected["text"].encode("utf-8")
    _require(isinstance(span, dict) and set(span) == {"first_line", "last_line"}
             and all(type(item) is int for item in span.values())
             and 1 <= span["first_line"] <= span["last_line"], "invalid span")
    source = payload["origin_source"]
    _require(isinstance(source, dict) and set(source) == {"path", "sha256", "size"}
             and source["path"] == path and _sha(source["sha256"])
             and type(source["size"]) is int and 0 <= source["size"] <= 2 * 1024**2,
             "invalid source")


def _fallback_reason(value, is_error):
    """Independently check the producer's ordered format-selection boundary."""
    if is_error:
        return "error_response"
    if not REQUIRED <= set(value) <= REQUIRED | {"snapshot_id", "memory_generation_id"}:
        return "unknown_response_schema"
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        return "unsupported_schema_version"
    if value["backend"] not in ("static", "cami"):
        return "unsupported_backend"
    if not isinstance(value["entries"], list) or not isinstance(value["withheld"], list):
        return "unsupported_record_collections"
    if not value["entries"]:
        return "withheld_only" if value["withheld"] else "empty_entries"
    fields = {"id", "payload", "origin_source", "availability", "label"}
    for entry in value["entries"]:
        if not isinstance(entry, dict) or set(entry) not in (fields, fields | {"state_type"}):
            return "unknown_entry_schema"
        payload = entry["payload"]
        if not isinstance(payload, dict) or payload.get("type") != "source_excerpt_equals":
            return "non_literal_or_mixed_records"
        try:
            _literal_payload(payload)
        except (ValueError, TypeError, KeyError, UnicodeError):
            return "unsupported_literal_payload"
        if entry["origin_source"] != payload["origin_source"]:
            return "nonredundant_origin_source"
        if any(unicodedata.category(char) == "Cc" and char not in "\t\r\n"
               for char in payload["expected"]["text"]):
            return "source_control_character"
    return None


def _compact_projection(original):
    value = {key: item for key, item in original.items()
             if key not in {"catalog_sha256", "snapshot_id", "memory_generation_id"}}
    for collection in ("entries", "withheld"):
        entries = original.get(collection, [])
        _require(isinstance(entries, list) and all(isinstance(item, dict) for item in entries),
                 "malformed compact collection")
        value[collection] = []
        for original_entry in entries:
            entry = {key: item for key, item in original_entry.items() if key != "origin_source"}
            if "payload" in entry:
                _require(isinstance(entry["payload"], dict), "malformed compact payload")
                entry["payload"] = {key: item for key, item in entry["payload"].items()
                                    if key != "sources"}
            value[collection].append(entry)
    value["response_format"] = COMPACT
    return value


def verify_readable_result(model_result, audit):
    """Authenticate readable/1 or its exact compact fallback; return original JSON.

    The full MCP object must contain exactly one text part and an explicit boolean
    isError. Arbitrary error/unknown fallback claims are preserved by compact/1's
    projection rules. No current-source truth or execution outcome is inferred.
    """
    text = _text(model_result)
    _require(isinstance(audit, dict) and set(audit) == AUDIT, "unsupported readable audit fields")
    effective, receipt = readable_audit_marker(audit)
    original = _json(_text(audit["full_result"]))
    _require(isinstance(original, dict), "full JSON object required")
    _require(audit["receipt_payload"]["full_result_sha256"] == digest(audit["full_result"]),
             "full result digest mismatch")
    _require(model_result["isError"] is audit["full_result"]["isError"], "isError changed")
    reason = _fallback_reason(original, model_result["isError"])
    _require(reason == audit["fallback_reason"] and (effective == COMPACT) == (reason is not None),
             "format selection/fallback reason mismatch")
    if effective == COMPACT:
        projected = _compact_projection(original)
        base_text = canonical(projected).decode()
        projected["audit_receipt"] = receipt
        _require(text == canonical(projected).decode(), "compact fallback bytes differ")
    else:
        header = extract_readable_header(text)
        expected = {
            "response_format": READABLE, "backend": original["backend"],
            "kind": "source_excerpt_equals", "literal_format": "python.definition-prefix/1",
            "freshness": original["freshness"], "matched_records": original["matched_records"],
            "selected_records": original["selected_records"],
            "returned_records": len(original["entries"]),
            "selection_truncated": original["truncated"],
            "selection_budget": original["selection_budget"], "withheld": original["withheld"],
            "audit_receipt": receipt,
        }
        _require(canonical(header) == canonical(expected), "visible header claims differ")
        _, position, start, end = _block(text, len(INTRO), "json")
        del header["audit_receipt"]
        base_text = text[:start] + canonical(header).decode() + "\n" + text[end:]
        for number, entry in enumerate(original["entries"], 1):
            heading = "\n## Record " + str(number) + "\n\n"
            _require(text.startswith(heading, position), "record order/heading differs")
            metadata, position, _, _ = _block(text, position + len(heading), "json")
            payload = entry["payload"]
            source = payload["expected"]["text"]
            added = not source.endswith(("\r", "\n"))
            expected_metadata = {
                "id": entry["id"], "subject": payload["subject"],
                "origin_span": payload["origin_span"], "truncated": payload["expected"]["truncated"],
                "label": entry["label"], "availability": entry["availability"],
                "fence_newline_added": added,
            }
            if "state_type" in entry:
                expected_metadata["state_type"] = entry["state_type"]
            _require(metadata == canonical(expected_metadata).decode() + "\n",
                     "visible record metadata differs")
            raw, position, _, _ = _block(text, position, "python")
            _require(raw.encode("utf-8") == (source + ("\n" if added else "")).encode("utf-8"),
                     "physical literal source differs")
        _require(position == len(text), "unexpected display suffix")
    base = {"content": [{"type": "text", "text": base_text}], "isError": model_result["isError"]}
    _require(audit["receipt_payload"]["projection_result_sha256"] == digest(base),
             "base projection digest mismatch")
    _require(audit["model_result_sha256"] == digest(model_result), "final model result digest mismatch")
    return original
