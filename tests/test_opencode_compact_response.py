"""Fast authored projection/transport controls; no CAMI imports, model or Docker."""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'integrations/opencode'))
import memory_adapter as adapter  # noqa: E402
from compact_response import FORMAT, compact_result  # noqa: E402
from memory_backend import canonical, digest, rank  # noqa: E402

TEXT = 'Historical-looking prose is user text.\n@decorator\n{"nested":"unchanged"}\nUnicode π; literal \\n; "quotes".'
SUBJECT = {'language': 'python', 'path': 'src/example.py', 'qualname': 'Example.method', 'node_kind': 'method'}
SOURCE = {'path': 'src/example.py', 'sha256': 'a' * 64, 'size': 91}


def response(arm, *, withheld=False):
    entry = {'id': 'first-note', 'payload': {'type': 'note', 'subject': SUBJECT, 'note_key': 'first-key', 'text': TEXT,
             'sources': [SOURCE]}, 'origin_source': SOURCE,
             'availability': 'unchecked_current' if arm == 'static' else 'manual_assertion_source_unchanged',
             'label': 'manual_assertion'}
    if arm == 'cami':
        entry['state_type'] = 'manual_note'
    value = {'schema_version': 1, 'backend': arm, 'query': 'Example.method', 'catalog_sha256': 'b' * 64,
             'matched_records': 8, 'selected_records': 1, 'truncated': True,
             'selection_budget': {'origin_record_bytes': 16384, 'used_bytes': 1234, 'ranking_before_availability': True},
             'freshness': 'origin only; current validity unchecked' if arm == 'static' else 'verified_readset; may change after verification; refresh after edits',
             'entries': [entry], 'withheld': []}
    if arm == 'cami':
        value.update(snapshot_id='c' * 64, memory_generation_id='d' * 64)
    if withheld:
        value['entries'] = []
        value['withheld'] = [{'id': 'first-note', 'subject': SUBJECT, 'kind': 'note', 'reason': 'manual_review_required', 'required_action': 'review_and_update_note'}]
    return value


def mcp(value, error=False):
    return {'content': [{'type': 'text', 'text': canonical(value).decode()}], 'isError': error}


def body(result):
    return json.loads(result['content'][0]['text'])


def assert_receipt(result, audit):
    assert digest(audit['full_result']) == audit['receipt_payload']['full_result_sha256']
    assert digest(result) == audit['model_result_sha256']
    value = body(result)
    receipt = value.pop('audit_receipt')
    base = mcp(value, result['isError'])
    assert digest(base) == audit['receipt_payload']['projection_result_sha256']
    assert digest(audit['receipt_payload']) == receipt == audit['receipt_sha256']


@pytest.mark.parametrize('arm', ['static', 'cami'])
@pytest.mark.parametrize('withheld', [False, True])
def test_projection_preserves_text_identifiers_and_semantics(arm, withheld):
    value = response(arm, withheld=withheld)
    original = copy.deepcopy(value)
    result, audit = compact_result(mcp(value))
    compact = body(result)
    assert value == original and audit['full_result'] == mcp(original)
    for key in ['backend', 'query', 'schema_version', 'matched_records', 'selected_records', 'truncated', 'selection_budget', 'freshness', 'withheld']:
        assert compact[key] == value[key]
    assert compact['response_format'] == FORMAT
    assert 'catalog_sha256' not in compact and 'snapshot_id' not in compact and 'memory_generation_id' not in compact
    if not withheld:
        entry = compact['entries'][0]
        assert entry['id'] == 'first-note'
        assert entry['payload']['subject'] == SUBJECT
        assert entry['payload']['text'] == TEXT and entry['payload']['note_key'] == 'first-key'
        assert entry['label'] == 'manual_assertion'
        assert entry['availability'] == value['entries'][0]['availability']
        assert 'sources' not in entry['payload'] and 'origin_source' not in entry
        if arm == 'cami':
            assert entry['state_type'] == 'manual_note'
    else:
        assert compact['entries'] == [] and TEXT not in canonical(compact).decode()
    assert_receipt(result, audit)


@pytest.mark.parametrize('kind,expected', [('symbol_exists', True), ('signature_equals', {'format': 'python.ast-signature/1', 'parameters': []})])
def test_typed_expectations_are_preserved(kind, expected):
    value = response('cami')
    value['entries'][0]['payload'] = {'type': kind, 'subject': SUBJECT, 'expected': expected}
    value['entries'][0].update(label='validated_structural_fact', availability='supported', state_type='checked')
    result, audit = compact_result(mcp(value))
    assert body(result)['entries'][0]['payload'] == value['entries'][0]['payload']
    assert_receipt(result, audit)


