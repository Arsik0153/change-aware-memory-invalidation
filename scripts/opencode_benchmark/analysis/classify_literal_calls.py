"""Catalog2 full/compact response authentication and literal tuple observations."""
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import PurePosixPath
import re

from literal_reference import FORMAT, LIMIT, body, sha

COMPACT = "research-memory-compact/1"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def require(value, reason):
    if not value:
        raise ValueError(reason)


def validate_catalog(catalog):
    require(isinstance(catalog, dict) and set(catalog) == {"schema_version", "source_roots", "excluded_paths", "records"}
            and type(catalog["schema_version"]) is int and catalog["schema_version"] == 2, "explicit catalog2 required; old notes use old analyzer")
    for key in ["source_roots", "excluded_paths"]:
        require(isinstance(catalog[key], list) and all(isinstance(p, str) for p in catalog[key]), "invalid catalog policy")
        for p in catalog[key]:
            require(p == "." or bool(p) and not PurePosixPath(p).is_absolute() and ".." not in PurePosixPath(p).parts and str(PurePosixPath(p)) == p and "\\" not in p and "\0" not in p, "unsafe policy path")
    require(bool(catalog["source_roots"]) and isinstance(catalog["records"], list) and 1 <= len(catalog["records"]) <= 1024, "invalid record count")
    ids, subjects = set(), set()
    for record in catalog["records"]:
        require(isinstance(record, dict) and set(record) == {"id", "payload", "source"}, "invalid record")
        rid, payload, source = record["id"], record["payload"], record["source"]
        require(isinstance(rid, str) and 0 < len(rid) <= 200 and rid not in ids, "duplicate/invalid record ID")
        ids.add(rid)
        require(isinstance(payload, dict) and set(payload) == {"type", "subject", "expected", "origin_source", "origin_span"} and payload["type"] == "source_excerpt_equals", "catalog2 supports explicit literal records only")
        subject, expected, span = payload["subject"], payload["expected"], payload["origin_span"]
        require(isinstance(subject, dict) and set(subject) == {"language", "path", "qualname", "node_kind"} and all(isinstance(x, str) and x for x in subject.values()) and subject["language"] == "python" and subject["node_kind"] in {"function", "method"}, "invalid literal subject")
        path = subject["path"]
        require(path != "." and not PurePosixPath(path).is_absolute() and ".." not in PurePosixPath(path).parts and str(PurePosixPath(path)) == path and "\\" not in path and "\0" not in path, "unsafe source path")
        require(any(p == "." or path == p or path.startswith(p + "/") for p in catalog["source_roots"])
                and not any(p == "." or path == p or path.startswith(p + "/") for p in catalog["excluded_paths"]), "subject outside policy")
        identity = canonical(subject)
        require(identity not in subjects, "duplicate subject")
        subjects.add(identity)
        require(isinstance(expected, dict) and set(expected) == {"format", "text", "truncated"} and expected["format"] == FORMAT and isinstance(expected["text"], str) and 1 <= len(expected["text"]) <= LIMIT and type(expected["truncated"]) is bool and (not expected["truncated"] or len(expected["text"]) == LIMIT), "invalid literal tuple")
        expected["text"].encode("utf-8")
        require(isinstance(span, dict) and set(span) == {"first_line", "last_line"} and all(type(n) is int for n in span.values()) and 1 <= span["first_line"] <= span["last_line"], "invalid origin span")
        require(isinstance(source, dict) and set(source) == {"path", "sha256", "size"} and source["path"] == path and isinstance(source["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", source["sha256"]) is not None and type(source["size"]) is int and 0 <= source["size"] <= 2 * 1024**2 and source == payload["origin_source"], "invalid portable origin source")
    return catalog


def projection(full):
    """Independent frozen compact/1 rule; no production projector invocation."""
    value = {k: v for k, v in full.items() if k not in {"catalog_sha256", "snapshot_id", "memory_generation_id"}}
    for channel in ["entries", "withheld"]:
        require(isinstance(full.get(channel), list) and all(isinstance(e, dict) for e in full[channel]), "malformed projection channel")
        value[channel] = []
        for original in full.get(channel, []):
            entry = {k: v for k, v in original.items() if k != "origin_source"}
            if "payload" in entry:
                require(isinstance(entry["payload"], dict), "malformed projection payload")
                entry["payload"] = {k: v for k, v in entry["payload"].items() if k != "sources"}
            value[channel].append(entry)
    value["response_format"] = COMPACT
    return value


def mcp(text):
    return {"content": [{"type": "text", "text": text}], "isError": False}


def authenticate_response(text, event):
    value = json.loads(text)
    require(isinstance(value, dict) and not value.get("error") and event.get("error") is None, "memory lookup error")
    if "response_format" not in value and "audit_receipt" not in value:
        require(event.get("response_format") is None and "response_audit" not in event, "unknown full trace format/audit")
        require(event.get("response_bytes") == len(canonical(mcp(text))), "full response byte count differs")
        return value, "full"
    require(value.get("response_format") == COMPACT and isinstance(value.get("audit_receipt"), str), "unknown/malformed compact format")
    require(event.get("response_format") == "compact", "compact trace marker missing")
    audit = event.get("response_audit")
    require(isinstance(audit, dict) and set(audit) == {"receipt_sha256", "receipt_payload", "full_result", "model_result_sha256"}, "compact audit missing/redacted/unsupported")
    full = audit["full_result"]
    require(isinstance(full, dict) and set(full) == {"content", "isError"} and full["isError"] is False and isinstance(full["content"], list) and len(full["content"]) == 1 and isinstance(full["content"][0], dict) and full["content"][0].get("type") == "text" and isinstance(full["content"][0].get("text"), str), "unsupported full audit MCP shape/error")
    payload = audit["receipt_payload"]
    require(isinstance(payload, dict) and set(payload) == {"format", "full_result_sha256", "projection_result_sha256"} and payload["format"] == COMPACT and payload["full_result_sha256"] == sha(canonical(full)), "full audit digest/format mismatch")
    original = json.loads(full["content"][0]["text"])
    require(isinstance(original, dict) and not original.get("error") and "audit_receipt" not in original and "response_format" not in original, "unsupported nested full response")
    projected = projection(original)
    require(payload["projection_result_sha256"] == sha(canonical(mcp(canonical(projected).decode()))), "projection digest mismatch")
    receipt = sha(canonical(payload))
    require(receipt == audit["receipt_sha256"] == value["audit_receipt"], "receipt digest mismatch")
    projected["audit_receipt"] = receipt
    require(projected == value and canonical(projected).decode() == text, "compact/full projection or model bytes differ")
    require(audit["model_result_sha256"] == sha(canonical(mcp(text))) and event.get("response_bytes") == len(canonical(mcp(text))), "final model result digest/byte mismatch")
    return original, "compact_verified"


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def boundary(analyzer, rows, call):
    end = call["state"].get("time", {}).get("end")
    writes = [r["part"] for r in rows if r.get("type") == "tool_use" and r["part"]["tool"] not in analyzer.READ_ONLY and not analyzer.memory_tool(r["part"]["tool"])]
    starts = [p.get("state", {}).get("time", {}).get("start") for p in writes]
    blocked = not finite(end) or any(not finite(s) or s <= end for s in starts)
    return {"source_assessable": not blocked, "reason": "possible_write_or_missing_timestamps" if blocked else "no_prior_or_overlapping_potential_write"}


def compare_record(record, origin, current, assessable):
    payload, source = record["payload"], record["source"]
    subject = payload["subject"]
    old = body(origin, subject["path"], subject["qualname"])
    if (old.status != "unique_definition" or old.source_sha256 != source["sha256"] or old.source_size != source["size"] or old.kind != subject["node_kind"] or old.expected() != payload["expected"] or {"first_line": old.first_line, "last_line": old.last_line} != payload["origin_span"]):
        return {"assessment": "unsupported_origin_binding", "origin_definition_status": old.status}
    result = {"origin_file_sha256": old.source_sha256, "origin_tuple": old.expected(), "origin_span": payload["origin_span"]}
    if not assessable:
        return {**result, "assessment": "unknown_after_possible_write", "current_source_not_substituted": True}
    now = body(current, subject["path"], subject["qualname"])
    result.update(current_definition_status=now.status, current_file_sha256=now.source_sha256,
                  source_file_changed=old.source_sha256 != now.source_sha256 if now.source_sha256 else None)
    if now.status == "unique_definition" and now.kind == subject["node_kind"]:
        result.update(assessment="same_literal_tuple" if old.expected() == now.expected() else "obsolete_literal_tuple",
                      current_tuple=now.expected(), current_span={"first_line": now.first_line, "last_line": now.last_line})
    elif now.status in {"absent_path", "absent_definition"}:
        result["assessment"] = "origin_definition_absent"
    else:
        result["assessment"] = "unknown_current_source"
    return result


def classify(analyzer, rows, catalog, origin, current, backend, backend_events):
    validate_catalog(catalog)
    body.cache_clear()  # No stale cache across operations/reused paths.
    records = {r["id"]: r for r in catalog["records"]}
    catalog_sha = sha(canonical(catalog))
    calls, seen = [], set()
    for row in rows:
        if row.get("type") != "tool_use":
            continue
        part = row["part"]
        require(part["id"] not in seen, "duplicate tool call ID")
        seen.add(part["id"])
        if analyzer.memory_tool(part["tool"]):
            calls.append(part)
    trace_shape = backend_events is None or isinstance(backend_events, list) and all(isinstance(e, dict) for e in backend_events)
    events = [e for e in backend_events or [] if isinstance(e, dict) and e.get("event") == "memory_lookup"] if trace_shape else []
    join_error = ("missing_backend_trace" if backend_events is None else "backend_lookup_count_mismatch" if len(events) != len(calls) else None)
    if not trace_shape:
        join_error = "malformed_backend_trace"
    elif backend_events is not None and any(e.get("backend") != backend or e.get("catalog_sha256") != catalog_sha for e in backend_events):
        join_error = "backend_catalog_identity_mismatch"
    observations, reports = [], []
    for index, call in enumerate(calls):
        report = {"call_id": call["id"], **boundary(analyzer, rows, call)}
        model = None
        try:
            require(call["state"].get("status") == "completed", "memory_tool_not_completed")
            text = call["state"]["output"]
            model = json.loads(text)
            require(join_error is None, join_error)
            event = events[index]
            arguments = call["state"].get("input")
            require(isinstance(arguments, dict) and event.get("query_sha256") == sha(canonical(arguments)), "backend_full_arguments_hash_mismatch")
            full, response_format = authenticate_response(text, event)
            require(type(full.get("schema_version")) is int and full["schema_version"] == 1 and full.get("catalog_sha256") == catalog_sha and full.get("backend") == backend and full.get("query") == arguments.get("query"), "full response schema/query/catalog/backend binding mismatch")
            returned, withheld = full["entries"], full["withheld"]
            require(isinstance(returned, list) and isinstance(withheld, list), "unsupported result channels")
            ids = [e["id"] for e in returned + withheld]
            require(len(ids) == len(set(ids)) and all(i in records for i in ids), "duplicate/unknown selected IDs")
            require(full.get("selected_records") == len(ids) and event.get("returned_records") == len(returned) and event.get("withheld_records") == len(withheld), "selected/returned/withheld counts differ")
            for entry in returned:
                record = records[entry["id"]]
                require(entry["payload"] == record["payload"] and entry["origin_source"] == record["source"], "returned payload/source differs from catalog")
            for entry in withheld:
                record = records[entry["id"]]
                require(entry.get("kind") == record["payload"]["type"] and entry.get("subject") == record["payload"]["subject"] and "payload" not in entry and "expected" not in entry, "withheld identity/history differs")
            report.update(status="supported", response_format=response_format, returned_ids=[e["id"] for e in returned], withheld_ids=[e["id"] for e in withheld])
            for channel, entries in [("returned", returned), ("withheld", withheld)]:
                for entry in entries:
                    record = records[entry["id"]]
                    observation = {"call_id": call["id"], "record_id": entry["id"], "channel": channel,
                                   "record_kind": "source_excerpt_equals", "subject": record["payload"]["subject"],
                                   "exposed_to_agent": channel == "returned", "causal_reliance": "not_inferred",
                                   **compare_record(record, origin, current, report["source_assessable"])}
                    if channel == "withheld":
                        observation.update(withheld_reason=entry.get("reason"), required_action=entry.get("required_action"), comparison_context_not_returned_to_agent=True)
                    observations.append(observation)
        except (ValueError, KeyError, TypeError, UnicodeError, IndexError, AttributeError) as error:
            def reported(channel):
                value = model.get(channel) if isinstance(model, dict) else None
                return [e.get("id") for e in value if isinstance(e, dict)] if isinstance(value, list) else None
            report.update(status="unsupported", reason=str(error), source_assessable=False,
                          reported_returned_ids=reported("entries"), reported_withheld_ids=reported("withheld"))
        reports.append(report)
    counts = Counter((r["channel"], r["record_kind"], r["assessment"]) for r in observations)
    return {"analysis_version": "source-excerpt-tuple-staleness/2", "memory_calls": reports, "records": observations,
            "unsupported_calls": sum(r["status"] == "unsupported" for r in reports),
            "counts": [{"channel": c, "record_kind": k, "assessment": a, "observations": n} for (c, k, a), n in sorted(counts.items())],
            "returned_record_observations": sum(r["channel"] == "returned" for r in observations),
            "withheld_record_observations": sum(r["channel"] == "withheld" for r in observations),
            "backend_crosscheck": {"status": "matched" if not join_error and all(r["status"] == "supported" for r in reports) else "unsupported", "reason": join_error},
            "causal_reliance": "not_inferred"}
