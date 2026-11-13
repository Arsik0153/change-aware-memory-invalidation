"""Independent physical/logical and arithmetic checks of compacted databases."""
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import statistics
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'src'))
from cami.product.memory.models import CodeView, MemoryGeneration, RecordRevision


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while b := f.read(1024 * 1024): h.update(b)
    return h.hexdigest()


def inspect(path):
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        assert db.execute('PRAGMA foreign_key_check').fetchone() is None
        version = db.execute('PRAGMA user_version').fetchone()[0]
        tables = {}
        for (name,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table'"):
            columns = 'generation_id,record_id,revision' if name == 'record_state' else '*'
            tables[name] = sorted(db.execute(f'SELECT {columns} FROM {name}').fetchall())
        raw = db.execute('SELECT g.value FROM memory_generation g JOIN product_head h ON g.id=h.generation_id WHERE h.singleton=1').fetchone()[0]
        head = MemoryGeneration.model_validate_json(raw)
        view = CodeView.model_validate_json(db.execute('SELECT value FROM index_view WHERE id=?', (head.index.generation_id,)).fetchone()[0])
        revisions = [RecordRevision.model_validate_json(r[0]) for r in db.execute('SELECT v.value FROM record r JOIN record_revision v ON r.id=v.record_id AND r.revision=v.revision ORDER BY r.id')]
        output = hashlib.sha256(head.model_dump_json().encode() + view.model_dump_json().encode() + b''.join(r.model_dump_json().encode() for r in revisions)).hexdigest()
        return version, tables, output


def audit(root, report):
    protocol = json.loads((root / 'protocol.json').read_text())
    summary = json.loads((root / 'summary.json').read_text())
    assert len(protocol['cases']) == len(summary['cases']) == 10
    checked = []
    for case, claimed in zip(protocol['cases'], summary['cases']):
        source = Path(case['source'])
        assert case['id'] == claimed['id']
        for name, expected in case['files'].items():
            assert sha(source / name) == expected
            if name != 'memory.sqlite3':
                for condition in ('baseline', 'compact'):
                    assert sha(root / case['id'] / condition / source.name / name) == expected
        paths = {c: root / case['id'] / c / source.name / 'memory.sqlite3' for c in ('baseline', 'compact')}
        bv, before, bo = inspect(paths['baseline'])
        av, after, ao = inspect(paths['compact'])
        assert (bv, av) == (1, 2) and before == after and bo == ao
        assert sha(paths['baseline']) == case['files']['memory.sqlite3']
        for c in paths:
            assert claimed['database_bytes'][c] == paths[c].stat().st_size
            assert claimed['cold'][c]['output_sha256'] == bo
            values = claimed['warm'][c]
            assert len(values) == 5 and all(math.isfinite(v) and v > 0 for v in values)
            assert claimed['warm_summary'][c] == {'median': statistics.median(values), 'min': min(values), 'max': max(values)}
        reduction = 100 * (1 - paths['compact'].stat().st_size / paths['baseline'].stat().st_size)
        assert reduction == claimed['database_reduction_percent'] and reduction >= 35
        checked.append({'id': case['id'], 'status': 'verified', 'logical_tables_equal': True,
            'public_output_sha256': bo, 'baseline_sha256': sha(paths['baseline']), 'compact_sha256': sha(paths['compact']),
            'result_sha256': sha(root / case['id'] / 'result.json'), 'database_reduction_percent': reduction})
    result = {'status': 'verified', 'cases': checked, 'protocol_sha256': sha(root / 'protocol.json'),
              'summary_sha256': sha(root / 'summary.json'), 'scope': 'Independent source-byte preservation, SQLite integrity, all authoritative logical rows, direct public-model projection, schema versions, sizes and timing arithmetic. Warm-call execution is backed by the pinned runner assertions; no claim of whole-agent speedup.'}
    (report / 'audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'verified_databases': len(checked)}))


if __name__ == '__main__':
    audit(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
