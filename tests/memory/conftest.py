from __future__ import annotations

import json
import os
import sqlite3

import pytest

from cami.product.memory.schema import EXPECTED_SCHEMAS, LEGACY_SCHEMA


@pytest.fixture
def legacy_database():
    """Reconstruct schema1's redundant rows from an otherwise identical schema2 DB."""
    def convert(path):
        with sqlite3.connect(path) as source:
            rows = {name: source.execute(f'SELECT * FROM {name}').fetchall()
                    for name in EXPECTED_SCHEMAS[2]}
        states = {row[0]: {s['record']['memory_id']: s for s in json.loads(row[3])['states']}
                  for row in rows['memory_generation']}
        legacy = path.with_name('schema1-fixture.sqlite3')
        with sqlite3.connect(legacy) as db:
            db.executescript(LEGACY_SCHEMA)
            db.execute('PRAGMA foreign_keys=ON')
            for table, values in rows.items():
                if table == 'record_state':
                    values = [(*row, json.dumps(states[row[0]][row[1]])) for row in values]
                if values:
                    marks = ','.join('?' for _ in values[0])
                    db.executemany(f'INSERT INTO {table} VALUES({marks})', values)
        os.replace(legacy, path)
    return convert
