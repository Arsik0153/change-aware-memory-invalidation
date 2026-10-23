from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import time

import pytest

from cami.cli import main
from cami.errors import IncompleteError
from cami.product import store, worktree
from cami.symbol_search import find_symbols


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def cli(root, query, *args, seed="1", timeout=20):
    return subprocess.run(
        [sys.executable, "-m", "cami.cli", "find", query, "--repo", str(root),
         "--format", "json", *args], capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "PYTHONHASHSEED": seed}, check=False)


def lookup(root, query, *args):
    result = cli(root, query, *args)
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    return json.loads(result.stdout)


def state_path(root):
    return store.GenerationStore(root, store.state_base()).path


def current(root):
    return (state_path(root) / "current.json").read_bytes()


def payload(data):
    return {key: value for key, value in data.items() if key != "observation"}


def run_hook(root, body, query="target"):
    script = ("import os, sys\nfrom pathlib import Path\n"
              "from cami import symbol_search as search\n"
              "from cami.product import store, worktree\n"
              "from cami.cli import main\n"
              f"root = Path({str(root)!r})\n" + body + "\n"
              f"raise SystemExit(main(['find', {query!r}, '--repo', str(root), '--format', 'json']))")
    return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          timeout=20, check=False)


def test_separate_process_live_lifecycle_and_head_isolation(repo):
    original = "def target(x=1): return x\n"
    revision = repo.commit({"api.py": original, "old.py": "def removed(): pass\n",
                            "caller.py": "from api import target\ndef caller(): return target()\n"})
    first = lookup(repo.root, "target")
    snapshot = first["snapshot"]
    assert snapshot["kind"] == "worktree"
    assert snapshot["base_commit"] == revision
    assert snapshot["consistency"] == "verified_readset"
    assert first["requested_revision"] is None
    assert first["observation"]["cache_reused"] is False
    assert first["observation"]["capture_started_at"] <= first["observation"]["verified_at"]
    again = lookup(repo.root, "target")
    assert again["observation"]["cache_reused"] is True
    assert payload(first) == payload(again)
    (repo.root / "api.py").write_text("def target(staged=2): return staged\n")
    repo.git("add", "api.py")
    (repo.root / "api.py").write_text("def target(live: int=3): return live\n")
    before_index = (repo.root / ".git/index").read_bytes()
    before_status = repo.git("status", "--porcelain")
    live = lookup(repo.root, "target")
    assert live["matches"][0]["signature_text"] == "def target(live: int=3)"
    head = lookup(repo.root, "target", "--revision", "HEAD")
    assert head["matches"][0]["signature_text"] == "def target(x=1)"
    assert head["snapshot"]["revision"] == revision
    assert lookup(repo.root, "target", "--revision", revision) == head | {"requested_revision": revision}
    assert (repo.root / ".git/index").read_bytes() == before_index
    assert repo.git("status", "--porcelain") == before_status
    assert live["snapshot"]["snapshot_id"] != snapshot["snapshot_id"]
    (repo.root / "api.py").write_text("# comment only\n" + (repo.root / "api.py").read_text())
    comment = lookup(repo.root, "target")
    assert comment["matches"][0]["start_line"] == 2
    assert comment["snapshot"]["snapshot_id"] != live["snapshot"]["snapshot_id"]
    (repo.root / "new file.py").write_text("def untracked(): pass\n")
    assert lookup(repo.root, "untracked")["matches"][0]["path"] == "new file.py"
    (repo.root / "old.py").unlink()
    deleted = lookup(repo.root, "removed")
    assert deleted["status"] == "not_found" and deleted["absence_confirmed"]
    (repo.root / "api.py").rename(repo.root / "renamed.py")
    renamed = lookup(repo.root, "target")
    assert renamed["matches"][0]["path"] == "renamed.py"
    assert renamed["matches"][0]["incoming"] == []
    assert lookup(repo.root, "caller")["matches"][0]["outgoing"] == []
    (repo.root / "renamed.py").unlink()
    (repo.root / "new file.py").unlink()
    (repo.root / "api.py").write_text(original)
    (repo.root / "old.py").write_text("def removed(): pass\n")
    restored = lookup(repo.root, "target")
    assert payload(restored) == payload(first)
    assert restored["observation"]["cache_reused"]
    assert repo.git("rev-parse", "HEAD") == revision


def test_parse_error_drops_old_definitions_and_edges_but_healthy_search_works(repo):
    repo.commit({"bad.py": "def old(): pass\n",
                 "good.py": "from bad import old\ndef healthy(): return old()\n"})
    assert lookup(repo.root, "old")["status"] == "found"
    (repo.root / "bad.py").write_text("def old(\n")
    bad = lookup(repo.root, "old")
    assert bad["status"] == "not_found" and not bad["absence_confirmed"]
    assert bad["coverage"] == "partial"
    assert {"path": "bad.py", "code": "parse_error"} in bad["limitations"]
    healthy = lookup(repo.root, "healthy")
    assert healthy["status"] == "found" and healthy["coverage"] == "partial"
    assert healthy["matches"][0]["outgoing"] == []
    (repo.root / "bad.py").write_text("def old(recovered=True): pass\n")
    recovered = lookup(repo.root, "old")
    assert recovered["coverage"] == "complete"
    assert recovered["matches"][0]["signature_text"] == "def old(recovered=True)"
    assert any(edge["relation"] == "calls" for edge in recovered["matches"][0]["incoming"])


