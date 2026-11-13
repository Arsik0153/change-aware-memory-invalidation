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
        value["base_files_sha256"] = "0" * 64
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


def test_concurrent_identical_publish_is_atomic_and_idempotent(case):
    from concurrent.futures import ThreadPoolExecutor
    before, after, cache, _, record = case
    (cache / (record['key'] + '.json')).unlink()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: replay.record(before, after, 'update value', 'toolchain-v1', cache), range(8)))
    assert all(result == record for result in results)
    assert [p.name for p in cache.iterdir()] == [record['key'] + '.json']


def test_interrupted_publication_leaves_no_visible_entry(case, monkeypatch):
    before, after, cache, _, record = case
    (cache / (record['key'] + '.json')).unlink()
    def failed_sync(*args):
        raise OSError('authored interrupted persistence')
    monkeypatch.setattr(replay.os, 'fsync', failed_sync)
    with pytest.raises(OSError):
        replay.record(before, after, 'update value', 'toolchain-v1', cache)
    assert list(cache.iterdir()) == []


def test_compression_is_bounded_and_rejects_trailing_payload(monkeypatch):
    import base64
    encoded = replay.encode(b'x' * 1024)
    assert replay.decode(encoded) == b'x' * 1024
    junk = base64.b64encode(base64.b64decode(encoded) + b'trailing').decode()
    with pytest.raises(ValueError):
        replay.decode(junk)
    monkeypatch.setattr(replay, 'MAX_BYTES', 32)
    with pytest.raises(ValueError):
        replay.decode(encoded)


def test_symlink_parent_cannot_put_output_or_cache_inside_input(case, tmp_path):
    before, after, cache, _, _ = case
    alias = tmp_path / 'alias'
    alias.symlink_to(before, target_is_directory=True)
    with pytest.raises(ValueError, match='outside'):
        replay.materialize(before, 'update value', 'toolchain-v1', cache, alias / 'output')
    with pytest.raises(ValueError, match='outside'):
        replay.record(before, after, 'update value', 'toolchain-v1', alias / 'cache')
    assert not (before / 'output').exists() and not (before / 'cache').exists()


def test_cli_materializes_a_candidate_and_reports_miss(case, tmp_path):
    import subprocess
    import sys
    before, after, cache, output, _ = case
    task_file = tmp_path / 'task.txt'
    task_file.write_text('update value')
    command = [sys.executable, str(Path(replay.__file__)), 'materialize', '--workspace', str(before),
               '--task-file', str(task_file), '--context-id', 'toolchain-v1', '--cache', str(cache), '--out', str(output)]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)['status'] == 'candidate_requires_grading'
    assert replay.inventory(output) == replay.inventory(after)
    task_file.write_text('different task')
    command[-1] = str(tmp_path / 'miss')
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)['status'] == 'miss' and not (tmp_path / 'miss').exists()
