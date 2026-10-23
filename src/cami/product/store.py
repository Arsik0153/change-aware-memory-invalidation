from __future__ import annotations

import errno
import fcntl
import hashlib
import os
import platform
import shutil
import stat
import sys
import tempfile
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import VERSION as PYDANTIC_VERSION
from pydantic import TypeAdapter, ValidationError

from cami.artifacts import parse
from cami.errors import IncompleteError
from cami.index import INDEX_VERSION, CodeIndex, IndexConfig
from cami.product.models import (
    Capture,
    Generation,
    IndexedWorktree,
    Manifest,
    Observation,
    Pointer,
    canonical_json,
    digest,
)
from cami.product.worktree import CaptureChanged, capture
from cami.repository import Snapshot

INDEX_ADAPTER = TypeAdapter(CodeIndex)
MAX_CAPTURE_ATTEMPTS = 3
MAX_CACHE_BYTES = 256 * 1024 * 1024


class CacheCorrupt(ValueError):
    pass


def state_base() -> Path:
    return (Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state")))
            .expanduser().resolve() / "cami")


def worktree_key(root: Path) -> str:
    return digest(str(root.resolve()))


def index_fingerprint() -> str:
    package = Path(__file__).parent.parent
    sources = [package / name for name in ("index.py", "symbol_search.py", "models.py",
                                           "repository.py")]
    sources.extend(sorted(
        (package / "product").glob("*.py")))
    return digest({"schema_version": 1, "index_version": INDEX_VERSION,
                   "python": sys.version, "implementation": platform.python_implementation(),
                   "pydantic": PYDANTIC_VERSION,
                   "sources": {path.relative_to(package).as_posix(): hashlib.sha256(
                       path.read_bytes()).hexdigest() for path in sources}})


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_file(path: Path, content: bytes) -> None:
    if len(content) > MAX_CACHE_BYTES:
        raise IncompleteError(f"product_state_io_error: {path.name} exceeds {MAX_CACHE_BYTES} bytes")
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _warning(message: str) -> None:
    print(f"cami cache: {message}", file=sys.stderr)


def _cache_open(name: str | Path, flags: int, parent_fd: int | None = None) -> int:
    try:
        return os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent_fd)
    except OSError as exc:
        if exc.errno in (errno.ENOTDIR, errno.ELOOP):
            raise CacheCorrupt(f"invalid cache object type: {name}") from exc
        raise


@contextmanager
def _cache_directory(name: str | Path, parent_fd: int | None = None) -> Iterator[int]:
    fd = _cache_open(name, os.O_RDONLY | os.O_DIRECTORY, parent_fd)
    try:
        yield fd
    finally:
        os.close(fd)


def _cache_read(parent_fd: int, name: str, limit: int = MAX_CACHE_BYTES) -> bytes:
    fd = _cache_open(name, os.O_RDONLY, parent_fd)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise CacheCorrupt(f"invalid cache file type or size: {name}")
        chunks = []
        size = 0
        while size <= before.st_size:
            chunk = os.read(fd, min(128 * 1024, before.st_size - size + 1))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        after = os.fstat(fd)
        linked = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        if size != before.st_size or any(
            getattr(before, field) != getattr(info, field)
            for info in (after, linked) for field in fields
        ):
            raise CacheCorrupt(f"cache file changed during read: {name}")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _manifest(fd: int) -> Manifest:
    return Manifest.model_validate_json(canonical_json(parse(
        _cache_read(fd, "manifest.json").decode("utf-8"))))


