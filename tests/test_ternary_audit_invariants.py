import pytest

from scripts.check_ternary_audit_invariants import explore,successors,verify_rank

EXACT={'true':['supported'],'false':['contradicted']}
SOUND={'true':['supported','contradicted','insufficient_evidence'],
       'false':['contradicted','insufficient_evidence']}


def test_unknown_withholds_true_claim_without_breaking_false_availability_bound():
    graph=explore(2,SOUND)
    verify_rank(graph)
    assert graph['false_withholding_states']==1
    witness=graph['false_withholding_witness']['prefix']
    assert witness[-1]['selected'] and witness[-1]['verdict']!='supported'
    exact=explore(2,EXACT)
    verify_rank(exact)
    assert exact['false_withholding_states']==0


def test_selected_inconclusive_result_hides_instead_of_carrying():
    edges=list(successors((False,True,3),4,SOUND))
    unknown=[(state,edge) for state,edge in edges if edge['verdict']=='insufficient_evidence']
    assert unknown and all(not state[1] and state[2]==0 for state,_ in unknown)


@pytest.mark.parametrize('kind',['unsound','carry_unknown'])
def test_relaxed_assumption_creates_reachable_unsafe_cycle(kind):
    outcomes={truth:['supported','contradicted','insufficient_evidence'] for truth in ('true','false')}
    graph=explore(2,outcomes if kind=='unsound' else SOUND,
                  carry_on_insufficient=kind=='carry_unknown')
    assert graph['risk']['unbounded'] and graph['risk']['cycle']
    with pytest.raises(AssertionError):
        verify_rank(graph)