@pytest.mark.parametrize('arm', ['static', 'cami'])
@pytest.mark.parametrize('mode', ['full', 'compact'])
@pytest.mark.parametrize('fail', [False, True])
def test_dispatch_same_backend_once_and_audited_errors(tmp_path, monkeypatch, arm, mode, fail):
    value, calls = response(arm), []
    class FakeBackend:
        def __init__(self, path):
            self.binding = {'repo': str(tmp_path / 'repo'), 'backend': arm, 'catalog_sha256': 'b' * 64, 'state_home': None}
        def lookup(self, query, limit):
            calls.append((query, limit))
            if fail:
                raise ValueError('AUTHORED failure')
            return copy.deepcopy(value), {'selected_records': 1, 'returned_records': 1, 'withheld_records': 0}
    monkeypatch.setattr(adapter, 'Backend', FakeBackend)
    trace = tmp_path / 'audit.jsonl'
    server = adapter.Server(tmp_path / 'binding.json', trace, response_format=mode)
    server.phase = 'ready'
    result = server.dispatch({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'memory_lookup', 'arguments': {'query': 'Example.method', 'limit': 3}}})
    assert calls == [('Example.method', 3)] and result['isError'] == fail
    record = json.loads(trace.read_text().splitlines()[-1])
    if mode == 'full':
        assert 'response_audit' not in record
        if not fail:
            assert result == mcp(value)  # Default/full result remains byte-identical.
        else:
            assert body(result)['error']['code'] == 'memory_lookup_failed'
    else:
        assert_receipt(result, record['response_audit'])
        if fail:
            full = body(record['response_audit']['full_result'])
            assert body(result)['error'] == full['error'] and body(result)['freshness'] == full['freshness']
            assert body(result)['entries'] == [] and body(result)['withheld'] == []
    assert record['response_bytes'] == len(canonical(result))


def test_exact_ids_distinguish_notes_and_selection_budget_is_unchanged():
    first = {'id': 'first-note', 'payload': response('static')['entries'][0]['payload'], 'source': SOURCE}
    second = copy.deepcopy(first)
    second['id'], second['payload']['note_key'] = 'second-note', 'second-key'
    catalog = {'records': [first, second]}
    selected, total = rank(catalog, 'second-note', 5)
    assert selected[0]['id'] == 'second-note' and total == 2
    value = response('static')
    value['entries'] = [dict(response('static')['entries'][0], id=r['id'], payload=r['payload']) for r in selected]
    value['selection_budget']['used_bytes'] = sum(len(canonical(r)) for r in selected)
    before = canonical(catalog)
    result, _ = compact_result(mcp(value))
    assert [e['id'] for e in body(result)['entries']] == [r['id'] for r in selected]
    assert body(result)['selection_budget'] == value['selection_budget'] and canonical(catalog) == before
    oversized = copy.deepcopy(first)
    oversized['payload']['text'] = 'x' * 17000
    assert rank({'records': [oversized, second]}, 'first-note', 5)[0] == []


def test_audit_receipt_changes_for_full_provenance_or_model_text_or_error_status():
    full = mcp(response('static'))
    result, audit = compact_result(full)
    changed = copy.deepcopy(full)
    val = body(changed)
    val['catalog_sha256'] = 'f' * 64
    changed['content'][0]['text'] = canonical(val).decode()
    assert compact_result(changed)[1]['receipt_sha256'] != audit['receipt_sha256']
    val['entries'][0]['payload']['text'] += 'new text'
    changed['content'][0]['text'] = canonical(val).decode()
    assert compact_result(changed)[1]['receipt_sha256'] != audit['receipt_sha256']
    changed = copy.deepcopy(full)
    changed['isError'] = True
    assert compact_result(changed)[1]['receipt_sha256'] != audit['receipt_sha256']
    assert_receipt(result, audit)


@pytest.mark.parametrize('mode', ['full', 'compact'])
def test_cli_optin_and_default(monkeypatch, tmp_path, mode):
    seen = []
    monkeypatch.setattr(adapter, 'serve', lambda binding, trace, **kwargs: seen.append(kwargs))
    argv = ['memory_adapter.py', 'serve', '--binding', str(tmp_path / 'binding'), '--trace', str(tmp_path / 'trace')]
    if mode == 'compact':
        argv += ['--response-format', 'compact']
    monkeypatch.setattr(sys, 'argv', argv)
    assert adapter.main() == 0 and seen == [{'response_format': mode}]


def test_stdio_compact_transport_has_only_jsonrpc_stdout(tmp_path, monkeypatch):
    class FakeBackend:
        def __init__(self, path):
            self.binding = {'repo': str(tmp_path / 'repo'), 'backend': 'static', 'catalog_sha256': 'b' * 64, 'state_home': None}
        def lookup(self, query, limit):
            return response('static'), {}
    monkeypatch.setattr(adapter, 'Backend', FakeBackend)
    messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'clientInfo': {}, 'capabilities': {}}},
                {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'memory_lookup', 'arguments': {'query': 'Example.method'}}}]
    incoming, outgoing = io.BytesIO(b''.join(canonical(m) + b'\n' for m in messages)), io.BytesIO()
    adapter.serve(tmp_path / 'binding', tmp_path / 'trace', incoming, outgoing, response_format='compact')
    replies = [json.loads(line) for line in outgoing.getvalue().splitlines()]
    assert [r['id'] for r in replies] == [1, 2]
    assert body(replies[-1]['result'])['response_format'] == FORMAT


def test_failed_audit_append_does_not_return_unbound_compact_response(tmp_path, monkeypatch):
    class FakeBackend:
        def __init__(self, path):
            self.binding = {'repo': str(tmp_path / 'repo'), 'backend': 'static', 'catalog_sha256': 'b' * 64, 'state_home': None}
        def lookup(self, query, limit):
            return response('static'), {}
    monkeypatch.setattr(adapter, 'Backend', FakeBackend)
    server = adapter.Server(tmp_path / 'binding', tmp_path / 'trace', response_format='compact')
    server.phase = 'ready'
    def fail(*args):
        raise OSError('AUTHORED trace failure')
    monkeypatch.setattr(adapter, 'trace', fail)
    with pytest.raises(OSError, match='trace failure'):
        server.dispatch({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'memory_lookup', 'arguments': {'query': 'Example.method'}}})
