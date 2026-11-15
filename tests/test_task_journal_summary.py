"""Authored temporary logs are fixtures, never production hit-rate data."""

import json

from integrations.opencode.task_replay import identity
from integrations.opencode.task_session import Journal
from scripts.practical.summarize_task_journals import summarize


def fixture(root, name, task, *, origin="user", complete=True):
    directory = root / name
    directory.mkdir()
    (directory / "before").mkdir()
    context = json.dumps({"origin": origin, "external": "authored unit fixture"})
    config = {"files": {}, "task": task, "context": context, "key": identity({}, task, context)}
    journal = Journal(directory / "events.sqlite")
    journal.append("prepared", config)
    if complete:
        (directory / "solution").mkdir()
        journal.append(
            "terminal",
            {
                "quality": "pass",
                "execution": "success",
                "cache_eligible": True,
                "solution_files": {},
            },
        )
    journal.close()


def test_only_exact_declared_user_inputs_count(tmp_path):
    fixture(tmp_path, "a", "same task")
    fixture(tmp_path, "b", "different task")
    fixture(tmp_path, "c", "same task")
    fixture(tmp_path, "d", "same task", origin="admission")
    result = summarize(tmp_path)
    assert result["captured_user_requests"] == 3
    assert result["exact_repeat_requests"] == 1
    assert result["opportunities_with_previously_cache_eligible_solution"] == 1
    assert result["observed_exact_repeat_fraction"] == 1 / 3
    assert len(result["excluded"]) == 1


def test_inflight_result_is_not_available_for_replay(tmp_path):
    fixture(tmp_path, "a", "same task", complete=False)
    fixture(tmp_path, "b", "same task")
    result = summarize(tmp_path)
    assert result["exact_repeat_requests"] == 1
    assert result["opportunities_with_previously_completed_quality_passing_solution"] == 0
    assert result["unfinished_user_requests"] == 1


def test_empty_denominator_is_not_zero_rate(tmp_path):
    fixture(tmp_path, "a", "task", origin="experiment")
    result = summarize(tmp_path)
    assert result["captured_user_requests"] == 0
    assert result["observed_exact_repeat_fraction"] is None


def test_missing_input_snapshot_is_excluded(tmp_path):
    fixture(tmp_path, "a", "task")
    (tmp_path / "a/before").rmdir()
    result = summarize(tmp_path)
    assert result["captured_user_requests"] == 0
    assert len(result["excluded"]) == 1
