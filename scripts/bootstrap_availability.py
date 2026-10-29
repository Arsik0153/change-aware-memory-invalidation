"""Exact availability probabilities for the frozen synthetic bootstrap generator."""
from __future__ import annotations

import argparse
import base64
import csv
import math
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

from cami.artifacts import file_hash, read_json, read_jsonl, reserve, write_json

ROOT = Path(__file__).resolve().parents[1]


def conditional(clusters: int, empty: int, repetitions: int) -> dict[str, float]:
    """Average over bootstrap draws, conditional on the dataset's empty clusters."""
    if (type(clusters) is not int or clusters < 2 or type(empty) is not int
            or not 0 <= empty <= clusters or type(repetitions) is not int or repetitions < 1):
        raise ValueError('require K>=2, 0<=Z<=K, B>=1 as integers')
    if empty == clusters:
        return {'available': 0.0, 'zero_sample': 1.0, 'zero_resample': 0.0, 'iterations': 0.0}
    single = (empty / clusters) ** clusters
    log_survival = repetitions * math.log1p(-single)
    failure = -math.expm1(log_survival)
    return {'available': math.exp(log_survival), 'zero_sample': 0.0,
            'zero_resample': failure,
            'iterations': failure / single if single else float(repetitions)}


def population(clusters: int, active_probability: float, repetitions: int) -> dict[str, float]:
    """Average over independent activity assignments and independent bootstrap draws."""
    conditional(clusters, 0, repetitions)
    if type(active_probability) not in (int, float) or not 0 <= active_probability <= 1:
        raise ValueError('q must be in [0,1]')
    terms = []
    masses = []
    for empty in range(clusters + 1):
        mass = (math.comb(clusters, empty) * (1 - active_probability) ** empty
                * active_probability ** (clusters - empty))
        masses.append(mass)
        terms.append((mass, conditional(clusters, empty, repetitions)))
    if not math.isclose(math.fsum(masses), 1.0, abs_tol=1e-12):
        raise ValueError('binomial probability mass lost numerical normalization')
    result = {key: math.fsum(mass * values[key] for mass, values in terms)
              for key in ('available', 'zero_sample', 'zero_resample', 'iterations')}
    if not math.isclose(sum(result[key] for key in ('available', 'zero_sample', 'zero_resample')),
                        1.0, abs_tol=1e-12):
        raise ValueError('outcome probabilities lost numerical normalization')
    return result


def saved_pilot(source: Path, scenarios: list[dict]) -> tuple[list[dict], str]:
    manifest = read_json(source / 'manifest.json')
    if manifest['status'] != 'complete':
        raise ValueError('pilot source is incomplete')
    for name in ('protocol.json', 'trials.jsonl', 'summary.json'):
        if file_hash(source / name) != manifest['artifact_hashes'][name]:
            raise ValueError(f'pilot source hash mismatch: {name}')
    protocol = read_json(source / 'protocol.json')
    if protocol['generator'] != 'paired_nested_bernoulli_v1' or protocol['scenarios'] != scenarios:
        raise ValueError('pilot generator or scenarios differ from sensitivity protocol')
    raw = read_jsonl(source / 'trials.jsonl')
    count = protocol['trials_per_scenario']
    identities = {(s['id'], trial) for s in scenarios for trial in range(count)}
    if len(raw) != len(identities) or {(r['scenario'], r['trial']) for r in raw} != identities:
        raise ValueError('missing or duplicate pilot datasets')
    repetitions = protocol['bootstrap_repetitions']
    rows = []
    for scenario in scenarios:
        values = [r for r in raw if r['scenario'] == scenario['id']]
        probabilities = []
        available = 0
        for row in values:
            left, right = row['left'], row['right']
            keys = {str(i) for i in range(scenario['clusters'])}
            if set(left) != keys or set(right) != keys:
                raise ValueError('pilot cluster identities differ from protocol')
            if any(left[k][1] != right[k][1] or left[k][1] < 0 for k in keys):
                raise ValueError('pilot denominator pairing is incompatible')
            empty = sum(left[k][1] == 0 for k in keys)
            probabilities.append(conditional(scenario['clusters'], empty, repetitions)['available'])
            lower, upper = row['interval']['lower'], row['interval']['upper']
            if (lower is None) != (upper is None):
                raise ValueError('partial pilot interval')
            available += lower is not None
        theory = population(scenario['clusters'], scenario['active_probability'], repetitions)
        rows.append({'scenario': scenario['id'], 'repetitions': repetitions, 'datasets': len(values),
                     'observed_available': available, 'observed_availability': available / len(values),
                     'expected_available_given_saved_datasets': math.fsum(probabilities),
                     'expected_available_under_generator': len(values) * theory['available'],
                     'population_availability': theory['available']})
    return rows, file_hash(source / 'manifest.json')


