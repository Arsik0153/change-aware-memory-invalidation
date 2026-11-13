"""Post-hoc bounds with unknown baseline usage; never change the primary verdict."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / 'scripts/opencode_benchmark/analysis'),
               str(REPO / 'reports/opencode-full-replay-20261114'),
               str(REPO / 'integrations/opencode')]
from full_replay_audit import audit  # noqa: E402
from aggregate_metrics import token_fields  # noqa: E402
from audit_token_components import compare, KEYS  # noqa: E402
from task_replay import inventory  # noqa: E402


def read(path):
    return json.loads(path.read_bytes())


def analyze(root):
    primary = audit(root)
    protocol, summary = read(root / 'protocol.json'), read(root / 'summary.json')
    if protocol['rules']['design'] != 'full-cami-result-memory-heldout-v1' or primary['eligible']:
        raise ValueError('this separate post-hoc analysis is specific to the incomplete heldout run')
    failed = {r['trial']['id']: r for r in primary['trials'] if not r['passed']}
    if set(failed) != {'r3-static-s1', 'r3-static-s3'}:
        raise ValueError('unexpected missingness; do not generalize the bound silently')
    forensic = read(root / 'diagnostics/forensic-quality.json')
    if not forensic['primary_terminal_hashes_unchanged'] or forensic['model_calls'] != 0:
        raise ValueError('forensic provenance differs')
    for row in forensic['trials']:
        name = row['trial']
        if name not in failed or row['primary_terminal_sha256'] != failed[name]['terminal_sha256']:
            raise ValueError('forensic grade is not bound to the original failed attempt')
        grade = read(root / 'diagnostics' / (name + '-evaluation/report.json'))
        sources = inventory(root / 'diagnostics' / (name + '-source/src'))
        if {k:v['sha256'] for k,v in sources.items()} != grade['source_files']:
            raise ValueError('forensic source differs')
        if row['forensic_quality'] != 'pass' or grade['outcomes'] != row['outcomes']:
            raise ValueError('forensic quality differs')
        if set(grade['outcomes']) != {'acceptance', 'regression'} or any(
            v['exit_code'] or v['counts']['failed'] or v['counts']['errors'] or not v['counts']['executed']
            for v in grade['outcomes'].values()):
            raise ValueError('both fixed quality checks must pass without allowances')
    if {r['trial'] for r in forensic['trials']} != set(failed):
        raise ValueError('forensic coverage differs')
    arms = ('plain', 'static', 'cami', 'cami_replay')
    blocks = {(rep, arm): {'tokens': dict.fromkeys(KEYS, 0),
              'observed_wall': summary['shared_preflight_wall_seconds'] / 20,
              'unknown_usage_trials': [], 'primary_failed_trials': []}
              for rep in range(1, 6) for arm in arms}
    for row in primary['trials']:
        trial = row['trial']
        directory = root / 'trials' / trial['id']
        terminal = read(directory / 'terminal.json')
        tokens = dict.fromkeys(KEYS, 0) if not terminal['model_calls'] else token_fields(read(directory / 'session/evidence/usage.json'))
        if any(type(v) is not int or v < 0 for v in tokens.values()):
            raise ValueError('nonnegative observed subtotals required')
        block = blocks[trial['repetition'], trial['condition']]
        for key in KEYS:
            block['tokens'][key] += tokens[key]
        block['observed_wall'] += terminal['wall_seconds']
        if not row['passed']:
            if trial['condition'] != 'static' or trial['id'] not in failed:
                raise ValueError('candidate or ungraded failure cannot support this bound')
            messages = read(directory / 'session/evidence/messages.json')
            if not any(m.get('type') == 'assistant' and not isinstance(m.get('tokens'), dict) for m in messages):
                raise ValueError('expected missing-response usage not found')
            block['unknown_usage_trials'].append(trial['id'])
            block['primary_failed_trials'].append(trial['id'])
    pairs = []
    for rep in range(1, 6):
        candidate = blocks[rep, 'cami_replay']
        if candidate['unknown_usage_trials'] or candidate['primary_failed_trials']:
            raise ValueError('candidate must have complete primary evidence')
        for arm in arms[:-1]:
            baseline = blocks[rep, arm]
            candidate_work = sum(candidate['tokens'][k] for k in KEYS if k != 'cache_read')
            baseline_work = sum(baseline['tokens'][k] for k in KEYS if k != 'cache_read')
            pairs.append({'repetition': rep, 'comparator': arm,
                'candidate_tokens': candidate['tokens'], 'baseline_known_token_subtotals': baseline['tokens'],
                'candidate_token_work': candidate_work, 'baseline_token_work_lower_bound': baseline_work,
                'candidate_pipeline_seconds': candidate['observed_wall'],
                'baseline_observed_pipeline_seconds_lower_bound': baseline['observed_wall'],
                'unknown_baseline_usage_trials': baseline['unknown_usage_trials'],
                'token_work_strictly_below_lower_bound': candidate_work < baseline_work,
                'wall_strictly_below_lower_bound': candidate['observed_wall'] < baseline['observed_wall'],
                'component_bound': compare(candidate['tokens'], baseline['tokens'])})
    return {'status': 'verified_post_hoc_bounds', 'primary_eligible': primary['eligible'],
            'primary_direction_supported': primary['direction_supported'],
            'protocol_sha256': primary['protocol_sha256'],
            'forensic_receipt_sha256': hashlib.sha256((root / 'diagnostics/forensic-quality.json').read_bytes()).hexdigest(),
            'all15_pairs_below_known_work_and_wall': all(p['token_work_strictly_below_lower_bound'] and p['wall_strictly_below_lower_bound'] for p in pairs),
            'all15_pairs_componentwise_nonincreasing': all(p['component_bound']['nonincreasing'] for p in pairs),
            'pairs': pairs,
            'scope': 'Chosen after observing the completed run, not preregistered confirmation. Unknown baseline response usage is nonnegative additional normalized consumption; its value is never estimated or entered as zero. Failed baseline wall already spent is a lower bound before any omitted grading cost. Candidate evidence is complete, and both failed baseline solutions passed separate forensic fixed grading. Under these assumptions C < B_known implies C < B_known + U for U >= 0; componentwise dominance gives nonincreasing modeled charge for identical nonnegative linear token prices. No actual invoice, retry-free counterfactual, causal effect of transport, confidence interval or production hit-rate claim. The original primary verdict remains inconclusive.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('out', type=Path)
    args = parser.parse_args()
    with args.out.open('x') as stream:
        json.dump(analyze(args.run), stream, indent=2, sort_keys=True)
        stream.write('\n')
