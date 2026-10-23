"""Verify a completed pilot timing series and publish operational tables without labels."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import statistics
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def publish(source, output):
    schedule = read(source / 'schedule.json')
    measurements = read(source / 'measurements.json')
    summary = read(source / 'summary.json')
    if len(measurements) != len(schedule['jobs']) or any(r['exit_code'] for r in measurements):
        raise ValueError('timing series incomplete or failed')
    cohorts = {}
    by_key = {}
    for row in measurements:
        manifest = read(Path(row['output']) / 'manifest.json')
        identity = {key: manifest[key] for key in
                    ('claim_hashes', 'cohort', 'excluded', 'input_hashes', 'parent_commit', 'child_commits')}
        if row['run_id'] in cohorts and cohorts[row['run_id']] != identity:
            raise ValueError(f"cohort or input mismatch: {row['run_id']}")
        cohorts[row['run_id']] = identity
        key = tuple(row[k] for k in ('variant', 'mode', 'phase', 'policy'))
        by_key.setdefault(key, []).append(row)
    output.mkdir(parents=True, exist_ok=False)
    table = []
    for group in summary['groups']:
        repeats = group['repetitions']
        if len(repeats) != 3 or any(r['runs'] != 12 for r in repeats):
            raise ValueError('expected three complete repetitions of twelve transitions')
        for field in ('selected', 'selections', 'verdicts', 'validation_reasons'):
            if any(r[field] != repeats[0][field] for r in repeats):
                raise ValueError(f'non-repeatable outcomes: {field}')
        result = {key: group[key] for key in ('variant', 'mode', 'phase', 'policy')}
        result['selected'] = repeats[0]['selected']
        for field in ('logical_validations', 'actual_validations', 'cache_hits'):
            values = {r['costs'][field] for r in repeats}
            if len(values) != 1:
                raise ValueError(f'non-repeatable cost counts: {field}')
            result[field] = values.pop()
        for field in ('index_seconds', 'initial_index_seconds', 'incremental_index_seconds',
                      'selection_seconds', 'actual_validation_seconds', 'reconstructed_validation_seconds'):
            result[field] = statistics.median(r['costs'][field] for r in repeats)
        for field in ('median_process_wall_seconds', 'min_process_wall_seconds', 'max_process_wall_seconds'):
            result[field] = group[field]
        result['preflight_seconds'] = statistics.median(
            sum(r['preflight_wall_seconds'] for r in by_key[tuple(result[k] for k in ('variant', 'mode', 'phase', 'policy'))]
                if r['repetition'] == repetition) for repetition in range(3))
        result['verdicts'] = repeats[0]['verdicts']
        result['selection_reasons'] = repeats[0]['selections']
        table.append(result)
    (output / 'verified_summary.json').write_text(json.dumps({
        'completed_jobs': len(measurements), 'identical_cohorts': len(cohorts),
        'source_hashes': read(source / 'sources.json'), 'table': table,
        'quality_metrics': None, 'independent_labels': 'pending'}, indent=2) + '\n')
    with (output / 'timings.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    lines = ['# Проверенные операционные измерения', '',
             'Значения относятся к 120 claim-transition за одно повторение. Время — сумма 12 процессов;',
             'медиана и диапазон по трём повторениям. Cache fill измерен отдельно. Labels отсутствуют.', '',
             '| Variant | Mode / phase | Policy | Selected | Logical / actual / hits | Index, s | Full process, median [min; max], s |',
             '|---|---|---|---:|---:|---:|---:|']
    for r in table:
        lines.append(f"| {r['variant']} | {r['mode']} / {r['phase']} | {r['policy']} | {r['selected']} | "
                     f"{r['logical_validations']} / {r['actual_validations']} / {r['cache_hits']} | "
                     f"{r['index_seconds']:.3f} | {r['median_process_wall_seconds']:.3f} "
                     f"[{r['min_process_wall_seconds']:.3f}; {r['max_process_wall_seconds']:.3f}] |")
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    variants = ('baseline', 'fixed_v1', 'predicate')
    policies = ('all_validate', 'file_validate', 'symbol_validate')
    figure, axes = plt.subplots(1, 2, figsize=(12, 4), sharey=True)
    for axis, mode in zip(axes, ('uncached', 'warm_verdict'), strict=True):
        for offset, variant in enumerate(variants):
            chosen = [next(r for r in table if r['variant'] == variant and r['mode'] == mode
                           and r['phase'] == 'measure' and r['policy'] == policy) for policy in policies]
            values = [r['median_process_wall_seconds'] for r in chosen]
            errors = [[r['median_process_wall_seconds'] - r['min_process_wall_seconds'] for r in chosen],
                      [r['max_process_wall_seconds'] - r['median_process_wall_seconds'] for r in chosen]]
            positions = [i + (offset - 1) * 0.25 for i in range(3)]
            axis.bar(positions, values, width=0.25, yerr=errors, capsize=3, label=variant)
        axis.set_xticks(range(3), ['all', 'file', 'symbol'])
        axis.set_title(mode)
        axis.set_xlabel('Validation policy')
    axes[0].set_ylabel('Full process seconds / 12 transitions')
    axes[1].legend()
    figure.suptitle('Median and observed range, 3 repeats; warm-cache fill reported separately')
    figure.tight_layout()
    figure.savefig(output / 'costs.png', dpi=160)
    plt.close(figure)
    lines.extend(['', '![Full process costs](costs.png)'])
    (output / 'summary.md').write_text('\n'.join(lines) + '\n')
    for name in ('schedule.json', 'sources.json', 'measurements.json', 'summary.json'):
        shutil.copyfile(source / name, output / name)
    (output / 'evidence_hashes.json').write_text(json.dumps({
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir()) if p.is_file()
    }, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    publish(args.input, args.out)
