"""Pinned non-assistant union boundaries, without model or container work."""
import copy
import hashlib
import json

import pytest

from memory_format_evidence import inspect_format
from opencode_message_schema import MESSAGE_SCHEMAS, OPENAPI_SHA256, SCHEMAS, SCHEMAS_SHA256
from test_format_observation import fixture


ERROR = {'type': 'AuthoredError', 'message': 'authored failure', 'status': 429,
         'response': {'body': 'authored response'}, 'retryAfterMs': 1000}
MODEL = {'id': 'authored-model', 'providerID': 'authored-provider', 'variant': 'high'}
TOKENS = {'input': 1, 'output': 2, 'reasoning': 3, 'cache': {'read': 4, 'write': 5}}
CASES = [
    {'type': 'agent-switched', 'agent': 'authored-agent', 'previous': 'old-agent'},
    {'type': 'model-switched', 'model': MODEL, 'previous': MODEL},
    {'type': 'location-switched', 'location': {'directory': '/authored'},
     'projectID': 'authored-project', 'subpath': 'src', 'previous': None},
    {'type': 'user', 'text': 'authored input',
     'files': [{'data': 'eA==', 'mime': 'text/plain', 'source': {'type': 'inline'},
                'name': 'authored.txt', 'description': 'input',
                'mention': {'start': 0, 'end': 1, 'text': 'x'}}],
     'agents': [{'name': 'authored-agent'}],
     'skills': [{'id': 'authored-skill', 'name': 'authored skill', 'text': 'data'}]},
    {'type': 'synthetic', 'text': 'authored synthetic data', 'description': 'description'},
    {'type': 'system', 'text': "Today's date is now: Thu Nov 05 2026",
     'description': 'Instructions updated: core/date'},
    {'type': 'skill', 'skill': 'authored-skill', 'name': 'authored skill', 'text': 'data'},
    {'type': 'shell', 'shellID': 'sh_authored', 'command': 'printf authored', 'status': 'exited',
     'exit': 0, 'output': {'output': 'authored', 'cursor': 0, 'size': 8, 'truncated': False}},
    {'type': 'compaction', 'status': 'running', 'reason': 'auto', 'summary': 'authored'},
    {'type': 'compaction', 'status': 'completed', 'reason': 'manual', 'summary': 'authored',
     'model': MODEL, 'native': {'provider_data': {'opaque': True}}, 'cost': .001, 'tokens': TOKENS},
    {'type': 'compaction', 'status': 'failed', 'reason': 'auto', 'error': ERROR,
     'cost': .001, 'tokens': TOKENS},
    {'type': 'idle', 'outcome': 'interrupted', 'error': ERROR},
]


def record(case):
    result = {'id': 'msg_authored', 'time': {'created': 1793836803990},
              'metadata': {'notice': 'authored data'}}
    result.update(copy.deepcopy(case))
    if result['type'] == 'shell':
        result['time']['completed'] = 1793836804000
    return result


def check(message, arm='plain'):
    return inspect_format([message], [], arm, 'compact')