def run(protocol_path: Path, output: Path) -> None:
    protocol = read_json(protocol_path)
    if (protocol['analysis_kind'] != 'post_pilot_exact_probability_sensitivity'
            or protocol['generator'] != 'paired_nested_bernoulli_v1'):
        raise ValueError('unsupported sensitivity protocol')
    scenarios, repetitions = protocol['scenarios'], protocol['bootstrap_repetitions']
    if not scenarios or len({s['id'] for s in scenarios}) != len(scenarios):
        raise ValueError('scenarios must be nonempty and unique')
    if not repetitions or repetitions != sorted(set(repetitions)):
        raise ValueError('repetitions must be nonempty, unique, and increasing')
    rows = []
    for scenario in scenarios:
        if not 0 < scenario['active_probability'] <= 1:
            raise ValueError('study requires q>0 for a defined population estimand')
        for count in repetitions:
            values = population(scenario['clusters'], scenario['active_probability'], count)
            rows.append({'scenario': scenario['id'], 'clusters': scenario['clusters'],
                         'active_probability': scenario['active_probability'], 'repetitions': count,
                         'population_availability': values['available'],
                         'zero_sample_denominator_probability': values['zero_sample'],
                         'zero_resample_denominator_probability': values['zero_resample'],
                         'expected_resample_iterations': values['iterations'],
                         'availability_limit_as_B_grows': scenario['active_probability'] ** scenario['clusters']})
    comparison, pilot_hash = saved_pilot(ROOT / protocol['simulation_source'], scenarios)
    reserve(output)
    (output / 'protocol.json').write_bytes(protocol_path.read_bytes())
    for name, records in [('availability.csv', rows), ('pilot_comparison.csv', comparison)]:
        with (output / name).open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    write_json(output / 'results.json', {'rows': rows, 'pilot_comparison': comparison})
    fig, axis = plt.subplots(figsize=(9, 5))
    dense = []
    for scenario in scenarios:
        if scenario['active_probability'] == 1:
            dense.append(str(scenario['clusters']))
            continue
        values = [r for r in rows if r['scenario'] == scenario['id']]
        axis.plot(repetitions, [r['population_availability'] for r in values], marker='o',
                  label=f"K={scenario['clusters']}, q={scenario['active_probability']}")
    if dense:
        axis.plot(repetitions, [1] * len(repetitions), linestyle='--', color='black',
                  label=f"q=1, K={','.join(dense)}")
    axis.set(xscale='log', yscale='log', xlabel='Requested bootstrap repetitions B',
             ylabel='Exact P(interval available)',
             title='Synthetic generator: interval availability under any-empty-resample failure')
    axis.grid(alpha=0.25)
    axis.legend()
    fig.tight_layout()
    fig.savefig(output / 'availability.png', dpi=180)
    fig.savefig(output / 'availability.svg')
    plt.close(fig)
    encoded = base64.b64encode((output / 'availability.png').read_bytes()).decode()
    (output / 'chart.html').write_text('<!doctype html><html><head><meta charset="utf-8"></head><body>'
        f'<img style="width:100%;height:auto" alt="Exact synthetic interval availability" src="data:image/png;base64,{encoded}">'
        '<p>Exact probabilities under the declared synthetic generator, not empirical coverage. '
        'Both axes are logarithmic. More repetitions can reveal an undefined resample; '
        'this is not a recommendation to reduce B or evidence of real-policy effectiveness.</p></body></html>')
    write_json(output / 'manifest.json', {'status': 'complete', 'study_id': protocol['study_id'],
        'calculation': 'finite binomial mixture; no new Monte Carlo sampling',
        'protocol_sha256': file_hash(protocol_path), 'script_sha256': file_hash(Path(__file__)),
        'git_head': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
        'python': sys.version, 'matplotlib_version': matplotlib.__version__,
        'pilot_manifest_sha256': pilot_hash, 'rows': len(rows),
        'limitations': ['Identical positive paired denominators in active clusters.',
                        'Exact for the declared ideal independent sampling model.',
                        'No coverage calibration, runtime benchmark, or real-data inference.'],
        'artifact_hashes': {p.name: file_hash(p) for p in sorted(output.iterdir()) if p.is_file()}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path, default=ROOT / 'examples/bootstrap_study/availability_protocol.json')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    run(args.protocol, args.out)
