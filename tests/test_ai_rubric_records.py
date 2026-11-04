import json

import pytest

from scripts import audit_ai_rubric_records as checker
from scripts.validate_ai_review import ReviewError


def fixture(tmp_path, monkeypatch):
    identity = {'reviewer_kind': 'ai_reviewer', 'human': False, 'provider': 'codex',
                'model': 'declared', 'reasoning_effort': 'high', 'agent_task': '/synthetic',
                'identity_basis': 'declared_invocation', 'independence_disclosure': 'unverified'}
    review = {**identity, 'items': [{'id': 'one', 'extracted_facts': {
        'definition_count': 1, 'unconditional': True, 'target_rebinding': False,
        'type_parameters_present': False, 'actual_signature': {'parameters': [],
        'returns_ast': None, 'decorators_ast': [], 'is_async': False}}}]}
    method = {**identity, 'tools': ['ast'], 'parser': {'python': 'test'},
              'whole_module_inspection_method': 'Synthetic full-module check.',
              'signature_extraction_method': 'Synthetic AST extraction.'}
    monkeypatch.setattr(checker, 'audit_review', lambda *args: {'status': 'tested separately'})
    monkeypatch.setattr(checker, 'load_packet', lambda *args: ({'one': {'kind': 'signature_equals'}}, {}, '', ''))
    (tmp_path/'review.json').write_text(json.dumps(review))
    (tmp_path/'methodology.json').write_text(json.dumps(method))
    return review


def test_required_rubric_fields_are_checked_without_rewriting_review(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    before = (tmp_path/'review.json').read_bytes()
    assert checker.audit(tmp_path, tmp_path)['items'] == 1
    assert before == (tmp_path/'review.json').read_bytes()


def test_placeholder_facts_and_missing_method_are_rejected(tmp_path, monkeypatch):
    review = fixture(tmp_path, monkeypatch)
    review['items'][0]['extracted_facts'] = {'placeholder': True}
    (tmp_path/'review.json').write_text(json.dumps(review))
    with pytest.raises(ReviewError, match='definition_count'):
        checker.audit(tmp_path, tmp_path)
    fixture(tmp_path, monkeypatch)
    (tmp_path/'methodology.json').unlink()
    with pytest.raises(FileNotFoundError):
        checker.audit(tmp_path, tmp_path)
