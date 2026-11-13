"""Observe original bytes through the real exporter, while publishing no text in receipts."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import container_worker as worker  # noqa: E402
from native_read_evidence import observe_message, summarize  # noqa: E402


def message(text="π user@example.invalid", *, message_id="msg_one", call_id="call_one"):
    return {"id": message_id, "type": "assistant", "content": [
        {"id": call_id, "type": "tool", "name": "read", "state": {
            "status": "completed", "input": {"filePath": "/sensitive/source.py"},
            "content": [{"type": "text", "text": text}], "output": "duplicate ignored"}}]}


class Pages:
    def __init__(self, *pages):
        self.pages = iter(pages)

    def request(self, *args, **kwargs):
        page = next(self.pages)
        if isinstance(page, Exception):
            raise page
        return page


def page(messages, cursor=None):
    return {"data": messages, "cursor": {"next": cursor}}


def test_paginated_export_counts_utf8_before_redaction_without_disclosing_text(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "OUT", tmp_path)
    original = message()
    other = message("abc", message_id="msg_two", call_id="call_two")
    server = Pages(page([{"id": "msg_user", "type": "user", "text": "authored input"}, original], "next"),
                   page([other, {"id": "msg_idle", "type": "idle"}]))
    _, messages = worker.messages_all(server, "session")
    receipt = json.loads((tmp_path / "native-read-bytes.json").read_text())
    expected = len("π user@example.invalid".encode()) + 3
    assert receipt["utf8_bytes"] == expected and receipt["complete"]
    assert receipt["read_calls"] == 2 and len(receipt["messages"]) == 4
    assert "user@example.invalid" not in json.dumps(messages)
    assert "[REDACTED_EMAIL]" in json.dumps(messages)
    raw = (tmp_path / "native-read-bytes.json").read_text()
    for forbidden in ("user@example.invalid", "sensitive", "filePath", "duplicate ignored", "π"):
        assert forbidden not in raw
    assert original["content"][0]["state"]["content"][0]["text"] == "π user@example.invalid"


def test_failed_pagination_keeps_subtotal_and_never_claims_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "OUT", tmp_path)
    with pytest.raises(TimeoutError):
        worker.messages_all(Pages(page([message("abc")], "next"), TimeoutError("authored")), "session")
    receipt = json.loads((tmp_path / "native-read-bytes.json").read_text())
    assert not receipt["export_complete"] and not receipt["complete"]
    assert receipt["utf8_bytes"] is None and receipt["observed_subtotal"] == 3


@pytest.mark.parametrize("fault", ["error", "running", "nontext", "missing_content", "duplicate", "unknown_message"])
def test_unknown_read_outcomes_cannot_become_zero(fault):
    value = message()
    part = value["content"][0]
    if fault in ("error", "running"):
        part["state"] = {"status": fault, "error": "secret failure body"}
    elif fault == "nontext":
        part["state"]["content"] = [{"type": "image", "data": "private"}]
    elif fault == "missing_content":
        del part["state"]["content"]
    elif fault == "duplicate":
        value["content"].append(part)
    else:
        value["type"] = "future-unknown-type"
    receipt = summarize([observe_message(value)], export_complete=True)
    assert not receipt["complete"] and receipt["utf8_bytes"] is None
    assert "secret failure body" not in json.dumps(receipt)


def test_empty_complete_export_is_zero_and_separate_exports_do_not_accumulate(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "OUT", tmp_path)
    worker.messages_all(Pages(page([message("abc")])), "session")
    worker.messages_all(Pages(page([])), "session")
    receipt = json.loads((tmp_path / "native-read-bytes.json").read_text())
    assert receipt["complete"] and receipt["utf8_bytes"] == 0 and receipt["read_calls"] == 0


def test_failed_read_capture_invalidates_previous_complete_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "OUT", tmp_path)
    worker.messages_all(Pages(page([message("abc")])), "session")
    worker.capture_failure(Pages(ConnectionError("authored")), "session", 1, {})
    receipt = json.loads((tmp_path / "native-read-bytes.json").read_text())
    assert not receipt["complete"] and receipt["utf8_bytes"] is None
    assert receipt["observed_subtotal"] == 3
