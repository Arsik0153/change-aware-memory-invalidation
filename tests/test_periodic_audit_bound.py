from scripts.check_periodic_audit_bound import false_run_risk, transition


def test_false_run_counts_states_and_detects_cycle():
    states = [{'state_id':s,'available':True,'truth':False} for s in ['a','b','c']]
    edges = [{'from':'a','to':'b'}, {'from':'b','to':'c'}]
    finite = false_run_risk(states,edges)
    assert finite['max_consecutive_false_available'] == 3
    assert finite['false_run_edges'] == edges
    cyclic = false_run_risk(states,edges + [{'from':'c','to':'a'}])
    assert cyclic['unbounded'] and len(cyclic['cycle']) == 3
    assert false_run_risk([],[])['max_consecutive_false_available'] == 0


def test_deadline_checks_before_carry_and_resets_only_after_validation():
    edge = {'selected':False,'changed_files':['unrelated.py'],
            'next_available':True,'to_program':10}
    normal = transition(edge,3,4,False)
    assert normal['selected'] and not normal['next_available'] and normal['next_age'] == 0
    wrong = transition(edge,3,4,False,off_by_one=True)
    assert not wrong['selected'] and wrong['next_age'] == 4
    reset = transition(edge,3,4,False,reset_on_change=True)
    assert not reset['selected'] and reset['next_age'] == 1


def test_baseline_recovery_check_still_wins_before_periodic_deadline():
    edge = {'selected':True,'changed_files':[],'next_available':True,'to_program':8}
    result = transition(edge,0,8,True)
    assert result['selected'] and not result['audit_due']
    assert result['next_available'] and result['next_age'] == 0
