"""Independent artifact and arithmetic audit of all80 full-study attempts."""
from __future__ import annotations

import argparse
import statistics
from pathlib import Path

from aggregate_metrics import token_fields
from aggregate_study import read, sha, verify_terminal, trial_tier, write

CONDITIONS = ('plain', 'static', 'cami', 'cami_replay')


def audit(root):
    protocol, summary = read(root / 'protocol.json'), read(root / 'summary.json')
    design = protocol['rules']['design']
    if design not in {'full-cami-result-memory-development-v2', 'full-cami-result-memory-heldout-v1', 'result-memory-ablation-development-v1'} or summary['rules'] != protocol['rules']:
        raise ValueError('unsupported protocol')
    if protocol['rules']['design'].endswith('heldout-v1'):
        if protocol['runtime']['bundle_kind'] != 'heldout' or any(t.get('candidate_root') != 'src/packaging' for t in protocol['runtime']['normalized']['tasks']):
            raise ValueError('heldout source boundary differs')
    arms = ('cami_replay', 'plain_replay') if design == 'result-memory-ablation-development-v1' else CONDITIONS
    if protocol['rules']['conditions'] != list(arms):
        raise ValueError('registered conditions differ')
    sequence = protocol['runtime']['normalized']['sequence']
    expected = []
    for rep in range(1, 6):
        for stage, task in enumerate(sequence, 1):
            offset = (rep + stage - 2) % len(arms)
            for condition in arms[offset:] + arms[:offset]:
                expected.append({'id': f'r{rep}-{condition}-s{stage}', 'condition': condition,
                    'arm': condition.removesuffix('_replay'),
                    'repetition': rep, 'stage': stage, 'task': task,
                    'expected_cache_hit': condition.endswith('_replay') and stage in (2, 4)})
    if len(expected) != len(arms) * 20 or protocol['schedule'] != expected:
        raise ValueError('changed schedule')
    if {p.name for p in (root / 'trials').iterdir()} != {t['id'] for t in expected}:
        raise ValueError('missing or unexpected attempts')
    rows, learned, tiers = [], {}, set()
    for trial in expected:
        directory = root / 'trials' / trial['id']
        record, terminal_sha, files = verify_terminal(directory)
        if record['trial'] != trial:
            raise ValueError('terminal schedule mismatch')
        row = {'trial': trial, 'terminal_sha256': terminal_sha, 'verified_artifacts': files,
               'passed': record['status'] == 'passed', 'wall_seconds': record['wall_seconds'], 'token_work': None}
        if row['passed']:
            grade = read(directory / 'evaluation/report.json')
            if grade['status'] != 'pass' or not grade['fixed_tests_restored'] or grade['agent_tests_scored']:
                raise ValueError('invalid grade binding')
            if protocol['runtime']['bundle_kind'] == 'heldout':
                canonical = read(directory / 'canonical-reset.json')['canonical_files']
                expected_outside = {name[4:]: row['sha256'] for name, row in canonical.items()
                                    if name.startswith('src/') and not name.startswith('src/packaging/')}
                actual_outside = {name: value for name, value in grade['source_files'].items()
                                  if not name.startswith('packaging/')}
                if expected_outside != actual_outside:
                    raise ValueError('heldout source escaped package boundary')
            for outcome in grade['outcomes'].values():
                if outcome['exit_code'] or outcome['counts']['failed'] or outcome['counts']['errors'] or not outcome['counts']['executed']:
                    raise ValueError('invalid quality outcome')
            key = (trial['repetition'], trial['condition'], trial['task'])
            hit = trial['expected_cache_hit']
            if record['cache_hit'] != hit or record['model_calls'] != int(not hit):
                raise ValueError('unexpected hit or model call count')
            if hit:
                if (directory / 'session').exists() or any(record['tokens'].values()):
                    raise ValueError('hit has model activity')
                previous = learned.get(key)
                if previous is None or previous['sources'] != grade['source_files'] or previous['key'] != read(directory / 'lookup.json')['key']:
                    raise ValueError('hit source/key not learned in same block/condition')
                row['token_work'] = 0
            else:
                tokens = token_fields(read(directory / 'session/evidence/usage.json'))
                if tokens != record['tokens'] or any(v is None for v in tokens.values()):
                    raise ValueError('token evidence differs')
                row['token_work'] = sum(tokens[k] for k in ('input', 'cache_write', 'output', 'reasoning'))
                tier = trial_tier(directory, {'terminal_present': True})
                if not tier['configuration_valid'] or not tier['provider_reported_complete']:
                    raise ValueError('tier evidence incomplete')
                tiers.update(tier['provider_reported_values'])
                if trial['condition'].endswith('_replay'):
                    learned[key] = {'sources': grade['source_files'], 'key': read(directory / 'record.json')['key']}
            if row['token_work'] != record['token_work']:
                raise ValueError('token arithmetic differs')
        rows.append(row)
    blocks = []
    for rep in range(1, 6):
        for condition in arms:
            members = [r for r in rows if r['trial']['repetition'] == rep and r['trial']['condition'] == condition]
            complete = len(members) == 4 and all(r['passed'] for r in members)
            blocks.append({'repetition': rep, 'condition': condition, 'complete': complete,
                'token_work': sum(r['token_work'] for r in members) if complete else None,
                'charged_wall_seconds': summary['shared_preflight_wall_seconds'] / (5 * len(arms)) + sum(r['wall_seconds'] for r in members) if complete else None})
    pairs = []
    for rep in range(1, 6):
        lookup = {b['condition']: b for b in blocks if b['repetition'] == rep}
        for comparator in arms[:-1]:
            pairs.append({'repetition': rep, 'comparator': comparator, **{
                k: lookup[arms[-1]][k] < lookup[comparator][k] if lookup[arms[-1]][k] is not None and lookup[comparator][k] is not None else None
                for k in ('token_work', 'charged_wall_seconds')}})
    probes = read(root / 'guard-probes.json')
    expected_probes = {(rep, condition, task) for rep in range(1, 6) for condition in arms if condition.endswith('_replay') for task in set(sequence)}
    if len(probes['probes']) != len(expected_probes) or {(p['repetition'], p.get('condition', 'cami_replay'), p['task']) for p in probes['probes']} != expected_probes:
        raise ValueError('changed-input probe coverage differs')
    probe_passed = all(p['status'] == 'miss' and p['output_absent'] and p['control_status'] == 'candidate_requires_grading' for p in probes['probes'])
    if probes['passed'] != probe_passed or summary['guard_probes_passed'] != probe_passed:
        raise ValueError('probe status differs')
    eligible = all(b['complete'] for b in blocks) and len(tiers) == 1 and probe_passed
    supported = eligible and all(p[k] is True for p in pairs for k in ('token_work', 'charged_wall_seconds'))
    if blocks != summary['blocks'] or pairs != summary['pairs'] or eligible != summary['eligible'] or supported != summary['direction_supported']:
        raise ValueError('primary aggregation differs')
    stats = {}
    for condition in arms:
        stats[condition] = {}
        for metric in ('token_work', 'charged_wall_seconds'):
            values = [b[metric] for b in blocks if b['condition'] == condition and b[metric] is not None]
            stats[condition][metric] = {'complete_blocks': len(values), 'median': statistics.median(values) if values else None,
                'min': min(values) if values else None, 'max': max(values) if values else None, 'values': values}
    return {'status': 'verified', 'protocol_sha256': sha(root / 'protocol.json'), 'eligible': eligible,
        'direction_supported': supported, 'blocks': blocks, 'pairs': pairs, 'statistics': stats, 'trials': rows,
        'scope': 'Five independent local memory initializations, not independent new tasks. Canonical exact repeats and source transition only. Wall arithmetic verified; no independent host-quietness proof.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    write(args.out, audit(args.run.resolve()))
