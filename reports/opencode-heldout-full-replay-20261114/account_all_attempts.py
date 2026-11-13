"""Retain observed costs of every attempt; failed/missing provider usage stays unknown."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo / 'scripts/opencode_benchmark/analysis'))
from aggregate_metrics import token_fields  # noqa: E402
from aggregate_study import verify_terminal, trial_tier  # noqa: E402

KEYS = ('input','cache_read','cache_write','output','reasoning')


def analyze(root):
    protocol = json.loads((root / 'protocol.json').read_text())
    expected = {row['id'] for row in protocol['schedule']}
    if {p.name for p in (root / 'trials').iterdir()} != expected or len(expected) != 80:
        raise ValueError('all80 scheduled attempts required')
    rows = []
    for trial in protocol['schedule']:
        directory = root / 'trials' / trial['id']
        record, terminal_sha, _ = verify_terminal(directory)
        if record['trial'] != trial:
            raise ValueError('trial binding differs')
        row = {'id': trial['id'], 'condition': trial['condition'], 'status': record['status'],
               'quality': record.get('quality', 'not_run'), 'error': record.get('error'),
               'declared_model_session_attempts': record['model_calls'],
               'observed_wall_seconds': record['wall_seconds'], 'terminal_sha256': terminal_sha,
               'cache_hit': record.get('cache_hit', False), 'unknown_usage': False,
               'provider_error_responses': [], 'assistant_responses_without_tokens': [],
               'native_retry_records': 0, 'missing_tier_responses': []}
        if not record['model_calls']:
            row['normalized_tokens'] = dict.fromkeys(KEYS, 0)
        else:
            evidence = directory / 'session/evidence'
            usage = evidence / 'usage.json'
            row['normalized_tokens'] = token_fields(json.loads(usage.read_text())) if usage.exists() else dict.fromkeys(KEYS, None)
            messages_path = evidence / 'messages.json'
            if messages_path.exists():
                messages = json.loads(messages_path.read_text())
                for message in messages:
                    if message.get('type') != 'assistant':
                        continue
                    if not isinstance(message.get('tokens'), dict):
                        row['assistant_responses_without_tokens'].append(message['id'])
                    if message.get('error'):
                        row['provider_error_responses'].append({'id': message['id'], 'type': message['error'].get('type'), 'finish': message.get('finish')})
                    row['native_retry_records'] += isinstance(message.get('retry'), dict)
            else:
                row['unknown_usage'] = True
            tier_path = evidence / 'service-tier.json'
            if tier_path.exists():
                tier = json.loads(tier_path.read_text())
                row['missing_tier_responses'] = [x['message_id'] for x in tier.get('assistant_response_observations',[]) if x.get('status') != 'provider_reported']
            row['tier'] = trial_tier(directory, {'terminal_present': True})
            row['unknown_usage'] |= bool(row['assistant_responses_without_tokens']) or any(v is None for v in row['normalized_tokens'].values())
        rows.append(row)
    totals = {}
    for condition in protocol['rules']['conditions']:
        group = [r for r in rows if r['condition'] == condition]
        totals[condition] = {'attempts': len(group), 'statuses': dict(Counter(r['status'] for r in group)),
            'quality_outcomes': dict(Counter(r['quality'] for r in group)),
            'declared_model_session_attempts': sum(r['declared_model_session_attempts'] for r in group),
            'observed_normalized_token_subtotals': {key: sum(r['normalized_tokens'][key] or 0 for r in group) for key in KEYS},
            'unknown_usage_trials': [r['id'] for r in group if r['unknown_usage']],
            'observed_wall_seconds_including_failed_attempts': sum(r['observed_wall_seconds'] for r in group),
            'cache_hits': sum(r['cache_hit'] for r in group),
            'native_retry_records': sum(r['native_retry_records'] for r in group)}
    return {'status': 'verified_observed_accounting', 'trials': rows, 'totals': totals,
            'scope': 'All scheduled attempts retained, including failures. Known normalized token subtotals are not estimates of missing provider usage or invoices. Native automatic retry records are counted separately from controller session attempts; no controller trial was repeated. Failed trial wall can end before capture/grading, so these observed sums are not complete comparable pipeline totals. Primary eligibility/decision is unchanged.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('out', type=Path)
    args = parser.parse_args()
    with args.out.open('x') as stream:
        json.dump(analyze(args.run), stream, indent=2, sort_keys=True)
        stream.write('\n')
