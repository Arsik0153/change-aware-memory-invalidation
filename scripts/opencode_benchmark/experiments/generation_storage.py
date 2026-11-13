"""Prospective isolated-process schema2/schema3 comparison on frozen real stores."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from path_validation import files, sha, write  # noqa: E402


def worker(source, directory):
    sys.path.insert(0, str(source))
    from cami.product.memory import store as module

    assert Path(module.__file__).resolve().is_relative_to(source)
    store = module.MemoryStore(directory)
    started, cpu_started = time.perf_counter(), time.process_time()
    with store.connection() as db:
        head = store.head(db)
        assert head is not None
        view = store.view(db, head.index.generation_id)
        revisions = store.revisions(db)
        assert len(revisions) == len(head.states) == 329
        payload = (head.model_dump_json().encode() + view.model_dump_json().encode()
                   + b''.join(record.model_dump_json().encode() for record in revisions))
        output = hashlib.sha256(payload).hexdigest()
        version = db.execute('PRAGMA user_version').fetchone()[0]
    wall, cpu = time.perf_counter() - started, time.process_time() - cpu_started
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(json.dumps({'wall_seconds': wall, 'cpu_seconds': cpu,
        'peak_rss_bytes': rss if sys.platform == 'darwin' else rss * 1024,
        'schema': version, 'output_sha256': output, 'output_bytes': len(payload),
        'records': len(revisions), 'source_sha256': sha(Path(module.__file__))}))


def logical_rows(path):
    import base64
    import zlib

    with sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('PRAGMA foreign_key_check').fetchone() is None
        version = db.execute('PRAGMA user_version').fetchone()[0]
        result = {}
        for (table,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table'"):
            rows = sorted(db.execute(f'SELECT * FROM {table}').fetchall())
            if table == 'memory_generation' and version == 3:
                plain = []
                for row in rows:
                    codec, length, body = row[3].split(':', 2)
                    assert codec == 'cami-json-zlib/1' and 0 < int(length) <= 256 * 1024 * 1024
                    decoder = zlib.decompressobj()
                    raw = decoder.decompress(base64.b64decode(body, validate=True), int(length) + 1)
                    assert len(raw) == int(length) and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
                    plain.append((*row[:3], raw.decode('utf-8')))
                rows = plain
            result[table] = hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()
    return result


def pins(sources):
    return {'sources': {side: files(Path(path)) for side, path in sources.items()},
            'runner': sha(Path(__file__)), 'helper': sha(Path(__file__).with_name('path_validation.py'))}


def run(protocol, out):
    assert pins(protocol['sources']) == protocol['pins']
    out.mkdir(parents=True, exist_ok=False)
    write(out / 'protocol.json', protocol)
    results = []
    for number, case in enumerate(protocol['cases']):
        original = Path(case['source'])
        assert files(original) == case['files']
        directories = {side: out / case['id'] / side / original.name for side in protocol['sources']}
        for directory in directories.values():
            shutil.copytree(original, directory)
        row = {'id': case['id'], 'cold': {}, 'samples': {side: [] for side in directories},
               'load_start': os.getloadavg()}
        for repetition in range(-1, 5):
            order = ('baseline', 'candidate') if (number + repetition) % 2 == 0 else ('candidate', 'baseline')
            for side in order:
                start = time.perf_counter()
                completed = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve()),
                    '--worker', '--source', protocol['sources'][side], '--directory', str(directories[side])],
                    capture_output=True, text=True, timeout=90, check=False)
                wall = time.perf_counter() - start
                receipt = {'returncode': completed.returncode, 'stdout': completed.stdout,
                           'stderr': completed.stderr, 'process_wall_seconds': wall}
                label = 'cold' if repetition == -1 else str(repetition)
                write(out / case['id'] / f'{label}-{side}.json', receipt)
                assert completed.returncode == 0 and not completed.stderr
                sample = json.loads(completed.stdout) | {'process_wall_seconds': wall}
                assert sample['output_sha256'] == case['output_sha256']
                assert sample['schema'] == (2 if side == 'baseline' else 3)
                assert sample['source_sha256'] == protocol['pins']['sources'][side]['cami/product/memory/store.py']
                if repetition == -1:
                    row['cold'][side] = sample
                else:
                    row['samples'][side].append(sample)
        expected = logical_rows(original / 'memory.sqlite3')
        for side, directory in directories.items():
            assert logical_rows(directory / 'memory.sqlite3') == expected
            actual = files(directory)
            assert actual.keys() == case['files'].keys()
            assert all(actual[name] == digest for name, digest in case['files'].items()
                       if name != 'memory.sqlite3' or side == 'baseline')
        assert files(original) == case['files']
        row['database_bytes'] = {side: (directory / 'memory.sqlite3').stat().st_size
                                 for side, directory in directories.items()}
        row['database_sha256'] = {side: sha(directory / 'memory.sqlite3')
                                  for side, directory in directories.items()}
        row['summary'] = {side: {
            metric: {'median': statistics.median(s[metric] for s in samples),
                     'min': min(s[metric] for s in samples), 'max': max(s[metric] for s in samples)}
            for metric in ('wall_seconds', 'cpu_seconds', 'process_wall_seconds', 'peak_rss_bytes')}
            for side, samples in row['samples'].items()}
        row['storage_reduction_percent'] = 100 * (1 - row['database_bytes']['candidate'] / row['database_bytes']['baseline'])
        row['ranges_separated'] = {metric: row['summary']['candidate'][metric]['max'] < row['summary']['baseline'][metric]['min']
                                   for metric in ('wall_seconds', 'process_wall_seconds', 'peak_rss_bytes')}
        row['status'] = 'verified'
        write(out / case['id'] / 'result.json', row)
        results.append(row)
        print(json.dumps({'id': row['id'], 'bytes': row['database_bytes'],
                          'summary': row['summary'], 'ranges_separated': row['ranges_separated']}), flush=True)
    assert pins(protocol['sources']) == protocol['pins']
    write(out / 'summary.json', {'status': 'verified', 'errors': 0, 'model_calls': 0, 'cases': results,
        'storage_target_passed': all(row['storage_reduction_percent'] >= 50 for row in results),
        'scope': protocol['scope']})


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--worker', action='store_true')
    p.add_argument('--source', type=Path)
    p.add_argument('--directory', type=Path)
    p.add_argument('--protocol', type=Path)
    p.add_argument('--inputs', type=Path)
    p.add_argument('--baseline', type=Path)
    p.add_argument('--candidate', type=Path)
    p.add_argument('--out', type=Path)
    a = p.parse_args()
    if a.worker:
        worker(a.source.resolve(), a.directory.resolve())
    elif a.out:
        run(json.loads(a.protocol.read_text()), a.out.resolve())
    else:
        inputs = json.loads(a.inputs.read_text())
        sources = {'baseline': str(a.baseline.resolve()), 'candidate': str(a.candidate.resolve())}
        write(a.protocol, {'design': 'production-generation-compression-v1', 'sources': sources,
            'pins': pins(sources), 'cases': inputs['cases'], 'python': sys.version,
            'platform': platform.platform(), 'cores': os.cpu_count(), 'repetitions_per_side': 5,
            'scope': 'Ten real schema2 stores; each side receives an independent copy. One first '
                     'process includes schema migration on the candidate. Then five alternating fresh '
                     'processes per side/case. Time validated connection, head/view/revisions, source '
                     'byte verification and output hashing; outer process time includes imports and exit. '
                     'Peak RSS is process-lifetime OS high-water mark, not retained heap. OS caches '
                     'uncontrolled. Primary success: >=50% smaller database in every case, exact public '
                     'outputs and all logical SQL rows, unchanged originals and other files. Secondary '
                     'latency/RSS claims require separated observed ranges in all cases. '
                     'Separate real MCP check is required; no model or whole-agent speed claim.'})
