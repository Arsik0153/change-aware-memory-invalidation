from __future__ import annotations

import fcntl
import hmac
import os
import secrets
import socket
import stat
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal


from cami.errors import IncompleteError, InputError
from cami.product.store import CacheCorrupt, _cache_directory, _cache_read, _sync_directory, worktree_key
from cami.product.watch.models import Request, Response, Session, Value, WatchStatus

CONTROL_SECONDS = 1.0
STOP_SECONDS = 10.0
MAX_REQUEST = 4096
MAX_RESPONSE = 65536


def now() -> str:
    return datetime.now(UTC).isoformat()


class WatchControlError(IncompleteError):
    pass


class LeaseIdentity(Value):
    directory_device: int
    directory_inode: int
    lease_device: int
    lease_inode: int


def _private_directory(fd: int) -> None:
    info = os.fstat(fd)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077):
        raise WatchControlError("watch_lock_integrity_error: expected private owned directory")


def _atomic(directory: Path, name: str, raw: bytes) -> None:
    temporary = directory / (".pending-" + secrets.token_hex(16))
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / name)
        _sync_directory(directory)
    finally:
        temporary.unlink(missing_ok=True)


def locate(repo: Path) -> tuple[Path, Path]:
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(repo),
             "rev-parse", "--show-toplevel", "--absolute-git-dir"],
            capture_output=True, timeout=CONTROL_SECONDS,
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WatchControlError(f"watch_repository_unavailable: {exc}") from exc
    lines = os.fsdecode(result.stdout).splitlines()
    if result.returncode or len(lines) != 2:
        raise InputError("watch requires a Git worktree")
    return Path(lines[0]).resolve(), Path(lines[1]).resolve() / "cami-watch"


def endpoint(session_id: str) -> Path:
    return Path("/tmp") / f"cami-watch-{os.geteuid()}" / (session_id + ".sock")


def prepare_endpoint(session_id: str) -> Path:
    path = endpoint(session_id)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    with _cache_directory(path.parent) as fd:
        _private_directory(fd)
    return path


@dataclass
class Lease:
    root: Path
    directory: Path
    directory_fd: int
    fd: int
    identity: LeaseIdentity
    held: bool = False

    @classmethod
    def open(cls, repo: Path, *, create: bool = False) -> Lease | None:
        root, directory = locate(repo)
        created = False
        if create:
            try:
                directory.mkdir(mode=0o700)
                created = True
            except FileExistsError:
                pass
        try:
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except FileNotFoundError:
            if create:
                raise WatchControlError("watch_lock_integrity_error: lease directory disappeared")
            return None
        fd = None
        try:
            _private_directory(directory_fd)
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
            if created:
                flags |= os.O_CREAT | os.O_EXCL
            fd = os.open("lease", flags, 0o600, dir_fd=directory_fd)
            info, parent = os.fstat(fd), os.fstat(directory_fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077 or info.st_size != 0 or info.st_nlink != 1):
                raise WatchControlError("watch_lock_integrity_error: invalid lifetime lease")
            actual = LeaseIdentity(directory_device=parent.st_dev, directory_inode=parent.st_ino,
                                   lease_device=info.st_dev, lease_inode=info.st_ino)
            if created:
                os.fsync(fd)
                _atomic(directory, "identity.json", actual.model_dump_json().encode())
                _sync_directory(directory.parent)
            identity = LeaseIdentity.model_validate_json(_cache_read(directory_fd, "identity.json", 4096))
            lease = cls(root, directory, directory_fd, fd, identity)
            lease.verify()
            return lease
        except BaseException:
            if fd is not None:
                os.close(fd)
            os.close(directory_fd)
            raise

    def verify(self) -> None:
        parent = os.stat(self.directory, follow_symlinks=False)
        held_parent = os.fstat(self.directory_fd)
        linked = os.stat("lease", dir_fd=self.directory_fd, follow_symlinks=False)
        held = os.fstat(self.fd)
        for info in (parent, held_parent):
            if (info.st_dev, info.st_ino) != (self.identity.directory_device,
                                             self.identity.directory_inode):
                raise WatchControlError("watch_lock_integrity_error: lease directory replaced")
        _private_directory(self.directory_fd)
        for info in (linked, held):
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077 or info.st_size or info.st_nlink != 1
                    or (info.st_dev, info.st_ino) != (self.identity.lease_device,
                                                    self.identity.lease_inode)):
                raise WatchControlError("watch_lock_integrity_error: lifetime lease damaged")
        identity = LeaseIdentity.model_validate_json(_cache_read(self.directory_fd, "identity.json", 4096))
        if identity != self.identity:
            raise WatchControlError("watch_lock_integrity_error: lifetime identity changed")

    def acquire(self) -> bool:
        self.verify()
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        self.held = True
        self.verify()
        return True

    def occupied(self) -> bool:
        self.verify()
        if self.held:
            return True
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        return False

    def session(self) -> Session:
        self.verify()
        session = Session.model_validate_json(_cache_read(self.directory_fd, "session.json", 16384))
        if (session.worktree_key != worktree_key(self.root)
                or session.settings.canonical_repo != str(self.root)
                or session.endpoint != str(endpoint(session.session_id))):
            raise WatchControlError("watch_session_mismatch: invalid discovery identity")
        info = os.stat("session.json", dir_fd=self.directory_fd, follow_symlinks=False)
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise WatchControlError("watch_session_mismatch: discovery is not private")
        return session

    def publish(self, session: Session) -> None:
        self.verify()
        _atomic(self.directory, "session.json", session.model_dump_json().encode())

    def close(self) -> None:
        os.close(self.fd)
        os.close(self.directory_fd)