def test_gitignore_hard_excludes_source_roots_and_configured_paths(repo):
    repo.commit({"src/pkg/api.py": "def target(): pass\n",
                 "tracked.py": "def tracked(): pass\n",
                 "nested/keep.py": "def keep(): pass\n"})
    (repo.root / ".gitignore").write_text("ignored/\ntracked.py\nnested/*.py\n!nested/keep.py\n")
    for directory in ("ignored", ".venv", "node_modules", "__pycache__", ".cache",
                      ".pytest_cache", ".mypy_cache", ".ruff_cache", "output", "runs",
                      "reports", "cache", "skip folder"):
        path = repo.root / directory
        path.mkdir(exist_ok=True)
        (path / "broken.py").write_text("def broken(\n")
    (repo.root / "nested/drop.py").write_text("def ignored_nested(): pass\n")
    clean = lookup(repo.root, "target", "--exclude", "skip folder")
    assert clean["coverage"] == "complete"
    assert clean["snapshot"]["source_roots"] == ["src", "."]
    assert lookup(repo.root, "tracked", "--exclude", "skip folder")["status"] == "found"
    assert lookup(repo.root, "keep", "--exclude", "skip folder")["status"] == "found"
    assert lookup(repo.root, "ignored_nested", "--exclude", "skip folder")["absence_confirmed"]
    restricted = lookup(repo.root, "tracked", "--source-root", "src")
    assert restricted["status"] == "not_found" and restricted["coverage"] == "complete"
    included = lookup(repo.root, "target")
    assert included["coverage"] == "partial"
    assert included["snapshot"]["snapshot_id"] != clean["snapshot"]["snapshot_id"]
    assert cli(repo.root, "target", "--revision", "HEAD", "--exclude", "skip folder").returncode == 2
    (repo.root / ".gitignore").write_text("tracked.py\n")
    changed_policy = lookup(repo.root, "ignored_nested", "--exclude", "skip folder",
                            "--exclude", "ignored")
    assert changed_policy["status"] == "found"


def test_global_and_repository_info_excludes_are_part_of_capture(repo, tmp_path):
    repo.commit({"a.py": "def target(): pass\n"})
    (repo.root / "global.py").write_text("def global_symbol(): pass\n")
    (repo.root / "local.py").write_text("def local_symbol(): pass\n")
    ignore = tmp_path / "global ignore"
    ignore.write_text("global.py\n")
    repo.git("config", "core.excludesFile", str(ignore))
    (repo.root / ".git/info/exclude").write_text("local.py\n")
    first = lookup(repo.root, "global_symbol")
    assert first["absence_confirmed"]
    assert lookup(repo.root, "local_symbol")["absence_confirmed"]
    ignore.write_text("")
    assert lookup(repo.root, "global_symbol")["status"] == "found"
    assert lookup(repo.root, "target")["snapshot"]["snapshot_id"] != first["snapshot"]["snapshot_id"]


def test_symlinks_special_files_and_product_state_are_not_followed(repo, tmp_path, monkeypatch):
    repo.commit({"a.py": "raise RuntimeError('must never execute')\ndef target(): pass\n"})
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.py").write_text("def leaked(): pass\n")
    (repo.root / "linked").symlink_to(outside, target_is_directory=True)
    (repo.root / "link.py").symlink_to(outside / "leak.py")
    os.mkfifo(repo.root / "pipe.py")
    monkeypatch.setenv("XDG_STATE_HOME", str(repo.root / "local state"))
    store.state_base().mkdir(parents=True)
    (store.state_base() / "bad.py").write_text("def broken(\n")
    data = lookup(repo.root, "leaked")
    assert data["status"] == "not_found" and data["coverage"] == "partial"
    assert {item["code"] for item in data["limitations"]} >= {
        "symlink_unsupported", "special_file_unsupported"}
    assert not any("local state" in (item["path"] or "") for item in data["limitations"])
    assert lookup(repo.root, "target")["status"] == "found"


def test_large_file_bytes_and_lfs_limitations_have_honest_identity(repo):
    repo.commit({"a.py": "def target(): pass\n"})
    large = repo.root / "large.py"
    large.write_bytes(b"#" * (2 * 1024 * 1024 + 1))
    (repo.root / "lfs.py").write_text("version https://git-lfs.github.com/spec/v1\n")
    first = lookup(repo.root, "target")
    assert first["coverage"] == "partial"
    assert {"path": "large.py", "code": "file_too_large"} in first["limitations"]
    assert {"path": "lfs.py", "code": "lfs_unsupported"} in first["limitations"]
    large.write_bytes(large.read_bytes()[:-1] + b"!")
    second = lookup(repo.root, "target")
    assert second["snapshot"]["snapshot_id"] != first["snapshot"]["snapshot_id"]


