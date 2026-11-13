"""Synthetic decision checks; deliberately no tasks or model outcomes."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from format_probe import native_reads, summarize  # noqa: E402
from study_schema import FORMAT_DESIGN, format_conditions, plan  # noqa: E402


def rows():
    study = dict(schema_version=2, design=FORMAT_DESIGN, bundle_kind="development",
        repetitions=1, arms=["plain", "static", "cami"], conditions=format_conditions(),
        memory_response_format="compact", normalized={"sequence": ["a", "a", "b", "b"]})
    return [{**r, "terminal_present": True, "quality_eligible": True, "tokens_complete": True,
        "native_reads_complete": True, "wall_complete": True, "charged_wall_seconds": 100,
        "token_work": 9 if r["response_format"] == "readable" else 10,
        "native_read_bytes": 99 if r["response_format"] == "readable" else 100,
        "service_tier": {"configuration_valid": True, "provider_reported_complete": True,
                         "provider_reported_values": ["default"]}} for r in plan(study)]


def test_both_backends_both_metrics_required_and_no_superiority():
    data = rows()
    report = summarize(data)
    assert report["direction_supported"] and report["superiority_claim"] is None
    assert not report["wall_comparison_eligible"]
    for condition in ("static_readable", "cami_readable"):
        for metric in ("token_work", "native_read_bytes"):
            changed = deepcopy(data)
            for row in changed:
                if row["condition"] == condition:
                    row[metric] = 1000
            assert not summarize(changed)["direction_supported"]


@pytest.mark.parametrize("key", ["quality_eligible", "tokens_complete", "wall_complete", "native_reads_complete"])
def test_one_failure_including_plain_prevents_support(key):
    data = rows()
    data[0][key] = False
    assert not summarize(data)["direction_supported"]
    assert not summarize(data[:-1])["direction_supported"]


def messages(text="π\n"):
    return [{"type": "assistant", "content": [{"id": "read1", "type": "tool", "name": "read",
             "state": {"status": "completed", "content": [{"type": "text", "text": text}],
                       "output": "duplicate projection must not be counted"}}]}]


def test_utf8_bytes_counted_once_and_shell_not_inferred():
    data = messages()
    data[0]["content"].append({"id": "shell1", "type": "tool", "name": "shell",
                              "state": {"status": "completed", "output": "cat source.py"}})
    assert native_reads(data) == {"bytes": 3, "observed_subtotal": 3, "calls": 1,
                                  "complete": True, "errors": []}
    assert not native_reads(messages("[REDACTED_EMAIL]"))["complete"]
    assert not native_reads(None)["complete"]
    assert not native_reads([])["complete"]
    data[0]["content"].append(deepcopy(data[0]["content"][0]))
    assert not native_reads(data)["complete"]


def test_valid_user_and_idle_records_do_not_hide_reads_or_invalidate_export():
    data = [{"id": "msg_user", "type": "user", "time": {"created": 1}, "text": "request"},
            *messages(), {"id": "msg_idle", "type": "idle", "time": {"created": 2}, "outcome": "succeeded"}]
    assert native_reads(data)["complete"] and native_reads(data)["bytes"] == 3
    data[-1]["content"] = [{"type": "tool", "name": "read"}]
    assert not native_reads(data)["complete"]


def projection_fixture():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness"))
    from native_read_evidence import observe_message, summarize as receipt
    from container_worker import public
    value = messages("π user@example.invalid")
    value[0]["id"] = "msg_one"
    return public(value), receipt([observe_message(m) for m in value], export_complete=True)


def test_original_count_survives_redaction_and_is_not_public_text_length():
    from format_probe import read_projection
    visible, receipt = projection_fixture()
    result = read_projection(visible, receipt)
    assert result["complete"] and result["bytes"] == len("π user@example.invalid".encode())
    assert result["bytes"] != len(visible[0]["content"][0]["state"]["content"][0]["text"].encode())


@pytest.mark.parametrize("fault", ["message_id", "call_id", "state", "missing", "negative", "total", "bool", "unredacted_size"])
def test_projection_cannot_misbind_calls_or_invent_totals(fault):
    from format_probe import read_projection
    visible, receipt = projection_fixture()
    row = receipt["messages"][0]["reads"][0]
    if fault == "message_id":
        receipt["messages"][0]["message_id"] = "msg_other"
    elif fault == "call_id":
        row["call_id"] = "other"
    elif fault == "state":
        row["status"] = "error"
    elif fault == "missing":
        receipt["messages"][0]["reads"] = []
    elif fault == "negative":
        row["utf8_bytes"] = -1
    elif fault == "total":
        receipt["utf8_bytes"] += 1
    elif fault == "bool":
        row["utf8_bytes"] = True
    else:
        visible[0]["content"][0]["state"]["content"][0]["text"] = "short"
    with pytest.raises(ValueError):
        read_projection(visible, receipt)


def test_v2_error_projection_counts_message_only_and_preserves_v1_semantics():
    from format_probe import read_projection
    from native_read_evidence import observe_message, summarize as receipt_for
    from container_worker import public
    data = messages()
    data[0]["id"] = "msg_error"
    text = "π failure for user@example.invalid"
    data[0]["content"][0]["state"] = {"status": "error", "error": {"type": "ToolError", "message": text}}
    receipt = receipt_for([observe_message(data[0])], export_complete=True)
    visible = public(data)
    assert read_projection(visible, receipt)["bytes"] == len(text.encode())
    assert not native_reads(visible)["complete"]  # historical fallback unchanged
    receipt["schema"] = "opencode-native-read-text/1"
    with pytest.raises(ValueError, match="byte count"):
        read_projection(visible, receipt)
    receipt["messages"][0]["reads"][0]["utf8_bytes"] = None
    receipt["messages"][0]["errors"] = ["read_not_completed"]
    receipt.update(complete=False, utf8_bytes=None, observed_subtotal=0, errors=["read_not_completed"])
    assert not read_projection(visible, receipt)["complete"]


def test_v2_error_unredacted_mismatch_rejected():
    from format_probe import read_projection
    from native_read_evidence import observe_message, summarize as receipt_for
    data = messages()
    data[0]["id"] = "msg_error"
    data[0]["content"][0]["state"] = {"status": "error", "error": {"type": "ToolError", "message": "abc"}}
    receipt = receipt_for([observe_message(data[0])], export_complete=True)
    data[0]["content"][0]["state"]["error"]["message"] = "x"
    with pytest.raises(ValueError, match="bytes differ"):
        read_projection(data, receipt)
