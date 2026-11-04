"""Optional display projection; full responses remain bound in audit evidence."""

from __future__ import annotations

import json

from memory_backend import canonical, digest

FORMAT = "research-memory-compact/1"


def compact_result(full_result):
    """Return a compact MCP result and its full canonical response audit receipt.

    Only provenance fields are removed. User text, expectations, identities of
    subjects, trust labels, freshness and selection metadata are retained.
    """
    value = json.loads(full_result["content"][0]["text"])
    compact = {
        key: item
        for key, item in value.items()
        if key not in {"catalog_sha256", "snapshot_id", "memory_generation_id"}
    }
    for collection in ("entries", "withheld"):
        projected = []
        for original in value.get(collection, []):
            entry = {key: item for key, item in original.items() if key != "origin_source"}
            if "payload" in entry:
                entry["payload"] = {
                    key: item for key, item in entry["payload"].items() if key != "sources"
                }
            projected.append(entry)
        compact[collection] = projected
    compact["response_format"] = FORMAT
    base_result = {
        "content": [{"type": "text", "text": canonical(compact).decode()}],
        "isError": full_result["isError"],
    }
    receipt_payload = {
        "format": FORMAT,
        "full_result_sha256": digest(full_result),
        "projection_result_sha256": digest(base_result),
    }
    receipt = digest(receipt_payload)
    compact["audit_receipt"] = receipt
    result = {
        "content": [{"type": "text", "text": canonical(compact).decode()}],
        "isError": full_result["isError"],
    }
    audit = {
        "receipt_sha256": receipt,
        "receipt_payload": receipt_payload,
        "full_result": full_result,
        "model_result_sha256": digest(result),
    }
    return result, audit
