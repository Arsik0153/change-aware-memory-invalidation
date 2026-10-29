"""Validate saved study counts and render a development report without rerunning bootstrap."""
from __future__ import annotations

import argparse
import base64
import math
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

from cami.artifacts import file_hash, read_json, read_jsonl, reserve, write_json


def report(source: Path, output: Path) -> None:
    manifest = read_json(source / 'manifest.json')
    if manifest['status'] != 'complete':
        raise ValueError('study is incomplete')
    for name in ('protocol.json', 'trials.jsonl', 'summary.json'):
        if file_hash(source / name) != manifest['artifact_hashes'][name]:
            raise ValueError(f'artifact hash mismatch: {name}')
    protocol = read_json(source / 'protocol.json')
    summary = read_json(source / 'summary.json')
    raw = read_jsonl(source / 'trials.jsonl')
    ids = [scenario['id'] for scenario in protocol['scenarios']]
    expected = {(name, trial) for name in ids for trial in range(protocol['trials_per_scenario'])}
    if len(raw) != len(expected) or {(r['scenario'], r['trial']) for r in raw} != expected:
        raise ValueError('missing or duplicate trials')
    for name in ids:
        rows = [r for r in raw if r['scenario'] == name]
        available = 0
        covered = 0
        reasons: Counter[str] = Counter()
        for row in rows:
            interval = row['interval']
            lo, hi = interval['lower'], interval['upper']
            if (lo is None) != (hi is None):
                raise ValueError('partial interval')
            if lo is None:
                reasons[interval['reason']] += 1
                if row['covered'] is not None:
                    raise ValueError('unavailable interval counted as covered')
            else:
                available += 1
                correct = lo <= summary['truth'] <= hi
                covered += correct
                if row['covered'] != correct or interval['reason'] is not None:
                    raise ValueError('inconsistent interval coverage')
            for policy in ('left', 'right'):
                if any(not 0 <= num <= den for num, den in row[policy].values()):
                    raise ValueError('invalid counters')
            ld = sum(den for _, den in row['left'].values())
            rd = sum(den for _, den in row['right'].values())
            estimate = (sum(num for num, _ in row['left'].values()) / ld
                        - sum(num for num, _ in row['right'].values()) / rd) if ld and rd else None
            if estimate != interval['estimate']:
                raise ValueError('estimate disagrees with raw counts')
        actual = summary['scenarios'][name]
        checked = {'trials': len(rows), 'available': available, 'covered': covered,
                   'availability': available / len(rows),
                   'conditional_coverage': covered / available if available else None,
                   'joint_available_and_covered': covered / len(rows),
                   'unavailable_reasons': dict(reasons)}
        if any(actual[key] != value for key, value in checked.items()):
            raise ValueError(f'summary disagrees with raw trials: {name}')
    reserve(output)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), sharey=True)
    for axis, key, title in zip(axes, ('availability', 'conditional_coverage'),
                               ('Interval availability', 'Coverage given availability'), strict=True):
        values = [summary['scenarios'][name][key] for name in ids]
        axis.barh(ids, [value or 0 for value in values], color='#2878a4')
        axis.set(xlim=(0, 1.18), xlabel='Proportion', title=title)
        for index, (name, value) in enumerate(zip(ids, values, strict=True)):
            row = summary['scenarios'][name]
            numerator, denominator = ((row['available'], row['trials']) if key == 'availability'
                                      else (row['covered'], row['available']))
            axis.text((value or 0) + 0.02, index, f'{numerator}/{denominator}' if denominator
                      else 'undefined', va='center', fontsize=9)
        axis.grid(axis='x', alpha=0.2)
    axes[1].axvline(0.95, color='#ba4b32', linestyle='--', label='Nominal 95%')
    axes[1].legend(loc='lower right', fontsize=9)
    axes[0].invert_yaxis()
    fig.suptitle('Synthetic development pilot: 100 datasets per scenario')
    fig.tight_layout()
    fig.savefig(output / 'coverage.png', dpi=160)
    fig.savefig(output / 'coverage.svg')
    plt.close(fig)
    encoded = base64.b64encode((output / 'coverage.png').read_bytes()).decode()
    (output / 'chart.html').write_text(
        '<!doctype html><html><head><meta charset="utf-8"></head><body>'
        f'<img alt="Synthetic bootstrap pilot" style="width:100%;height:auto" '
        f'src="data:image/png;base64,{encoded}">'
        '<p>Development only. Dense: q=1; sparse: q=0.1. K is the cluster count. '
        'Labels show actual numerators/denominators. No claim of real-data coverage. '
        'Maximum Monte Carlo SE is 0.5/sqrt(n), reaching 0.5 when n=1.</p></body></html>')
    write_json(output / 'validation.json', {
        'validated_trials': len(raw), 'source_manifest_sha256': file_hash(source / 'manifest.json'),
        'checked': ['artifact_hashes', 'trial_coverage', 'counters', 'estimates',
                    'interval_coverage', 'availability_and_coverage_summary'],
        'max_mcse_all_trials': 0.5 / math.sqrt(protocol['trials_per_scenario']),
    })


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report(args.input, args.out)
