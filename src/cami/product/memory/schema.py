"""Versioned SQLite layout; compact only duplicate, verified generation states."""
from __future__ import annotations

import sqlite3

from cami.errors import IncompleteError
from cami.product.memory.models import MemoryGeneration, RecordState

LEGACY_SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE record (id TEXT PRIMARY KEY, revision INTEGER NOT NULL);
CREATE TABLE record_revision (
    record_id TEXT NOT NULL REFERENCES record(id), revision INTEGER NOT NULL,
    value TEXT NOT NULL, PRIMARY KEY(record_id, revision));
CREATE TABLE index_view (id TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE memory_generation (
    id TEXT PRIMARY KEY, sequence INTEGER NOT NULL UNIQUE,
    index_id TEXT NOT NULL REFERENCES index_view(id), value TEXT NOT NULL);
CREATE TABLE record_state (
    generation_id TEXT NOT NULL REFERENCES memory_generation(id),
    record_id TEXT NOT NULL REFERENCES record(id), revision INTEGER NOT NULL,
    value TEXT NOT NULL, PRIMARY KEY(generation_id, record_id),
    FOREIGN KEY(record_id, revision) REFERENCES record_revision(record_id, revision));
CREATE TABLE validation_event (
    id TEXT PRIMARY KEY, record_id TEXT NOT NULL, revision INTEGER NOT NULL,
    generation_id TEXT NOT NULL REFERENCES memory_generation(id), value TEXT NOT NULL,
    FOREIGN KEY(record_id, revision) REFERENCES record_revision(record_id, revision));
CREATE TABLE operation_receipt (
    request_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, value TEXT NOT NULL);
CREATE TABLE product_head (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    generation_id TEXT NOT NULL REFERENCES memory_generation(id), catalog_epoch INTEGER NOT NULL);
CREATE TABLE source_reference (
    index_id TEXT NOT NULL REFERENCES index_view(id), path TEXT NOT NULL,
    sha256 TEXT NOT NULL, size INTEGER NOT NULL, PRIMARY KEY(index_id, path));
PRAGMA user_version=1;
COMMIT;
"""

SCHEMA = LEGACY_SCHEMA.replace(
    "    value TEXT NOT NULL, PRIMARY KEY(generation_id, record_id),",
    "    PRIMARY KEY(generation_id, record_id),",
).replace("PRAGMA user_version=1;", "PRAGMA user_version=2;")
EXPECTED_SCHEMAS = {
    version: {
        statement.split()[2]: " ".join(statement.split())
        for statement in schema.split(";") if statement.lstrip().startswith("CREATE TABLE ")
    }
    for version, schema in ((1, LEGACY_SCHEMA), (2, SCHEMA))
}


def compact_legacy(db: sqlite3.Connection) -> None:
    if db.execute("PRAGMA user_version").fetchone()[0] != 1:
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        for generation_id, raw in db.execute("SELECT id,value FROM memory_generation"):
            generation = MemoryGeneration.model_validate_json(raw)
            states = {item.record.memory_id: item for item in generation.states}
            rows = db.execute(
                "SELECT record_id,revision,value FROM record_state WHERE generation_id=?",
                (generation_id,),
            ).fetchall()
            if (generation.memory_generation_id != generation_id
                    or len(states) != len(generation.states)
                    or set(states) != {row[0] for row in rows}):
                raise IncompleteError("memory_database_corrupt: generation state index differs")
            for record_id, revision, value in rows:
                if (states[record_id].record.revision != revision
                        or RecordState.model_validate_json(value) != states[record_id]):
                    raise IncompleteError("memory_database_corrupt: duplicate state differs")
        db.execute("ALTER TABLE record_state RENAME TO legacy_record_state")
        db.execute(EXPECTED_SCHEMAS[2]["record_state"])
        db.execute("INSERT INTO record_state SELECT generation_id,record_id,revision "
                   "FROM legacy_record_state")
        db.execute("DROP TABLE legacy_record_state")
        db.execute("PRAGMA user_version=2")
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    # This is the already captured private copy; live publication remains atomic.
    db.execute("VACUUM")
