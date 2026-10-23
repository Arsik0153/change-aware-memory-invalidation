"""Paired operational timings. No label file is opened by this script."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

POLICIES = ('keep_all', 'clear_all', 'file_invalidate', 'symbol_invalidate',
            'all_validate', 'file_validate', 'symbol_validate')


def read(path):
    return json.loads(path.read_text())


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def benchmark(dataset_path, output, baseline_src, repetitions=3):
    output.mkdir(parents=True, exist_ok=False)
    dataset = read(dataset_path)
    if any(r['split'] != 'development' for r in dataset['runs']):
        raise ValueError('timing development pilot only; never evaluate heldout data here')
    variants = {'baseline': (baseline_src.resolve(), '1.0'),
                'fixed_v1': (Path(__file__).resolve().parents[1] / 'src', '1.0'),
                'predicate': (Path(__file__).resolve().parents[1] / 'src', '1.1')}
    for name, (root, protocol) in tuple(variants.items()):
        frozen = output / 'sources' / name
        shutil.copytree(root, frozen, ignore=shutil.ignore_patterns('__pycache__'))
        variants[name] = (frozen, protocol)
    write(output / 'sources.json', {name: {'protocol': protocol, 'root': str(root),
          'sha256': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted(root.rglob('*.py'))}} for name, (root, protocol) in variants.items()})
    schedule = []
    rng = random.Random(42)
    for repetition in range(repetitions):
        for entry in dataset['runs']:
            original = dataset_path.parent / entry['config_path']
            for mode in ('uncached', 'warm_verdict'):
                names = list(variants)
                rng.shuffle(names)
                for variant in names:
                    directory = output / 'inputs' / str(repetition) / entry['run_id'] / mode / variant
                    base = read(original)
                    directory.mkdir(parents=True)
                    inputs = [base[key] for key in ('claims_path', 'provenance_path', 'parent_receipts_path')]
                    inputs += [row['evidence_path'] for row in rows(original.parent / base['parent_receipts_path'])]
                    inputs += [row['predicate']['probe_path'] for row in rows(original.parent / base['claims_path'])
                               if row['kind'] == 'behavior_test']
                    if base.get('graph_views_path'):
                        inputs += [str(Path(base['graph_views_path']) / f'{revision}.json')
                                   for revision in (base['parent_commit'], *base['child_commits'])]
                    for relative in inputs:
                        if Path(relative).is_absolute() or '..' in Path(relative).parts:
                            raise ValueError('pilot inputs must use contained relative artifact paths')
                        destination = directory / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(original.parent / relative, destination)
                    base['repo']['path'] = str((original.parent / base['repo']['path']).resolve())
                    base['protocol_version'] = variants[variant][1]
                    base['replicate_id'] = repetition
                    base['cache_dir'] = str((output / 'cache' / str(repetition) / entry['run_id'] / variant).resolve()) if mode == 'warm_verdict' else None
                    policies = list(POLICIES if mode == 'uncached' else POLICIES[-3:])
                    rng.shuffle(policies)
                    if mode == 'warm_verdict':
                        policies.insert(0, 'prime_all_validate')
                    for policy in policies:
                        actual = policy.removeprefix('prime_')
                        config = {**base, 'policy': {**base['policy'], 'id': actual}}
                        config_path = directory / f'benchmark-{policy}.json'
                        write(config_path, config)
                        schedule.append({'repetition': repetition, 'run_id': entry['run_id'],
                                         'variant': variant, 'mode': mode, 'policy': actual,
                                         'phase': 'cache_fill' if policy.startswith('prime_') else 'measure',
                                         'config': str(config_path.resolve()),
                                         'output': str((output / 'runs' / str(len(schedule))).resolve())})
    write(output / 'schedule.json', {'seed': 42, 'repetitions': repetitions, 'jobs': schedule,
          'cold_definition': 'empty per-run AST cache and no verdict cache; OS caches uncontrolled',
          'warm_definition': 'verdict cache prefilled in separately measured all_validate run; AST cache starts empty',
          'quality_metrics': None, 'quality_reason': 'independent_labels_pending'})
    results = []
    for i, job in enumerate(schedule):
        env = {**os.environ, 'PYTHONPATH': str(variants[job['variant']][0])}
        command = [sys.executable, '-m', 'cami.cli', 'run', '--config', job['config'], '--out', job['output']]
        started = time.perf_counter()
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        elapsed = time.perf_counter() - started
        target = Path(job['output'])
        (output / 'logs').mkdir(exist_ok=True)
        (output / 'logs' / f'{i}.txt').write_text(result.stdout + result.stderr)
        record = {**job, 'command': command, 'exit_code': result.returncode, 'process_wall_seconds': elapsed}
        if result.returncode:
            results.append(record)
            write(output / 'measurements.json', results)
            raise RuntimeError(f'job {i} failed; see logs/{i}.txt')
        costs = rows(target / 'costs.jsonl')
        record['costs'] = {key: sum(c.get(key, 0) or 0 for c in costs) for key in (
            'wall_seconds', 'cpu_seconds', 'index_seconds', 'initial_index_seconds',
            'incremental_index_seconds', 'selection_seconds', 'logical_validations',
            'actual_validations', 'cache_hits', 'test_executions', 'actual_validation_seconds',
            'reconstructed_validation_seconds')}
        record['preflight_wall_seconds'] = sum(c['wall_seconds'] for c in costs if c['phase'] == 'preflight')
        record['selections'] = dict(collections.Counter(reason for s in rows(target / 'selections.jsonl') for reason in s['reasons']))
        record['selected'] = sum(s['selected'] for s in rows(target / 'selections.jsonl'))
        record['verdicts'] = dict(collections.Counter(v['verdict'] for v in rows(target / 'validations.jsonl')))
        record['validation_reasons'] = dict(collections.Counter(v['reason'] for v in rows(target / 'validations.jsonl')))
        results.append(record)
        write(output / 'measurements.json', results)
        if (i + 1) % 28 == 0:
            print(f'{i + 1}/{len(schedule)} timing jobs completed', flush=True)
    summarize(output)


def summarize(output):
    results = read(output / 'measurements.json')
    groups = {}
    for result in results:
        key = (result['variant'], result['mode'], result['phase'], result['policy'])
        groups.setdefault(key, {}).setdefault(result['repetition'], []).append(result)
    summaries = []
    for key, repeats in sorted(groups.items()):
        totals = []
        for repetition, batch in sorted(repeats.items()):
            total = {'repetition': repetition, 'runs': len(batch),
                     'process_wall_seconds': sum(r['process_wall_seconds'] for r in batch),
                     'selected': sum(r['selected'] for r in batch),
                     'costs': {k: sum(r['costs'][k] for r in batch) for k in batch[0]['costs']}}
            for field in ('selections', 'verdicts', 'validation_reasons'):
                count = collections.Counter()
                for row in batch:
                    count.update(row[field])
                total[field] = dict(count)
            totals.append(total)
        summaries.append(dict(zip(('variant', 'mode', 'phase', 'policy'), key, strict=True)) | {
            'repetitions': totals, 'median_process_wall_seconds': statistics.median(t['process_wall_seconds'] for t in totals),
            'min_process_wall_seconds': min(t['process_wall_seconds'] for t in totals),
            'max_process_wall_seconds': max(t['process_wall_seconds'] for t in totals)})
    write(output / 'summary.json', {'groups': summaries, 'quality_metrics': None,
                                  'comparison': 'baseline vs fixed_v1 isolates implementation fixes; fixed_v1 vs predicate isolates protocol; development only'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--baseline-src', type=Path, required=True)
    parser.add_argument('--repetitions', type=int, default=3)
    args = parser.parse_args()
    benchmark(args.dataset.resolve(), args.out.resolve(), args.baseline_src, args.repetitions)
