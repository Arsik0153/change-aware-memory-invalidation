"""Authored schedule/isolation checks. No model, credentials, Docker or task data."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import study_controller as controller  # noqa: E402
from study_ledger import summarize  # noqa: E402
from study_schema import (  # noqa: E402
    FORMAT_DESIGN, format_conditions, plan, trial_response_format, validate_design,
)


def study():
    return dict(schema_version=2, design=FORMAT_DESIGN, bundle_kind="development",
                arms=["plain", "static", "cami"], repetitions=1,
                conditions=format_conditions(), memory_response_format="compact",
                normalized={"sequence": ["a", "a", "b", "b"]})


def test_twenty_trials_preserve_each_condition_history():
    data = study()
    rows = plan(data)
    assert len(rows) == len({r["id"] for r in rows}) == 20
    seen = {}
    for row in rows:
        if row["predecessor"] is not None:
            previous = seen[row["predecessor"]]
            assert previous["condition"] == row["condition"]
            assert previous["stage"] + 1 == row["stage"]
        seen[row["id"]] = row
    expected = [c["id"] for c in format_conditions()]
    for stage in range(1, 5):
        actual = [r["condition"] for r in rows if r["stage"] == stage]
        assert actual == expected[stage-1:] + expected[:stage-1]
    assert sum(r["arm"] == "plain" for r in rows) == 4
    for row in rows:
        assert trial_response_format(data, row) == row["response_format"]


@pytest.mark.parametrize("change", [
    {"bundle_kind": "heldout"}, {"repetitions": 3}, {"conditions": []},
    {"memory_response_format": "readable"}, {"design": "unregistered"},
    {"schema_version": 1},
])
def test_changed_design_is_rejected(change):
    data = study()
    data.update(change)
    with pytest.raises(ValueError):
        validate_design(data)


def test_response_override_cannot_enter_frozen_trial():
    data = study()
    row = deepcopy(plan(data)[1])
    row["response_format"] = "readable"
    with pytest.raises(ValueError, match="frozen"):
        trial_response_format(data, row)


def test_failed_construction_still_has_separate_condition_namespaces(tmp_path, monkeypatch):
    data = study()
    data["bundle_path"] = str(tmp_path)
    data["normalized"]["tasks"] = [{"id": "a", "archive": "absent", "archive_sha256": "0" * 64}]
    monkeypatch.setattr(controller, "validate", lambda *a, **kw: data)
    def failed_reset(*args):
        raise ValueError("authored reset failure, no model may start")
    monkeypatch.setattr(controller, "reset", failed_reset)
    monkeypatch.setattr(controller, "session", lambda *a: pytest.fail("model reached"))
    for row in plan(data)[:5]:
        result = controller.run_trial(data, "a" * 64, tmp_path, row, None)
        assert result["status"] == "failed" and not result["memory_usable"]
    assert {p.name for p in (tmp_path / "namespaces").iterdir()} == {
        "r1-" + c["id"] for c in format_conditions()
    }


def test_summary_keeps_formats_separate_without_superiority_claim():
    rows = plan(study())
    records = {r["id"]: {"trial": r, "status": "passed", "quality": "pass",
        "costs": {"complete": True, "charged_host_wall_seconds": 1}}
        for r in rows}
    summary = summarize(records, planned_trials=20)
    assert summary["planned_trials"] == summary["terminal_trials"] == 20
    assert len(summary["blocks"]) == 5
    assert all(b["four_stage_complete"] and b["charged_host_wall_seconds"] == 4
               for b in summary["blocks"])
    assert summary["speedup_claim"] is None


@pytest.mark.parametrize("value", ["https://host.docker.internal:1234", "http://example.com:80",
    "http://user:secret@localhost:1234", "http://localhost:1234/path", "http://localhost:1234?key=x",
    "http://localhost:1234#x", "http://localhost", "http://localhost:0", 42])
def test_auth_bridge_rejects_nonlocal_or_credential_bearing_urls(value):
    from study_schema import shared_server_value
    with pytest.raises(ValueError):
        shared_server_value({"shared_server": value})


@pytest.mark.parametrize("condition", [c["id"] for c in format_conditions()])
def test_session_forwards_exact_condition_and_auth_bridge(monkeypatch, tmp_path, condition):
    import study_runtime as runtime
    from study_schema import shared_server_value
    data = study()
    data.update(harness="fake.py", runtime_manifest_path="fake.json", reported_token_budget=1000000,
                image="image", cami_source="source", adapter="adapter", service_tier="priority",
                shared_server="http://host.docker.internal:49374", model="openai/gpt-6.1-sol#high")
    row = next(r for r in plan(data) if r["condition"] == condition)
    def stopped_before_launch(argv, timeout):
        assert argv[argv.index("--arm") + 1] == row["arm"]
        assert argv[argv.index("--memory-response-format") + 1] == row["response_format"]
        assert argv[argv.index("--shared-server") + 1] == shared_server_value(data)
        assert argv[argv.index("--service-tier") + 1] == "priority"
        assert ("--binding-relative" in argv) == (row["arm"] != "plain")
        raise RuntimeError("authored stop before subprocess")
    monkeypatch.setattr(runtime, "command", stopped_before_launch)
    with pytest.raises(RuntimeError, match="authored stop"):
        runtime.session(data, row, tmp_path, tmp_path, tmp_path, tmp_path / "session")
