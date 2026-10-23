from __future__ import annotations

import fcntl
import hashlib
import os
import platform
import shutil
import sys
import tempfile
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
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _warning(message: str) -> None:
    print(f"cami cache: {message}", file=sys.stderr)


class GenerationStore:
    def __init__(self, root: Path, base: Path):
        self.key = worktree_key(root)
        self.path = base / "repos" / self.key

    @contextmanager
    def writer(self) -> Iterator[None]:
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.path / "writer.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def check_pointer(self, fingerprint: str) -> None:
        try:
            raw = (self.path / "current.json").read_bytes()
        except FileNotFoundError:
            return
        try:
            pointer = Pointer.model_validate_json(canonical_json(parse(raw.decode("utf-8"))))
        except (ValidationError, ValueError):
            _warning("invalid current pointer; validating captured generation")
            return
        path = self.path / "generations" / pointer.generation_id
        if not path.is_dir():
            _warning("current generation is missing; rebuilding from captured inputs")
            return
        try:
            manifest = Manifest.model_validate_json(canonical_json(parse(
                (path / "manifest.json").read_text(encoding="utf-8"))))
        except (ValidationError, ValueError, FileNotFoundError, IsADirectoryError):
            _warning("current manifest is invalid; validating captured generation")
            return
        if manifest.fingerprint != fingerprint:
            _warning("analyzer fingerprint changed; rebuilding from captured inputs")

    def load(self, generation_id: str, captured: Capture, fingerprint: str) -> Generation | None:
        path = self.path / "generations" / generation_id
        if not path.exists():
            return None
        try:
            manifest = Manifest.model_validate_json(canonical_json(parse(
                (path / "manifest.json").read_text(encoding="utf-8"))))
            if (manifest.worktree_key != self.key or manifest.generation_id != generation_id
                    or manifest.fingerprint != fingerprint
                    or manifest.snapshot_id != captured.snapshot_id
                    or manifest.policy != captured.policy or manifest.entries != captured.entries):
                raise ValueError("generation identity is incompatible")
            raw_index = (path / "index.json").read_bytes()
            if hashlib.sha256(raw_index).hexdigest() != manifest.index_sha256:
                raise ValueError("index checksum mismatch")
            parse(raw_index.decode("utf-8"))
            index = INDEX_ADAPTER.validate_json(raw_index, strict=True)
            if index.revision != "worktree:" + captured.snapshot_id:
                raise ValueError("index refers to a different snapshot")
            return Generation(manifest, index)
        except (ValidationError, ValueError, FileNotFoundError, IsADirectoryError) as exc:
            _warning(f"unusable generation {generation_id} ({type(exc).__name__}); rebuilding")
            return None

    def publish(self, generation: Generation, index_bytes: bytes | None) -> None:
        generations = self.path / "generations"
        generations.mkdir(exist_ok=True)
        destination = generations / generation.manifest.generation_id
        if index_bytes is not None:
            temporary = Path(tempfile.mkdtemp(prefix=".pending-", dir=self.path))
            try:
                _write_file(temporary / "index.json", index_bytes)
                _write_file(temporary / "manifest.json",
                            canonical_json(generation.manifest.model_dump(mode="json")))
                _sync_directory(temporary)
                if destination.exists():
                    # A damaged generation is never repaired in place under a reader.
                    quarantine = self.path / (".corrupt-" + temporary.name.removeprefix(".pending-"))
                    os.replace(destination, quarantine)
                os.replace(temporary, destination)
                _sync_directory(generations)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        pointer = canonical_json(Pointer(generation_id=generation.manifest.generation_id)
                                 .model_dump(mode="json"))
        pointer_fd, pointer_path = tempfile.mkstemp(prefix=".pointer-", dir=self.path)
        temporary_pointer = Path(pointer_path)
        try:
            with os.fdopen(pointer_fd, "wb") as stream:
                stream.write(pointer)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_pointer, self.path / "current.json")
            _sync_directory(self.path)
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
    except OSError as exc:
        raise IncompleteError(f"product_state_io_error: {exc}") from exc
