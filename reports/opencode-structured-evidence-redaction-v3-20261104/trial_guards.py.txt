"""Metadata-only guards for explicitly owned, freshly constructed trial inputs."""
from __future__ import annotations

import os
import shutil
import subprocess


def git_closure(workspace):
    gitdir = workspace / ".git"
    if not gitdir.is_dir() or gitdir.is_symlink() or any(p.is_symlink() for p in gitdir.rglob("*")):
        raise ValueError("trial requires an ordinary fresh .git without symlinks")
    for name in ["objects/info/alternates", "info/grafts", "commondir", "shallow"]:
        if (gitdir / name).exists():
            raise ValueError("alternate/partial/worktree Git state is outside fresh trial closure")
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    def git(*args):
        result = subprocess.run(["git", "--no-replace-objects", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "safe.directory=" + str(workspace), "-c", "protocol.allow=never", "-C", str(workspace), *args],
            env=env, capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise ValueError("fresh Git metadata guard failed")
        return result.stdout.splitlines()
    commits = git("rev-list", "--all")
    refs = git("for-each-ref", "--format=%(refname)")
    if len(commits) != 1 or len(refs) != 1 or not refs[0].startswith("refs/heads/") or git("remote"):
        raise ValueError("trial must contain exactly one initial commit/ref and no remotes")
    head = git("rev-parse", "--verify", "HEAD^{commit}")[0]
    if commits != [head] or len(git("rev-list", "--parents", "-n", "1", head)[0].split()) != 1:
        raise ValueError("trial HEAD must be the sole parentless initial commit")
    local = {line.split()[0] for line in git("cat-file", "--batch-all-objects", "--batch-check=%(objectname)")}
    reachable = {line.split()[0] for line in git("rev-list", "--objects", "--all")}
    if local != reachable:
        raise ValueError("unreachable/extra Git objects may expose upstream or future history")
    return {"policy": "fresh_single_initial_commit_no_remotes_extra_refs_unreachable_objects", "HEAD": head,
            "commits": 1, "refs": refs, "local_objects": len(local), "reachable_objects": len(reachable),
            "construction_requirement": "Caller recreates Git metadata from canonical source each stage; task may commit afterward. No upstream .git copied."}


def storage_snapshot(paths):
    return {"free_bytes": shutil.disk_usage(paths[0]).free, "owned_path_bytes": {
        str(path): sum(p.stat().st_size for p in path.rglob("*") if not p.is_symlink() and p.is_file()) if path.exists() else 0 for path in paths},
        "enforcement": "phase observations only; no hard aggregate writable-storage quota"}
