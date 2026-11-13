from __future__ import annotations

import json
import os
import sqlite3

import pytest

from cami.product.memory.encoding import decode_generation
from cami.product.memory.schema import COMPACT_SCHEMA, EXPECTED_SCHEMAS, LEGACY_SCHEMA


@pytest.fixture
def legacy_database():
    """Reconstruct an old uncompressed database without changing model values."""
    def convert(path, version=1):
        assert version in (1, 2)
        with sqlite3.connect(path) as source:
            current = source.execute('PRAGMA user_version').fetchone()[0]
            rows = {name: source.execute(f'SELECT * FROM {name}').fetchall()
                    for name in EXPECTED_SCHEMAS[2]}
        if current == 3:
            rows['memory_generation'] = [(*row[:3], decode_generation(row[3]))
                                          for row in rows['memory_generation']]
        rows['record_state'] = [row[:3] for row in rows['record_state']]
        states = {row[0]: {s['record']['memory_id']: s for s in json.loads(row[3])['states']}
                  for row in rows['memory_generation']}
        legacy = path.with_name(f'schema{version}-fixture.sqlite3')
        with sqlite3.connect(legacy) as db:
            db.executescript(LEGACY_SCHEMA if version == 1 else COMPACT_SCHEMA)
            db.execute('PRAGMA foreign_keys=ON')
            for table, values in rows.items():
                if table == 'record_state' and version == 1:
                    values = [(*row, json.dumps(states[row[0]][row[1]])) for row in values]
                if values:
                    marks = ','.join('?' for _ in values[0])
                    db.executemany(f'INSERT INTO {table} VALUES({marks})', values)
        os.replace(legacy, path)
    return convert
