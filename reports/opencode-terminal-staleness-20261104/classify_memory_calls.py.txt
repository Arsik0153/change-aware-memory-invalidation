"""Authenticate both response channels; literal comparisons never infer reliance."""

from __future__ import annotations

from collections import Counter
import hashlib
import json


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode()


def classify_withheld(analyzer, record, origin, current, assessable):
    if record["payload"]["type"] != "note":
        return {"assessment": "typed_record_not_literal_note"}
    if not assessable:
        return {"assessment": "unknown_after_possible_write"}
    subject = record["payload"]["subject"]
    old_status, old_hash, old_excerpt = analyzer.body(origin, subject["path"], subject["qualname"])
    if (
        old_status != "unique_definition"
        or old_hash != record["source"]["sha256"]
        or old_excerpt not in record["payload"]["text"]
    ):
        return {"assessment": "unsupported_origin_binding", "origin_definition_status": old_status}
    status, current_hash, excerpt = analyzer.body(current, subject["path"], subject["qualname"])
    result = {
        "current_definition_status": status,
        "origin_file_sha256": old_hash,
        "current_file_sha256": current_hash,
        "source_file_changed": current_hash != old_hash if current_hash else None,
    }
    if status == "unique_definition":
        result.update(
            assessment="same_literal_excerpt"
            if old_excerpt == excerpt
            else "obsolete_literal_excerpt",
            origin_excerpt_sha256=hashlib.sha256(old_excerpt.encode()).hexdigest(),
            current_excerpt_sha256=hashlib.sha256(excerpt.encode()).hexdigest(),
        )
    elif status in {"absent_path", "absent_definition"}:
        result["assessment"] = "origin_definition_absent"
    else:
        result["assessment"] = "unknown_current_source"
    return result


def classify(analyzer, rows, catalog, origin, current, backend):
    catalog_rows = {r["id"]: r for r in catalog["records"]}
    if len(catalog_rows) != len(catalog["records"]):
        raise ValueError("duplicate frozen catalog IDs")
    catalog_sha = hashlib.sha256(canonical(catalog)).hexdigest()
    calls, valid, unsupported, payloads = {}, [], [], {}
    for row in rows:
        if row.get("type") != "tool_use":
            continue
        part = row["part"]
        if part["id"] in calls:
            raise ValueError("duplicate tool-call ID; timestamps/coverage unsupported")
        calls[part["id"]] = part
        if not analyzer.memory_tool(part["tool"]):
            valid.append(row)
            continue
        state = part["state"]
        if state.get("status") != "completed":
            unsupported.append(
                {
                    "call_id": part["id"],
                    "status": "unsupported",
                    "reason": "memory_tool_not_completed",
                    "tool_status": state.get("status"),
                }
            )
            continue
        payload = None
        try:
            payload = json.loads(state["output"])
            if payload.get("error"):
                raise ValueError("memory_tool_error:" + str(payload["error"]))
            if payload["catalog_sha256"] != catalog_sha or payload["backend"] != backend:
                raise ValueError("response catalog/backend binding mismatch")
            entries, withheld = payload["entries"], payload["withheld"]
            selected = entries + withheld
            ids = [r["id"] for r in selected]
            if len(set(ids)) != len(ids) or any(i not in catalog_rows for i in ids):
                raise ValueError("duplicate/unknown returned or withheld record ID")
            if payload.get("selected_records") != len(selected):
                raise ValueError("selected count differs from returned+withheld IDs")
            for entry in entries:
                record = catalog_rows[entry["id"]]
                if (
                    entry["payload"] != record["payload"]
                    or entry["origin_source"] != record["source"]
                ):
                    raise ValueError("returned payload/source differs from frozen catalog")
            for entry in withheld:
                record = catalog_rows[entry["id"]]
                if (
                    entry.get("kind") != record["payload"]["type"]
                    or entry.get("subject") != record["payload"]["subject"]
                ):
                    raise ValueError("withheld kind/subject differs from frozen catalog")
            payloads[part["id"]] = payload
            valid.append(row)
        except (ValueError, KeyError, TypeError) as error:
            unsupported.append(
                {
                    "call_id": part["id"],
                    "status": "unsupported",
                    "reason": str(error),
                    "reported_returned_ids": [
                        e.get("id") for e in payload.get("entries", []) if isinstance(e, dict)
                    ]
                    if isinstance(payload, dict)
                    else None,
                    "reported_withheld_ids": [
                        e.get("id") for e in payload.get("withheld", []) if isinstance(e, dict)
                    ]
                    if isinstance(payload, dict)
                    else None,
                }
            )
    reference = analyzer.analyze(valid, catalog, origin, current)
    reference_calls = {r["call_id"]: r for r in reference["memory_calls"]}
    returned = {(r["call_id"], r["record_id"]): r for r in reference["records"]}
    expected_returned = {
        (call_id, entry["id"]) for call_id, p in payloads.items() for entry in p["entries"]
    }
    if set(returned) != expected_returned:
        raise ValueError("independent returned-ID coverage differs from existing analyzer")
    output, reports = [], []
    for call_id, payload in payloads.items():
        report = dict(
            reference_calls[call_id],
            status="supported",
            returned_ids=[e["id"] for e in payload["entries"]],
            withheld_ids=[e["id"] for e in payload["withheld"]],
        )
        reports.append(report)
        for channel, entries in [
            ("returned", payload["entries"]),
            ("withheld", payload["withheld"]),
        ]:
            for entry in entries:
                record = catalog_rows[entry["id"]]
                row = {
                    "call_id": call_id,
                    "record_id": entry["id"],
                    "channel": channel,
                    "record_kind": record["payload"]["type"],
                    "subject": record["payload"]["subject"],
                    "causal_reliance": "not_inferred",
                }
                if channel == "returned":
                    row.update(returned[call_id, entry["id"]])
                    if record["payload"]["type"] != "note":
                        row["assessment"] = "typed_record_not_literal_note"
                else:
                    row.update(
                        classify_withheld(
                            analyzer, record, origin, current, report["source_assessable"]
                        ),
                        withheld_reason=entry.get("reason"),
                        required_action=entry.get("required_action"),
                    )
                output.append(row)
    reports.extend(unsupported)
    counts = Counter((r["channel"], r["record_kind"], r["assessment"]) for r in output)
    return {
        "memory_calls": reports,
        "records": output,
        "unsupported_calls": len(unsupported),
        "counts": [
            {
                "channel": channel,
                "record_kind": kind,
                "assessment": assessment,
                "observations": count,
            }
            for (channel, kind, assessment), count in sorted(counts.items())
        ],
        "returned_record_observations": sum(r["channel"] == "returned" for r in output),
        "withheld_record_observations": sum(r["channel"] == "withheld" for r in output),
    }
