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


def _same_number(actual, expected) -> bool:
    if expected is None:
        return actual is None
    return (type(actual) in (int, float) and math.isfinite(actual)
            and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-15))


def validate_study(source: Path):
    """Check saved outputs against raw counts and the declared generator's analytic truth.

    This does not regenerate random datasets or recompute bootstrap quantiles.
    """
    manifest = read_json(source / 'manifest.json')
    if manifest['status'] != 'complete':
        raise ValueError('study is incomplete')
    for name in ('protocol.json', 'trials.jsonl', 'summary.json'):
        if file_hash(source / name) != manifest['artifact_hashes'][name]:
            raise ValueError(f'artifact hash mismatch: {name}')
    protocol = read_json(source / 'protocol.json')
    summary = read_json(source / 'summary.json')
    raw = read_jsonl(source / 'trials.jsonl')
    if protocol['generator'] != 'paired_nested_bernoulli_v1':
        raise ValueError('unsupported generator for independent report validation')
    probabilities = protocol['left_probabilities']
    multiplier = protocol['right_probability_multiplier']
    sizes = protocol['cluster_sizes']
    trials = protocol['trials_per_scenario']
    repetitions = protocol['bootstrap_repetitions']
    scenarios = protocol['scenarios']
    if (not probabilities or any(type(p) not in (int, float) or not 0 <= p <= 1 for p in probabilities)
            or type(multiplier) not in (int, float) or not 0 <= multiplier <= 1
            or not sizes or any(type(n) is not int or n < 1 for n in sizes)
            or type(trials) is not int or trials < 1
            or type(repetitions) is not int or repetitions < 1 or not scenarios):
        raise ValueError('invalid generator parameters')
    truth = math.fsum(probabilities) / len(probabilities) * (1 - multiplier)
    if not _same_number(summary['truth'], truth) or not _same_number(manifest['truth'], truth):
        raise ValueError('truth disagrees with independent generator formula')
    if summary['truth'] != manifest['truth']:
        raise ValueError('summary and manifest disagree on the recorded truth')
    if (manifest['study_id'] != protocol['study_id']
            or manifest['protocol_sha256'] != file_hash(source / 'protocol.json')):
        raise ValueError('manifest disagrees with protocol identity')
    ids = [scenario['id'] for scenario in scenarios]
    if (len(set(ids)) != len(ids) or any(not isinstance(name, str) or not name for name in ids)
            or set(summary['scenarios']) != set(ids)):
        raise ValueError('invalid or inconsistent scenario identities')
    expected = {(name, trial) for name in ids for trial in range(trials)}
    if (len(raw) != len(expected) or {(r['scenario'], r['trial']) for r in raw} != expected
            or any(type(r['trial']) is not int for r in raw)):
        raise ValueError('missing or duplicate trials')
    for scenario in scenarios:
        name, clusters = scenario['id'], scenario['clusters']
        active = scenario['active_probability']
        if (type(clusters) is not int or clusters < 2 or type(active) not in (int, float)
                or not 0 < active <= 1):
            raise ValueError('invalid scenario parameters')
        rows = [r for r in raw if r['scenario'] == name]
        available = covered = 0
        reasons: Counter[str] = Counter()
        estimates, widths, undefined_probabilities = [], [], []
        keys = {str(index) for index in range(clusters)}
        for row in rows:
            if set(row['left']) != keys or set(row['right']) != keys:
                raise ValueError('paired cluster identities disagree with protocol')
            for key in keys:
                left, right = row['left'][key], row['right'][key]
                if (len(left) != 2 or len(right) != 2
                        or any(type(value) is not int for value in (*left, *right))
                        or not 0 <= right[0] <= left[0] <= left[1]
                        or left[1] != right[1] or left[1] not in (0, *sizes)):
                    raise ValueError('invalid paired nested Bernoulli counters')
                if left[1] and not any(
                    (right[0] == 0 or probability * multiplier > 0)
                    and (left[0] == right[0] or probability > probability * multiplier)
                    and (left[0] == left[1] or probability < 1)
                    for probability in probabilities
                ):
                    raise ValueError('counters are impossible under the declared generator')
            empty = sum(den == 0 for _, den in row['left'].values())
            if (type(row['empty_clusters']) is not int or row['empty_clusters'] != empty
                    or (active == 1 and empty != 0)):
                raise ValueError('empty-cluster diagnostics disagree with raw counters')
            # Counts determine the empty-resample probability independently of CAMI.
            single = (empty / clusters) ** clusters
            probability = 1.0 if single == 1 else -math.expm1(repetitions * math.log1p(-single))
            if not _same_number(row['probability_undefined_resample'], probability):
                raise ValueError('undefined-resample probability disagrees with analytic formula')
            undefined_probabilities.append(probability)
            ld = sum(den for _, den in row['left'].values())
            rd = sum(den for _, den in row['right'].values())
            estimate = (sum(num for num, _ in row['left'].values()) / ld
                        - sum(num for num, _ in row['right'].values()) / rd) if ld and rd else None
            interval = row['interval']
            if not _same_number(interval['estimate'], estimate):
                raise ValueError('estimate disagrees with raw counts')
            if estimate is not None:
                estimates.append(estimate)
            if interval['clusters'] != clusters or interval['repetitions'] != repetitions:
                raise ValueError('interval dimensions disagree with protocol')
            support = interval.get('denominator_support')
            expected_support = {'schema_version': 1, 'left_nonzero_clusters': clusters - empty,
                                'right_nonzero_clusters': clusters - empty,
                                'joint_nonzero_clusters': clusters - empty}
            if support is not None and support != expected_support:
                raise ValueError('denominator support disagrees with raw counters')
            lo, hi = interval['lower'], interval['upper']
            if (lo is None) != (hi is None):
                raise ValueError('partial interval')
            if lo is None:
                reason = 'zero_denominator' if empty == clusters else 'zero_denominator_in_resample'
                if interval['reason'] != reason or empty == 0 or row['covered'] is not None:
                    raise ValueError('unavailable interval contradicts denominator diagnostics')
                reasons[reason] += 1
            else:
                if (type(lo) not in (int, float) or type(hi) not in (int, float)
                        or not 0 <= lo <= hi <= 1 or estimate is None):
                    raise ValueError('invalid interval bounds')
                available += 1
                # Use the independently verified saved float at exact interval boundaries.
                correct = lo <= summary['truth'] <= hi
                covered += correct
                if row['covered'] is not correct or interval['reason'] is not None:
                    raise ValueError('inconsistent interval coverage')
                widths.append(hi - lo)
        actual = summary['scenarios'][name]
        counts = {'trials': len(rows), 'available': available, 'covered': covered,
                  'defined_estimates': len(estimates), 'unavailable_reasons': dict(reasons)}
        numbers = {'availability': available / len(rows),
                   'conditional_coverage': covered / available if available else None,
                   'joint_available_and_covered': covered / len(rows),
                   'mean_width_when_available': math.fsum(widths) / available if available else None,
                   'bias_when_estimate_defined': math.fsum(estimates) / len(estimates) - truth if estimates else None,
                   'max_mcse_unconditional': 0.5 / math.sqrt(len(rows)),
                   'max_mcse_conditional': 0.5 / math.sqrt(available) if available else None,
                   'expected_unavailable_count': math.fsum(undefined_probabilities)}
        if (set(actual) != set(counts) | set(numbers)
                or any(type(actual[key]) is not type(value) or actual[key] != value
                       for key, value in counts.items())
                or any(not _same_number(actual[key], value) for key, value in numbers.items())):
            raise ValueError(f'summary disagrees with raw trials: {name}')
    return protocol, summary, raw


