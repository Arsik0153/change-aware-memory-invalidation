from __future__ import annotations

import errno
import hashlib
import os
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Literal

from cami.errors import IncompleteError, InputError, ResourceError
from cami.models import safe_path
from cami.product.inputs import EXCLUDED_DIRS, ROOT_OUTPUTS, code_input, configuration_inputs
from cami.product.models import Capture, CapturedPath, CapturePolicy, InputEntry, digest
from cami.repository import MAX_FILE_BYTES, Blob, git

LiteralKind = Literal["file", "symlink", "submodule", "special"]


class CaptureChanged(Exception):
    pass


def repository_root(repo: Path) -> Path:
    if not repo.is_dir():
        raise InputError(f"repository directory does not exist: {repo}")
    return Path(os.fsdecode(git(repo, "rev-parse", "--show-toplevel")).strip()).resolve()


def _base_commit(root: Path) -> str | None:
    try:
        return git(root, "rev-parse", "--verify", "--quiet", "HEAD").decode().strip()
    except InputError as exc:
        if str(exc):
            raise
        return None


def _stamp(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _read_file(parent_fd: int, name: str) -> tuple[bytes | None, str, os.stat_result]:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    try:
        return _read_regular(fd, name)
    finally:
        os.close(fd)


def _read_regular(fd: int, name: str) -> tuple[bytes | None, str, os.stat_result]:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise CaptureChanged(f"file type changed: {name}")
    sha = hashlib.sha256()
    chunks: list[bytes] = []
    size = 0
    while size <= before.st_size:
        chunk = os.read(fd, min(128 * 1024, before.st_size - size + 1))
        if not chunk:
            break
        sha.update(chunk)
        size += len(chunk)
        if size <= MAX_FILE_BYTES:
            chunks.append(chunk)
    if _stamp(before) != _stamp(os.fstat(fd)) or size != before.st_size:
        raise CaptureChanged(f"file changed during read: {name}")
    return b"".join(chunks) if size <= MAX_FILE_BYTES else None, sha.hexdigest(), before


def _external_ignore(path: Path) -> tuple[str, str | None]:
    try:
        info = path.stat()
    except FileNotFoundError:
        return str(path), None
    except OSError as exc:
        raise IncompleteError(f"capture_ignore_error: {path}: {exc}") from exc
    if path.resolve() == Path(os.devnull) and stat.S_ISCHR(info.st_mode):
        return str(path), hashlib.sha256(b"").hexdigest()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
        raise IncompleteError(f"capture_ignore_unsupported: {path}: expected regular ignore file "
                              f"of at most {MAX_FILE_BYTES} bytes, or {os.devnull}")
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        if _stamp(info) != _stamp(os.fstat(fd)):
            raise CaptureChanged(f"ignore file replaced: {path}")
        _, sha, _ = _read_regular(fd, str(path))
        if _stamp(info) != _stamp(path.stat()):
            raise CaptureChanged(f"ignore file replaced: {path}")
        return str(path), sha
    finally:
        os.close(fd)


def _within(path: str, prefix: str) -> bool:
    return prefix == "." or path == prefix or path.startswith(prefix + "/")


def _ignored_paths(root: Path, paths: tuple[str, ...]) -> set[str]:
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root),
             "check-ignore", "--no-index", "--stdin", "-z", "-v", "--non-matching"],
            input=b"".join(path.encode() + b"\0" for path in paths), capture_output=True,
            check=False, timeout=60,
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"})
    except FileNotFoundError as exc:
        raise ResourceError("Git is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise IncompleteError("capture_io_error: Git ignore check timed out") from exc
    if result.returncode not in (0, 1) or result.stderr:
        raise IncompleteError("capture_ignore_error: " + result.stderr.decode(errors="replace"))
    ignored = set()
    output = result.stdout.split(b"\0")
    for offset in range(0, len(output) - 1, 4):
        _, _, pattern, raw_path = output[offset:offset + 4]
        if pattern and not pattern.startswith(b"!"):
            ignored.add(raw_path.decode())
    return ignored


def capture(root: Path, source_roots: tuple[str, ...] | None,
            excluded_paths: tuple[str, ...], state_base: Path,
            probe_paths: tuple[str, ...] = ()) -> Capture:
    """Read supported inputs without following worktree symlinks or executing target code."""
    try:
        return _capture(root, source_roots, excluded_paths, state_base, probe_paths)
    except OSError as exc:
        if exc.errno in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.ESTALE):
            raise CaptureChanged(str(exc)) from exc
        raise IncompleteError(f"capture_io_error: {exc}") from exc


