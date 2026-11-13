"""Secondary pricing-independent audit; never infer actual subscription charges."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/opencode_benchmark/analysis'))
from full_replay_audit import audit  # noqa: E402
from aggregate_metrics import token_fields  # noqa: E402

KEYS = ('input', 'cache_read', 'cache_write', 'output', 'reasoning')
ARMS = ('plain', 'static', 'cami', 'cami_replay')


def compare(candidate, baseline):
    if set(candidate) != set(KEYS) or set(baseline) != set(KEYS):
        raise ValueError('all five disjoint normalized token components required')
    if any(type(value) is not int or value < 0 for values in (candidate, baseline) for value in values.values()):
        raise ValueError('nonnegative integer components required')
    introduced = [key for key in KEYS if baseline[key] == 0 and candidate[key] > 0]
    reductions = {key: 1 - candidate[key] / baseline[key] for key in KEYS if baseline[key] > 0}
    return {'nonincreasing': all(candidate[k] <= baseline[k] for k in KEYS),
            'strict_components': [k for k in KEYS if candidate[k] < baseline[k]],
            'introduced_components': introduced, 'fraction_reduction_by_component': reductions,
            'weighted_reduction_bounds': None if introduced or not reductions else [min(reductions.values()), max(reductions.values())]}


def analyze(root):
    verified = audit(root)
    if not verified['eligible']:
        raise ValueError('complete quality and telemetry eligibility required')
    blocks = {(rep, arm): dict.fromkeys(KEYS, 0) for rep in range(1, 6) for arm in ARMS}
    for trial in verified['trials']:
        row = trial['trial']
        directory = root / 'trials' / row['id']
        terminal = json.loads((directory / 'terminal.json').read_bytes())
        actual = dict.fromkeys(KEYS, 0) if row['expected_cache_hit'] else token_fields(json.loads((directory / 'session/evidence/usage.json').read_bytes()))
        if actual != terminal['tokens'] or any(v is None for v in actual.values()):
            raise ValueError('component evidence mismatch')
        for key in KEYS:
            blocks[row['repetition'], row['condition']][key] += actual[key]
    pairs = [{'repetition': rep, 'comparator': arm,
              'candidate': blocks[rep, 'cami_replay'], 'baseline': blocks[rep, arm],
              **compare(blocks[rep, 'cami_replay'], blocks[rep, arm])}
             for rep in range(1, 6) for arm in ARMS[:-1]]
    return {'status': 'verified', 'analysis': 'secondary_component_dominance_v1',
            'protocol_sha256': verified['protocol_sha256'], 'pairs': pairs,
            'all15_pairs_componentwise_nonincreasing': all(p['nonincreasing'] for p in pairs),
            'strict_components_in_every_pair': sorted(set.intersection(*(set(p['strict_components']) for p in pairs))),
            'statistics': {arm: {key: {'median': statistics.median(blocks[rep, arm][key] for rep in range(1, 6)),
                                      'min': min(blocks[rep, arm][key] for rep in range(1, 6)),
                                      'max': max(blocks[rep, arm][key] for rep in range(1, 6))} for key in KEYS} for arm in ARMS},
            'interpretation': 'For identical nonnegative per-component linear token rates, componentwise dominance implies no greater modeled token charge. Strict decrease needs a positive rate on a strictly reduced component. Bounds apply when baseline modeled token charge is positive; zero-baseline components must introduce no usage. No actual prices, invoice, subscription savings, request overheads or missing provider fields are inferred. Normalized OpenCode2.2.5 components are disjoint; cache_read is included. This secondary analysis does not alter the frozen primary success gate.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    with args.out.open('x') as stream:
        json.dump(analyze(args.run), stream, indent=2, sort_keys=True)
        stream.write('\n')