def report(source: Path, output: Path) -> None:
    protocol, summary, raw = validate_study(source)
    ids = [scenario['id'] for scenario in protocol['scenarios']]
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
    fig.suptitle(f"Synthetic development pilot: {protocol['trials_per_scenario']} datasets per scenario")
    fig.tight_layout()
    fig.savefig(output / 'coverage.png', dpi=160)
    fig.savefig(output / 'coverage.svg')
    plt.close(fig)
    encoded = base64.b64encode((output / 'coverage.png').read_bytes()).decode()
    (output / 'chart.html').write_text(
        '<!doctype html><html><head><meta charset="utf-8"></head><body>'
        f'<img alt="Synthetic bootstrap pilot" style="width:100%;height:auto" '
        f'src="data:image/png;base64,{encoded}">'
        '<p>Development only. Cluster counts K and active probabilities q are declared in protocol.json. '
        'Labels show actual numerators/denominators. No claim of real-data coverage. '
        'Maximum Monte Carlo SE is 0.5/sqrt(n), reaching 0.5 when n=1.</p></body></html>')
    write_json(output / 'validation.json', {
        'validated_trials': len(raw), 'source_manifest_sha256': file_hash(source / 'manifest.json'),
        'reporter_sha256': file_hash(Path(__file__)), 'matplotlib_version': matplotlib.__version__,
        'checked': ['artifact_hashes', 'trial_coverage', 'counters', 'estimates',
                    'interval_coverage', 'all_summary_fields', 'independent_generator_truth',
                    'paired_cluster_population', 'generator_counter_support', 'empty_denominator_probabilities',
                    'interval_dimensions_and_denominator_support'],
        'float_comparison_tolerance': {'relative': 1e-12, 'absolute': 1e-15},
        'coverage_truth': 'saved truth after independent analytic check within recorded tolerance',
        'not_checked': ['random-stream reproduction', 'bootstrap quantile recomputation'],
        'max_mcse_all_trials': 0.5 / math.sqrt(protocol['trials_per_scenario']),
    })


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report(args.input, args.out)
