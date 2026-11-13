"""Independent SQL/raw-byte reconstruction; no production or prototype codec imports."""
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import zlib


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tables(path):
    with sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('PRAGMA foreign_key_check').fetchone() is None
        return db.execute('PRAGMA user_version').fetchone()[0], {
            name: sorted(db.execute(f'SELECT * FROM {name}').fetchall())
            for (name,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}


protocol = json.loads(Path(sys.argv[1]).read_text())
root = Path(sys.argv[2]).resolve()
summary = json.loads((root / 'summary.json').read_text())
assert len(protocol['cases']) == len(summary['cases']) == 10
checked = []
for case, row in zip(protocol['cases'], summary['cases'], strict=True):
    assert case['id'] == row['id']
    original = Path(case['source']) / 'memory.sqlite3'
    candidate = root / (case['id'] + '.sqlite3')
    assert sha(original) == case['files']['memory.sqlite3'] == row['original_sha256']
    assert sha(candidate) == row['prototype_sha256']
    bv, before = tables(original)
    av, after = tables(candidate)
    assert (bv, av) == (2, 1003)
    originals = {r[0]: r[3].encode('utf-8') for r in before['memory_generation']}
    restored = []
    for entry in after['memory_generation']:
        codec, size, body = entry[3].split(':', 2)
        assert codec == 'cami-json-zlib/1' and int(size) == len(originals[entry[0]])
        raw = zlib.decompress(base64.b64decode(body, validate=True))
        assert raw == originals[entry[0]]
        restored.append((*entry[:3], raw.decode('utf-8')))
    after['memory_generation'] = restored
    assert before == after
    assert original.stat().st_size == row['original_bytes']
    assert candidate.stat().st_size == row['prototype_bytes']
    assert row['size_reduction_percent'] == 100 * (1 - row['prototype_bytes'] / row['original_bytes'])
    assert row['size_reduction_percent'] >= 50
    checked.append({'id': case['id'], 'status': 'verified', 'all_sql_rows_exact': True})
result = {'status': 'verified', 'cases': checked, 'summary_sha256': sha(root / 'summary.json'),
          'scope': 'Offline copied-file representation only. All SQL rows reconstruct exactly, '
                   'including original generation JSON bytes; original hashes unchanged. '
                   'No production compatibility, speed or model efficiency claim.'}
Path(sys.argv[3]).write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
