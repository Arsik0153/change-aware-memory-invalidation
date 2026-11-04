"""Authored public evidence; no source, model, authentication or container work."""
import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from memory_format_evidence import COMPACT, digest, inspect_format  # noqa: E402


def fixture(arm='cami', mode='compact', error=False):
    arguments = {'query': 'example', 'limit': 3}
    value = {'schema_version': 1, 'backend': arm, 'entries': [], 'withheld': []}
    event = {'event': 'memory_lookup', 'backend': arm, 'query_sha256': digest(arguments)}
    if mode == 'full':
        value['catalog_sha256'] = 'a' * 64
    else:
        receipt_payload = {'format': COMPACT, 'full_result_sha256': 'b' * 64,
                           'projection_result_sha256': 'c' * 64}
        receipt = digest(receipt_payload)
        value.update(response_format=COMPACT, audit_receipt=receipt)
        event.update(response_format='compact', response_audit={
            'receipt_sha256': receipt, 'receipt_payload': receipt_payload})
    if error:
        value['error'] = {'code': 'memory_lookup_failed'}
    part = {'id': 'call-1', 'type': 'tool', 'name': 'research_memory_memory_lookup',
            'state': {'status': 'completed', 'input': arguments,
                      'content': [{'type': 'text', 'text': json.dumps(value)}]}}
    return [{'type': 'assistant', 'content': [part]}], [event]


@pytest.mark.parametrize('arm', ['static', 'cami'])
@pytest.mark.parametrize('mode', ['full', 'compact'])
@pytest.mark.parametrize('error', [False, True])
def test_actual_markers_and_errors_match(arm, mode, error):
    messages, events = fixture(arm, mode, error)
    result = inspect_format(messages, events, arm, mode)
    assert result['status'] == 'matched'
    assert result['completed_observations'] == 1
    assert 'metadata_binding_only' in result['receipt_verification']


@pytest.mark.parametrize('selected', ['full', 'compact'])
def test_opposite_valid_format_rejected(selected):
    actual = 'full' if selected == 'compact' else 'compact'
    messages, events = fixture(mode=actual)
    assert inspect_format(messages, events, 'cami', selected)['status'] == 'unsupported_or_mismatch'


@pytest.mark.parametrize('arm', ['plain', 'static', 'cami'])
def test_no_observations_are_explicit(arm):
    expected = 'not_applicable' if arm == 'plain' else 'not_observed'
    assert inspect_format([], [], arm, 'compact')['status'] == expected


@pytest.mark.parametrize('fault', ['truncated', 'nonjson', 'nonmemory', 'missingmarker', 'badreceipt', 'badquery', 'missingtrace', 'duplicateid'])
def test_unverifiable_or_mismatched_evidence_rejected(fault):
    messages, events = fixture()
    part = messages[0]['content'][0]
    if fault == 'truncated':
        part['state']['metadata'] = {'truncated': True}
    elif fault == 'nonjson':
        part['state']['content'][0]['text'] = 'not JSON'
    elif fault == 'nonmemory':
        part['state']['content'][0]['text'] = '{}'
    elif fault == 'missingmarker':
        value = json.loads(part['state']['content'][0]['text'])
        del value['response_format']
        part['state']['content'][0]['text'] = json.dumps(value)
    elif fault == 'badreceipt':
        events[0]['response_audit']['receipt_sha256'] = '0' * 64
    elif fault == 'badquery':
        events[0]['query_sha256'] = digest('example')
    elif fault == 'missingtrace':
        events = []
    else:
        messages[0]['content'].append(copy.deepcopy(part))
    assert inspect_format(messages, events, 'cami', 'compact')['status'] == 'unsupported_or_mismatch'


def test_plain_memory_exposure_rejected():
    messages, events = fixture()
    assert inspect_format(messages, events, 'plain', 'compact')['status'] == 'unsupported_or_mismatch'


def test_role_field_cannot_hide_nonconforming_message_schema():
    assert inspect_format([{'role': 'assistant', 'content': []}], [], 'cami', 'full')['status'] == 'unsupported_or_mismatch'


def test_failed_call_is_explicit_without_claim_of_observation():
    messages, _ = fixture()
    messages[0]['content'][0]['state'] = {'status': 'error'}
    result = inspect_format(messages, [], 'cami', 'compact')
    assert result['status'] == 'not_observed' and len(result['incomplete_calls']) == 1


def test_scrubbed_text_does_not_imply_exact_receipt_integrity():
    messages, events = fixture()
    value = json.loads(messages[0]['content'][0]['state']['content'][0]['text'])
    value['entries'] = [{'payload': {'text': '[REDACTED_EMAIL]'}}]
    messages[0]['content'][0]['state']['content'][0]['text'] = json.dumps(value)
    result = inspect_format(messages, events, 'cami', 'compact')
    assert result['status'] == 'matched'
    assert 'original full/projected/model bytes not checked' in result['receipt_verification']


def test_repeated_arguments_use_multiset_counts_not_message_order():
    messages, events = fixture()
    second = copy.deepcopy(messages[0]['content'][0])
    second['id'] = 'call-2'
    messages[0]['content'].append(second)
    events.append(copy.deepcopy(events[0]))
    assert inspect_format(messages, list(reversed(events)), 'cami', 'compact')['status'] == 'matched'
    assert inspect_format(messages, events[:1], 'cami', 'compact')['status'] == 'unsupported_or_mismatch'