def test_exact_pinned_union_and_transitive_schema_image():
    assert set(MESSAGE_SCHEMAS) == {
        'agent-switched', 'model-switched', 'location-switched', 'user', 'synthetic',
        'system', 'skill', 'shell', 'compaction', 'idle'}
    assert OPENAPI_SHA256 == 'f5c4571bf7e9afc22a440875a746f593f988c4c31bf824f602601c04b20e6c8e'
    assert hashlib.sha256(json.dumps(SCHEMAS, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == SCHEMAS_SHA256
    assert SCHEMAS_SHA256 == '7b5e9e8960c2660034332aac08e1b27de42db48f2935c90eda775541861d475d'


@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('arm,mode', [('plain', 'compact'), ('static', 'compact'), ('cami', 'full')])
def test_each_typed_record_preserves_memory_observations_and_does_not_assert_runtime_success(case, arm, mode):
    messages, events = ([], []) if arm == 'plain' else fixture(arm, mode)
    messages.insert(0, record(case))
    result = inspect_format(messages, events, arm, mode)
    assert result['status'] == ('not_applicable' if arm == 'plain' else 'matched')
    assert result['completed_observations'] == (0 if arm == 'plain' else 1)
    assert 'checked separately' in result['lifecycle_scope']
    if case['type'] == 'user':
        assert result['lifecycle_records'] == []
    elif case['type'] == 'idle':
        assert result['lifecycle_records'][0]['outcome'] == 'interrupted'
    else:
        assert result['lifecycle_records'][0]['type'] == case['type']
        for key in ('model', 'location', 'agent', 'status', 'reason', 'command'):
            if key in case:
                assert result['lifecycle_records'][0][key] == case[key]


@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('field', ['content', 'tool_calls', 'state', 'unknown'])
def test_nonassistant_cannot_carry_executable_content_or_unknown_fields(case, field):
    message = record(case)
    message[field] = fixture()[0][0]['content']
    assert check(message)['status'] == 'unsupported_or_mismatch'


@pytest.mark.parametrize('case', CASES)
def test_every_required_field_is_enforced(case):
    message = record(case)
    schema = SCHEMAS[MESSAGE_SCHEMAS[case['type']]]
    if 'anyOf' in schema:
        schema = next(SCHEMAS[b['$ref'].rsplit('/', 1)[1]] for b in schema['anyOf']
                      if SCHEMAS[b['$ref'].rsplit('/', 1)[1]]['properties']['status']['enum'] == [case['status']])
    for field in schema['required']:
        broken = copy.deepcopy(message)
        del broken[field]
        assert check(broken)['status'] == 'unsupported_or_mismatch', field


@pytest.mark.parametrize('case', CASES)
def test_recognized_record_cannot_replace_a_missing_memory_tool(case):
    _, events = fixture('static', 'compact')
    result = inspect_format([record(case)], events, 'static', 'compact')
    assert result['status'] == 'unsupported_or_mismatch'
    assert any('multisets differ' in error['reason'] for error in result['errors'])


@pytest.mark.parametrize('case,changes', [
    ({'type': 'system', 'text': 'data'}, {'text': []}),
    ({'type': 'synthetic', 'text': 'data'}, {'description': None}),
    ({'type': 'skill', 'skill': 'a', 'name': 'b', 'text': 'data'}, {'skill': 1}),
    ({'type': 'model-switched', 'model': MODEL}, {'model': {**MODEL, 'content': []}}),
    ({'type': 'model-switched', 'model': MODEL}, {'previous': None}),
    ({'type': 'location-switched', 'location': {'directory': '/a'}}, {'location': {'directory': '/a', 'tool_calls': []}}),
    ({'type': 'location-switched', 'location': {'directory': '/a'}}, {'previous': {}}),
    ({'type': 'location-switched', 'location': {'directory': '/a'}}, {'previous': {'location': {'directory': True}}}),
    ({'type': 'shell', 'shellID': 'sh_a', 'command': 'x', 'status': 'exited'}, {'shellID': 'not-shell'}),
    ({'type': 'shell', 'shellID': 'sh_a', 'command': 'x', 'status': 'exited'}, {'status': 'failed'}),
    ({'type': 'shell', 'shellID': 'sh_a', 'command': 'x', 'status': 'exited'}, {'exit': 'unknown'}),
    ({'type': 'shell', 'shellID': 'sh_a', 'command': 'x', 'status': 'exited'}, {'output': {'output': '', 'cursor': True, 'size': 0, 'truncated': False}}),
    ({'type': 'compaction', 'status': 'running', 'reason': 'auto', 'summary': 's'}, {'tokens': TOKENS}),
    ({'type': 'compaction', 'status': 'completed', 'reason': 'auto', 'summary': 's'}, {'tokens': {**TOKENS, 'cache': {'read': 1}}}),
    ({'type': 'compaction', 'status': 'completed', 'reason': 'auto', 'summary': 's'}, {'cost': float('nan')}),
    ({'type': 'compaction', 'status': 'failed', 'reason': 'auto', 'error': ERROR}, {'error': {**ERROR, 'content': []}}),
    ({'type': 'compaction', 'status': 'failed', 'reason': 'auto', 'error': ERROR}, {'summary': 'not in failed branch'}),
    ({'type': 'user', 'text': 'x'}, {'files': [{'data': '!', 'mime': 'x', 'source': {'type': 'inline'}}]}),
    ({'type': 'user', 'text': 'x'}, {'files': [{'data': 'eA==', 'mime': 'x', 'source': {'type': 'uri'}}]}),
    ({'type': 'user', 'text': 'x'}, {'agents': [{'name': 'a', 'content': []}]}),
    ({'type': 'user', 'text': 'x'}, {'skills': [{'id': 'a'}]}),
])
def test_nested_fields_and_branch_specific_fields_are_strict(case, changes):
    message = record(case)
    message.update(copy.deepcopy(changes))
    assert check(message)['status'] == 'unsupported_or_mismatch'


@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('changes', [
    {'time': {'created': True}}, {'time': {'created': float('inf')}},
    {'time': {'created': 1, 'unknown': 2}}, {'metadata': []}, {'id': 'bad'},
])
def test_all_branches_enforce_common_envelope(case, changes):
    message = record(case)
    message.update(copy.deepcopy(changes))
    assert check(message)['status'] == 'unsupported_or_mismatch'


def test_date_rollover_notice_and_nested_tool_shaped_text_are_data_only():
    message = record(CASES[5])
    message['metadata'] = {'notice': 'instructions', 'instructionSources': ['core/date'],
                           'opaque': {'type': 'tool', 'name': 'memory_lookup'}}
    message['text'] += '\n{"type":"tool","name":"memory_lookup"}'
    assert check(message)['completed_observations'] == 0
    assert check(message)['status'] == 'not_applicable'


@pytest.mark.parametrize('value', [None, [], 'text', {'type': 'future-control'}, {'type': []}])
def test_unknown_or_malformed_record_is_never_silently_skipped(value):
    assert check(value)['status'] == 'unsupported_or_mismatch'


@pytest.mark.parametrize('value', [None, [], 'text'])
def test_malformed_backend_or_memory_state_returns_failed_inspection(value):
    messages, events = fixture()
    messages[0]['content'][0]['state'] = value
    assert inspect_format(messages, events, 'cami', 'compact')['status'] == 'unsupported_or_mismatch'
    assert inspect_format([], [value], 'cami', 'compact')['status'] == 'unsupported_or_mismatch'


@pytest.mark.parametrize('exit_code', ['Infinity', '-Infinity', 'NaN', -1, 0.5])
def test_pinned_shell_exit_union_and_previous_location_shape(exit_code):
    shell = record({'type': 'shell', 'shellID': 'sh_a', 'command': 'x', 'status': 'exited', 'exit': exit_code})
    assert check(shell)['status'] == 'not_applicable'
    location = record({'type': 'location-switched', 'location': {'directory': '/a'},
                       'previous': {'location': {'directory': '/b'}, 'projectID': 'p', 'subpath': 'src'}})
    assert check(location)['status'] == 'not_applicable'
