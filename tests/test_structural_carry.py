from cami.artifacts import read_json
from scripts.check_structural_carry import PLAN, claims, observe, snapshot


def test_missing_subject_change_is_detected():
    plan = read_json(PLAN)
    parent = snapshot('def f(x): return x\n')
    child = snapshot('def f(x, y): return x\n')
    claim = claims(parent, 'control')[1]
    correct = observe(parent, child, claim, plan)
    broken = observe(parent, child, claim, plan, suppress_changed_symbols=True)
    assert correct['selected'] and not correct['carry_violation']
    assert broken['carry_violation'] and broken['child_verdict'] == 'contradicted'


def test_same_oid_limitation_is_not_carried():
    plan = read_json(PLAN)
    source = 'def f(x): return x\n'
    parent = snapshot(source)
    child = snapshot(source, mode='120000', limitation='symlink_unsupported')
    assert parent.blobs[0].object_id == child.blobs[0].object_id
    row = observe(parent, child, claims(parent, 'mode')[0], plan)
    assert row['warm_index_equals_fresh']
    assert row['selected'] and row['child_verdict'] == 'insufficient_evidence'
    assert not row['carry_violation']