def test_submodule_is_reported_without_entering_its_directory(repo):
    oid = repo.commit({"a.py": "def target(): pass\n"})
    repo.git("update-index", "--add", "--cacheinfo", f"160000,{oid},dependency")
    (repo.root / "dependency").mkdir()
    (repo.root / "dependency/hidden.py").write_text("def hidden(): pass\n")
    result = lookup(repo.root, "hidden")
    assert result["status"] == "not_found" and not result["absence_confirmed"]
    assert {"path": "dependency", "code": "submodule_unsupported"} in result["limitations"]


def test_cached_index_reused_in_fresh_process_without_invoking_builder(repo):
    repo.commit({"a.py": "def target(x): return x\n"})
    first = lookup(repo.root, "target")
    result = run_hook(repo.root, "def forbidden(*args, **kwargs):\n"
                                "    raise AssertionError('unexpected rebuild')\n"
                                "search.build_index = forbidden")
    assert result.returncode == 0, result.stderr
    second = json.loads(result.stdout)
    assert payload(second) == payload(first)
    assert second["observation"]["cache_reused"] is True


def test_cached_capture_is_verified_again_before_reuse(repo, monkeypatch):
    repo.commit({"a.py": "def target(old=True): pass\n"})
    first = lookup(repo.root, "target")
    load = store.GenerationStore.load
    changed = []

    def changing(storage, generation_id, captured, fingerprint):
        generation = load(storage, generation_id, captured, fingerprint)
        if generation is not None and not changed:
            changed.append(1)
            (repo.root / "a.py").write_text("def target(fresh=True): pass\n")
        return generation

    monkeypatch.setattr(store.GenerationStore, "load", changing)
    result = find_symbols(repo.root, "target")
    assert changed
    assert result.matches[0].signature_text == "def target(fresh=True)"
    assert result.snapshot.generation_id != first["snapshot"]["generation_id"]
    assert not result.observation.cache_reused


def test_json_payload_is_sorted_and_stable_across_process_hash_seeds(repo):
    repo.commit({"a.py": "def target(x): return helper(x)\ndef helper(x): return x\n",
                 "b.py": "from a import target\ndef caller(): return target(2)\n"})
    first = json.loads(cli(repo.root, "target", seed="11").stdout)
    second = json.loads(cli(repo.root, "target", seed="97").stdout)
    assert payload(first) == payload(second)


@pytest.mark.parametrize("damage", ["index", "manifest", "schema", "boolean_schema", "identity",
                                   "duplicate_keys", "missing_index", "pointer", "orphan"])
def test_corrupt_or_incompatible_state_rebuilds_with_diagnostics(repo, damage):
    repo.commit({"a.py": "def target(): pass\n"})
    first = lookup(repo.root, "target")
    path = state_path(repo.root)
    generation = path / "generations" / first["snapshot"]["generation_id"]
    manifest_path = generation / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if damage == "index":
        (generation / "index.json").write_bytes(b"truncated")
    elif damage == "manifest":
        manifest_path.write_bytes(b"{")
    elif damage in ("schema", "boolean_schema", "identity"):
        if damage == "identity":
            manifest["snapshot_id"] = "0" * 64
        else:
            manifest["schema_version"] = True if damage == "boolean_schema" else 99
        manifest_path.write_text(json.dumps(manifest))
    elif damage == "duplicate_keys":
        manifest_path.write_text('{"schema_version":1,' + manifest_path.read_text()[1:])
    elif damage == "missing_index":
        (generation / "index.json").unlink()
    elif damage == "pointer":
        (path / "current.json").write_text('{"generation_id":"../../escape"}')
    else:
        (path / "current.json").write_text('{"schema_version":1,"generation_id":"' + "0"*64 + '"}')
    result = cli(repo.root, "target")
    assert result.returncode == 0, result.stderr
    assert "cami cache:" in result.stderr
    data = json.loads(result.stdout)
    assert payload(data) == payload(first)
    assert data["observation"]["cache_reused"] is (damage in ("pointer", "orphan"))
    assert lookup(repo.root, "target")["observation"]["cache_reused"] is True


def test_linked_worktrees_have_independent_current_pointers(repo, tmp_path):
    repo.commit({"a.py": "def target(main=True): pass\n"})
    linked = tmp_path / "linked worktree"
    repo.git("worktree", "add", "--detach", str(linked), "HEAD")
    (linked / "a.py").write_text("def target(linked=True): pass\n")
    original = lookup(repo.root, "target")
    other = lookup(linked, "target")
    assert original["matches"][0]["signature_text"] == "def target(main=True)"
    assert other["matches"][0]["signature_text"] == "def target(linked=True)"
    assert state_path(repo.root) != state_path(linked)
    assert current(repo.root) != current(linked)
    assert lookup(repo.root, "target")["snapshot"] == original["snapshot"]


