from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from cami.errors import InputError, ResourceError
from cami.models import RepoLocation, safe_path

MAX_FILE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Blob:
    path: str
    object_id: str
    mode: str
    content: bytes | None
    limitation: str | None

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content or b"").hexdigest()


@dataclass(frozen=True)
class Snapshot:
    repo_id: str
    revision: str
    blobs: tuple[Blob, ...]

    def by_path(self) -> dict[str, Blob]:
        return {blob.path: blob for blob in self.blobs}


def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(
            ["git", "--no-replace-objects", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(repo), *args],
            capture_output=True, check=False, timeout=60, input=input_bytes,
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"},
        )
    except FileNotFoundError as exc:
        raise ResourceError("Git is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise ResourceError("Git command timed out") from exc
    if result.returncode:
        raise InputError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def resolve(repo: Path, revision: str) -> str:
    if revision.startswith("-") or "\x00" in revision:
        raise InputError("invalid Git revision")
    return git(repo, "rev-parse", "--verify", "--end-of-options", revision + "^{commit}").decode().strip()


def chain(repo: Path, parent: str, children: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    base = resolve(repo, parent)
    revisions = tuple(resolve(repo, child) for child in children)
    previous = base
    for revision in revisions:
        parents = git(repo, "rev-list", "--parents", "-n", "1", revision).decode().split()[1:]
        if parents != [previous]:
            raise InputError(f"{revision} must have exactly one parent, {previous}")
        previous = revision
    return base, revisions


def read_snapshot(repo: RepoLocation, revision: str, *,
                  max_file_bytes: int = MAX_FILE_BYTES) -> Snapshot:
    if max_file_bytes < 1:
        raise InputError("max_file_bytes must be positive")
    root = Path(repo.path)
    oid = resolve(root, revision)
    entries: list[tuple[str, str, str, str | None]] = []
    readable: set[str] = set()
    for entry in git(root, "ls-tree", "-rzl", "--full-tree", oid).split(b"\x00"):
        if not entry:
            continue
        info, raw_path = entry.split(b"\t", 1)
        try:
            path = safe_path(raw_path.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise InputError("Git contains an unsupported path") from exc
        mode, kind, blob_id, size = info.decode().split()
        limitation = None
        if kind == "commit":
            limitation = "submodule_unsupported"
        elif mode == "120000":
            limitation = "symlink_unsupported"
        elif int(size) > max_file_bytes:
            limitation = "file_too_large"
        else:
            readable.add(blob_id)
        entries.append((path, blob_id, mode, limitation))
    content_by_id: dict[str, bytes] = {}
    if readable:
        batch = git(root, "cat-file", "--batch", input_bytes=("\n".join(sorted(readable)) + "\n").encode())
        offset = 0
        for expected in sorted(readable):
            end = batch.index(b"\n", offset)
            header = batch[offset:end].decode().split()
            if len(header) != 3 or header[0] != expected or header[1] != "blob":
                raise ResourceError(f"Git blob unavailable offline: {expected}")
            blob_size = int(header[2])
            content_by_id[expected] = batch[end+1:end+1+blob_size]
            offset = end + blob_size + 2
    blobs: list[Blob] = []
    for path, blob_id, mode, limitation in entries:
        content = content_by_id.get(blob_id)
        if content is not None and content.startswith(b"version https://git-lfs.github.com/spec/v1"):
            limitation, content = "lfs_unsupported", None
        blobs.append(Blob(path, blob_id, mode, content, limitation))
    return Snapshot(repo.repo_id, oid, tuple(blobs))


def changed_files(before: Snapshot, after: Snapshot) -> frozenset[str]:
    left, right = before.by_path(), after.by_path()
    return frozenset(path for path in left.keys() | right.keys()
                     if path not in left or path not in right
                     or (left[path].object_id, left[path].mode) != (right[path].object_id, right[path].mode))


def materialize(snapshot: Snapshot, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for blob in snapshot.blobs:
        if blob.limitation:
            raise ResourceError(f"cannot materialize {blob.path}: {blob.limitation}")
        path = destination / blob.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob.content or b"")
        path.chmod(0o555 if blob.mode == "100755" else 0o444)