def _capture(root: Path, source_roots: tuple[str, ...] | None,
             excluded_paths: tuple[str, ...], state_base: Path,
             probe_paths: tuple[str, ...]) -> Capture:
    roots = tuple(sorted(set(source_roots))) if source_roots is not None else (".",)
    if not roots:
        raise InputError("at least one source root is required")
    for path in (*roots, *excluded_paths, *probe_paths):
        safe_path(path)
    excluded = set(excluded_paths)
    if state_base.is_relative_to(root):
        excluded.add(state_base.relative_to(root).as_posix())
    base_commit = _base_commit(root)
    tracked: set[str] = set()
    submodules: set[str] = set()
    for record in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not record:
            continue
        header, raw_path = record.split(b"\t", 1)
        try:
            path = safe_path(raw_path.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise InputError("Git contains an unsupported path") from exc
        tracked.add(path)
        if header.startswith(b"160000 "):
            submodules.add(path)
    tracked_parents = {parent.as_posix() for path in tracked
                       for parent in PurePosixPath(path).parents}
    default_ignore = (Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
                      / "git" / "ignore")
    excludes_file = git(root, "config", "-z", "--path", "--get", "--default",
                        str(default_ignore), "core.excludesFile").decode().removesuffix("\0")
    global_ignore = Path(excludes_file).expanduser()
    if not global_ignore.is_absolute():
        global_ignore = root / global_ignore
    info_exclude = Path(os.fsdecode(git(root, "rev-parse", "--path-format=absolute",
                                       "--git-path", "info/exclude")).strip())
    ignore_inputs: list[tuple[str, str | None]] = [_external_ignore(info_exclude)]
    if excludes_file:
        ignore_inputs.append(_external_ignore(global_ignore))
    ignore_case = git(root, "config", "--get", "--default", "", "core.ignorecase").decode()
    entries: list[InputEntry] = []
    blobs: list[Blob] = []
    directories: dict[str, set[str]] = {}
    ignored_prefixes: set[str] = set()

    def record_config(fd: int, name: str, path: str) -> bytes | None:
        content, sha, info = _read_file(fd, name)
        limitation = "file_too_large" if content is None else None
        if content is not None and content.startswith(b"version https://git-lfs.github.com/spec/v1"):
            content, limitation = None, "lfs_unsupported"
        mode = format(info.st_mode, "o")
        entries.append(InputEntry(path=path, kind="file", mode=mode, sha256=sha,
                                  size=info.st_size, limitation=limitation))
        blobs.append(Blob(path, sha, mode, content, limitation))
        return content

    def walk(fd: int, prefix: str) -> None:
        before = os.fstat(fd)
        with os.scandir(fd) as scan:
            children = sorted(scan, key=lambda entry: entry.name)
        directories[prefix] = {child.name for child in children}
        candidates: list[tuple[str, os.DirEntry[str]]] = []
        for child in children:
            path = f"{prefix}/{child.name}" if prefix else child.name
            try:
                path.encode("utf-8")
                safe_path(path)
            except (UnicodeEncodeError, ValueError) as exc:
                raise InputError("worktree contains an unsupported path") from exc
            if child.name in EXCLUDED_DIRS or (not prefix and child.name in ROOT_OUTPUTS):
                continue
            if child.name == ".gitignore":
                info = child.stat(follow_symlinks=False)
                if stat.S_ISREG(info.st_mode):
                    if info.st_size > MAX_FILE_BYTES:
                        raise IncompleteError(f"capture_ignore_unsupported: {path}: "
                                              f"ignore file exceeds {MAX_FILE_BYTES} bytes")
                    _, ignore_sha, _ = _read_file(fd, child.name)
                    ignore_inputs.append((path, ignore_sha))
                elif stat.S_ISLNK(info.st_mode):
                    ignore_inputs.append((path, "symlink_not_used_by_git"))
                else:
                    raise IncompleteError(f"capture_ignore_unsupported: {path}: "
                                          "expected regular .gitignore file")
            if any(_within(path, item) for item in excluded):
                continue
            if not any(_within(path, item) or _within(item, path) for item in roots):
                continue
            candidates.append((path, child))
        ignored: set[str] = set()
        if candidates:
            ignored = _ignored_paths(root, tuple(path for path, _ in candidates))
        for path, child in candidates:
            if path in ignored and path not in tracked and path not in tracked_parents:
                ignored_prefixes.add(path)
                continue
            info = child.stat(follow_symlinks=False)
            mode = format(info.st_mode, "o")
            limitation = None
            content = None
            sha: str | None = None
            size = info.st_size
            kind: LiteralKind
            uncertain_input = ((stat.S_ISLNK(info.st_mode) and not path.endswith(".json"))
                               or path in submodules)
            if (not stat.S_ISDIR(info.st_mode) and not code_input(path, roots)
                    and not (uncertain_input and any(_within(path, item) or _within(item, path)
                                                     for item in roots))):
                continue
            if path in submodules:
                kind, limitation, size = "submodule", "submodule_unsupported", 0
            elif stat.S_ISLNK(info.st_mode):
                kind, limitation = "symlink", "symlink_unsupported"
                sha = hashlib.sha256(os.fsencode(os.readlink(child.name, dir_fd=fd))).hexdigest()
                if _stamp(info) != _stamp(os.stat(child.name, dir_fd=fd, follow_symlinks=False)):
                    raise CaptureChanged(f"symlink changed: {path}")
            elif stat.S_ISDIR(info.st_mode):
                nested_fd = os.open(child.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                    dir_fd=fd)
                try:
                    walk(nested_fd, path)
                finally:
                    os.close(nested_fd)
                continue
            elif stat.S_ISREG(info.st_mode):
                kind = "file"
                content, sha, read_info = _read_file(fd, child.name)
                if _stamp(info) != _stamp(read_info):
                    raise CaptureChanged(f"file replaced: {path}")
                if content is None:
                    limitation = "file_too_large"
                elif content.startswith(b"version https://git-lfs.github.com/spec/v1"):
                    content, limitation = None, "lfs_unsupported"
            else:
                kind, limitation, size = "special", "special_file_unsupported", 0
            entries.append(InputEntry(path=path, kind=kind, mode=mode, sha256=sha,
                                      size=size, limitation=limitation))
            blobs.append(Blob(path, sha or digest([path, kind, mode]), mode, content, limitation))
        if _stamp(before) != _stamp(os.fstat(fd)):
            raise CaptureChanged(f"directory changed during traversal: {prefix or '.'}")

    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        walk(root_fd, "")

        def metadata_parent(path: str) -> int:
            parent_fd = os.dup(root_fd)
            try:
                for part in path.split("/")[:-1]:
                    child_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                       dir_fd=parent_fd)
                    os.close(parent_fd)
                    parent_fd = child_fd
                return parent_fd
            except OSError:
                os.close(parent_fd)
                raise

        def metadata_exists(path: str) -> bool:
            try:
                parent_fd = metadata_parent(path)
            except (FileNotFoundError, NotADirectoryError):
                return False
            try:
                os.stat(path.rsplit("/", 1)[-1], dir_fd=parent_fd, follow_symlinks=False)
                return True
            except FileNotFoundError:
                return False
            finally:
                os.close(parent_fd)

        def read_config(path: str) -> bytes | None:
            parent_fd = metadata_parent(path)
            name = path.rsplit("/", 1)[-1]
            try:
                info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    limitation = "symlink_unsupported" if stat.S_ISLNK(info.st_mode) else "special_file_unsupported"
                    entries.append(InputEntry(path=path, kind="symlink" if stat.S_ISLNK(info.st_mode)
                                              else "special", mode=format(info.st_mode, "o"),
                                              sha256=None, size=info.st_size, limitation=limitation))
                    blobs.append(Blob(path, digest([path, limitation]), "", None, limitation))
                    return None
                return record_config(parent_fd, name, path)
            finally:
                os.close(parent_fd)

        configuration_inputs((blob.path for blob in blobs), metadata_exists, read_config)
    finally:
        os.close(root_fd)
    entries.sort(key=lambda item: item.path)
    blobs.sort(key=lambda blob: blob.path)
    if source_roots is None and any(blob.path.startswith("src/") and blob.path.endswith(".py")
                                    for blob in blobs):
        roots = ("src", ".")
    policy = CapturePolicy(source_roots=roots, excluded_paths=tuple(sorted(excluded)),
                           excluded_dirs=EXCLUDED_DIRS, root_outputs=ROOT_OUTPUTS,
                           ignore_fingerprint=digest([sorted(ignore_inputs), ignore_case]))
    coverage: list[CapturedPath] = []
    present = {entry.path for entry in entries if entry.kind == "file" and not entry.limitation}
    ignored_probes = _ignored_paths(root, tuple(sorted(set(probe_paths)))) if probe_paths else set()
    for path in sorted(set(probe_paths)):
        parts = PurePosixPath(path).parts
        status: Literal["present", "absent", "excluded", "ignored", "unavailable"]
        if (not code_input(path, roots)
                or any(_within(path, item) for item in excluded)
                or any(part in EXCLUDED_DIRS for part in parts)
                or parts[0] in ROOT_OUTPUTS):
            status = "excluded"
        elif (any(_within(path, item) for item in ignored_prefixes)
              or (path in ignored_probes and path not in tracked)):
            status = "ignored"
        elif path in present:
            status = "present"
        else:
            status = "unavailable"
            for offset, part in enumerate(parts):
                parent = "/".join(parts[:offset])
                if parent in directories and part not in directories[parent]:
                    status = "absent"
                    break
        coverage.append(CapturedPath(path=path, status=status))
    identity: dict[str, object] = {
        "policy": policy.model_dump(mode="json"),
        "entries": [entry.model_dump(mode="json") for entry in entries]}
    if coverage:
        identity["path_coverage"] = [item.model_dump(mode="json") for item in coverage]
    snapshot_id = digest(identity)
    return Capture(snapshot_id, base_commit, policy, tuple(entries), tuple(blobs), tuple(coverage))
