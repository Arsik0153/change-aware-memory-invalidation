"""Handwritten checks of runner mechanics; never collect the frozen challenge."""
import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).with_name('check_reference_alignment.py')
if not SCRIPT.is_file():
    SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/check_reference_alignment.py'
SPEC = importlib.util.spec_from_file_location('alignment_runner_under_test', SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
PARENT = 'def f(x):\n    return x\n'


def observe(tmp_path, child_source, expected):
    reference = runner.load_reference(runner.REFERENCE)
    return runner.observe_pair(PARENT, {'id': 'handwritten', 'child_source': child_source,
        'authored_expected': expected}, tmp_path, reference)


def test_unchanged_supported_claims_remain_available_without_symbol_selection(tmp_path):
    input_row, comparisons, states = observe(tmp_path, PARENT,
        {'symbol_exists': 'supported', 'signature_equals': 'supported'})
    assert len(comparisons) == 2
    assert len(states) == 6
    assert (tmp_path / input_row['sources']['child']['path']).read_bytes() == PARENT.encode()
    for row in states:
        assert row['state']['available']
        assert row['state']['state'] == 'valid'
        assert not row['available_when_reference_not_supported']
        assert row['selection']['selected'] == (row['selector_variant'] == 'all_validate')
    assert all(not row['production_reference_child_mismatch'] for row in comparisons)
    for row in states:
        assert row['state']['last_supported_commit'] == row['parent_revision']


def test_signature_change_withholds_only_signature_claim(tmp_path):
    _, comparisons, states = observe(tmp_path, 'def f(x, y):\n    return x\n',
        {'symbol_exists': 'supported', 'signature_equals': 'contradicted'})
    assert all(row['selection']['selected'] for row in states)
    for row in states:
        if row['claim_kind'] == 'signature_equals':
            assert row['selected_validation_result']['verdict'] == 'contradicted'
            assert row['state']['state'] == 'stale'
            assert not row['state']['available']
        else:
            assert row['state']['available']
    assert all(not row['production_reference_child_mismatch'] for row in comparisons)


def test_file_anchor_falls_back_on_namespace_uncertainty(tmp_path):
    _, comparisons, states = observe(tmp_path, PARENT + 'from other import *\n',
        {'symbol_exists': 'uncertain', 'signature_equals': 'uncertain'})
    assert all(row['reference_results']['child']['verdict'] == 'uncertain'
               for row in comparisons)
    for row in states:
        assert not row['available_when_provably_contradicted']
        assert row['available_when_reference_uncertain'] == row['state']['available']
        assert row['available_when_reference_not_supported'] == row['state']['available']
        if row['selector_variant'] == 'file_anchor':
            assert row['policy']['id'] == 'symbol_validate'
            assert row['provenance']['anchors'][0]['scope'] == 'file'
            assert row['provenance']['anchors'][0]['qualname'] == 'f'
            assert 'anchor_file_changed' in row['selection']['reasons']
            assert row['selected_validation_result']['verdict'] == 'insufficient_evidence'
            assert row['state']['state'] == 'needs_validation'
            assert not row['state']['available']
