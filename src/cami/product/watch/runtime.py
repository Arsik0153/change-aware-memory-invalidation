from __future__ import annotations

import os
import secrets
import selectors
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FrameType
from typing import BinaryIO, Literal

from cami.product.store import CacheCorrupt, worktree_key
from cami.product.watch.control import (
    MAX_REQUEST, MAX_RESPONSE, Lease, WatchControlError, authenticated, now, prepare_endpoint,
)
from cami.product.watch.models import (
    OperationResult, Request, Response, Session, WatchError, WatchEvent, WatchSettings, WatchStatus,
)


@dataclass
class Operation:
    process: subprocess.Popen[bytes]
    action: Literal["observe", "refresh"]
    output: BinaryIO
    errors: BinaryIO
    started: float
    cancelled: bool = False

    @classmethod
    def start(cls, settings: WatchSettings, action: Literal["observe", "refresh"],
              lease_fd: int | None = None) -> Operation:
        output = tempfile.TemporaryFile()
        errors = None
        process = None
        try:
            errors = tempfile.TemporaryFile()
            process = subprocess.Popen(
                [sys.executable, "-m", "cami.product.watch.worker", action], stdin=subprocess.PIPE,
                stdout=output, stderr=errors, close_fds=True,
                pass_fds=() if lease_fd is None else (lease_fd,))
            assert process.stdin is not None
            process.stdin.write(settings.model_dump_json().encode())
            process.stdin.close()
            return cls(process, action, output, errors, time.monotonic())
        except BaseException as exc:
            if process is not None:
                try:
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                except BaseException as cleanup_error:
                    exc.add_note(f"owned worker cleanup failed: {cleanup_error}")
            for stream in (None if process is None else process.stdin, output, errors):
                if stream is not None:
                    try:
                        stream.close()
                    except BaseException as cleanup_error:
                        exc.add_note(f"worker stream cleanup failed: {cleanup_error}")
            raise

    def cancel(self) -> None:
        if not self.cancelled and self.process.poll() is None:
            self.cancelled = True
            self.process.terminate()

    def finish(self) -> OperationResult:
        self.process.wait()
        try:
            self.output.seek(0)
            raw = self.output.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE or self.process.returncode:
                self.errors.seek(0)
                raise WatchControlError("watch_operation_failed: "
                                        + self.errors.read(1800).decode(errors="replace"))
            result = OperationResult.model_validate_json(raw)
            if (result.action != self.action
                    or sum(value is not None for value in
                           (result.observation, result.success, result.error)) != 1
                    or (result.observation is not None and self.action != "observe")
                    or (result.success is not None and self.action != "refresh")):
                raise WatchControlError("watch_operation_failed: invalid result")
            return result
        finally:
            self.output.close()
            self.errors.close()


@dataclass
class Client:
    data: bytearray
    deadline: float


@dataclass(frozen=True)
class BoundEndpoint:
    path: Path
    device: int
    inode: int

    @classmethod
    def bind(cls, server: socket.socket, path: Path) -> BoundEndpoint:
        server.bind(str(path))
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
            raise WatchControlError("watch_endpoint_invalid: bound endpoint unverifiable")
        return cls(path, info.st_dev, info.st_ino)

    def matches(self) -> bool:
        info = self.path.lstat()
        return (stat.S_ISSOCK(info.st_mode) and info.st_uid == os.geteuid()
                and (info.st_dev, info.st_ino) == (self.device, self.inode))

    def unlink(self) -> None:
        try:
            if self.matches():
                self.path.unlink()
        except FileNotFoundError:
            pass


