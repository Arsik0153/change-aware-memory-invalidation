import pytest

from scripts.check_behavior_reachability import changing_cycle, prefix_to


@pytest.mark.parametrize('selected,changed,expected', [
    (False, ['unrelated.py'], True), (True, ['unrelated.py'], False), (False, [], False)])
def test_persistent_error_cycle_requires_real_changes_without_validation(selected, changed, expected):
    states = [{'state_id': s, 'false_availability': True} for s in ['a', 'b']]
    edges = [{'from': 'a', 'to': 'b', 'selected': selected, 'changed_files': changed},
             {'from': 'b', 'to': 'a', 'selected': False, 'changed_files': ['unrelated.py']}]
    cycle = changing_cycle(states, edges)
    assert bool(cycle) is expected
    if cycle:
        assert len(cycle) == 2
        assert cycle[0]['from'] == cycle[-1]['to']
        assert all(a['to'] == b['from'] for a, b in zip(cycle, cycle[1:]))


def test_error_prefix_preserves_transition_order():
    edges = [{'from': 'start', 'to': 'middle'}, {'from': 'middle', 'to': 'error'}]
    assert prefix_to('error', {'middle': 0, 'error': 1}, edges) == edges
    assert prefix_to('start', {'middle': 0}, edges) == []
