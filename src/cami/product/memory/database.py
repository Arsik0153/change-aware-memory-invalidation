from __future__ import annotations

import fcntl
import hashlib
import os
import shutil
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from cami.errors import IncompleteError
from cami.product.store import (
    MAX_CACHE_BYTES, CacheCorrupt, _cache_directory, _cache_open, _cache_read,
    _sync_directory, _write_file,
)

JOURNAL_MAGIC = bytes.fromhex("d9d505f920a163d7")
SQLITE_LOCK_START = 0x40000000
STAT_FIELDS = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def read_evidence(path: Path, limit: int = MAX_CACHE_BYTES) -> bytes:
    with _cache_directory(path.parent) as parent_fd:
        return _cache_read(parent_fd, path.name, min(limit, MAX_CACHE_BYTES))


def _optional_evidence(path: Path) -> bytes | None:
    try:
        return read_evidence(path)
    except FileNotFoundError:
        return None


def _sha(raw: bytes | None) -> str | None:
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return tuple(getattr(info, field) for field in STAT_FIELDS)


def _lock(fd: int) -> None:
    # SQLite's Unix VFS locks the pending, reserved and 510 shared bytes here.
    try:
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB, 512, SQLITE_LOCK_START)
    except BlockingIOError as exc:
        raise IncompleteError("memory_database_busy: another SQLite connection is active") from exc