class GenerationStore:
    def __init__(self, root: Path, base: Path):
        self.key = worktree_key(root)
        self.path = base / "repos" / self.key

    @contextmanager
    def writer(self) -> Iterator[None]:
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        with _cache_directory(self.path) as parent_fd:
            lock = _cache_open("writer.lock", os.O_RDWR | os.O_CREAT, parent_fd)
            try:
                if not stat.S_ISREG(os.fstat(lock).st_mode):
                    raise IncompleteError("product_state_io_error: writer.lock is not a regular file")
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
            finally:
                os.close(lock)

    @contextmanager
    def _generation(self, generation_id: str) -> Iterator[int]:
        with _cache_directory(self.path) as root_fd, \
                _cache_directory("generations", root_fd) as generations_fd, \
                _cache_directory(generation_id, generations_fd) as generation_fd:
            yield generation_fd

    def check_pointer(self, fingerprint: str) -> None:
        try:
            with _cache_directory(self.path) as fd:
                raw = _cache_read(fd, "current.json", 4096)
            pointer = Pointer.model_validate_json(canonical_json(parse(raw.decode("utf-8"))))
        except FileNotFoundError:
            return
        except (ValidationError, ValueError):
            _warning("invalid current pointer; validating captured generation")
            return
        try:
            with self._generation(pointer.generation_id) as fd:
                manifest = _manifest(fd)
        except (ValidationError, ValueError, FileNotFoundError):
            _warning("current manifest is invalid; validating captured generation")
            return
        if manifest.fingerprint != fingerprint:
            _warning("analyzer fingerprint changed; rebuilding from captured inputs")

    def load(self, generation_id: str, captured: Capture, fingerprint: str) -> Generation | None:
        try:
            with self._generation(generation_id) as fd:
                try:
                    manifest = _manifest(fd)
                    raw_index = _cache_read(fd, "index.json")
                except FileNotFoundError as exc:
                    raise ValueError("generation is incomplete") from exc
            if (manifest.worktree_key != self.key or manifest.generation_id != generation_id
                    or manifest.fingerprint != fingerprint
                    or manifest.snapshot_id != captured.snapshot_id
                    or manifest.policy != captured.policy or manifest.entries != captured.entries):
                raise ValueError("generation identity is incompatible")
            if hashlib.sha256(raw_index).hexdigest() != manifest.index_sha256:
                raise ValueError("index checksum mismatch")
            parse(raw_index.decode("utf-8"))
            index = INDEX_ADAPTER.validate_json(raw_index, strict=True)
            if index.revision != "worktree:" + captured.snapshot_id:
                raise ValueError("index refers to a different snapshot")
            return Generation(manifest, index)
        except FileNotFoundError:
            return None
        except (ValidationError, ValueError) as exc:
            _warning(f"unusable generation {generation_id} ({type(exc).__name__}); rebuilding")
            return None

    def publish(self, generation: Generation, index_bytes: bytes | None) -> None:
        with _cache_directory(self.path) as root_fd:
            try:
                with _cache_directory("generations", root_fd):
                    pass
            except (FileNotFoundError, ValueError):
                self._quarantine(root_fd, "generations", root_fd)
                os.mkdir("generations", mode=0o700, dir_fd=root_fd)
            with _cache_directory("generations", root_fd) as generations_fd:
                self._publish_generation(generation, index_bytes, root_fd, generations_fd)
            try:
                info = os.stat("current.json", dir_fd=root_fd, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    self._quarantine(root_fd, "current.json", root_fd)
            except FileNotFoundError:
                pass
            self._publish_pointer(generation, root_fd)

    def _quarantine(self, source_fd: int, name: str, root_fd: int) -> None:
        try:
            os.replace(name, ".corrupt-" + uuid.uuid4().hex,
                       src_dir_fd=source_fd, dst_dir_fd=root_fd)
        except FileNotFoundError:
            pass

    def _publish_generation(self, generation: Generation, index_bytes: bytes | None,
                            root_fd: int, generations_fd: int) -> None:
        if index_bytes is not None:
            temporary = Path(tempfile.mkdtemp(prefix=".pending-", dir=self.path))
            try:
                _write_file(temporary / "index.json", index_bytes)
                _write_file(temporary / "manifest.json",
                            canonical_json(generation.manifest.model_dump(mode="json")))
                _sync_directory(temporary)
                self._quarantine(generations_fd, generation.manifest.generation_id, root_fd)
                os.replace(temporary.name, generation.manifest.generation_id,
                           src_dir_fd=root_fd, dst_dir_fd=generations_fd)
                os.fsync(generations_fd)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)

    def _publish_pointer(self, generation: Generation, root_fd: int) -> None:
        pointer = canonical_json(Pointer(generation_id=generation.manifest.generation_id)
                                 .model_dump(mode="json"))
        pointer_fd, pointer_path = tempfile.mkstemp(prefix=".pointer-", dir=self.path)
        temporary_pointer = Path(pointer_path)
        try:
            with os.fdopen(pointer_fd, "wb") as stream:
                stream.write(pointer)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_pointer.name, "current.json",
                       src_dir_fd=root_fd, dst_dir_fd=root_fd)
            os.fsync(root_fd)
        finally:
            temporary_pointer.unlink(missing_ok=True)


def refresh(root: Path, source_roots: tuple[str, ...] | None, excluded_paths: tuple[str, ...],
            build: Callable[[Snapshot, IndexConfig], CodeIndex]) -> IndexedWorktree:
    base = state_base()
    store = GenerationStore(root, base)
    try:
        with store.writer():
            fingerprint = index_fingerprint()
            store.check_pointer(fingerprint)
            for _ in range(MAX_CAPTURE_ATTEMPTS):
                started = datetime.now(UTC).isoformat()
                try:
                    captured = capture(root, source_roots, excluded_paths, base)
                    generation_id = digest([captured.snapshot_id, fingerprint])
                    generation = store.load(generation_id, captured, fingerprint)
                    reused = generation is not None
                    index_bytes = None
                    if generation is None:
                        index = build(captured.as_snapshot(), IndexConfig(captured.policy.source_roots))
                        index_bytes = INDEX_ADAPTER.dump_json(index)
                        manifest = Manifest(
                            worktree_key=store.key, snapshot_id=captured.snapshot_id,
                            generation_id=generation_id, fingerprint=fingerprint,
                            policy=captured.policy, entries=captured.entries,
                            index_sha256=hashlib.sha256(index_bytes).hexdigest())
                        generation = Generation(manifest, index)
                    verified = capture(root, source_roots, excluded_paths, base)
                    if (verified.snapshot_id != captured.snapshot_id
                            or verified.base_commit != captured.base_commit):
                        raise CaptureChanged("inputs, policy, or HEAD changed during indexing")
                    observation = Observation(capture_started_at=started,
                                              verified_at=datetime.now(UTC).isoformat(),
                                              cache_reused=reused)
                    store.publish(generation, index_bytes)
                    return IndexedWorktree(captured, generation, observation)
                except CaptureChanged:
                    continue
            raise IncompleteError("capture_unstable: worktree changed during all three capture attempts")
    except (OSError, CacheCorrupt) as exc:
        raise IncompleteError(f"product_state_io_error: {exc}") from exc
