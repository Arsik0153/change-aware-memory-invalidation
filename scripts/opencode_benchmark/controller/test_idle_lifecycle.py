"""Real pinned Idle boundary, distinct from memory observations/execution success."""

import copy

import pytest

from memory_format_evidence import inspect_format
from test_format_observation import fixture


def idle(outcome='succeeded'):
    return {'id': 'msg_authored_idle', 'type': 'idle', 'time': {'created': 1793831759606},
            'outcome': outcome}


@pytest.mark.parametrize('outcome', ['succeeded', 'failed', 'interrupted'])
@pytest.mark.parametrize('arm,mode', [('plain', 'compact'), ('static', 'compact'), ('cami', 'full')])
def test_idle_is_not_a_tool_or_execution_success_claim(outcome, arm, mode):
    messages, events = ([], []) if arm == 'plain' else fixture(arm, mode)
    messages.append(idle(outcome))
    result = inspect_format(messages, events, arm, mode)
    assert result['status'] == ('not_applicable' if arm == 'plain' else 'matched')
    assert result['completed_observations'] == (0 if arm == 'plain' else 1)
    assert result['lifecycle_records'] == [
        {'id': 'msg_authored_idle', 'outcome': outcome, 'has_error': False}]


def test_structured_error_and_opaque_metadata_are_retained_without_relabeling_outcome():
    message = idle('failed')
    message.update(metadata={'arbitrary': {'text': 'not an execution'}}, error={
        'type': 'ProviderError', 'message': 'authored error', 'status': 429,
        'response': {'body': 'authored body'}, 'retryAfterMs': 1000})
    result = inspect_format([message], [], 'plain', 'compact')
    assert result['status'] == 'not_applicable'
    assert result['lifecycle_records'][0]['outcome'] == 'failed'
    assert result['lifecycle_records'][0]['has_error']


@pytest.mark.parametrize('fault', [
    {'content': []}, {'tool_calls': []}, {'tool': 'memory_lookup'}, {'unknown': 1},
    {'type': 'future-control'}, {'outcome': 'future'}, {'id': 'not-a-message'},
    {'time': {}}, {'time': {'created': True}}, {'time': {'created': float('inf')}},
    {'time': {'created': 1, 'unknown': 2}}, {'metadata': None}, {'error': None},
    {'error': {'type': 'Error'}}, {'error': {'type': 'Error', 'message': 'x', 'extra': 1}},
    {'error': {'type': 'Error', 'message': 'x', 'status': True}},
    {'error': {'type': 'Error', 'message': 'x', 'status': 600}},
    {'error': {'type': 'Error', 'message': 'x', 'retryAfterMs': -1}},
    {'error': {'type': 'Error', 'message': 'x', 'response': {'body': 'x', 'extra': 1}}},
])
def test_malformed_or_tool_carrying_control_records_are_rejected(fault):
    message = idle()
    message.update(copy.deepcopy(fault))
    assert inspect_format([message], [], 'plain', 'compact')['status'] == 'unsupported_or_mismatch'


@pytest.mark.parametrize('content', [None, {}, [None], ['text']])
def test_assistant_requires_real_part_array(content):
    message = {'type': 'assistant'}
    if content is not None:
        message['content'] = content
    assert inspect_format([message], [], 'plain', 'compact')['status'] == 'unsupported_or_mismatch'


def test_idle_cannot_hide_executed_backend_lookup():
    _, events = fixture('static', 'compact')
    result = inspect_format([idle()], events, 'static', 'compact')
    assert result['status'] == 'unsupported_or_mismatch'
    assert any('multisets differ' in row['reason'] for row in result['errors'])
