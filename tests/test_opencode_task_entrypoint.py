"""Session binding and accounting use authored HTTP responses, without model calls."""

import io
import json

import pytest

from integrations.opencode import run_task
from integrations.opencode.task_session import telemetry


@pytest.mark.parametrize("kind", ["request_finished", "provider_error"])
def test_partial_usage_survives_failed_request_without_double_counting(kind):
    rows = [
        {"type": "request_started", "id": "a"},
        {"type": kind, "id": "a", "usage": {"input": 13, "output": None, "reasoning": -1}},
    ]
    result = telemetry([("response", {"line": json.dumps(row)}) for row in rows + rows[1:]])
    assert result["complete"] is False
    assert result["total"] is None
    assert result["missing_usage"] == ["a"]
    assert result["known_subtotal"] == {
        "input": 13,
        "output": 0,
        "reasoning": 0,
        "cache_read": 0,
        "cache_write": 0,
    }
    assert result["known_component_requests"] == {
        "input": 1,
        "output": 0,
        "reasoning": 0,
        "cache_read": 0,
        "cache_write": 0,
    }


def fake_api(monkeypatch, tmp_path, *, wrong_location=False, provider_error=False):
    config = tmp_path / ".config/opencode"
    config.mkdir(parents=True)
    (config / "service.json").write_text(json.dumps({"password": "authored-test-password"}))
    monkeypatch.setattr(run_task.Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_task, "service_url", lambda: "http://127.0.0.1:12345")
    model = {"providerID": "openai", "id": "gpt-6.1-sol", "variant": "high"}
    session = {
        "id": "s1",
        "location": {"directory": str(tmp_path / "wrong" if wrong_location else tmp_path)},
        "model": model,
        "outcome": "succeeded",
        "time": {"idle": 1},
    }
    calls = []

    def urlopen(request, timeout):
        calls.append((request.method, request.full_url))
        if "/message?" in request.full_url:
            message = {
                "id": "m1",
                "type": "assistant",
                "time": {"completed": 1},
                "tokens": {
                    "input": 7,
                    "output": 2,
                    "reasoning": 3,
                    "cache": {"read": 11, "write": 0},
                },
            }
            if provider_error:
                message["error"] = {"type": "provider.transport"}
            value = {"data": [message], "cursor": {}}
        elif request.full_url.endswith("/prompt"):
            value = {"data": {}}
        else:
            value = {"data": session}
        return io.BytesIO(json.dumps(value).encode())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    return calls


def test_location_is_verified_before_model_prompt(monkeypatch, tmp_path):
    calls = fake_api(monkeypatch, tmp_path, wrong_location=True)
    with pytest.raises(ValueError, match="binding"):
        run_task.forward("unused-pinned-binary", "openai/gpt-6.1-sol#high", "task")
    assert len(calls) == 1
    assert not any(url.endswith("/prompt") for _, url in calls)


@pytest.mark.parametrize("provider_error", [False, True])
def test_accounting_retains_provider_errors(monkeypatch, tmp_path, capsys, provider_error):
    fake_api(monkeypatch, tmp_path, provider_error=provider_error)
    assert run_task.forward("unused-pinned-binary", "openai/gpt-6.1-sol#high", "task") == 0
    events = [("response", {"line": line}) for line in capsys.readouterr().out.splitlines()]
    result = telemetry(events)
    assert result["complete"] is (not provider_error)
    if provider_error:
        assert result["total"] is None
        assert result["missing_usage"] == ["m1"]
        assert result["known_subtotal"] == {
            "input": 7,
            "output": 2,
            "reasoning": 3,
            "cache_read": 11,
            "cache_write": 0,
        }
    else:
        assert result["requests"] == 1
        assert result["total"] == {
            "input": 7,
            "output": 2,
            "reasoning": 3,
            "cache_read": 11,
            "cache_write": 0,
        }
