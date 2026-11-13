"""Content-free native read byte observations before publication redaction."""
from __future__ import annotations

SCHEMA = "opencode-native-read-text/2"
NON_ASSISTANT = {"user", "idle", "system", "synthetic", "shell", "skill", "compaction",
                 "agent-switched", "location-switched", "model-switched"}


def observe_message(message):
    result = {"message_id": message["id"], "reads": [], "errors": []}
    kind = message.get("type")
    if kind in NON_ASSISTANT:
        return result
    if kind != "assistant" or not isinstance(message.get("content"), list):
        result["errors"].append("unsupported_message_shape")
        return result
    for part in message["content"]:
        if not isinstance(part, dict):
            result["errors"].append("unsupported_part_shape")
            continue
        if part.get("type") != "tool" or part.get("name") != "read":
            continue
        call_id = part.get("id")
        if not isinstance(call_id, str) or not call_id:
            result["errors"].append("missing_read_identity")
            continue
        state = part.get("state")
        row = {"call_id": call_id, "status": "unknown", "utf8_bytes": None}
        result["reads"].append(row)
        if not isinstance(state, dict) or state.get("status") not in {"completed", "error", "pending", "running"}:
            result["errors"].append("unsupported_read_state")
            continue
        row["status"] = state["status"]
        content = state.get("content")
        if state["status"] == "error":
            error = state.get("error")
            if (isinstance(error, dict) and set(error) == {"type", "message"}
                    and isinstance(error["type"], str) and isinstance(error["message"], str)):
                try:
                    row["utf8_bytes"] = len(error["message"].encode("utf-8"))
                except UnicodeEncodeError:
                    result["errors"].append("invalid_read_text_encoding")
            else:
                result["errors"].append("unsupported_read_error")
        elif state["status"] != "completed":
            result["errors"].append("read_not_completed")
        elif not isinstance(content, list) or any(
            not isinstance(item, dict) or item.get("type") != "text" or not isinstance(item.get("text"), str)
            for item in content
        ):
            result["errors"].append("unsupported_read_result")
        else:
            try:
                row["utf8_bytes"] = sum(len(item["text"].encode("utf-8")) for item in content)
            except UnicodeEncodeError:
                result["errors"].append("invalid_read_text_encoding")
    return result


def summarize(observations, *, export_complete):
    ids = [o["message_id"] for o in observations]
    calls = [r["call_id"] for o in observations for r in o["reads"]]
    errors = sorted({error for o in observations for error in o["errors"]})
    if len(ids) != len(set(ids)) or len(calls) != len(set(calls)):
        errors.append("duplicate_identity")
    values = [r["utf8_bytes"] for o in observations for r in o["reads"]]
    complete = export_complete and not errors and all(value is not None for value in values)
    subtotal = sum(value for value in values if value is not None)
    return {"schema": SCHEMA, "source": "pre_publication_message_export",
        "export_complete": export_complete, "complete": complete,
        "utf8_bytes": subtotal if complete else None, "observed_subtotal": subtotal,
        "read_calls": len(calls), "messages": observations, "errors": errors,
        "scope": "Native read result text before redaction: completed content text plus error.message for the exact {type, message} error object. No source bodies, paths, inputs or content hashes. Pending/running, unsupported errors, nontext and incomplete exports remain unknown. Error type labels and serialization wrappers are excluded. Shell reads and wire bytes are not inferred."}