class Watcher:
    def __init__(self, lease: Lease, settings: WatchSettings, output_format: str):
        self.lease, self.settings, self.output_format = lease, settings, output_format
        session_id = secrets.token_hex(16)
        self.endpoint = prepare_endpoint(session_id)
        self.selector = selectors.DefaultSelector()
        self.clients: dict[socket.socket, Client] = {}
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        bound: BoundEndpoint | None = None
        try:
            bound = BoundEndpoint.bind(self.server, self.endpoint)
            self.bound_endpoint = bound
            os.chmod(self.endpoint, 0o600)
            self.session = Session(
                session_id=session_id, capability=secrets.token_hex(32), endpoint=str(self.endpoint),
                endpoint_device=bound.device, endpoint_inode=bound.inode,
                worktree_key=worktree_key(lease.root), settings=settings, pid_hint=os.getpid())
            self.server.listen(16)
            self.server.setblocking(False)
            self.selector.register(self.server, selectors.EVENT_READ)
            self.lease.publish(self.session)
        except BaseException as exc:
            try:
                if bound is not None:
                    bound.unlink()
            except OSError as cleanup_error:
                exc.add_note(f"watch endpoint cleanup failed: {cleanup_error}")
            finally:
                self.server.close()
                self.selector.close()
            raise
        self.status = WatchStatus(
            lifecycle="starting", reason="initial_refresh", ownership="lease_and_session_verified",
            retrieved_at=now(), session_id=session_id, pid_hint=os.getpid(),
            worktree_key=self.session.worktree_key, settings=settings, phase="starting")
        self.operation: Operation | None = None
        self.next_action: Literal["observe", "refresh"] = "refresh"
        self.next_at = time.monotonic()
        self.pending_key: str | None = None
        self.pending_first = 0.0
        self.pending_last = 0.0
        self.failures = 0
        self.stopping = False
        self.failed = False
        self.old_signals: dict[int, Callable[[int, FrameType | None], object] | int | None] = {}

    def emit(self, event: Literal["started", "refresh_started", "refreshed", "pending", "error", "stopping", "stopped"],
             reason: str) -> None:
        value = WatchEvent(event=event, timestamp=now(), session_id=self.session.session_id,
                           reason=reason, success=self.status.latest_successful if event == "refreshed"
                           else None, error=self.status.last_error if event == "error" else None)
        if self.output_format == "json":
            raw = value.model_dump_json().encode() + b"\n"
        else:
            details = (f" (generation {value.success.memory_generation_id[:12]})" if value.success else
                       f": {value.error.message}" if value.error else "")
            raw = f"cami watch {event}: {reason}{details}\n".encode()
        try:
            os.write(sys.stdout.fileno(), raw)
        except (BlockingIOError, BrokenPipeError):
            pass

    def stop(self, reason: str) -> None:
        if self.stopping:
            return
        self.stopping = True
        self.status = self.status.model_copy(update={"lifecycle": "stopping", "phase": "stopping",
                                                    "reason": reason, "data_freshness": "unknown"})
        if self.operation is not None:
            self.operation.cancel()
        self.emit("stopping", reason)

    def _signal(self, signum: int, frame: object) -> None:
        self.stop("signal_received")

    def _drop(self, client: socket.socket) -> None:
        self.selector.unregister(client)
        self.clients.pop(client, None)
        client.close()

    def control(self) -> None:
        for key, _ in self.selector.select(0.05):
            stream = key.fileobj
            assert isinstance(stream, socket.socket)
            if stream is self.server:
                client, _ = self.server.accept()
                client.setblocking(False)
                if len(self.clients) >= 16:
                    client.close()
                    continue
                self.clients[client] = Client(bytearray(), time.monotonic() + 1.0)
                self.selector.register(client, selectors.EVENT_READ)
                continue
            client_state = self.clients[stream]
            try:
                raw = stream.recv(MAX_REQUEST + 1 - len(client_state.data))
                client_state.data.extend(raw)
                if not raw or len(client_state.data) > MAX_REQUEST:
                    self._drop(stream)
                    continue
                if b"\n" not in client_state.data:
                    continue
                if (not client_state.data.endswith(b"\n") or client_state.data.count(b"\n") != 1):
                    self._drop(stream)
                    continue
                message = Request.model_validate_json(client_state.data[:-1])
                if not authenticated(message, self.session):
                    self._drop(stream)
                    continue
                self.verify()
                if message.action == "stop":
                    self.stop("cooperative_stop")
                response = Response(session_id=self.session.session_id, nonce=message.nonce,
                                    status=self.status.model_copy(update={"retrieved_at": now()}))
                stream.send(response.model_dump_json().encode() + b"\n")
                self._drop(stream)
            except (OSError, ValueError, CacheCorrupt, WatchControlError):
                if stream in self.clients:
                    self._drop(stream)
        for client, state in tuple(self.clients.items()):
            if time.monotonic() >= state.deadline:
                self._drop(client)

    def verify(self) -> None:
        self.lease.verify()
        if self.lease.session() != self.session:
            raise WatchControlError("watch_session_mismatch: active discovery changed")
        if not self.bound_endpoint.matches():
            raise WatchControlError("watch_endpoint_invalid: active endpoint replaced")

    def error(self, error: WatchError) -> None:
        self.pending_key = None
        self.failures += 1
        delay = min(10.0, 0.5 * 2 ** min(self.failures - 1, 5))
        self.next_at = time.monotonic() + delay
        self.next_action = "refresh"
        error = error.model_copy(update={"retry_at": (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()})
        self.status = self.status.model_copy(update={"last_error": error, "phase": "retry_wait",
                                                    "data_freshness": "unknown", "current_observation": None})
        self.emit("error", error.code)

    def complete(self, result: OperationResult) -> None:
        if result.error is not None:
            self.error(result.error)
            return
        self.failures = 0
        self.status = self.status.model_copy(update={"last_error": None, "lifecycle": "running"})
        instant = time.monotonic()
        if result.success is not None:
            self.pending_key = None
            self.status = self.status.model_copy(update={
                "latest_successful": result.success, "refreshes": self.status.refreshes + 1,
                "phase": "idle", "pending_since": None, "data_freshness": "unknown",
                "current_observation": None, "reason": "refresh_completed"})
            self.emit("refreshed", "refresh_completed")
            self.next_action, self.next_at = "observe", instant
            return
        observation = result.observation
        assert observation is not None
        self.status = self.status.model_copy(update={
            "current_observation": observation, "polls": self.status.polls + 1,
            "data_freshness": "matching_at_observation" if observation.relation == "matching" else "changed",
            "reason": observation.reason})
        if observation.relation == "matching":
            self.pending_key = None
            self.status = self.status.model_copy(update={"phase": "idle", "pending_since": None})
        else:
            if self.pending_key is None:
                self.pending_first = instant
                self.status = self.status.model_copy(update={"pending_since": now()})
                self.emit("pending", observation.reason)
            if self.pending_key != observation.comparison_key:
                self.pending_last = instant
                self.pending_key = observation.comparison_key
            self.status = self.status.model_copy(update={"phase": "pending"})
            deadline = min(self.pending_last + self.settings.debounce_seconds,
                           self.pending_first + self.settings.max_deferral_seconds)
            if instant >= deadline:
                self.next_action, self.next_at = "refresh", instant
                return
            self.next_action = "observe"
            self.next_at = min(instant + self.settings.poll_seconds, deadline)
            return
        self.next_action, self.next_at = "observe", instant + self.settings.poll_seconds

    def run(self) -> int:
        stdout_fd = sys.stdout.fileno()
        was_blocking = os.get_blocking(stdout_fd)
        os.set_blocking(stdout_fd, False)
        for signum in (signal.SIGINT, signal.SIGTERM):
            self.old_signals[signum] = signal.signal(signum, self._signal)
        self.emit("started", "initial_refresh")
        try:
            while True:
                try:
                    self.verify()
                except (OSError, ValueError, CacheCorrupt, WatchControlError) as exc:
                    if not self.failed:
                        self.failed = True
                        self.error(WatchError(code="watch_lock_integrity_error", message=str(exc)[:2000],
                                              occurred_at=now()))
                        self.stop("ownership_unverifiable")
                if (self.operation is not None and not self.operation.cancelled
                        and time.monotonic() >= self.operation.started + self.settings.operation_seconds):
                    self.operation.cancel()
                    self.status = self.status.model_copy(update={
                        "data_freshness": "unknown", "current_observation": None,
                        "last_error": WatchError(code="watch_operation_timeout",
                                                 message="operation deadline exceeded; waiting for cleanup",
                                                 occurred_at=now())})
                if self.operation is not None and self.operation.process.poll() is not None:
                    operation, self.operation = self.operation, None
                    try:
                        result = operation.finish()
                        if not self.stopping:
                            self.complete(result)
                    except (OSError, ValueError, WatchControlError) as exc:
                        if not self.stopping:
                            self.error(WatchError(code="watch_operation_failed", message=str(exc)[:2000],
                                                  occurred_at=now()))
                if self.stopping and self.operation is None:
                    break
                instant = time.monotonic()
                if not self.stopping and self.operation is None and instant >= self.next_at:
                    try:
                        self.operation = Operation.start(self.settings, self.next_action, self.lease.fd)
                        if self.next_action == "refresh":
                            self.emit("refresh_started", "scheduled_refresh")
                        self.status = self.status.model_copy(update={
                            "phase": "refreshing" if self.next_action == "refresh" else "observing",
                            "data_freshness": "unknown"})
                    except OSError as exc:
                        self.error(WatchError(code="watch_operation_start_failed", message=str(exc)[:2000],
                                              occurred_at=now()))
                self.control()
            self.emit("stopped", "ownership_unverifiable" if self.failed else "session_stopped")
            return 4 if self.failed else 0
        finally:
            if self.operation is not None:
                self.operation.cancel()
                # The lifetime lease remains held until owned work and its cleanup have ended.
                self.operation.process.wait()
                self.operation.output.close()
                self.operation.errors.close()
            for saved_signum, handler in self.old_signals.items():
                signal.signal(saved_signum, handler)
            for client in tuple(self.clients):
                self._drop(client)
            self.selector.close()
            try:
                self.bound_endpoint.unlink()
            finally:
                self.server.close()
            os.set_blocking(stdout_fd, was_blocking)