def test_sha256_git_and_unborn_worktree_are_supported(tmp_path):
    root = tmp_path / "sha256 repo"
    subprocess.run(["git", "init", "-q", "--object-format=sha256", str(root)], check=True)
    (root / "a.py").write_text("def target(): pass\n")
    data = lookup(root, "target")
    assert data["snapshot"]["base_commit"] is None
    for args in (("config", "user.email", "test@example.invalid"),
                 ("config", "user.name", "Fixture"), ("add", "."), ("commit", "-qm", "fixture")):
        subprocess.run(["git", "-C", str(root), *args], check=True)
    head = lookup(root, "target", "--revision", "HEAD")
    assert len(head["snapshot"]["revision"]) == 64
    assert lookup(root, "target")["snapshot"]["snapshot_id"] == data["snapshot"]["snapshot_id"]


@pytest.mark.parametrize("operation", ["edit", "rename", "delete"])
def test_change_during_build_discards_candidate_and_retries(repo, monkeypatch, operation):
    repo.commit({"a.py": "def target(old=True): pass\n"})
    from cami import symbol_search as search
    build = search.build_index
    builds = []

    def changing(snapshot, config):
        index = build(snapshot, config)
        builds.append(index)
        if len(builds) == 1:
            if operation == "edit":
                (repo.root / "a.py").write_text("def target(fresh=True): pass\n")
            elif operation == "rename":
                (repo.root / "a.py").rename(repo.root / "new.py")
            else:
                (repo.root / "a.py").unlink()
        return index

    monkeypatch.setattr(search, "build_index", changing)
    result = find_symbols(repo.root, "target")
    assert len(builds) == 2
    if operation == "delete":
        assert result.status == "not_found" and result.absence_confirmed
    else:
        match, = result.matches
        assert match.path == ("new.py" if operation == "rename" else "a.py")
        assert "fresh" in match.signature_text if operation == "edit" else True
    assert len(list((state_path(repo.root) / "generations").iterdir())) == 1


def test_continuous_changes_fail_bounded_retry_without_publishing_or_returning_old(repo, monkeypatch, capsys):
    repo.commit({"a.py": "def target(old=True): pass\n"})
    lookup(repo.root, "target")
    previous = current(repo.root)
    (repo.root / "a.py").write_text("def target(changing=True): pass\n")
    from cami import symbol_search as search
    build = search.build_index
    calls = []

    def changing(snapshot, config):
        calls.append(1)
        index = build(snapshot, config)
        path = repo.root / "a.py"
        path.write_text(path.read_text() + "# another concurrent edit\n")
        return index

    monkeypatch.setattr(search, "build_index", changing)
    assert main(["find", "target", "--repo", str(repo.root), "--format", "json"]) == 4
    output = capsys.readouterr()
    assert output.out == "" and "capture_unstable" in output.err
    assert len(calls) == 3 and current(repo.root) == previous


def test_permission_failure_during_verification_is_not_a_delete_or_partial_publish(repo, monkeypatch, capsys):
    repo.commit({"a.py": "def target(old=True): pass\n"})
    lookup(repo.root, "target")
    previous = current(repo.root)
    (repo.root / "a.py").write_text("def target(new=True): pass\n")
    read = worktree._read_file
    calls = []

    def denied(fd, name):
        if name == "a.py":
            calls.append(1)
            if len(calls) == 2:
                raise PermissionError("controlled fixture denial")
        return read(fd, name)

    monkeypatch.setattr(worktree, "_read_file", denied)
    assert main(["find", "target", "--repo", str(repo.root), "--format", "json"]) == 4
    output = capsys.readouterr()
    assert output.out == "" and "capture_io_error" in output.err
    assert current(repo.root) == previous


