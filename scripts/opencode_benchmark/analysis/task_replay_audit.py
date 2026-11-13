"""Independent evidence checks for the frozen exact-repeat development block."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

from aggregate_metrics import token_fields
from aggregate_study import read, sha, verify_terminal, trial_tier, write

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'integrations/opencode'))
from task_replay import inventory  # noqa: E402


def audit(root):
    protocol = read(root / 'protocol.json')
    summary = read(root / 'summary.json')
    if protocol['rules']['design'] != 'exact-task-replay-development-v1' or summary['rules'] != protocol['rules']:
        raise ValueError('unsupported or inconsistent protocol')
    sequence = protocol['runtime']['normalized']['sequence']
    expected = []
    for stage, task in enumerate(sequence, 1):
        for condition in (('plain', 'exact_replay') if stage % 2 else ('exact_replay', 'plain')):
            expected.append({'id': f'{condition}-s{stage}', 'condition': condition, 'stage': stage,
                'task': task, 'expected_cache_hit': condition == 'exact_replay' and stage in (2, 4)})
    if len(expected) != 8 or protocol['schedule'] != expected or len(summary['records']) != 8:
        raise ValueError('incomplete or altered schedule')
    observed, tiers, learned = [], set(), {}
    for scheduled, claimed in zip(expected, summary['records']):
        directory = root / scheduled['id']
        terminal, terminal_sha, artifact_count = verify_terminal(directory)
        if terminal != claimed or terminal['trial'] != scheduled or terminal['status'] != 'passed':
            raise ValueError('terminal identity/status differs')
        hit = scheduled['expected_cache_hit']
        if terminal['cache_hit'] != hit or terminal['model_calls'] != (0 if hit else 1):
            raise ValueError('model-call accounting differs from schedule')
        grade = read(directory / 'evaluation/report.json')
        if grade['status'] != 'pass' or not grade['fixed_tests_restored'] or grade['agent_tests_scored']:
            raise ValueError('quality evidence invalid')
        for name in ('acceptance', 'regression'):
            outcome = grade['outcomes'][name]
            if outcome['exit_code'] != 0 or outcome['counts']['failed'] or outcome['counts']['errors']:
                raise ValueError('fixed test outcome invalid')
        sources = {name: record['sha256'] for name, record in inventory(directory / 'candidate/src').items()}
        if sources != grade['source_files']:
            raise ValueError('graded source differs from candidate')
        if hit:
            if (directory / 'session').exists() or terminal['tokens'] != dict.fromkeys(terminal['tokens'], 0):
                raise ValueError('hit unexpectedly has model evidence or token cost')
            prior = learned.get(scheduled['task'])
            if prior is None or prior['sources'] != sources:
                raise ValueError('hit does not reproduce same-condition earlier learned source')
            if read(directory / 'lookup.json')['key'] != prior['key']:
                raise ValueError('hit key differs from learned result')
            token_work = 0
        else:
            session = read(directory / 'session/manifest.json')
            for name, expected_sha in session['artifact_hashes'].items():
                if sha(directory / 'session' / name) != expected_sha:
                    raise ValueError('session hash mismatch')
            fields = token_fields(read(directory / 'session/evidence/usage.json'))
            if fields != terminal['tokens'] or any(v is None for v in fields.values()):
                raise ValueError('token evidence differs')
            token_work = sum(fields[k] for k in ('input', 'cache_write', 'output', 'reasoning'))
            tier = trial_tier(directory, {'terminal_present': True})
            if not tier['configuration_valid'] or not tier['provider_reported_complete']:
                raise ValueError('tier evidence incomplete')
            tiers.update(tier['provider_reported_values'])
            if scheduled['condition'] == 'exact_replay':
                learned[scheduled['task']] = {'sources': sources, 'key': read(directory / 'record.json')['key']}
        if token_work != terminal['token_work']:
            raise ValueError('token arithmetic differs')
        if not isinstance(terminal['wall_seconds'], (int, float)) or not math.isfinite(terminal['wall_seconds']) or terminal['wall_seconds'] < 0:
            raise ValueError('invalid measured duration')
        observed.append({'trial': scheduled, 'terminal_sha256': terminal_sha,
                         'verified_artifacts': artifact_count, 'token_work': token_work,
                         'wall_seconds': terminal['wall_seconds']})
    blocks = {}
    for condition in ('plain', 'exact_replay'):
        members = [r for r in observed if r['trial']['condition'] == condition]
        blocks[condition] = {'complete': True, 'token_work': sum(r['token_work'] for r in members),
            'charged_wall_seconds': summary['shared_preflight_wall_seconds'] / 2 + sum(r['wall_seconds'] for r in members)}
    supported = len(tiers) == 1 and all(blocks['exact_replay'][k] < blocks['plain'][k]
                                      for k in ('token_work', 'charged_wall_seconds'))
    if blocks != summary['blocks'] or summary['direction_supported'] != supported or summary['model_calls'] != 6:
        raise ValueError('primary summary arithmetic differs')
    return {'status': 'verified', 'protocol_sha256': sha(root / 'protocol.json'), 'blocks': blocks,
        'direction_supported': supported, 'provider_reported_tiers': sorted(tiers), 'trials': observed,
        'scope': 'Exact repeated tasks with fresh grading. First-solution and recording costs included. Measured pipeline durations verified arithmetically, not an independent clock or host-quietness audit. No inference for changed-input reuse or general task distributions.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    write(args.out, audit(args.run.resolve()))
