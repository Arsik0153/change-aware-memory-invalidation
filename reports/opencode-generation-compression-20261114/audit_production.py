"""Recheck exact SQL reconstruction, process receipts, physical bounds and arithmetic."""
import base64
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import statistics
import sys
import zlib


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts}


def logical(path):
    with sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('PRAGMA foreign_key_check').fetchone() is None
        version = db.execute('PRAGMA user_version').fetchone()[0]
        assert version in (2, 3)
        tables = {name: sorted(db.execute(f'SELECT * FROM {name}').fetchall())
                  for (name,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        if version == 3:
            generations, total = [], 0
            for row in tables['memory_generation']:
                codec, length, body = row[3].split(':', 2)
                assert codec == 'cami-json-zlib/1' and str(int(length)) == length
                size = int(length)
                assert 0 < size <= 256 * 1024 * 1024
                total += size
                assert total <= 256 * 1024 * 1024
                compressed = base64.b64decode(body, validate=True)
                assert base64.b64encode(compressed).decode('ascii') == body
                decoder = zlib.decompressobj()
                raw = decoder.decompress(compressed, size + 1)
                assert len(raw) == size and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
                generations.append((*row[:3], raw.decode('utf-8')))
            tables['memory_generation'] = generations
        return version, tables


root = Path(sys.argv[1]).resolve()
protocol, summary = read(root / 'protocol.json'), read(root / 'summary.json')
assert len(protocol['cases']) == len(summary['cases']) == 10
for side, source in protocol['sources'].items():
    assert files(Path(source)) == protocol['pins']['sources'][side]
count, checked = 0, []
for case, row in zip(protocol['cases'], summary['cases'], strict=True):
    assert case['id'] == row['id'] and row['status'] == 'verified'
    original = Path(case['source'])
    assert files(original) == case['files']
    _, original_rows = logical(original / 'memory.sqlite3')
    for side in ('baseline', 'candidate'):
        directory = root / case['id'] / side / original.name
        version, rows = logical(directory / 'memory.sqlite3')
        assert version == (2 if side == 'baseline' else 3) and rows == original_rows
        actual = files(directory)
        assert actual.keys() == case['files'].keys()
        for name, expected in case['files'].items():
            if name != 'memory.sqlite3' or side == 'baseline':
                assert actual[name] == expected
        assert row['database_bytes'][side] == (directory / 'memory.sqlite3').stat().st_size
        assert row['database_sha256'][side] == actual['memory.sqlite3']
        assert len(row['samples'][side]) == 5
        for repetition in range(-1, 5):
            label = 'cold' if repetition == -1 else str(repetition)
            receipt = read(root / case['id'] / f'{label}-{side}.json')
            assert receipt['returncode'] == 0 and receipt['stderr'] == ''
            observed = json.loads(receipt['stdout']) | {'process_wall_seconds': receipt['process_wall_seconds']}
            sample = row['cold'][side] if repetition == -1 else row['samples'][side][repetition]
            assert observed == sample and sample['schema'] == version
            assert sample['records'] == 329 and sample['output_sha256'] == case['output_sha256']
            assert sample['source_sha256'] == protocol['pins']['sources'][side]['cami/product/memory/store.py']
            for metric in ('wall_seconds', 'cpu_seconds', 'process_wall_seconds', 'peak_rss_bytes'):
                assert math.isfinite(sample[metric]) and sample[metric] > 0
            count += 1
        for metric, claim in row['summary'][side].items():
            values = [sample[metric] for sample in row['samples'][side]]
            assert claim == {'median': statistics.median(values), 'min': min(values), 'max': max(values)}
    for metric, flag in row['ranges_separated'].items():
        assert flag == (row['summary']['candidate'][metric]['max'] < row['summary']['baseline'][metric]['min'])
    assert row['storage_reduction_percent'] == 100 * (1 - row['database_bytes']['candidate'] / row['database_bytes']['baseline'])
    assert row['storage_reduction_percent'] >= 50
    checked.append({'id': case['id'], 'status': 'verified', 'all_logical_rows_exact': True,
                    'original_unchanged': True, 'result_sha256': sha(root / case['id'] / 'result.json')})
assert count == 120 and summary['storage_target_passed'] is True
result = {'status': 'verified', 'verified_processes': count, 'model_calls': 0,
          'cases': checked, 'summary_sha256': sha(root / 'summary.json'),
          'scope': 'Exact reconstruction of all SQL values including historic raw generation JSON; '
                   'physical originals and other files unchanged; every successful process receipt, '
                   'correct frozen source import, output hash, latency/RSS arithmetic and size gate.'}
Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
