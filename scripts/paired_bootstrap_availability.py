"""Conditional paired-bootstrap availability for fixed denominator support sets.

Exact inclusion-exclusion for one resample; Decimal arithmetic for finite B.
This development analysis changes neither the estimator nor admission rules.
"""
from __future__ import annotations

import argparse
import base64
import csv
from decimal import Decimal, localcontext
from fractions import Fraction
import json
from pathlib import Path

from scripts.verify_cami import source_snapshot

ROOT = Path(__file__).resolve().parents[1]


def bad_resample_probability(clusters: int, left: int, right: int, joint: int) -> Fraction:
    if (any(type(v) is not int for v in (clusters, left, right, joint)) or clusters < 2
            or not 0 <= left <= clusters or not 0 <= right <= clusters
            or not max(0, left + right - clusters) <= joint <= min(left, right)):
        raise ValueError('Require integer K>=2 and feasible marginal/joint support counts')
    return (Fraction(clusters - left, clusters) ** clusters
            + Fraction(clusters - right, clusters) ** clusters
            - Fraction(clusters - left - right + joint, clusters) ** clusters)


def conditional(clusters: int, left: int, right: int, joint: int, repetitions: int) -> dict:
    bad = bad_resample_probability(clusters, left, right, joint)
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError('Repetitions must be a positive integer')
    with localcontext() as context:
        context.prec = 100
        good = 1 - bad
        defined = bool(left and right)
        available = (Decimal(good.numerator) / Decimal(good.denominator)) ** repetitions if defined else Decimal(0)
        return {'single_bad_numerator': bad.numerator, 'single_bad_denominator': bad.denominator,
                'single_valid_numerator': good.numerator, 'single_valid_denominator': good.denominator,
                'sample_estimate_defined': defined, 'available': str(available),
                'zero_sample': str(Decimal(not defined)),
                'zero_resample': str(1 - available if defined else Decimal(0)),
                'precision': context.prec}


def load_protocol(path: Path) -> dict:
    plan = json.loads(path.read_text())
    if plan['analysis_kind'] != 'post_pilot_conditional_paired_denominator_support':
        raise ValueError('Unsupported analysis kind')
    scenarios, repetitions = plan['scenarios'], plan['bootstrap_repetitions']
    if not scenarios or len({s['id'] for s in scenarios}) != len(scenarios):
        raise ValueError('Scenarios must be nonempty and unique')
    if not repetitions or repetitions != sorted(set(repetitions)):
        raise ValueError('Repetitions must be nonempty, unique and increasing')
    for scenario in scenarios:
        for count in repetitions:
            conditional(scenario['clusters'], scenario['left_nonzero'], scenario['right_nonzero'],
                        scenario['joint_nonzero'], count)
    return plan


def plot(rows: list[dict], out: Path) -> None:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    styles = [('shared', 'Complete overlap', '#2166ac'),
              ('partial', 'Partial overlap', '#1b7837'),
              ('disjoint', 'Disjoint support', '#b2182b')]
    for axis, prefix, count in zip(axes, ('sparse', 'moderate'), (2, 8), strict=True):
        for suffix, label, color in styles:
            series = [r for r in rows if r['id'] == prefix + '-' + suffix]
            axis.plot([r['repetitions'] for r in series], [float(r['available']) for r in series],
                      marker='o', label=label, color=color)
        axis.set_xscale('log')
        axis.set_xlabel('Bootstrap repetitions B')
        axis.set_ylabel('P(interval available | support sets)')
        axis.set_title(f'K=20, L=R={count}')
        axis.grid(alpha=.25)
    axes[0].set_yscale('log')
    axes[0].set_title('K=20, L=R=2 (log probability scale)')
    axes[1].set_ylim(.8, 1.005)
    axes[1].legend(fontsize=8)
    figure.suptitle('Support overlap affects availability, not evidence of coverage')
    figure.tight_layout()
    figure.savefig(out / 'availability.png', dpi=180)
    figure.savefig(out / 'availability.svg')
    plt.close(figure)
    encoded = base64.b64encode((out / 'availability.png').read_bytes()).decode()
    (out / 'availability.html').write_text(
        '<!doctype html><meta charset="utf-8"><body style="margin:0;background:transparent">'
        '<img style="width:100%;height:auto" alt="Conditional bootstrap availability by support overlap" '
        f'src="data:image/png;base64,{encoded}"></body>')


def run(protocol: Path, out: Path) -> None:
    from cami.artifacts import file_hash, reserve, write_json

    plan = load_protocol(protocol)
    if out.resolve().is_relative_to(protocol.resolve().parent):
        raise ValueError('Output must be outside the protocol directory')
    before = source_snapshot(ROOT)
    if before['source_status']:
        raise ValueError('Commit source changes before the analysis')
    reserve(out)
    manifest = {'status': 'running', 'source_before': before, 'protocol_sha256': file_hash(protocol),
                'scope': plan['analysis_kind'], 'decimal_precision': 100,
                'random_datasets_generated': 0, 'changes_to_production_estimator': False}
    write_json(out / 'manifest.json', manifest)
    try:
        (out / 'protocol.json').write_bytes(protocol.read_bytes())
        rows = []
        for scenario in plan['scenarios']:
            for count in plan['bootstrap_repetitions']:
                values = conditional(scenario['clusters'], scenario['left_nonzero'], scenario['right_nonzero'],
                                     scenario['joint_nonzero'], count)
                rows.append({**scenario, 'repetitions': count, **values})
        write_json(out / 'results.json', {'rows': rows})
        with (out / 'availability.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        plot(rows, out)
        after = source_snapshot(ROOT)
        manifest.update(source_after=after, source_snapshots_match=before == after, rows=len(rows))
        assert before == after
        assert file_hash(protocol) == manifest['protocol_sha256']
        manifest['status'] = 'complete'
    except Exception as exc:
        manifest.update(status='failed', failure={'type': type(exc).__name__, 'message': str(exc)})
        raise
    finally:
        manifest['artifact_hashes'] = {p.name: file_hash(p) for p in sorted(out.iterdir())
                                       if p.is_file() and p.name != 'manifest.json'}
        write_json(out / 'manifest.json', manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path,
                        default=ROOT / 'examples/bootstrap_study/paired_support_protocol.json')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    run(args.protocol, args.out)
