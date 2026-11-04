"""Research-only periodic selector; not registered as a production CAMI policy."""
from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

from cami import engine
from cami.artifacts import digest, file_hash, read_json, write_json
from cami.models import PolicyConfig, Selection
from cami.policies import SelectionContext, select_claims


class PeriodicAudit:
    def __init__(self, history: tuple[str, ...], interval: int):
        if type(interval) is not int or interval < 1:
            raise ValueError('interval must be a positive integer')
        if len(history) < 2 or len(set(history)) != len(history):
            raise ValueError('history requires unique parent and child revisions')
        self.history = history
        self.positions = {revision: i for i, revision in enumerate(history)}
        self.interval = interval

    def __call__(self, context: SelectionContext, policy: PolicyConfig) -> tuple[Selection, ...]:
        if policy.id != 'symbol_validate':
            raise ValueError('research audit requires symbol_validate')
        position = self.positions.get(context.commit)
        if position is None or position == 0:
            raise ValueError('current commit must be a frozen child')
        previous = {state.claim_id: state for state in context.previous}
        ids = {claim.claim_id for claim in context.claims}
        if len(previous) != len(context.previous) or ids != set(previous):
            raise ValueError('previous states must match claim identities exactly')
        due = {}
        for claim_id, state in previous.items():
            checked = self.positions.get(state.last_checked_commit)
            if state.revision != self.history[position-1]:
                raise ValueError('previous revision must be immediate predecessor')
            if checked is None or checked >= position:
                raise ValueError('last checked commit must precede current child')
            due[claim_id] = position - checked >= self.interval
        decisions = select_claims(context, policy)
        if len(decisions) != len(ids) or {d.claim_id for d in decisions} != ids:
            raise ValueError('baseline decisions must match claim identities exactly')
        if any(d.commit != context.commit for d in decisions):
            raise ValueError('baseline decision revision mismatch')
        return tuple(d.model_copy(update={'selected':True,
            'reasons':tuple(sorted(set(d.reasons) | {'periodic_audit'}))})
            if due[d.claim_id] else d for d in decisions)


def execute(config: Path, out: Path, interval: int | None) -> None:
    data = read_json(config)
    history = (data['parent_commit'], *data['child_commits'])
    metadata = {'kind':'research_only_periodic_audit_prototype', 'interval':interval,
                'adapter_sha256':file_hash(Path(__file__)), 'history_sha256':digest(history),
                'override_applied':interval is not None, 'production_policy_changed':False}
    def write_record(path, value):
        if path == out / 'manifest.json':
            value = {**value, 'research_adapter':metadata, 'evaluation_eligible':False,
                     'ineligibility_reason':'research_only_policy_integration_experiment'}
        write_json(path,value)

    with patch.object(engine,'write_json',write_record):
        if interval is None:
            engine.run_experiment(config,out)
        else:
            with patch.object(engine,'select_claims',PeriodicAudit(history,interval)):
                engine.run_experiment(config,out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--interval',type=int)
    args = parser.parse_args()
    execute(args.config,args.out,args.interval)
