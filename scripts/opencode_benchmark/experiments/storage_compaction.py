"""Paired storage experiment on copied real databases; never calls a model."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from cami.product.memory.store import MemoryStore  # noqa: E402


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def files(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*')) if p.is_file()}


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def pins(baseline):
    names = ['product/memory/store.py', 'product/memory/schema.py', 'product/memory/models.py',
             'product/memory/database.py', 'product/store.py']
    return {**{name: sha(ROOT / 'src/cami' / name) for name in names},
            'baseline': sha(baseline), 'runner': sha(Path(__file__))}


def logical_rows(path):
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")]
        tables = {}
        for name in names:
            columns = 'generation_id,record_id,revision' if name == 'record_state' else '*'
            rows = sorted(db.execute(f'SELECT {columns} FROM {name}').fetchall())
            tables[name] = hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()
        assert db.execute('PRAGMA foreign_key_check').fetchone() is None
        assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    return tables


def operation(store):
    started = time.perf_counter()
    with store.connection() as db:
        head = store.head(db)
        assert head is not None
        view = store.view(db, head.index.generation_id)
        records = store.revisions(db)
        output = hashlib.sha256(head.model_dump_json().encode() + view.model_dump_json().encode()
                                + b''.join(r.model_dump_json().encode() for r in records)).hexdigest()
    return {'wall_seconds': time.perf_counter() - started, 'output_sha256': output}


def run(protocol, out):
    baseline = Path(protocol['baseline'])
    if protocol['pins'] != pins(baseline):
        raise ValueError('frozen implementation differs')
    if out.exists():
        raise ValueError('new output required; no replacement runs')
    out.mkdir(parents=True)
    write(out / 'protocol.json', protocol)
    spec = importlib.util.spec_from_file_location('baseline_memory_store', baseline)
    old = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old
    spec.loader.exec_module(old)
    records = []
    for number, case in enumerate(protocol['cases']):
        source = Path(case['source'])
        if files(source) != case['files']:
            raise ValueError('source evidence changed')
        paths = {c: out / case['id'] / c / source.name for c in ('baseline', 'compact')}
        for path in paths.values():
            shutil.copytree(source, path)
        stores = {'baseline': old.MemoryStore(paths['baseline']), 'compact': MemoryStore(paths['compact'])}
        entry = {'id': case['id'], 'cold': {}, 'warm': {c: [] for c in stores},
                 'load_start': os.getloadavg()}
        order = ('baseline', 'compact') if number % 2 == 0 else ('compact', 'baseline')
        for condition in order:
            entry['cold'][condition] = operation(stores[condition])
        expected = entry['cold']['baseline']['output_sha256']
        assert entry['cold']['compact']['output_sha256'] == expected
        assert logical_rows(stores['baseline'].path) == logical_rows(stores['compact'].path)
        with stores['baseline'].observation_connection() as db:
            ids = [r.memory_id for r in stores['baseline'].revisions(db)]
            selected = [ids[0], ids[len(ids) // 2], ids[-1]]
            histories = [stores['baseline'].history(db, ident) for ident in selected]
        with stores['compact'].observation_connection() as db:
            assert db.execute('PRAGMA user_version').fetchone()[0] == 2
            assert histories == [stores['compact'].history(db, ident) for ident in selected]
        for repetition in range(5):
            order = ('baseline', 'compact') if (number + repetition) % 2 == 0 else ('compact', 'baseline')
            for condition in order:
                measured = operation(stores[condition])
                assert measured['output_sha256'] == expected
                entry['warm'][condition].append(measured['wall_seconds'])
        entry['database_bytes'] = {c: store.path.stat().st_size for c, store in stores.items()}
        entry['memory_directory_bytes'] = {c: sum(p.stat().st_size for p in path.rglob('*') if p.is_file())
                                           for c, path in paths.items()}
        entry['warm_summary'] = {c: {'median': statistics.median(v), 'min': min(v), 'max': max(v)}
                                 for c, v in entry['warm'].items()}
        entry['database_reduction_percent'] = 100 * (1 - entry['database_bytes']['compact'] / entry['database_bytes']['baseline'])
        entry['warm_median_reduction_percent'] = 100 * (1 - entry['warm_summary']['compact']['median'] / entry['warm_summary']['baseline']['median'])
        entry['warm_ranges_separated'] = entry['warm_summary']['compact']['max'] < entry['warm_summary']['baseline']['min']
        entry['status'] = 'verified'
        write(out / case['id'] / 'result.json', entry)
        records.append(entry)
        print(json.dumps({k: entry[k] for k in ('id', 'status', 'database_reduction_percent', 'warm_median_reduction_percent', 'warm_ranges_separated')}), flush=True)
        if files(source) != case['files']:
            raise ValueError('original evidence changed')
    if pins(baseline) != protocol['pins']:
        raise ValueError('implementation changed during measurements')
    write(out / 'summary.json', {'status': 'verified', 'model_calls': 0, 'cases': records,
        'scope': protocol['scope'], 'storage_target_passed': all(r['database_reduction_percent'] >= 35 for r in records),
        'warm_all_case_medians_lower': all(r['warm_median_reduction_percent'] > 0 for r in records),
        'warm_all_ranges_separated': all(r['warm_ranges_separated'] for r in records)})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--freeze', type=Path, required=True)
    p.add_argument('--baseline', type=Path)
    p.add_argument('--source-run', type=Path)
    p.add_argument('--run', action='store_true')
    p.add_argument('--out', type=Path)
    a = p.parse_args()
    if a.run:
        if a.out is None:
            p.error('--run requires --out')
        run(json.loads(a.freeze.read_text()), a.out.resolve())
        return
    if a.freeze.exists() or a.baseline is None or a.source_run is None:
        p.error('freeze requires new path, baseline and source-run')
    cases = []
    for rep in range(1, 6):
        for condition in ('cami', 'cami_replay'):
            name = f'r{rep}-{condition}'
            roots = list((a.source_run.resolve() / 'namespaces' / name / 'memory').rglob('memory.sqlite3'))
            assert len(roots) == 1
            source = roots[0].parent
            cases.append({'id': name, 'source': str(source), 'files': files(source)})
    write(a.freeze, {'design': 'duplicate-state-compaction-v1', 'baseline': str(a.baseline.resolve()),
        'pins': pins(a.baseline), 'cases': cases, 'python': sys.version, 'sqlite': sqlite3.sqlite_version,
        'platform': platform.platform(), 'warm_repetitions_per_case': 5,
        'scope': 'Ten copied stores from completed development run, not new tasks. First operation includes private-copy schema migration and compaction. Five alternating subsequent operations include validated connection, head/revisions/view, source-byte verification and result serialization. Exact public outputs, sampled histories, logical rows and foreign keys must agree; original evidence remains unchanged. Primary storage target >=35% smaller DB in every case. Report warm medians/ranges; overlapping ranges do not establish speedup. No model calls or whole-agent speed claim.'})


if __name__ == '__main__':
    main()
