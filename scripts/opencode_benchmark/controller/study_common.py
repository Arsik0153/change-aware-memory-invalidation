"""Shared strict file boundaries, command evidence, and immutable records."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import time

ARMS = ("plain", "static", "cami")
DOCKER = ["docker", "--host=unix:///var/run/docker.sock"]


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    with Path(path).open("x") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def contained(root, relative):
    rel = Path(relative)
    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
        raise ValueError("unsafe relative path")
    path = root / rel
    if any(p.is_symlink() for p in [path, *path.parents] if p.is_relative_to(root)):
        raise ValueError("symlink in sealed path")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("path escapes root")
    return path


def inventory(root, *, omit_git=False, max_bytes=None, max_files=None):
    """Never follow links or read special files, including agent-created paths."""
    result = {}
    seen_bytes = 0
    if root.is_symlink() or not root.is_dir():
        raise ValueError("ordinary directory required")
    for directory, dirs, files in os.walk(root, followlinks=False):
        if omit_git and Path(directory) == root:
            dirs[:] = [d for d in dirs if d != ".git"]
            files = [f for f in files if f != ".git"]
        for name in dirs + files:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ValueError("nonregular candidate/asset: " + str(path.relative_to(root)))
            seen_bytes += path.stat().st_size
            if (max_bytes is not None and seen_bytes > max_bytes) or (
                max_files is not None and len(result) >= max_files
            ):
                raise ValueError("file inventory exceeds explicit byte/count bounds")
            result[path.relative_to(root).as_posix()] = {
                "sha256": digest(path),
                "bytes": path.stat().st_size,
                "mode": stat.S_IMODE(mode),
            }
    return dict(sorted(result.items()))


def file_hashes(root):
    return {name: row["sha256"] for name, row in inventory(root).items()}


def verify_files(root, expected):
    for name, expected_sha in expected.items():
        path = contained(root, name)
        if not path.is_file() or digest(path) != expected_sha:
            raise ValueError("sealed file mismatch: " + name)


def command(argv, *, cwd=None, env=None, timeout=60):
    """Always preserve bounded timeout output; no retry or shell interpretation."""
    start = time.monotonic()
    environment = dict(os.environ if env is None else env)
    for key in [
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ]:
        environment.pop(key, None)
    child = subprocess.Popen(
        [str(x) for x in argv],
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    expired = False
    try:
        stdout, stderr = child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        expired = True
        os.killpg(child.pid, signal.SIGKILL)
        stdout, stderr = child.communicate()
    return {
        "argv": [str(x) for x in argv],
        "returncode": child.returncode,
        "timeout": expired,
        "wall_seconds": time.monotonic() - start,
        "stdout": stdout.decode(errors="replace"),
        "stderr": stderr.decode(errors="replace"),
    }


def require_success(result):
    if result["returncode"] or result["timeout"]:
        raise RuntimeError("bounded command failed; see preserved command evidence")
    return result


def bytes_used(root):
    return sum(row["bytes"] for row in inventory(root).values())


def chown(root):
    for directory, dirs, files in os.walk(root, followlinks=False):
        os.chown(directory, 65534, 65534, follow_symlinks=False)
        for name in dirs + files:
            os.chown(Path(directory) / name, 65534, 65534, follow_symlinks=False)
