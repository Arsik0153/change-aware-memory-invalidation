"""Owned canonical source resets and Git-independent source patch export."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tarfile
import time
import uuid

from study_common import command, digest, inventory, read, require_success, write


def extract(archive, target):
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as stream:
        names = set()
        for member in stream.getmembers():
            rel = Path(member.name)
            if (
                rel.is_absolute()
                or ".." in rel.parts
                or ".git" in rel.parts
                or not (member.isfile() or member.isdir())
                or member.name in names
            ):
                raise ValueError("archive contains unsafe/nonregular/history/duplicate entry")
            names.add(member.name)
        stream.extractall(target, filter="data")
    inventory(target)


def create_namespace(path, study_sha):
    path.mkdir(parents=True, exist_ok=False)
    workspace, memory = path / "workspace", path / "memory"
    workspace.mkdir()
    memory.mkdir()
    info = workspace.stat()
    write(
        path / "identity.json",
        {
            "study_sha256": study_sha,
            "id": str(uuid.uuid4()),
            "workspace": str(workspace.resolve()),
            "device": info.st_dev,
            "inode": info.st_ino,
        },
    )
    return path


def verify_namespace(path, study_sha):
    identity = read(path / "identity.json")
    workspace, memory = path / "workspace", path / "memory"
    info = workspace.lstat()
    if (
        workspace.is_symlink()
        or memory.is_symlink()
        or not memory.is_dir()
        or identity["study_sha256"] != study_sha
        or identity["workspace"] != str(workspace.resolve())
        or identity["device"] != info.st_dev
        or identity["inode"] != info.st_ino
    ):
        raise ValueError("workspace/memory namespace identity mismatch")
    return workspace, memory


def reset(namespace, archive, expected_sha, study_sha):
    start = time.monotonic()
    workspace, _ = verify_namespace(namespace, study_sha)
    if digest(archive) != expected_sha:
        raise ValueError("canonical archive changed")
    for entry in workspace.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    extract(archive, workspace)
    before = inventory(workspace)
    env = dict(
        os.environ,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_AUTHOR_NAME="Canonical study source",
        GIT_AUTHOR_EMAIL="study@invalid",
        GIT_COMMITTER_NAME="Canonical study source",
        GIT_COMMITTER_EMAIL="study@invalid",
        GIT_AUTHOR_DATE="2000-01-01T00:00:00+0000",
        GIT_COMMITTER_DATE="2000-01-01T00:00:00+0000",
    )
    for name in list(env):
        if name.startswith("GIT_") and name not in {
            "GIT_CONFIG_NOSYSTEM",
            "GIT_CONFIG_GLOBAL",
            "GIT_AUTHOR_NAME",
            "GIT_AUTHOR_EMAIL",
            "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL",
            "GIT_AUTHOR_DATE",
            "GIT_COMMITTER_DATE",
        }:
            del env[name]
    logs = []
    for args in [
        ["init", "--quiet", "--template=", "--initial-branch=canonical"],
        ["config", "core.hooksPath", "/dev/null"],
        ["add", "--force", "--all"],
        ["commit", "--quiet", "--no-gpg-sign", "-m", "Canonical source only"],
        ["rev-list", "--all"],
        ["remote"],
        ["fsck", "--no-reflogs", "--unreachable"],
    ]:
        item = command(
            ["git", "-c", "safe.directory=" + str(workspace), "-C", workspace, *args], env=env
        )
        logs.append(item)
        require_success(item)
    if (
        len(logs[-3]["stdout"].splitlines()) != 1
        or logs[-2]["stdout"].strip()
        or logs[-1]["stdout"].strip()
    ):
        raise ValueError("canonical repository contains unexpected history/remotes/objects")
    if inventory(workspace, omit_git=True) != before:
        raise ValueError("Git initialization changed canonical source")
    return {
        "archive_sha256": expected_sha,
        "canonical_files": before,
        "git_commands": logs,
        "wall_seconds": time.monotonic() - start,
        "upstream_history_exposed": False,
        "single_commit": logs[-3]["stdout"].strip(),
    }


def capture(workspace, canonical, out):
    """Snapshot src/** using actual bytes even if the agent committed or deleted Git."""
    out.mkdir(parents=True, exist_ok=False)
    source = workspace / "src"
    current = inventory(source, max_bytes=64 * 1024 * 1024, max_files=10000)
    if any((source / name).stat().st_nlink != 1 for name in current):
        raise ValueError("hardlinked source is not admitted")
    if sum(row["bytes"] for row in current.values()) > 64 * 1024 * 1024 or len(current) > 10000:
        raise ValueError("candidate source exceeds fixed export safety bound")
    initial = {name[4:]: row for name, row in canonical.items() if name.startswith("src/")}
    added = sorted(set(current) - set(initial))
    deleted = sorted(set(initial) - set(current))
    changed = sorted(
        name for name in current.keys() & initial.keys() if current[name] != initial[name]
    )
    shutil.copytree(source, out / "src")
    if inventory(out / "src") != current:
        raise ValueError("candidate changed during source export")
    # Non-source modifications are recorded independently of Git. They never enter grading.
    all_files = inventory(workspace, omit_git=True)
    outside = sorted(
        name
        for name in set(all_files) | set(canonical)
        if not name.startswith("src/") and all_files.get(name) != canonical.get(name)
    )
    record = {
        "source_files": current,
        "added": added,
        "deleted": deleted,
        "changed": changed,
        "outside_source_changes": outside,
        "workspace_files_excluding_git": all_files,
        "workspace_logical_bytes_excluding_git": sum(row["bytes"] for row in all_files.values()),
        "agent_test_changes_admitted": False,
        "captured_from_git": False,
        "source_scope": "regular files src/**",
    }
    write(out / "source-patch.json", record)
    return record


def evaluation_workspace(bundle, task, candidate, out):
    target = out / "workspace"
    extract(bundle / task["archive"], target)
    shutil.rmtree(target / "src")
    shutil.copytree(candidate / "src", target / "src")
    if task["replace_regression_tests"]:
        tests = target / task["regression"]
        if tests.exists():
            shutil.rmtree(tests)
        shutil.copytree(bundle / task["replace_regression_tests"], tests)
    else:
        # Copy fixed acceptance directory plus its original conftest, never agent tests.
        dest = target / task["oracle_root"]
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(bundle / task["oracle_root"], dest)
    inventory(target)
    return target