class Publication(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    format: Literal["cami.memory-publication/1"] = "cami.memory-publication/1"
    before: Sha256
    after: Sha256
    journal: Sha256 | None


@dataclass(frozen=True)
class DatabaseCapture:
    path: Path
    fd: int
    info: os.stat_result
    main: bytes
    journal: bytes | None

    @property
    def journal_path(self) -> Path:
        return self.path.with_name(self.path.name + "-journal")

    @property
    def pending_path(self) -> Path:
        return self.path.with_name("memory.pending")

    def verify(self) -> None:
        try:
            linked = self.path.lstat()
        except FileNotFoundError as exc:
            raise IncompleteError("memory_database_unavailable: database disappeared") from exc
        if any(_identity(info) != _identity(self.info)
               for info in (os.fstat(self.fd), linked)):
            raise IncompleteError("memory_database_unavailable: database changed during capture")
        if any(os.path.lexists(self.path.with_name(self.path.name + suffix))
               for suffix in ("-wal", "-shm")):
            raise IncompleteError("memory_database_unavailable: WAL storage is unsupported")
        if _optional_evidence(self.journal_path) != self.journal:
            raise IncompleteError("memory_database_unavailable: journal changed during capture")

    def pending(self) -> tuple[Publication, bytes] | None:
        if not os.path.lexists(self.pending_path):
            return None
        with _cache_directory(self.pending_path) as directory:
            publication = Publication.model_validate_json(_cache_read(directory, "commit.json", 4096))
            raw = _cache_read(directory, "next.sqlite3")
            try:
                journal = _cache_read(directory, "original-journal")
            except FileNotFoundError:
                journal = None
        if _sha(raw) != publication.after or _sha(journal) != publication.journal:
            raise IncompleteError("memory_publication_error: pending evidence checksum mismatch")
        return publication, raw

    def publish(self, raw: bytes) -> None:
        self.verify()
        if raw == self.main and self.journal is None:
            return
        publication = Publication(before=hashlib.sha256(self.main).hexdigest(),
                                  after=hashlib.sha256(raw).hexdigest(),
                                  journal=_sha(self.journal))
        with tempfile.TemporaryDirectory(prefix=".memory-publish-", dir=self.path.parent) as temp:
            directory = Path(temp)
            _write_file(directory / "next.sqlite3", raw)
            if self.journal is not None:
                _write_file(directory / "original-journal", self.journal)
            _write_file(directory / "commit.json", publication.model_dump_json().encode())
            _sync_directory(directory)
            self.verify()
            if os.path.lexists(self.pending_path):
                raise IncompleteError("memory_publication_error: pending publication exists")
            os.rename(directory, self.pending_path)
            _sync_directory(self.path.parent)
        self.complete(publication, raw)

    def complete(self, publication: Publication, raw: bytes) -> None:
        current = _sha(self.main)
        journal = _sha(self.journal)
        if (self.pending() != (publication, raw)
                or _sha(raw) != publication.after
                or current not in (publication.before, publication.after)
                or journal not in (publication.journal, None)):
            raise IncompleteError("memory_publication_error: database or journal differs from commit")
        self.verify()
        # A prior attempt may have failed the parent fsync after publishing the intent.
        _sync_directory(self.pending_path)
        _sync_directory(self.path.parent)
        with tempfile.TemporaryDirectory(prefix=".memory-install-", dir=self.path.parent) as temp:
            installed = Path(temp) / self.path.name
            new_fd = None
            try:
                if current != publication.after:
                    _write_file(installed, raw)
                    new_fd = _cache_open(installed, os.O_RDWR)
                    _lock(new_fd)
                    self.verify()
                if self.journal is not None:
                    # Its durable exact copy and the validated next image precede this unlink.
                    self.journal_path.unlink()
                    _sync_directory(self.path.parent)
                if current != publication.after:
                    os.replace(installed, self.path)
                    _sync_directory(self.path.parent)
                # Retire the whole intact intent before deleting any of its files.
                retired = Path(tempfile.mkdtemp(prefix=".memory-retired-", dir=self.path.parent))
                os.replace(self.pending_path, retired)
                _sync_directory(self.path.parent)
                shutil.rmtree(retired)
            finally:
                if new_fd is not None:
                    os.close(new_fd)


def _check_recovery_resources(main: bytes, journal: bytes | None) -> None:
    if len(main) < 100 or main[:16] != b"SQLite format 3\0":
        raise IncompleteError("memory_database_error: invalid SQLite header")
    if main[18:20] != b"\1\1":
        raise IncompleteError("memory_database_unavailable: only rollback-journal storage is supported")
    if journal is None:
        return
    # A super-journal footer names another filesystem resource. Never let SQLite follow it.
    if journal[-8:] == JOURNAL_MAGIC:
        raise IncompleteError("memory_database_unavailable: attached-database journal is unsupported")
    if len(journal) < 28 or journal[:8] == b"\0" * 8:
        return
    if journal[:8] != JOURNAL_MAGIC:
        raise IncompleteError("memory_database_unavailable: unrecognized rollback journal")
    page_size = int.from_bytes(main[16:18], "big")
    page_size = 65536 if page_size == 1 else page_size
    pages = int.from_bytes(journal[16:20], "big")
    sector_size = int.from_bytes(journal[20:24], "big")
    journal_page_size = int.from_bytes(journal[24:28], "big")
    if (page_size < 512 or page_size > 65536 or page_size & (page_size - 1)
            or pages * page_size > MAX_CACHE_BYTES
            or sector_size < 512 or sector_size > 65536 or sector_size & (sector_size - 1)
            or journal_page_size not in (0, page_size)):
        raise IncompleteError("memory_database_unavailable: unsupported rollback journal bounds")


@contextmanager
def capture_database(path: Path) -> Iterator[DatabaseCapture]:
    with _cache_directory(path.parent) as parent_fd:
        expected = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(expected.st_mode) or not 0 < expected.st_size <= MAX_CACHE_BYTES:
            raise CacheCorrupt("expected bounded nonempty regular memory database")
        fd = _cache_open(path.name, os.O_RDWR, parent_fd)
        try:
            info = os.fstat(fd)
            if _identity(info) != _identity(expected):
                raise CacheCorrupt("memory database changed before capture")
            _lock(fd)
            chunks = []
            size = 0
            while size <= info.st_size:
                chunk = os.read(fd, min(128 * 1024, info.st_size - size + 1))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            if size != info.st_size:
                raise CacheCorrupt("memory database changed during capture")
            snapshot = DatabaseCapture(path, fd, info, b"".join(chunks),
                                       _optional_evidence(path.with_name(path.name + "-journal")))
            snapshot.verify()
            _check_recovery_resources(snapshot.main, snapshot.journal)
            yield snapshot
        finally:
            os.close(fd)
