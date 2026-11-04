"""Observed MCP format markers, separate from exact pre-publication receipt bytes."""
from collections import Counter
import hashlib
import json
import math
import re

COMPACT = 'research-memory-compact/1'


def digest(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def sha_value(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def idle_lifecycle(message):
    """Pinned OpenCode 2.2.5 Idle record; it cannot contain tool executions."""
    allowed = {'id', 'type', 'metadata', 'time', 'outcome', 'error'}
    if (set(message) - allowed or not {'id', 'type', 'time', 'outcome'} <= set(message)
            or not isinstance(message['id'], str) or not message['id'].startswith('msg_')
            or message['type'] != 'idle'
            or message['outcome'] not in ('succeeded', 'failed', 'interrupted')
            or 'metadata' in message and not isinstance(message['metadata'], dict)):
        raise ValueError('invalid pinned idle lifecycle record')
    timing = message['time']
    if (not isinstance(timing, dict) or set(timing) != {'created'}
            or isinstance(timing['created'], bool)
            or not isinstance(timing['created'], (int, float))
            or isinstance(timing['created'], float) and not math.isfinite(timing['created'])):
        raise ValueError('invalid idle lifecycle timestamp')
    if 'error' in message:
        error = message['error']
        if (not isinstance(error, dict)
                or set(error) - {'type', 'message', 'status', 'response', 'retryAfterMs'}
                or not {'type', 'message'} <= set(error)
                or not all(isinstance(error[key], str) for key in ('type', 'message'))):
            raise ValueError('invalid idle structured error')
        for key, low, high in [('status', 100, 599), ('retryAfterMs', 0, 9007199254740991)]:
            if key in error and (type(error[key]) is not int or not low <= error[key] <= high):
                raise ValueError('invalid idle structured error number')
        if 'response' in error and (not isinstance(error['response'], dict)
                or set(error['response']) != {'body'}
                or not isinstance(error['response']['body'], str)):
            raise ValueError('invalid idle structured error response')
    return {'id': message['id'], 'outcome': message['outcome'], 'has_error': 'error' in message}


def visible_marker(part, arm, selected):
    state = part['state']
    if state.get('metadata', {}).get('truncated'):
        raise ValueError('transport-truncated response')
    content = state['content']
    if len(content) != 1 or content[0].get('type') != 'text':
        raise ValueError('expected one complete text result')
    value = json.loads(content[0]['text'])
    if (value.get('schema_version') != 1 or not isinstance(value.get('entries'), list)
            or not isinstance(value.get('withheld'), list)):
        raise ValueError('unsupported memory envelope')
    if 'error' in value:
        if value['error'].get('code') != 'memory_lookup_failed' or value['entries'] or value['withheld']:
            raise ValueError('unsupported memory error envelope')
    elif value.get('backend') != arm or not sha_value(value.get('catalog_sha256')) and selected == 'full':
        raise ValueError('memory backend/catalog mismatch')
    if selected == 'full':
        if 'response_format' in value or 'audit_receipt' in value:
            raise ValueError('compact markers in selected full response')
        receipt = None
    else:
        receipt = value.get('audit_receipt')
        if value.get('response_format') != COMPACT or not sha_value(receipt):
            raise ValueError('compact response marker or receipt missing')
    if not isinstance(state.get('input'), dict):
        raise ValueError('tool arguments unavailable')
    return digest(state['input']), receipt


def backend_marker(event, arm, selected):
    if event.get('backend') != arm or not sha_value(event.get('query_sha256')):
        raise ValueError('backend identity or argument digest missing')
    if selected == 'full':
        if 'response_format' in event or 'response_audit' in event:
            raise ValueError('compact backend event in selected full mode')
        return event['query_sha256'], None
    audit = event.get('response_audit', {})
    payload = audit.get('receipt_payload', {})
    receipt = audit.get('receipt_sha256')
    if (event.get('response_format') != 'compact' or payload.get('format') != COMPACT
            or not sha_value(payload.get('full_result_sha256'))
            or not sha_value(payload.get('projection_result_sha256'))
            or not sha_value(receipt) or digest(payload) != receipt):
        raise ValueError('compact backend receipt metadata mismatch')
    return event['query_sha256'], receipt


def inspect_format(messages, events, arm, selected):
    if selected not in ('full', 'compact') or arm not in ('plain', 'static', 'cami'):
        raise ValueError('unsupported frozen memory configuration')
    visible, backend, observations, errors, incomplete = [], [], [], [], []
    seen, lifecycle = set(), []
    if not isinstance(messages, list) or not isinstance(events, list):
        raise ValueError('complete message and backend event arrays required')
    for message in messages:
        if isinstance(message, dict) and message.get('type') == 'idle':
            try:
                lifecycle.append(idle_lifecycle(message))
            except (ValueError, KeyError, TypeError) as error:
                errors.append({'reason': str(error)})
            continue
        if not isinstance(message, dict) or message.get('type') not in ('user', 'assistant'):
            errors.append({'reason': 'unsupported pinned API message schema'})
            continue
        if message.get('type') != 'assistant':
            continue
        content = message.get('content')
        if not isinstance(content, list) or not all(isinstance(part, dict) for part in content):
            errors.append({'reason': 'assistant content must be an explicit part array'})
            continue
        for part in content:
            name = part.get('name', '')
            if part.get('type') == 'tool' and not isinstance(name, str):
                errors.append({'reason': 'tool name must be a string'})
                continue
            if part.get('type') != 'tool' or not (name == 'memory_lookup' or name.endswith('_memory_lookup')):
                continue
            call_id = part.get('id')
            if not isinstance(call_id, str) or call_id in seen:
                errors.append({'reason': 'missing or duplicate memory call ID'})
                continue
            seen.add(call_id)
            if arm == 'plain':
                errors.append({'call_id': call_id, 'reason': 'plain observed external memory call'})
                continue
            if part.get('state', {}).get('status') != 'completed':
                incomplete.append({'call_id': call_id, 'status': part.get('state', {}).get('status')})
                continue
            try:
                key = visible_marker(part, arm, selected)
                visible.append(key)
                observations.append({'call_id': call_id, 'query_sha256': key[0], 'audit_receipt': key[1], 'format': selected})
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                errors.append({'call_id': call_id, 'reason': str(error)})
    for index, event in enumerate(events):
        if event.get('event') != 'memory_lookup':
            continue
        try:
            if arm == 'plain':
                raise ValueError('plain observed memory backend event')
            backend.append(backend_marker(event, arm, selected))
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            errors.append({'backend_event': index, 'reason': str(error)})
    if Counter(visible) != Counter(backend):
        errors.append({'reason': 'visible/backend argument and receipt multisets differ'})
    status = 'unsupported_or_mismatch' if errors else (
        'not_applicable' if arm == 'plain' else 'matched' if visible else 'not_observed')
    return {'requested_format': selected, 'arm': arm, 'status': status,
            'completed_observations': len(observations), 'observations': observations,
            'incomplete_calls': incomplete, 'errors': errors,
            'lifecycle_records': lifecycle,
            'lifecycle_scope': 'Validated non-tool records; outcomes retained, execution success is checked separately by the session harness',
            'correlation': 'multiset of complete-arguments digest and optional receipt; no timing/order pairing inferred',
            'receipt_verification': 'metadata_binding_only; original full/projected/model bytes not checked after publication scrub'}
