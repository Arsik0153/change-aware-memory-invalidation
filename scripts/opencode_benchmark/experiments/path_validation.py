"""Isolated-process A/B on real schema-2 stores; no model calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts}


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def worker(source, directory):
    sys.path.insert(0, str(source))
    from cami.product.memory.store import MemoryStore
    from cami import models

    assert Path(models.__file__).resolve().is_relative_to(source)
    store = MemoryStore(directory)
    started, cpu_started = time.perf_counter(), time.process_time()
    with store.connection() as db:
        head = store.head(db)
        assert head is not None
        view = store.view(db, head.index.generation_id)
        records = store.revisions(db)
        assert records and view.sources and head.states
        payload = (head.model_dump_json().encode() + view.model_dump_json().encode()
                   + b''.join(r.model_dump_json().encode() for r in records))
        output = hashlib.sha256(payload).hexdigest()
    result = {'wall_seconds': time.perf_counter() - started,
              'cpu_seconds': time.process_time() - cpu_started,
              'output_sha256': output, 'output_bytes': len(payload),
              'records': len(records), 'states': len(head.states),
              'source_sha256': sha(Path(models.__file__))}
    cache = getattr(models, '_cached_path_validation', None)
    if cache is not None:
        result['lexical_cache'] = cache.cache_info()._asdict()
    print(json.dumps(result))


def run(protocol, out):
    assert sha(Path(__file__)) == protocol['runner_sha256']
    for side in ('baseline', 'candidate'):
        assert files(Path(protocol[side])) == protocol['source_files'][side]
    out.mkdir(parents=True, exist_ok=False)
    write(out / 'protocol.json', protocol)
    results = []
    for number, case in enumerate(protocol['cases']):
        source = Path(case['source'])
        assert files(source) == case['files']
        paths = {side: out / case['id'] / side / source.name
                 for side in ('baseline', 'candidate')}
        for directory in paths.values():
            shutil.copytree(source, directory)
        row = {'id': case['id'], 'samples': {side: [] for side in paths},
               'load_start': os.getloadavg()}
        expected = case['output_sha256']
        for repetition in range(5):
            order = ('baseline', 'candidate') if (number + repetition) % 2 == 0 else ('candidate', 'baseline')
            for side in order:
                start = time.perf_counter()
                completed = subprocess.run(
                    [sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--worker',
                     '--source', protocol[side], '--directory', str(paths[side])],
                    capture_output=True, text=True, timeout=60, check=False)
                process_wall = time.perf_counter() - start
                artifact = out / case['id'] / f'{repetition}-{side}.json'
                receipt = {'returncode': completed.returncode, 'stderr': completed.stderr,
                           'stdout': completed.stdout, 'process_wall_seconds': process_wall}
                write(artifact, receipt)
                assert completed.returncode == 0 and not completed.stderr, receipt
                sample = json.loads(completed.stdout)
                assert sample['output_sha256'] == expected
                assert sample['source_sha256'] == protocol['source_files'][side]['cami/models.py']
                sample['process_wall_seconds'] = process_wall
                row['samples'][side].append(sample)
        row['summary'] = {
            side: {metric: {'median': statistics.median(s[metric] for s in samples),
                           'min': min(s[metric] for s in samples),
                           'max': max(s[metric] for s in samples)}
                   for metric in ('wall_seconds', 'cpu_seconds', 'process_wall_seconds')}
            for side, samples in row['samples'].items()}
        row['ranges_separated'] = {
            metric: row['summary']['candidate'][metric]['max'] < row['summary']['baseline'][metric]['min']
            for metric in ('wall_seconds', 'process_wall_seconds')}
        row['status'] = 'verified'
        for directory in paths.values():
            assert files(directory) == case['files']
        assert files(source) == case['files']
        write(out / case['id'] / 'result.json', row)
        results.append(row)
        print(json.dumps({'id': row['id'], 'summary': row['summary'],
                          'ranges_separated': row['ranges_separated']}), flush=True)
    for side in paths:
        assert files(Path(protocol[side])) == protocol['source_files'][side]
    write(out / 'summary.json', {'status': 'verified', 'errors': 0, 'model_calls': 0,
                                'cases': results, 'scope': protocol['scope']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--protocol', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--measured-storage', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.source.resolve(), args.directory.resolve())
    elif args.out:
        run(json.loads(args.protocol.read_text()), args.out.resolve())
    else:
        measured = args.measured_storage.resolve()
        storage_protocol = json.loads((measured / 'protocol.json').read_text())
        storage_summary = json.loads((measured / 'summary.json').read_text())
        cases = []
        for case, result in zip(storage_protocol['cases'], storage_summary['cases'], strict=True):
            assert case['id'] == result['id']
            source = measured / case['id'] / 'compact' / Path(case['source']).name
            cases.append({'id': case['id'], 'source': str(source), 'files': files(source),
                          'output_sha256': result['cold']['compact']['output_sha256']})
        sources = {'baseline': args.baseline.resolve(), 'candidate': args.candidate.resolve()}
        write(args.protocol, {'design': 'bounded-lexical-validation-v1',
            **{side: str(path) for side, path in sources.items()},
            'source_files': {side: files(path) for side, path in sources.items()},
            'cases': cases, 'runner_sha256': sha(Path(__file__)), 'python': sys.version,
            'platform': platform.platform(), 'cores': os.cpu_count(),
            'repetitions_per_case_and_side': 5,
            'scope': 'Ten immutable schema2 source-memory stores from development tasks. '
                     'Five alternating fresh subprocesses per side/case, lexical cache initially empty. '
                     'Internal operation includes validated open, head/view/revisions, source verification '
                     'and output serialization. Parent process wall also includes Python imports/startup. '
                     'OS file cache uncontrolled and shared; no disk-cold claim. Exact output hashes and '
                     'all physical files must remain equal. Separate full MCP measurement required for '
                     'user-facing latency. No model requests or whole-agent speed claim. '
                     'Claim a consistent local improvement only if ranges separate in all cases.'})


if __name__ == '__main__':
    main()
