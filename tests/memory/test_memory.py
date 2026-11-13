from __future__ import annotations

import ast
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from cami.errors import IncompleteError, InputError
from cami.product.memory.adapters import HybridIndexPort, ecma_view, python_signature
from cami.product.memory.models import (
    AgentContext, CheckedClaim, ExistsPayload, IndexRef,
    PathCoverage, RecordRevision, SignaturePayload, SymbolKey,
)
from cami.product.memory.validation import check
from cami.product.service import ProductMemory
from cami.typescript_analyzer import analyze_typescript

BASE = 'def create_user(name: str) -> str:\n    return name\n'
BODY = 'def create_user(name: str) -> str:\n    return "user"\n'
SUBJECT = 'src/api.py:create_user'


@pytest.fixture
def memory(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    (root / 'src').mkdir()
    (root / 'src/api.py').write_text(BASE)
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    return ProductMemory(root)


def cli(memory, *args):
    return subprocess.run([sys.executable, '-m', 'cami.cli', 'memory', *args,
                           '--repo', str(memory.root), '--format', 'json'],
                          capture_output=True, text=True)


def pin(memory, tmp_path):
    context = memory.context(SUBJECT)
    path = tmp_path / 'context.json'
    path.write_text(context.model_dump_json())
    return context, path


def test_real_cli_driver(tmp_path):
    script = Path(__file__).with_name('cli_driver.py')
    result = subprocess.run([sys.executable, str(script), '--out', str(tmp_path / 'acceptance')],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['status'] == 'passed'


def test_concurrent_remember_and_cas_updates(memory, tmp_path):
    context, path = pin(memory, tmp_path)
    def remember(request_id):
        return cli(memory, 'remember', 'symbol_exists', SUBJECT, '--from-context', str(path),
                   '--request-id', request_id)
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        results = list(pool.map(remember, ('worker-a', 'worker-b')))
    assert [r.returncode for r in results] == [0, 0]
    receipts = [json.loads(r.stdout) for r in results]
    assert receipts[0]['memory_id'] == receipts[1]['memory_id']
    assert sorted(r['changed'] for r in receipts) == [False, True]
    history = memory.history(receipts[0]['memory_id'])
    assert len(history.revisions) == len(history.checks) == 1
    note = memory.remember('note', SUBJECT, context, 'note', note_key='key', text='Original')
    def update(text):
        return cli(memory, 'update', note.memory_id, '--if-revision', '1',
                   '--from-context', str(path), '--request-id', f'update-{text}', '--text', text)
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        updates = list(pool.map(update, ('A', 'B')))
    assert sorted(r.returncode for r in updates) == [0, 2]
    assert 'revision_conflict' in next(r.stderr for r in updates if r.returncode == 2)
    assert len(memory.history(note.memory_id).revisions) == 2


def test_stale_origin_and_context_tampering(memory, tmp_path):
    context, _ = pin(memory, tmp_path)
    (memory.root / 'src/api.py').write_text('def create_user(name: int) -> int:\n    return name\n')
    receipt = memory.remember('signature_equals', SUBJECT, context, 'stale')
    current = memory.context(SUBJECT)
    item = current.withheld[0]
    assert item.reason == 'signature_mismatch'
    assert item.record.origin == context.index
    assert isinstance(item.state, CheckedClaim)
    assert item.state.check.index == current.index
    assert memory.remember('signature_equals', SUBJECT, context, 'stale') == receipt
    raw = context.model_dump(mode='json')
    raw['code'][0]['signature']['parameters'][0]['name'] = 'forged'
    forged = AgentContext.model_validate_json(json.dumps(raw))
    with pytest.raises(InputError, match='context_mismatch'):
        memory.remember('signature_equals', SUBJECT, forged, 'forged')
    with pytest.raises(InputError, match='request_id_conflict'):
        memory.remember('symbol_exists', SUBJECT, context, 'stale')


@pytest.mark.parametrize('policy', ['exclude', 'ignore', 'symlink'])
def test_uncovered_is_not_absence(memory, policy):
    context = memory.context(SUBJECT)
    memory.remember('symbol_exists', SUBJECT, context, 'exists')
    path = memory.root / 'src/api.py'
    if policy == 'exclude':
        memory.excludes = ('src',)
    elif policy == 'ignore':
        (memory.root / '.gitignore').write_text('src/\n')
    else:
        path.unlink()
        path.symlink_to('missing.py')
    current = memory.context(SUBJECT)
    assert not current.facts
    assert current.withheld[0].reason == ('source_unavailable' if policy == 'symlink'
                                          else 'scope_uncovered')
    assert current.withheld[0].state.check.verdict == 'insufficient_evidence'


def test_missing_parent_path_has_captured_witness(memory):
    context = memory.context(SUBJECT)
    memory.remember('symbol_exists', SUBJECT, context, 'exists')
    (memory.root / 'src/api.py').unlink()
    (memory.root / 'src').rmdir()
    current = memory.context(SUBJECT)
    check_ref = current.withheld[0].state.check
    assert check_ref.reason == 'subject_absent'
    assert check_ref.evidence[0].reason == 'path_absent_in_scope'
    assert check_ref.evidence[0].index == current.index


def test_failed_refresh_keeps_historical_head_and_returns_error(memory, monkeypatch):
    origin = memory.context(SUBJECT)
    memory.remember('symbol_exists', SUBJECT, origin, 'exists')
    with memory.index_store.writer(), memory.store.connection() as db:
        before = memory.store.head(db)
    (memory.root / 'src/api.py').write_text(BODY)
    def fail(*args):
        raise IncompleteError('fixture interrupted before commit')
    monkeypatch.setattr(HybridIndexPort, 'verify', fail)
    with pytest.raises(IncompleteError, match='interrupted'):
        memory.context(SUBJECT)
    with memory.index_store.writer(), memory.store.connection() as db:
        assert memory.store.head(db) == before
    monkeypatch.undo()


def test_old_source_and_corrupt_database_are_not_empty_memory(memory):
    context = memory.context(SUBJECT)
    memory.remember('symbol_exists', SUBJECT, context, 'exists')
    source = context.code[0].source
    (memory.root / 'src/api.py').write_text(BODY)
    memory.context(SUBJECT)
    assert memory.store.read_source(source) == BASE.encode()
    (memory.store.objects / source.sha256).write_bytes(b'corrupt')
    with pytest.raises(IncompleteError, match='source_evidence_corrupt'):
        memory.context(SUBJECT)
    memory.store.path.write_bytes(b'not sqlite')
    with pytest.raises(IncompleteError, match='memory_database_error'):
        memory.context(SUBJECT)


def test_rename_and_removed_edges_remain_in_invalidation_scopes(memory):
    (memory.root / 'src/api.py').write_text('def callee():\n    return 1\n\n'
                                          'def create_user(name: str) -> str:\n    callee()\n    return name\n')
    origin = memory.context(SUBJECT)
    memory.remember('symbol_exists', SUBJECT, origin, 'exists')
    before = memory.refresh()
    (memory.root / 'src/api.py').rename(memory.root / 'src/renamed.py')
    after = memory.refresh()
    assert after.states[0].state.check.reason == 'subject_absent'
    assert 'src/api.py' in after.states[0].invalidation_scopes
    assert {s for s in before.states[0].invalidation_scopes if s.startswith('edge:')} \
        <= set(after.states[0].invalidation_scopes)


def test_python_default_none_type_parameters_and_body_independence():
    old = ast.parse('async def f[T](x: T = None, *, y=None) -> T:\n    return x\n').body[0]
    new = ast.parse('async def f[T](x: T = None, *, y=None) -> T:\n    raise Exception()\n').body[0]
    assert python_signature(old) == python_signature(new)
    value = python_signature(old)
    assert value.parameters[0].default == 'Constant(value=None)'
    assert value.parameters[1].default == 'Constant(value=None)'
    assert value.type_parameters == ("TypeVar(name='T')",)
    absent = python_signature(ast.parse('def f(x):\n    pass\n').body[0])
    assert absent.parameters[0].default is None


def test_actual_ecma_port_and_neutral_predicates():
    def view(raw):
        analysis = analyze_typescript({'src/api.ts': raw})
        ref = IndexRef(worktree_key='a' * 64, snapshot_id=hashlib.sha256(raw).hexdigest(),
                       generation_id=hashlib.sha256(raw).hexdigest(),
                       policy_fingerprint='b' * 64, analyzer_fingerprint='c' * 64)
        return ecma_view(analysis, ref, {'src/api.ts': raw},
                         (PathCoverage(path='src/api.ts', status='present'),))
    initial = view(b'export function create_user(name: string): string { return name; }')
    definition = initial.definitions[0]
    expected = definition.signature
    assert expected.model_dump(mode='json') == {
        'format': 'ecma.syntax-signature/2', 'parameters': [
            {'pattern': '["Identifier","name"]', 'optional': False, 'rest': False,
             'default': None, 'annotation': '["StringKeyword","string"]'}],
        'type_parameters': [], 'return_annotation': '["StringKeyword","string"]', 'is_async': False, 'generator': False}
    record = RecordRevision(memory_id='d' * 64, revision=1,
                            payload=SignaturePayload(subject=definition.subject, expected=expected),
                            origin=initial.index, created_at='fixture', previous_revision=None)
    assert check(record, initial, 'initial').verdict == 'supported'
    body = view(b'export function create_user(name: string): string { return "user"; }')
    assert check(record, body, 'body').verdict == 'supported'
    trivia = view(b'export function create_user( name /* comment */: string ): string { return name; }')
    assert trivia.definitions[0].signature == expected
    signature = view(b'export function create_user(name: number): string { return "user"; }')
    assert check(record, signature, 'signature').reason == 'signature_mismatch'
    parse = view(b'export function create_user(:')
    assert check(record, parse, 'parse').reason == 'parse_error'
    ambiguous = view(b'function create_user(name: string) {} function create_user(name: string) {}')
    assert check(record, ambiguous, 'ambiguous').reason == 'ambiguous_binding'
    unknown = record.model_copy(update={'payload': ExistsPayload(subject=SymbolKey(
        language='unknown', path='src/api.ts', qualname='create_user', node_kind='function'))})
    assert check(unknown, initial, 'unknown').reason == 'unsupported_language'


@pytest.mark.parametrize('point', ['before-index', 'after-index', 'before-db', 'after-db'])
def test_kill_and_retry_has_one_revision_and_receipt(memory, tmp_path, point):
    context, path = pin(memory, tmp_path)
    memory.remember('note', SUBJECT, context, 'note', note_key='key', text='Old source')
    (memory.root / 'src/api.py').write_text(BODY)
    script = '''
import os, signal, sqlite3, sys
from cami.product.store import GenerationStore
from cami.cli import main
point = sys.argv[1]
if point.endswith('index'):
    original = GenerationStore.publish
    def publish(self, *args):
        if point == 'before-index': os.kill(os.getpid(), signal.SIGKILL)
        original(self, *args)
        os.kill(os.getpid(), signal.SIGKILL)
    GenerationStore.publish = publish
else:
    original_connect = sqlite3.connect
    class KillConnection(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql == 'COMMIT' and point == 'before-db':
                os.kill(os.getpid(), signal.SIGKILL)
            result = super().execute(sql, *args)
            if sql == 'COMMIT' and point == 'after-db':
                os.kill(os.getpid(), signal.SIGKILL)
            return result
    def connect(*args, **kwargs):
        return original_connect(*args, **kwargs, factory=KillConnection)
    sqlite3.connect = connect
main(sys.argv[2:])
'''
    arguments = ['memory', 'remember', 'symbol_exists', SUBJECT, '--repo', str(memory.root),
                 '--from-context', str(path), '--request-id', 'crash-request', '--format', 'json']
    killed = subprocess.run([sys.executable, '-c', script, point, *arguments],
                            capture_output=True, text=True)
    assert killed.returncode == -9, killed.stderr
    retry = subprocess.run([sys.executable, '-m', 'cami.cli', *arguments],
                           capture_output=True, text=True)
    assert retry.returncode == 0, retry.stderr
    repeated = subprocess.run([sys.executable, '-m', 'cami.cli', *arguments],
                              capture_output=True, text=True)
    assert repeated.returncode == 0, repeated.stderr
    assert json.loads(repeated.stdout) == json.loads(retry.stdout)
    receipt = json.loads(retry.stdout)
    history = memory.history(receipt['memory_id'])
    assert len(history.revisions) == 1 and len(history.checks) == 1
    current = memory.context(SUBJECT)
    assert current.index.generation_id == history.generations[-1].index.generation_id
    assert current.facts[0].state.check.index == current.index
    assert current.withheld[0].reason == 'manual_review_required'
    with sqlite3.connect(memory.store.path) as db:
        assert db.execute("SELECT count(*) FROM operation_receipt WHERE request_id='crash-request'") \
            .fetchone()[0] == 1


def test_concurrent_context_and_mutation_never_mix_generations(memory, tmp_path):
    context, path = pin(memory, tmp_path)
    memory.remember('symbol_exists', SUBJECT, context, 'exists')
    (memory.root / 'src/api.py').write_text(BODY)
    def invoke(number):
        if number % 2:
            return cli(memory, 'remember', 'signature_equals', SUBJECT, '--from-context', str(path),
                       '--request-id', f'concurrent-{number}')
        return cli(memory, 'context', SUBJECT)
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        results = list(pool.map(invoke, range(8)))
    assert all(r.returncode == 0 for r in results), [r.stderr for r in results]
    for result in results[::2]:
        current = AgentContext.model_validate_json(result.stdout)
        assert all(d.source.index == current.index for d in current.code)
        with memory.index_store.writer(), memory.store.connection() as db:
            raw = db.execute('SELECT value FROM memory_generation WHERE id=?',
                             (current.memory_generation_id,)).fetchone()[0]
        from cami.product.memory.encoding import decode_generation

        assert json.loads(decode_generation(raw))['index'] == current.index.model_dump(mode='json')


def test_actual_ecma_unsupported_method_unresolved_and_schema_mismatch():
    files = {'api.ts': b'export class User { private save(x: string = "value") {} }\n'
                       b'declare function pending(x: string): void;\n'
                       b'export const inferred = (x: string) => x;\n'}
    analysis = analyze_typescript(files)
    ref = IndexRef(worktree_key='a' * 64, snapshot_id='b' * 64, generation_id='c' * 64,
                   policy_fingerprint='d' * 64, analyzer_fingerprint='e' * 64)
    view = ecma_view(analysis, ref, files, (PathCoverage(path='api.ts', status='present'),))
    facts = {d.subject.qualname: d for d in view.definitions}
    assert facts['User.save'].signature is None
    expected = facts['inferred'].signature
    assert expected.return_annotation is None
    def record(subject, signature):
        return RecordRevision(memory_id='f' * 64, revision=1,
                              payload=SignaturePayload(subject=subject, expected=signature),
                              origin=ref, created_at='fixture', previous_revision=None)
    assert check(record(facts['User.save'].subject, expected), view, 'method').reason \
        == 'unsupported_symbol_kind'
    assert check(record(facts['pending'].subject, expected), view, 'pending').reason \
        == 'binding_unresolved'
    python = python_signature(ast.parse('def inferred(x):\n    return x\n').body[0])
    assert check(record(facts['inferred'].subject, python), view, 'schema').reason \
        == 'signature_schema_mismatch'
    unsupported = SymbolKey(language='python', path='api.ts', qualname='Missing', node_kind='class')
    assert check(record(unsupported, python), view, 'unsupported').reason == 'unsupported_symbol_kind'


def test_exact_snapshot_revert_preserves_intermediate_history(memory):
    origin = memory.context(SUBJECT)
    claim = memory.remember('signature_equals', SUBJECT, origin, 'signature')
    note = memory.remember('note', SUBJECT, origin, 'note', note_key='key', text='Manual assertion')
    supported = memory.context(SUBJECT)
    original_check = supported.facts[0].state.check
    (memory.root / 'src/api.py').write_text('def create_user(name: int):\n    return name\n')
    assert memory.context(SUBJECT).withheld[0].reason in (
        'signature_mismatch', 'manual_review_required')
    (memory.root / 'src/api.py').write_text(BASE)
    restored = memory.context(SUBJECT)
    assert restored.index == origin.index
    assert restored.memory_generation_id != supported.memory_generation_id
    assert restored.facts[0].state.type == 'checked'
    assert restored.facts[0].state.check.check_id != original_check.check_id
    assert restored.facts[0].state.check.checked_at != original_check.checked_at
    assert restored.withheld[0].record.memory_id == note.memory_id
    history = memory.history(claim.memory_id)
    assert [c.reason for c in history.checks] == [
        'predicate_matches', 'signature_mismatch', 'predicate_matches']
    repeated = memory.refresh()
    assert repeated.memory_generation_id == restored.memory_generation_id
    assert len(memory.history(claim.memory_id).checks) == 3
