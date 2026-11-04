import pytest

from scripts.analyze_ai_pilot import compare


def packet():
    cases = {name: {'kind': 'symbol_exists', 'source_sha256': 'a'*64} for name in ('authentic', 'control')}
    origins = [{'id': name, 'source_origin': {'group_id': 'one'},
                'origin_class': 'authentic_parent_claim' if name == 'authentic' else 'private_authored_control',
                'transformation': None if name == 'authentic' else {'type': 'nonexistent_name', 'expected_verdict': 'contradicted'}}
               for name in cases]
    reference = [{'id': 'authentic', 'verdict': 'supported'}, {'id': 'control', 'verdict': 'contradicted'}]
    return cases, origins, reference


def test_agreement_retains_group_dependence_and_does_not_create_labels():
    cases, origins, reference = packet()
    summary, rows = compare(cases, origins, reference, {'reviewer_a': reference, 'reviewer_b': reference})
    assert summary['all']['cases'] == 2 and summary['all']['unique_source_hashes'] == 1
    assert summary['authentic']['cases'] == summary['controls']['cases'] == 1
    assert summary['human_review_count'] == summary['labels_created'] == summary['receipts_created'] == 0
    assert not summary['expansion_blocked_by_control_or_disagreement']
    assert not any(r['unresolved'] for r in rows)


def test_shared_wrong_control_is_not_resolved_by_majority():
    cases, origins, reference = packet()
    wrong = [{'id': r['id'], 'verdict': 'supported'} for r in reference]
    summary, rows = compare(cases, origins, wrong, {'reviewer_a': wrong, 'reviewer_b': wrong})
    assert summary['expansion_blocked_by_control_or_disagreement']
    assert summary['all']['ai_pair_disagreements'] == 0
    assert summary['controls']['control_failures'] == {'mechanical': 1, 'reviewer_a': 1, 'reviewer_b': 1}
    assert rows[1]['control_failures']


def test_authentic_disagreement_is_preserved_even_with_two_votes():
    cases, origins, reference = packet()
    uncertain = [{'id': 'authentic', 'verdict': 'uncertain'}, reference[1]]
    summary, rows = compare(cases, origins, reference, {'reviewer_a': reference, 'reviewer_b': uncertain})
    assert summary['expansion_blocked_by_control_or_disagreement']
    assert rows[0]['unresolved'] and rows[0]['verdicts']['reviewer_b'] == 'uncertain'
    assert summary['all']['ai_pair_disagreements'] == 1


@pytest.mark.parametrize('bad', [[], [{'id': 'authentic', 'verdict': 'supported'}]*2])
def test_missing_or_duplicate_records_are_rejected(bad):
    cases, origins, reference = packet()
    with pytest.raises(ValueError, match='identities'):
        compare(cases, origins, reference, {'reviewer_a': bad, 'reviewer_b': reference})