def test_growing_file_read_terminates_without_chasing_appended_bytes(repo, monkeypatch):
    path = repo.root / "a.py"
    path.write_text("def target(): pass\n")
    read = os.read
    calls = []

    def growing(fd, size):
        calls.append(1)
        if len(calls) > 8:
            raise AssertionError("capture kept reading a continuously growing input")
        content = read(fd, size)
        with path.open("ab") as stream:
            stream.write(b"# concurrent append\n" * 1024)
        return content

    fd = os.open(repo.root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        monkeypatch.setattr(worktree.os, "read", growing)
        with pytest.raises(worktree.CaptureChanged):
            worktree._read_file(fd, "a.py")
    finally:
        os.close(fd)


def test_directory_replaced_by_symlink_never_reads_the_target(repo, tmp_path, monkeypatch):
    repo.commit({"pkg/a.py": "def target(): pass\n"})
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.py").write_text("def leaked(): pass\n")
    read = worktree._read_file
    swapped = []

    def swapping(fd, name):
        if name == "a.py" and not swapped:
            swapped.append(1)
            (repo.root / "pkg").rename(repo.root / "oldpkg")
            (repo.root / "pkg").symlink_to(outside, target_is_directory=True)
        return read(fd, name)

    monkeypatch.setattr(worktree, "_read_file", swapping)
    result = find_symbols(repo.root, "leaked")
    assert result.status == "not_found" and result.coverage == "partial"
    assert all(module.path != "pkg/a.py" for module in store.INDEX_ADAPTER.validate_json(
        (state_path(repo.root) / "generations" / json.loads(current(repo.root))["generation_id"]
         / "index.json").read_bytes()).python.modules)


@pytest.mark.parametrize("phase", ["before_generation", "after_generation", "before_pointer", "after_pointer"])
def test_crash_recovery_publishes_only_complete_immutable_generations(repo, phase):
    repo.commit({"a.py": "def target(old=True): pass\n"})
    first = lookup(repo.root, "target")
    old_pointer = current(repo.root)
    old_dir = state_path(repo.root) / "generations" / first["snapshot"]["generation_id"]
    old_index = (old_dir / "index.json").read_bytes()
    (repo.root / "a.py").write_text("def target(fresh=True): pass\n")
    result = run_hook(repo.root, f"""
replace = store.os.replace
def crash(source, destination, **kwargs):
    destination = Path(destination)
    is_generation = len(destination.name) == 64
    is_pointer = destination.name == 'current.json'
    phase = {phase!r}
    if (phase == 'before_generation' and is_generation) or (phase == 'before_pointer' and is_pointer):
        os._exit(73)
    replace(source, destination, **kwargs)
    if (phase == 'after_generation' and is_generation) or (phase == 'after_pointer' and is_pointer):
        os._exit(73)
store.os.replace = crash
""")
    assert result.returncode == 73, result.stderr
    assert result.stdout == ""
    assert (current(repo.root) == old_pointer) is (phase != "after_pointer")
    recovered = lookup(repo.root, "target")
    assert recovered["matches"][0]["signature_text"] == "def target(fresh=True)"
    assert recovered["observation"]["cache_reused"] is (phase != "before_generation")
    assert (old_dir / "index.json").read_bytes() == old_index


def wait_file(path, process):
    deadline = time.monotonic() + 10
    while not path.exists() and time.monotonic() < deadline and process.poll() is None:
        time.sleep(0.01)
    assert path.exists(), process.communicate(timeout=2)


def test_concurrent_finds_serialize_refresh_and_pin_the_same_generation(repo, tmp_path):
    repo.commit({"a.py": "def target(fresh=True): pass\n"})
    ready, release, started, captured = (tmp_path / name for name in (
        "ready", "release", "started", "captured"))
    prefix = ("import sys, time\nfrom pathlib import Path\n"
              "from cami import symbol_search as search\nfrom cami.product import store\n"
              "from cami.cli import main\n")
    finish = f"raise SystemExit(main(['find','target','--repo',{str(repo.root)!r},'--format','json']))\n"
    writer = prefix + f"""
build = search.build_index
def paused(snapshot, config):
    index = build(snapshot, config)
    Path({str(ready)!r}).touch()
    deadline = time.monotonic() + 10
    while not Path({str(release)!r}).exists():
        if time.monotonic() > deadline:
            raise RuntimeError('fixture release timed out')
        time.sleep(0.01)
    return index
search.build_index = paused
""" + finish
    reader = prefix + f"""
capture = store.capture
def observing(*args):
    Path({str(captured)!r}).touch()
    return capture(*args)
store.capture = observing
Path({str(started)!r}).touch()
""" + finish
    first = subprocess.Popen([sys.executable, "-c", writer], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    second = None
    try:
        wait_file(ready, first)
        second = subprocess.Popen([sys.executable, "-c", reader], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        wait_file(started, second)
        assert not captured.exists() and second.poll() is None
        release.touch()
        out1, err1 = first.communicate(timeout=15)
        out2, err2 = second.communicate(timeout=15)
        assert first.returncode == second.returncode == 0, (err1, err2)
        assert not err1 and not err2
        data1, data2 = json.loads(out1), json.loads(out2)
        assert payload(data1) == payload(data2)
        assert not data1["observation"]["cache_reused"]
        assert data2["observation"]["cache_reused"]
        assert captured.exists()
        assert len(list((state_path(repo.root) / "generations").iterdir())) == 1
    finally:
        release.touch()
        for process in (first, second):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate()


def test_storage_failure_preserves_pointer_and_does_not_return_stale(repo, monkeypatch):
    repo.commit({"a.py": "def target(old=True): pass\n"})
    lookup(repo.root, "target")
    before = current(repo.root)
    (repo.root / "a.py").write_text("def target(fresh=True): pass\n")
    write = store._write_file

    def failing(path, content):
        if path.name == "manifest.json":
            raise OSError("controlled full device")
        write(path, content)

    monkeypatch.setattr(store, "_write_file", failing)
    with pytest.raises(IncompleteError, match="product_state_io_error"):
        find_symbols(repo.root, "target")
    assert current(repo.root) == before
    assert len(list((state_path(repo.root) / "generations").iterdir())) == 1


def test_policy_and_indexer_fingerprints_change_generation_identity(repo, monkeypatch):
    repo.commit({"a.py": "def target(): pass\n"})
    first = find_symbols(repo.root, "target")
    monkeypatch.setattr(store, "index_fingerprint", lambda: hashlib.sha256(b"new indexer").hexdigest())
    second = find_symbols(repo.root, "target")
    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id
    assert first.snapshot.generation_id != second.snapshot.generation_id
    assert not second.observation.cache_reused


@pytest.mark.parametrize("kind", ["regular", "symlink", "dev_null", "info", "global"])
def test_git_effective_external_ignore_is_verified_and_reused(repo, tmp_path, kind):
    repo.commit({"a.py": "def target(): pass\n"})
    (repo.root / "hidden.py").write_text("def hidden(): pass\n")
    referent = tmp_path / "ignore-rules"
    referent.write_text("hidden.py\n")
    if kind == "info":
        referent = repo.root / ".git/info/exclude"
        referent.write_text("hidden.py\n")
    elif kind == "global":
        referent = tmp_path / "config/git/ignore"
        referent.parent.mkdir(parents=True)
        referent.write_text("hidden.py\n")
    else:
        source = referent
        if kind == "symlink":
            source = tmp_path / "ignore-link"
            source.symlink_to(referent)
        elif kind == "dev_null":
            source = os.devnull
        repo.git("config", "core.excludesFile", str(source))
    first = lookup(repo.root, "target")
    assert lookup(repo.root, "target")["observation"]["cache_reused"]
    hidden = lookup(repo.root, "hidden")
    assert hidden["status"] == ("found" if kind == "dev_null" else "not_found")
    if kind != "dev_null":
        referent.write_text("other.py\n")
        changed = lookup(repo.root, "target")
        for field in ("snapshot_id", "generation_id"):
            assert changed["snapshot"][field] != first["snapshot"][field]
        assert changed["snapshot"]["policy"]["ignore_fingerprint"] != first["snapshot"]["policy"]["ignore_fingerprint"]
        assert lookup(repo.root, "hidden")["status"] == "found"
        assert lookup(repo.root, "target")["observation"]["cache_reused"]


@pytest.mark.parametrize("prefix", ["", "pkg/"])
def test_source_exclusion_does_not_hide_active_ignore_policy(repo, prefix):
    repo.commit({prefix + "a.py": "def target(): pass\n"})
    ignore = repo.root / (prefix + ".gitignore")
    ignore.write_text("*.one\n")
    args = ("--exclude", prefix + ".gitignore", "--source-root", prefix.rstrip("/") or ".")
    first = lookup(repo.root, "target", *args)
    ignore.write_text("*.two\n")
    second = lookup(repo.root, "target", *args)
    assert second["matches"] == first["matches"]
    for field in ("snapshot_id", "generation_id"):
        assert second["snapshot"][field] != first["snapshot"][field]
    assert second["snapshot"]["policy"]["ignore_fingerprint"] != first["snapshot"]["policy"]["ignore_fingerprint"]
    assert not second["observation"]["cache_reused"]
    assert lookup(repo.root, "target", *args)["observation"]["cache_reused"]


@pytest.mark.parametrize("artifact", ["index.json", "manifest.json", "current.json", "generation", "generations"])
@pytest.mark.parametrize("kind", ["fifo", "directory", "symlink", "socket"])
def test_cache_artifact_types_repair_persistently_without_following_targets(repo, tmp_path, artifact, kind):
    repo.commit({"a.py": "def target(): pass\n"})
    first = lookup(repo.root, "target")
    state = state_path(repo.root)
    generation = state / "generations" / first["snapshot"]["generation_id"]
    damaged = (generation if artifact == "generation" else state / "generations"
               if artifact == "generations" else state / "current.json"
               if artifact == "current.json" else generation / artifact)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("outside must remain untouched")
    if damaged.is_dir():
        shutil.rmtree(damaged)
    else:
        damaged.unlink()
    if kind == "fifo":
        os.mkfifo(damaged)
    elif kind == "socket":
        fd = os.open(damaged.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with socket.socket(socket.AF_UNIX) as node:
                node.bind(f"/proc/self/fd/{fd}/{damaged.name}")
        finally:
            os.close(fd)
    elif kind == "symlink":
        damaged.symlink_to(outside, target_is_directory=True)
    elif artifact in ("generation", "generations"):
        damaged.write_text("a directory was replaced by a file")
    else:
        damaged.mkdir()
    result = cli(repo.root, "target", timeout=4)
    assert result.returncode == 0, result.stderr
    assert "cami cache:" in result.stderr
    repaired = json.loads(result.stdout)
    assert payload(repaired) == payload(first)
    assert generation.is_dir() and not generation.is_symlink()
    assert (generation / "index.json").is_file()
    assert (generation / "manifest.json").is_file()
    assert not (generation / "manifest.json").is_symlink()
    assert sentinel.read_text() == "outside must remain untouched"
    assert list(outside.iterdir()) == [sentinel]
    assert lookup(repo.root, "target")["observation"]["cache_reused"]
    if kind == "socket":
        assert any(stat.S_ISSOCK(path.lstat().st_mode)
                   for path in state.rglob("*") if ".corrupt-" in str(path))
        reused = run_hook(repo.root, "def forbidden(*args, **kwargs):\n"
                          "    raise AssertionError('repaired cache must be reused')\n"
                          "search.build_index = forbidden")
        assert reused.returncode == 0, reused.stderr
        assert json.loads(reused.stdout)["observation"]["cache_reused"]


def test_repaired_fifo_index_releases_lock_for_concurrent_process_reuse(repo):
    repo.commit({"a.py": "def target(): pass\n"})
    first = lookup(repo.root, "target")
    index = state_path(repo.root) / "generations" / first["snapshot"]["generation_id"] / "index.json"
    index.unlink()
    os.mkfifo(index)
    repaired = cli(repo.root, "target", timeout=4)
    assert repaired.returncode == 0, repaired.stderr
    processes = []
    try:
        for _ in range(2):
            processes.append(subprocess.Popen(
                [sys.executable, "-m", "cami.cli", "find", "target", "--repo", str(repo.root),
                 "--format", "json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        for process in processes:
            stdout, stderr = process.communicate(timeout=8)
            assert process.returncode == 0 and not stderr, stderr
            data = json.loads(stdout)
            assert payload(data) == payload(first)
            assert data["observation"]["cache_reused"]
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=2)


@pytest.mark.parametrize("kind", ["fifo", "directory", "device", "loop", "oversize"])
def test_unsupported_external_ignore_fails_before_git_can_block(repo, tmp_path, kind):
    repo.commit({"a.py": "def target(): pass\n"})
    source = tmp_path / "ignore-config"
    if kind == "fifo":
        os.mkfifo(source)
    elif kind == "directory":
        source.mkdir()
    elif kind == "device":
        source.symlink_to("/dev/zero")
    elif kind == "loop":
        source.symlink_to(source)
    else:
        with source.open("wb") as stream:
            stream.truncate(worktree.MAX_FILE_BYTES + 1)
    repo.git("config", "core.excludesFile", str(source))
    result = cli(repo.root, "target", timeout=4)
    assert result.returncode == 4 and not result.stdout
    assert ("capture_ignore_error" if kind == "loop" else "capture_ignore_unsupported") in result.stderr
    assert not (state_path(repo.root) / "current.json").exists()


def test_explicit_empty_excludes_file_disables_default_global_ignore(repo, tmp_path):
    repo.commit({"a.py": "def target(): pass\n"})
    default = tmp_path / "config/git/ignore"
    default.parent.mkdir(parents=True)
    default.write_text("hidden.py\n")
    (repo.root / "hidden.py").write_text("def hidden(): pass\n")
    assert lookup(repo.root, "hidden")["status"] == "not_found"
    repo.git("config", "core.excludesFile", "")
    found = lookup(repo.root, "hidden")
    assert found["status"] == "found"
    default.write_text("*.py\n")
    assert lookup(repo.root, "hidden")["snapshot"] == found["snapshot"]
    assert lookup(repo.root, "hidden")["observation"]["cache_reused"]


@pytest.mark.parametrize("role", ["external_symlink", "excluded_local"])
def test_ignore_metadata_changed_after_cache_load_discards_candidate(repo, tmp_path, monkeypatch, role):
    repo.commit({"a.py": "def target(): pass\n"})
    rules = tmp_path / "ignore-rules" if role == "external_symlink" else repo.root / ".gitignore"
    rules.write_text("*.one\n")
    if role == "external_symlink":
        link = tmp_path / "ignore-link"
        link.symlink_to(rules)
        repo.git("config", "core.excludesFile", str(link))
    args = ("--exclude", ".gitignore")
    first = lookup(repo.root, "target", *args)
    load = store.GenerationStore.load
    calls = []

    def changing(self, *parameters):
        candidate = load(self, *parameters)
        calls.append(candidate is not None)
        if len(calls) == 1:
            rules.write_text("*.two\n")
        return candidate

    monkeypatch.setattr(store.GenerationStore, "load", changing)
    result = find_symbols(repo.root, "target", excluded_paths=(".gitignore",))
    assert calls == [True, False]
    assert result.snapshot.snapshot_id != first["snapshot"]["snapshot_id"]
    assert result.snapshot.policy.ignore_fingerprint != first["snapshot"]["policy"]["ignore_fingerprint"]
    assert not result.observation.cache_reused
    assert lookup(repo.root, "target", *args)["observation"]["cache_reused"]


def test_oversized_cache_index_repairs_before_reading_bytes(repo):
    repo.commit({"a.py": "def target(): pass\n"})
    first = lookup(repo.root, "target")
    index = state_path(repo.root) / "generations" / first["snapshot"]["generation_id"] / "index.json"
    with index.open("wb") as stream:
        stream.truncate(store.MAX_CACHE_BYTES + 1)
    repaired = cli(repo.root, "target", timeout=4)
    assert repaired.returncode == 0, repaired.stderr
    assert payload(json.loads(repaired.stdout)) == payload(first)
    assert index.stat().st_size < store.MAX_CACHE_BYTES
    assert lookup(repo.root, "target")["observation"]["cache_reused"]


@pytest.mark.parametrize("kind", ["fifo", "socket", "directory", "symlink"])
def test_cache_open_race_to_invalid_type_is_bounded_and_repairs(repo, monkeypatch, kind):
    repo.commit({"a.py": "def target(): pass\n"})
    first = lookup(repo.root, "target")
    index = state_path(repo.root) / "generations" / first["snapshot"]["generation_id"] / "index.json"
    opened = store._cache_open
    swaps = []

    def swapping(name, flags, parent_fd=None):
        if name == "index.json" and not swaps:
            swaps.append(True)
            index.unlink()
            if kind == "fifo":
                os.mkfifo(index)
            elif kind == "socket":
                with socket.socket(socket.AF_UNIX) as node:
                    node.bind(f"/proc/self/fd/{parent_fd}/index.json")
            elif kind == "directory":
                index.mkdir()
            else:
                index.symlink_to(index.parent / "manifest.json")
        return opened(name, flags, parent_fd)

    monkeypatch.setattr(store, "_cache_open", swapping)
    result = find_symbols(repo.root, "target")
    assert swaps and not result.observation.cache_reused
    assert index.is_file()
    assert lookup(repo.root, "target")["observation"]["cache_reused"]


@pytest.mark.parametrize("error", [errno.EACCES, errno.EIO, errno.ENXIO])
@pytest.mark.parametrize("operation", ["open", "read"])
def test_regular_cache_io_errors_remain_fatal_without_repair(repo, monkeypatch, capsys, error, operation):
    repo.commit({"a.py": "def target(): pass\n"})
    first = lookup(repo.root, "target")
    state = state_path(repo.root)
    files = {path: path.read_bytes() for path in state.rglob("*") if path.is_file()}
    opened = store.os.open
    read = store.os.read
    index = state / "generations" / first["snapshot"]["generation_id"] / "index.json"
    identity = index.stat()

    def denied_open(name, *args, **kwargs):
        if name == "index.json":
            raise OSError(error, "controlled regular cache open failure")
        return opened(name, *args, **kwargs)

    def denied_read(fd, size):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino):
            raise OSError(error, "controlled regular cache read failure")
        return read(fd, size)

    with monkeypatch.context() as patch:
        patch.setattr(store.os, operation, denied_open if operation == "open" else denied_read)
        assert main(["find", "target", "--repo", str(repo.root), "--format", "json"]) == 4
    output = capsys.readouterr()
    assert not output.out and "product_state_io_error" in output.err
    assert f"Errno {error}" in output.err
    assert files == {path: path.read_bytes() for path in state.rglob("*") if path.is_file()}
    assert not list(state.glob(".corrupt-*"))
    reused = lookup(repo.root, "target")
    assert payload(reused) == payload(first) and reused["observation"]["cache_reused"]


def test_cache_replacement_before_open_is_rejected_before_read(tmp_path, monkeypatch):
    path = tmp_path / "index.json"
    path.write_bytes(b"old")
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(b"new")
    opened = store._cache_open

    def swapping(name, flags, parent_fd=None):
        replacement.replace(path)
        return opened(name, flags, parent_fd)

    def forbidden(fd, size):
        raise AssertionError("a replaced file must be rejected before reading bytes")

    with store._cache_directory(tmp_path) as fd:
        monkeypatch.setattr(store, "_cache_open", swapping)
        monkeypatch.setattr(store.os, "read", forbidden)
        with pytest.raises(store.CacheCorrupt, match="changed before read"):
            store._cache_read(fd, "index.json")


def test_cache_read_growth_stops_at_initial_size(tmp_path, monkeypatch):
    path = tmp_path / "index.json"
    path.write_bytes(b"{}")
    read = os.read
    calls = []

    def growing(fd, size):
        calls.append(size)
        assert len(calls) <= 3, "cache read kept chasing appended bytes"
        chunk = read(fd, size)
        with path.open("ab") as stream:
            stream.write(b" " * 1024)
        return chunk

    with store._cache_directory(tmp_path) as fd:
        monkeypatch.setattr(store.os, "read", growing)
        with pytest.raises(store.CacheCorrupt, match="changed during read"):
            store._cache_read(fd, "index.json")


def test_cache_permission_failure_is_fatal_and_preserves_pointer(repo, monkeypatch, capsys):
    repo.commit({"a.py": "def target(): pass\n"})
    lookup(repo.root, "target")
    before = current(repo.root)
    read = store._cache_read

    def denied(fd, name, *args):
        if name == "index.json":
            raise PermissionError("controlled cache denial")
        return read(fd, name, *args)

    monkeypatch.setattr(store, "_cache_read", denied)
    assert main(["find", "target", "--repo", str(repo.root), "--format", "json"]) == 4
    output = capsys.readouterr()
    assert not output.out and "product_state_io_error" in output.err
    assert current(repo.root) == before


@pytest.mark.parametrize("kind", ["fifo", "symlink", "directory"])
def test_invalid_writer_lock_fails_without_blocking_or_following(repo, tmp_path, kind):
    repo.commit({"a.py": "def target(): pass\n"})
    lookup(repo.root, "target")
    lock = state_path(repo.root) / "writer.lock"
    lock.unlink()
    outside = tmp_path / "outside-lock"
    outside.write_text("untouched")
    if kind == "fifo":
        os.mkfifo(lock)
    elif kind == "symlink":
        lock.symlink_to(outside)
    else:
        lock.mkdir()
    result = cli(repo.root, "target", timeout=4)
    assert result.returncode == 4 and not result.stdout
    assert "product_state_io_error" in result.stderr
    assert outside.read_text() == "untouched"