def receive(stream: socket.socket, limit: int, deadline: float) -> bytes:
    chunks = bytearray()
    while len(chunks) <= limit:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise WatchControlError("watch_control_timeout: response deadline exceeded")
        stream.settimeout(remaining)
        chunk = stream.recv(min(4096, limit + 1 - len(chunks)))
        if not chunk:
            raise WatchControlError("watch_control_error: incomplete message")
        chunks.extend(chunk)
        if b"\n" in chunks:
            if not chunks.endswith(b"\n") or chunks.count(b"\n") != 1 or len(chunks) > limit:
                raise WatchControlError("watch_control_error: invalid message framing")
            return bytes(chunks[:-1])
    raise WatchControlError("watch_control_error: oversized message")


def request(lease: Lease, session: Session, action: Literal["status", "stop"]) -> WatchStatus:
    deadline = time.monotonic() + CONTROL_SECONDS
    path = Path(session.endpoint)
    with _cache_directory(path.parent) as fd:
        _private_directory(fd)
        info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
    if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077
            or (info.st_dev, info.st_ino) != (session.endpoint_device, session.endpoint_inode)):
        raise WatchControlError("watch_endpoint_invalid: expected private owned socket")
    message = Request(session_id=session.session_id, capability=session.capability,
                      nonce=secrets.token_hex(16), action=action)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(max(0.001, deadline - time.monotonic()))
        stream.connect(session.endpoint)
        stream.sendall(message.model_dump_json().encode() + b"\n")
        response = Response.model_validate_json(receive(stream, MAX_RESPONSE, deadline))
    if (response.session_id != session.session_id or response.nonce != message.nonce
            or response.status.session_id != session.session_id
            or response.status.worktree_key != session.worktree_key
            or response.status.settings != session.settings
            or response.status.ownership != "lease_and_session_verified"
            or response.status.lifecycle not in ("starting", "running", "stopping")
            or lease.session() != session or (not lease.occupied() and action != "stop")):
        raise WatchControlError("watch_session_mismatch: control response does not match occupied lease")
    return response.status


def authenticated(message: Request, session: Session) -> bool:
    return (message.session_id == session.session_id
            and hmac.compare_digest(message.capability, session.capability))


def inspect(repo: Path, *, stop: bool = False) -> WatchStatus:
    root, _ = locate(repo)
    lease = None
    try:
        lease = Lease.open(root)
        if lease is None or not lease.occupied():
            return WatchStatus(lifecycle="stopped", phase="stopped", reason="lease_free",
                               ownership="lease_free", retrieved_at=now(), worktree_key=worktree_key(root))
        session = lease.session()
        result = request(lease, session, "stop" if stop else "status")
        if not stop:
            return result
        deadline = time.monotonic() + STOP_SECONDS
        while time.monotonic() < deadline:
            if not lease.occupied():
                return result.model_copy(update={"lifecycle": "stopped", "phase": "stopped",
                                                "ownership": "lease_free", "reason": "session_stopped",
                                                "data_freshness": "unknown", "retrieved_at": now()})
            if lease.session() != session:
                raise WatchControlError("watch_session_mismatch: session changed while stopping")
            time.sleep(0.05)
        raise WatchControlError("watch_stop_timeout: matched session has not released its lease")
    except (OSError, ValueError, CacheCorrupt, WatchControlError) as exc:
        return WatchStatus(lifecycle="unknown", reason=str(exc)[:2000], ownership="unknown",
                           retrieved_at=now(), worktree_key=worktree_key(root))
    finally:
        if lease is not None:
            lease.close()
