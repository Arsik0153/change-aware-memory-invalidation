from dataclasses import replace
from unittest.mock import patch

import pytest

from cami.index import ChangeSet
from cami.models import Anchor, MemoryState, PolicyConfig, Provenance, Selection, ValidationResult
from cami.policies import SelectionContext, advance_state
from scripts.check_structural_carry import claims, snapshot
from scripts.periodic_audit_adapter import PeriodicAudit

HISTORY = ('parent','one','two','three','four','five')
POLICY = PolicyConfig(id='symbol_validate')


def context(position, *, checked='parent', previous=None):
    claim = claims(snapshot('def f(x):\n    return x\n'),'audit')[0]
    provenance = Provenance(claim_id=claim.claim_id,scenario_id='intact',
        anchors=(Anchor(path='module.py',qualname='f',scope='symbol',observed_commit='parent',
                        content_hash='0'*64,origin='manual'),),known_incomplete=False)
    state = previous or MemoryState(claim_id=claim.claim_id,revision=HISTORY[position-1],
        state='valid',last_checked_commit=checked,last_supported_commit='parent',
        last_verdict='supported',basis='validated',current_provenance=provenance,available=True)
    return SelectionContext(HISTORY[position],(claim,),(provenance,),(state,),
        ChangeSet(frozenset(),frozenset(),(),frozenset(),frozenset(),False))


def test_deadline_counts_unchanged_source_and_recreated_adapter_is_identical():
    for position in (1,2,3):
        decision, = PeriodicAudit(HISTORY,4)(context(position),POLICY)
        assert not decision.selected
    first, = PeriodicAudit(HISTORY,4)(context(4),POLICY)
    recreated, = PeriodicAudit(HISTORY,4)(context(4),POLICY)
    assert first == recreated and first.selected and first.reasons == ('periodic_audit',)
    after, = PeriodicAudit(HISTORY,4)(context(5,checked='four'),POLICY)
    assert not after.selected


def test_inconclusive_audit_withholds_and_baseline_retries_next_commit():
    current = context(4)
    decision, = PeriodicAudit(HISTORY,4)(current,POLICY)
    result = ValidationResult(claim_id=decision.claim_id,commit='four',validator='behavior_test',
        verdict='insufficient_evidence',reason='probe_timeout',input_hash='0'*64,duration_seconds=0)
    state = advance_state(current.previous[0],decision,POLICY,result,False)
    assert not state.available and state.last_checked_commit == 'four'
    next_decision, = PeriodicAudit(HISTORY,4)(context(5,previous=state),POLICY)
    assert next_decision.selected and next_decision.reasons == ('previously_unavailable',)


@pytest.mark.parametrize('checked',[None,'missing','four','five'])
def test_rejects_missing_or_nonpast_last_check(checked):
    with pytest.raises(ValueError,match='last checked'):
        PeriodicAudit(HISTORY,4)(context(4,checked=checked),POLICY)


def test_rejects_stale_previous_revision_instead_of_resetting_age():
    current = context(4)
    state = current.previous[0].model_copy(update={'revision':'one'})
    with pytest.raises(ValueError,match='immediate predecessor'):
        PeriodicAudit(HISTORY,4)(replace(current,previous=(state,)),POLICY)


@pytest.mark.parametrize('interval',[0,-1,True,1.5])
def test_rejects_invalid_intervals(interval):
    with pytest.raises(ValueError,match='positive integer'):
        PeriodicAudit(HISTORY,interval)


def test_rejects_ambiguous_history_and_wrong_policy():
    with pytest.raises(ValueError,match='unique'):
        PeriodicAudit(('parent','one','one'),4)
    with pytest.raises(ValueError,match='symbol_validate'):
        PeriodicAudit(HISTORY,4)(context(1),PolicyConfig(id='symbol_invalidate'))


def test_rejects_wrong_baseline_identity():
    wrong = Selection(claim_id='other',commit='one',selected=False,reasons=())
    with patch('scripts.periodic_audit_adapter.select_claims',return_value=(wrong,)):
        with pytest.raises(ValueError,match='baseline decisions'):
            PeriodicAudit(HISTORY,4)(context(1),POLICY)


def test_worker_marks_initial_and_failed_manifests_as_research(tmp_path):
    from cami.artifacts import file_hash, read_json, write_json
    from cami import engine
    from scripts.periodic_audit_adapter import execute
    config, out = tmp_path/'config.json', tmp_path/'run'
    write_json(config,{'parent_commit':'parent','child_commits':['one']})
    captured = []

    def fail_run(config_path, output):
        output.mkdir()
        for status in ('running','failed'):
            engine.write_json(output/'manifest.json',{'status':status,'evaluation_eligible':True})
            captured.append(read_json(output/'manifest.json'))
        raise RuntimeError('controlled failure')

    with patch.object(engine,'run_experiment',fail_run):
        with pytest.raises(RuntimeError,match='controlled failure'):
            execute(config,out,4)
    assert [m['status'] for m in captured] == ['running','failed']
    assert all(not m['evaluation_eligible'] and m['research_adapter']['override_applied'] for m in captured)
    sealed = file_hash(out/'manifest.json')
    with patch.object(engine,'run_experiment',side_effect=FileExistsError('already exists')):
        with pytest.raises(FileExistsError):
            execute(config,out,4)
    assert file_hash(out/'manifest.json') == sealed
