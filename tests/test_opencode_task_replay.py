"""Exact replay must never reuse a result across changed task inputs."""
import importlib.util
from pathlib import Path
import json
import shutil

import pytest

spec = importlib.util.spec_from_file_location("task_replay", Path(__file__).parents[1] / "integrations/opencode/task_replay.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


@pytest.fixture
def case(tmp_path):
    before, after, cache, output = (tmp_path / n for n in ("before", "after", "cache", "output"))
    (before / "src").mkdir(parents=True)
    (before / "src/old.py").write_text("value = 1\n")
    (before / "src/deleted.py").write_text("obsolete = True\n")
    (before / "config.toml").write_text("setting = 1\n")
    shutil.copytree(before, after)
    (after / "src/old.py").write_text("value = 2\n")
    (after / "src/deleted.py").unlink()
    (after / "src/new.py").write_text("from .old import value\n")
    recorded = replay.record(before, after, "update value", "toolchain-v1", cache)
    return before, after, cache, output, recorded


def test_hit_reproduces_source_changes_without_mutating_input(case):
    before, after, cache, output, record = case
    initial = replay.inventory(before)
    result = replay.materialize(before, "update value", "toolchain-v1", cache, output)
    assert result["status"] == "candidate_requires_grading" and result["model_calls"] == 0
    assert replay.inventory(output) == replay.inventory(after)
    assert replay.inventory(before) == initial
    assert replay.record(before, after, "update value", "toolchain-v1", cache) == record


@pytest.mark.parametrize("change", ["source", "config", "added_file", "task", "environment", "mode"])
def test_changed_inputs_are_a_miss_without_creating_output(case, change):
    before, _, cache, output, _ = case
    task, context = "update value", "toolchain-v1"
    if change == "source":
        (before / "src/old.py").write_text("value = 3\n")
    elif change == "config":
        (before / "config.toml").write_text("setting = 2\n")
    elif change == "added_file":
        (before / "untracked.py").write_text("extra input\n")
    elif change == "mode":
        (before / "src/old.py").chmod(0o755)
    elif change == "task":
        task += " differently"
    else:
        context = "toolchain-v2"
    assert replay.materialize(before, task, context, cache, output)["status"] == "miss"
    assert not output.exists()


@pytest.mark.parametrize("fault", ["traversal", "body", "base", "mode"])
def test_corrupt_entry_rejected_before_materialization(case, fault):
    before, _, cache, output, record = case
    path = cache / (record["key"] + ".json")
    value = json.loads(path.read_text())
    if fault == "traversal":
        value["changes"]["src/../../escape"] = value["changes"].pop("src/old.py")
    elif fault == "body":
        value["changes"]["src/old.py"]["content"] = "YQ=="
    elif fault == "base":
        value["base_files"] = {}
    else:
        value["changes"]["src/old.py"]["mode"] = 0o4777
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        replay.materialize(before, "update value", "toolchain-v1", cache, output)
    assert not output.exists()


def test_existing_output_is_never_overwritten(case):
    before, _, cache, output, _ = case
    output.mkdir()
    (output / "owned.txt").write_text("user data")
    with pytest.raises(ValueError):
        replay.materialize(before, "update value", "toolchain-v1", cache, output)
    assert (output / "owned.txt").read_text() == "user data"


def test_changed_during_copy_discards_candidate(case, monkeypatch):
    before, _, cache, output, _ = case
    original = shutil.copytree
    def racing_copy(*args, **kwargs):
        result = original(*args, **kwargs)
        (before / "config.toml").write_text("concurrent edit")
        return result
    monkeypatch.setattr(replay.shutil, "copytree", racing_copy)
    with pytest.raises(ValueError, match="changed during copy"):
        replay.materialize(before, "update value", "toolchain-v1", cache, output)
    assert not output.exists()
    assert (before / "config.toml").read_text() == "concurrent edit"


def test_symlink_input_is_rejected(case, tmp_path):
    before, _, cache, output, _ = case
    (before / "src/link.py").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="nonregular"):
        replay.materialize(before, "update value", "toolchain-v1", cache, output)
    assert not output.exists()
