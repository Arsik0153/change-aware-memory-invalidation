from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum
from pathlib import Path

from pydantic import ValidationError

from cami.errors import IncompleteError, InputError
from cami.product.store import (
    MAX_CACHE_BYTES, CacheCorrupt, _sync_directory, _write_file,
)
from cami.product.memory.database import capture_database, read_evidence as read_evidence
from cami.product.memory.encoding import (
    check_decoded_budget, decode_generation, encode_generation,
)
from cami.product.memory.schema import SCHEMA, EXPECTED_SCHEMAS, upgrade_legacy
from cami.product.memory.models import (
    CheckedClaim, CodeView, MemoryGeneration, MutationReceipt, RecordHistory,
    RecordRevision, SourceRef,
)

INITIALIZED = b"cami.memory/1\n"


class DatabaseRole(Enum):
    FIRST_USE = "first_use"
    LEGACY = "legacy"
    ESTABLISHED = "established"


class MemoryStore:
    def __init__(self, directory: Path):
        self.path = directory / "memory.sqlite3"
        self.objects = directory / "source-objects"
        self.initialized = directory / "memory.initialized"

    def _initialize(self) -> None:
        # No caller can write knowledge until the complete DB and ownership proof are durable.
        with tempfile.TemporaryDirectory(prefix=".memory-init-", dir=self.path.parent) as temporary:
            path = Path(temporary) / self.path.name
            db = sqlite3.connect(path, isolation_level=None)
            try:
                db.execute("PRAGMA synchronous=FULL")
                db.executescript(SCHEMA)
            finally:
                db.close()
            try:
                os.link(path, self.path)
            except FileExistsError as exc:
                raise IncompleteError(
                    "memory_database_unavailable: database appeared during initialization") from exc
            _sync_directory(self.path.parent)

    def _mark_initialized(self) -> None:
        with tempfile.TemporaryDirectory(prefix=".memory-owner-", dir=self.path.parent) as temporary:
            path = Path(temporary) / self.initialized.name
            _write_file(path, INITIALIZED)
            os.replace(path, self.initialized)
            _sync_directory(self.path.parent)

    def _role(self) -> DatabaseRole:
        try:
            initialized = read_evidence(self.initialized, len(INITIALIZED))
        except FileNotFoundError:
            initialized = None
        if initialized is not None and initialized != INITIALIZED:
            raise IncompleteError("memory_ownership_error: unknown initialization proof")
        try:
            self.path.lstat()
        except FileNotFoundError:
            if initialized is not None or os.path.lexists(self.objects):
                raise IncompleteError("memory_database_unavailable: established database missing")
            return DatabaseRole.FIRST_USE
        return DatabaseRole.LEGACY if initialized is None else DatabaseRole.ESTABLISHED

    def _image(self, db: sqlite3.Connection) -> bytes:
        size = (db.execute("PRAGMA page_count").fetchone()[0]
                * db.execute("PRAGMA page_size").fetchone()[0])
        if size > MAX_CACHE_BYTES:
            raise IncompleteError("memory_database_unavailable: database exceeds size limit")
        if db.execute("PRAGMA user_version").fetchone()[0] == 3:
            check_decoded_budget(row[0] for row in db.execute("SELECT value FROM memory_generation"))
        return db.serialize()

    def _validate_connection(self, db: sqlite3.Connection, private: Path) -> None:
        db.execute("BEGIN")
        try:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in EXPECTED_SCHEMAS:
                raise IncompleteError("memory_schema_error: expected schema version 1, 2 or 3")
            expected_tables = EXPECTED_SCHEMAS[version]
            tables = {name: " ".join(sql.split()) for name, sql in db.execute(
                "SELECT name,sql FROM sqlite_schema WHERE type='table'")}
            if tables != expected_tables or db.execute(
                "SELECT 1 FROM sqlite_schema WHERE type IN ('view','trigger') "
                "OR (type='index' AND sql IS NOT NULL)").fetchone() is not None:
                raise IncompleteError("memory_schema_error: unrecognized schema")
            if self._image(db) != read_evidence(private):
                raise IncompleteError("memory_database_unavailable: connection differs from database")
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise IncompleteError("memory_database_corrupt")
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise IncompleteError("memory_database_corrupt: foreign keys")
            for (value,) in db.execute("SELECT value FROM index_view"):
                view = CodeView.model_validate_json(value)
                if view.index.worktree_key != self.path.parent.name:
                    raise IncompleteError("memory_database_scope_mismatch")
            head = self.head(db)
            if head is not None:
                if head.index.worktree_key != self.path.parent.name:
                    raise IncompleteError("memory_database_scope_mismatch")
            elif any(db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None
                     for table in expected_tables):
                raise IncompleteError("memory_database_corrupt: knowledge without head")
        finally:
            db.execute("ROLLBACK")

    @contextmanager
    def _private_connection(self, raw: bytes,
                            journal: bytes | None) -> Iterator[sqlite3.Connection]:
        with tempfile.TemporaryDirectory(prefix=".memory-session-", dir=self.path.parent) as temp:
            private = Path(temp) / self.path.name
            _write_file(private, raw)
            if journal is not None:
                _write_file(private.with_name(private.name + "-journal"), journal)
            db = sqlite3.connect(private.absolute().as_uri() + "?mode=rw", uri=True,
                                 timeout=10, isolation_level=None)
            try:
                self._validate_connection(db, private)
                yield db
            finally:
                db.close()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        try:
            role = self._role()
            if role is DatabaseRole.FIRST_USE:
                self._initialize()
            if os.path.lexists(self.path.with_name("memory.pending")):
                with capture_database(self.path) as snapshot:
                    pending = snapshot.pending()
                    assert pending is not None
                    publication, raw = pending
                    with self._private_connection(raw, None):
                        pass
                    snapshot.complete(publication, raw)
            with capture_database(self.path) as snapshot, \
                    self._private_connection(snapshot.main, snapshot.journal) as db:
                snapshot.verify()
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("PRAGMA synchronous=FULL")
                upgrade_legacy(db)
                if role is not DatabaseRole.ESTABLISHED:
                    self._mark_initialized()
                yield db
                if db.in_transaction:
                    db.execute("ROLLBACK")
                snapshot.publish(self._image(db))
        except (sqlite3.Error, ValidationError, CacheCorrupt) as exc:
            raise IncompleteError(f"memory_database_error: {exc}") from exc

    @contextmanager
    def observation_connection(self) -> Iterator[sqlite3.Connection | None]:
        """Inspect established knowledge without initializing or completing live recovery."""
        try:
            if self._role() is DatabaseRole.FIRST_USE:
                yield None
                return
            with capture_database(self.path) as snapshot:
                if snapshot.journal is not None or snapshot.pending() is not None:
                    raise IncompleteError("memory_observation_requires_refresh: recovery pending")
                with self._private_connection(snapshot.main, None) as db:
                    snapshot.verify()
                    db.execute("PRAGMA query_only=ON")
                    yield db
                    snapshot.verify()
        except (sqlite3.Error, ValidationError, CacheCorrupt) as exc:
            raise IncompleteError(f"memory_database_error: {exc}") from exc

    def put_sources(self, captured: dict[str, bytes], view: CodeView) -> None:
        self.objects.mkdir(exist_ok=True)
        _sync_directory(self.objects.parent)
        for source in view.sources:
            raw = captured[source.path]
            if len(raw) != source.size or hashlib.sha256(raw).hexdigest() != source.sha256:
                raise IncompleteError("captured_source_checksum_mismatch")
            destination = self.objects / source.sha256
            if os.path.lexists(destination):
                self.read_source(source)
                continue
            temporary = self.objects / (".pending-" + str(os.getpid()))
            temporary.unlink(missing_ok=True)
            try:
                _write_file(temporary, raw)
                os.replace(temporary, destination)
                _sync_directory(self.objects)
            finally:
                temporary.unlink(missing_ok=True)

    def read_source(self, source: SourceRef) -> bytes:
        try:
            raw = read_evidence(self.objects / source.sha256, source.size)
        except CacheCorrupt as exc:
            raise IncompleteError(f"source_evidence_corrupt: {source.path}") from exc
        except OSError as exc:
            raise IncompleteError(f"source_evidence_unavailable: {source.path}") from exc
        if len(raw) != source.size or hashlib.sha256(raw).hexdigest() != source.sha256:
            raise IncompleteError(f"source_evidence_corrupt: {source.path}")
        return raw

    def head(self, db: sqlite3.Connection) -> MemoryGeneration | None:
        row = db.execute("SELECT generation_id FROM product_head WHERE singleton=1").fetchone()
        return self.generation(db, row[0]) if row else None

    def generation(self, db: sqlite3.Connection, generation_id: str) -> MemoryGeneration | None:
        row = db.execute("SELECT value FROM memory_generation WHERE id=?", (generation_id,)).fetchone()
        if row is None:
            return None
        raw = decode_generation(row[0]) if db.execute("PRAGMA user_version").fetchone()[0] == 3 else row[0]
        return MemoryGeneration.model_validate_json(raw)

    def view(self, db: sqlite3.Connection, generation_id: str) -> CodeView:
        row = db.execute("SELECT value FROM index_view WHERE id=?", (generation_id,)).fetchone()
        if row is None:
            raise InputError("unknown immutable context generation")
        view = CodeView.model_validate_json(row[0])
        for source in view.sources:
            self.read_source(source)
        return view

    def revisions(self, db: sqlite3.Connection) -> tuple[RecordRevision, ...]:
        return tuple(RecordRevision.model_validate_json(row[0]) for row in db.execute(
            "SELECT v.value FROM record r JOIN record_revision v "
            "ON r.id=v.record_id AND r.revision=v.revision ORDER BY r.id"))

    def receipt(self, db: sqlite3.Connection, request_id: str,
                request_hash: str) -> MutationReceipt | None:
        row = db.execute("SELECT request_hash,value FROM operation_receipt WHERE request_id=?",
                         (request_id,)).fetchone()
        if row is None:
            return None
        if row[0] != request_hash:
            raise InputError("request_id_conflict: request ID already used with different content")
        return MutationReceipt.model_validate_json(row[1])

    def save_revision(self, db: sqlite3.Connection, record: RecordRevision) -> None:
        db.execute("INSERT INTO record(id,revision) VALUES(?,?) ON CONFLICT(id) "
                   "DO UPDATE SET revision=excluded.revision", (record.memory_id, record.revision))
        db.execute("INSERT INTO record_revision VALUES(?,?,?)",
                   (record.memory_id, record.revision, record.model_dump_json()))

    def publish(self, db: sqlite3.Connection, view: CodeView, generation: MemoryGeneration) -> None:
        raw = view.model_dump_json()
        existing = db.execute("SELECT value FROM index_view WHERE id=?",
                              (view.index.generation_id,)).fetchone()
        if existing and CodeView.model_validate_json(existing[0]) != view:
            raise IncompleteError("immutable_index_identity_conflict")
        db.execute("INSERT OR IGNORE INTO index_view VALUES(?,?)", (view.index.generation_id, raw))
        for source in view.sources:
            db.execute("INSERT OR IGNORE INTO source_reference VALUES(?,?,?,?)",
                       (view.index.generation_id, source.path, source.sha256, source.size))
        db.execute("INSERT INTO memory_generation VALUES(?,?,?,?)",
                   (generation.memory_generation_id, generation.sequence, view.index.generation_id,
                    encode_generation(generation.model_dump_json())))
        for item in generation.states:
            record = item.record
            db.execute("INSERT INTO record_state VALUES(?,?,?)",
                       (generation.memory_generation_id, record.memory_id, record.revision))
            if isinstance(item.state, CheckedClaim):
                check = item.state.check
                db.execute("INSERT INTO validation_event VALUES(?,?,?,?,?)",
                           (check.check_id, record.memory_id, record.revision,
                            generation.memory_generation_id, check.model_dump_json()))
        db.execute("INSERT INTO product_head VALUES(1,?,?) ON CONFLICT(singleton) "
                   "DO UPDATE SET generation_id=excluded.generation_id, "
                   "catalog_epoch=excluded.catalog_epoch",
                   (generation.memory_generation_id, generation.catalog_epoch))

    def history(self, db: sqlite3.Connection, memory_id: str) -> RecordHistory:
        from cami.product.memory.models import CheckRef

        revisions = tuple(RecordRevision.model_validate_json(row[0]) for row in db.execute(
            "SELECT value FROM record_revision WHERE record_id=? ORDER BY revision", (memory_id,)))
        if not revisions:
            raise InputError("unknown memory ID")
        compressed = db.execute("PRAGMA user_version").fetchone()[0] == 3
        return RecordHistory(
            memory_id=memory_id, revisions=revisions,
            generations=tuple(MemoryGeneration.model_validate_json(
                decode_generation(row[0]) if compressed else row[0]) for row in db.execute(
                "SELECT DISTINCT g.value FROM memory_generation g JOIN record_state s "
                "ON s.generation_id=g.id WHERE s.record_id=? ORDER BY g.sequence", (memory_id,))),
            checks=tuple(CheckRef.model_validate_json(row[0]) for row in db.execute(
                "SELECT e.value FROM validation_event e JOIN memory_generation g "
                "ON g.id=e.generation_id WHERE e.record_id=? ORDER BY g.sequence", (memory_id,))))
