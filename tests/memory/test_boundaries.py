from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys

import pytest

from cami.errors import IncompleteError
from cami.product.memory.adapters import ecma_view
from cami.product.memory.models import IndexRef, PathCoverage, RecordRevision, SignaturePayload
from cami.product.memory.validation import check
from cami.product.service import ProductMemory
from cami.typescript_analyzer import analyze_typescript

BASE = 'def target(x: int = None) -> int:\n    return x\n'
SUBJECT = 'src/api.py:target'


@pytest.fixture
def memory(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    (root / 'src').mkdir(parents=True)
    (root / 'src/api.py').write_text(BASE)
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    return ProductMemory(root)


def cli(memory, *args, timeout=5):
    return subprocess.run([sys.executable, '-B', '-m', 'cami.cli', 'memory', *args,
                           '--repo', str(memory.root), '--format', 'json'],
                          capture_output=True, text=True, timeout=timeout)


def ecma(source):
    raw = source.encode()
    fingerprint = hashlib.sha256(raw).hexdigest()
    ref = IndexRef(worktree_key='a' * 64, snapshot_id=fingerprint, generation_id=fingerprint,
                   policy_fingerprint='b' * 64, analyzer_fingerprint='c' * 64)
    return ecma_view(analyze_typescript({'api.ts': raw}), ref, {'api.ts': raw},
                     (PathCoverage(path='api.ts', status='present'),))


@pytest.mark.parametrize(('old', 'new'), [
    ('x = -1', 'x = +1'),
    ('x = ++counter', 'x = --counter'),
    ('x = counter++', 'x = counter--'),
    ('x = left + right', 'x = left - right'),
    ('x = left && right', 'x = left || right'),
    ('x = left < right', 'x = left > right'),
    ('x = left ?? right', 'x = left || right'),
    ('x: keyof string[]', 'x: readonly string[]'),
    ('x: {readonly key: string}', 'x: {key: string}'),
    ('x: {key?: string}', 'x: {key: string}'),
    ('x: [string, number]', 'x: [number, string]'),
    ('x = [1, 2]', 'x = [2, 1]'),
    ('x = "first"', 'x = "second"'),
    ('x = /a/i', 'x = /a/g'),
    ('x = `a${left}b`', 'x = `a${right}b`'),
    ('x: {[K in keyof T]+?: T[K]}', 'x: {[K in keyof T]-?: T[K]}'),
])
def test_ecma_semantic_syntax_changes_contradict(old, new):
    origin = ecma(f'export function target({old}) {{ return 1; }}')
    current = ecma(f'export function target({new}) {{ return 1; }}')
    definition = origin.definitions[0]
    record = RecordRevision(memory_id='d' * 64, revision=1,
                            payload=SignaturePayload(subject=definition.subject,
                                                     expected=definition.signature),
                            origin=origin.index, created_at='fixture', previous_revision=None)
    result = check(record, current, 'changed')
    assert (result.verdict, result.reason) == ('contradicted', 'signature_mismatch')


def test_ecma_comments_and_format_are_equal():
    old = ecma('export function target(x = -1, y: keyof string[]) { return 1; }')
    new = ecma('export function target( x /* note */ = - 1,\n'
               ' y: keyof /* note */ string [ ] ) { return 2; }')
    assert old.definitions[0].signature == new.definitions[0].signature


@pytest.mark.parametrize('kind', ['fifo', 'directory', 'symlink', 'oversized'])
def test_cas_special_files_fail_without_losing_head(memory, tmp_path, kind):
    origin = memory.context(SUBJECT)
    receipt = memory.remember('signature_equals', SUBJECT, origin, 'claim')
    history = memory.history(receipt.memory_id)
    source = origin.code[0].source
    path = memory.store.objects / source.sha256
    path.unlink()
    if kind == 'fifo':
        os.mkfifo(path)
    elif kind == 'directory':
        path.mkdir()
    elif kind == 'symlink':
        target = tmp_path / 'same-bytes'
        target.write_bytes(BASE.encode())
        path.symlink_to(target)
    else:
        with path.open('wb') as stream:
            stream.truncate(1024 * 1024 * 1024)
    try:
        result = cli(memory, 'context', SUBJECT, timeout=3)
        assert result.returncode == 4, result.stdout + result.stderr
        assert 'source_evidence_' in result.stderr
    finally:
        if kind == 'directory':
            path.rmdir()
        else:
            path.unlink()
        path.write_bytes(BASE.encode())
    assert memory.history(receipt.memory_id) == history
    assert cli(memory, 'context', SUBJECT).returncode == 0


def test_missing_established_database_is_not_recreated(memory):
    origin = memory.context(SUBJECT)
    receipt = memory.remember('symbol_exists', SUBJECT, origin, 'claim')
    history = memory.history(receipt.memory_id)
    raw = memory.store.path.read_bytes()
    memory.store.path.unlink()
    result = cli(memory, 'context', SUBJECT)
    assert result.returncode == 4, result.stdout + result.stderr
    assert 'memory_database_unavailable' in result.stderr
    assert not memory.store.path.exists()
    memory.store.path.write_bytes(raw)
    assert memory.history(receipt.memory_id) == history
    assert len(memory.context(SUBJECT).facts) == 1


def test_existing_unknown_database_is_never_initialized(memory):
    memory.index_store.path.mkdir(parents=True)
    with sqlite3.connect(memory.store.path) as db:
        db.execute('CREATE TABLE precious(value TEXT)')
        db.execute("INSERT INTO precious VALUES('keep')")
    with pytest.raises(IncompleteError, match='memory_schema_error'):
        memory.context(SUBJECT)
    with sqlite3.connect(memory.store.path) as db:
        assert db.execute('SELECT value FROM precious').fetchone() == ('keep',)


def test_old_signature_format_is_withheld_without_retargeting():
    view = ecma('export function target(x = +1) {}')
    definition = view.definitions[0]
    old_expected = definition.signature.model_copy(update={'format': 'ecma.syntax-signature/1'})
    record = RecordRevision(memory_id='d' * 64, revision=1,
                            payload=SignaturePayload(subject=definition.subject,
                                                     expected=old_expected),
                            origin=view.index, created_at='fixture', previous_revision=None)
    result = check(record, view, 'upgrade')
    assert (result.verdict, result.reason) == ('insufficient_evidence', 'signature_schema_mismatch')
    assert record.payload.expected.format == 'ecma.syntax-signature/1'


def test_legacy_database_is_adopted_without_changing_knowledge(memory):
    origin = memory.context(SUBJECT)
    receipt = memory.remember('symbol_exists', SUBJECT, origin, 'claim')
    history = memory.history(receipt.memory_id)
    memory.store.initialized.unlink()
    assert memory.history(receipt.memory_id) == history
    assert memory.store.initialized.is_file()
    assert memory.remember('symbol_exists', SUBJECT, origin, 'claim') == receipt


def test_legacy_source_objects_prove_missing_database_is_loss(memory):
    memory.context(SUBJECT)
    memory.store.initialized.unlink()
    memory.store.path.unlink()
    result = cli(memory, 'context', SUBJECT)
    assert result.returncode == 4 and 'memory_database_unavailable' in result.stderr
    assert not memory.store.path.exists()


@pytest.mark.parametrize('kind', ['fifo', 'directory', 'symlink', 'dangling'])
def test_database_special_paths_do_not_block_or_create_empty(memory, tmp_path, kind):
    memory.context(SUBJECT)
    raw = memory.store.path.read_bytes()
    memory.store.path.unlink()
    if kind == 'fifo':
        os.mkfifo(memory.store.path)
    elif kind == 'directory':
        memory.store.path.mkdir()
    else:
        target = tmp_path / 'outside-db'
        if kind == 'symlink':
            target.write_bytes(raw)
        memory.store.path.symlink_to(target)
    result = cli(memory, 'context', SUBJECT)
    assert result.returncode == 4 and not result.stdout
    if kind == 'dangling':
        assert not target.exists()
    if kind == 'symlink':
        assert target.read_bytes() == raw


@pytest.mark.parametrize('point', [
    'before-schema', 'after-schema', 'before-db-publish', 'after-db-publish',
    'before-owner-publish', 'after-owner-publish', 'before-yield',
])
def test_first_use_kill_and_retry_is_idempotent(memory, tmp_path, point):
    script = '''
import os, signal, sqlite3, sys
from cami.cli import main
from cami.product.memory.store import MemoryStore
point = sys.argv[1]
def kill():
    os.kill(os.getpid(), signal.SIGKILL)
original_connect = sqlite3.connect
class KillConnection(sqlite3.Connection):
    def executescript(self, script):
        if point == 'before-schema': kill()
        result = super().executescript(script)
        if point == 'after-schema': kill()
        return result
def connect(*args, **kwargs):
    return original_connect(*args, **kwargs, factory=KillConnection)
sqlite3.connect = connect
original_replace = os.replace
original_link = os.link
def link(source, destination, *args, **kwargs):
    if point == 'before-db-publish': kill()
    result = original_link(source, destination, *args, **kwargs)
    if point == 'after-db-publish': kill()
    return result
os.link = link
def replace(source, destination, *args, **kwargs):
    phase = 'db-publish' if str(destination).endswith('memory.sqlite3') else 'owner-publish'
    if point == 'before-' + phase: kill()
    result = original_replace(source, destination, *args, **kwargs)
    if point == 'after-' + phase: kill()
    return result
os.replace = replace
original_mark = MemoryStore._mark_initialized
def mark(self):
    original_mark(self)
    if point == 'before-yield': kill()
MemoryStore._mark_initialized = mark
main(sys.argv[2:])
'''
    killed = subprocess.run([sys.executable, '-B', '-c', script, point, 'memory', 'context',
                             SUBJECT, '--repo', str(memory.root), '--format', 'json'],
                            capture_output=True, text=True, timeout=5)
    assert killed.returncode == -9, killed.stderr
    first = cli(memory, 'context', SUBJECT)
    assert first.returncode == 0, first.stderr
    context = json.loads(first.stdout)
    marker = memory.store.initialized.read_bytes()
    second = cli(memory, 'context', SUBJECT)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)['memory_generation_id'] == context['memory_generation_id']
    path = tmp_path / 'context.json'
    path.write_text(first.stdout)
    args = ('remember', 'symbol_exists', SUBJECT, '--from-context', str(path),
            '--request-id', 'retry-first-use')
    receipt = cli(memory, *args)
    repeated = cli(memory, *args)
    assert receipt.returncode == repeated.returncode == 0
    assert receipt.stdout == repeated.stdout
    assert len(memory.history(json.loads(receipt.stdout)['memory_id']).revisions) == 1
    assert memory.store.initialized.read_bytes() == marker


@pytest.mark.parametrize('kind', ['fifo', 'directory', 'symlink', 'oversized'])
def test_context_input_reads_are_bounded_and_do_not_follow(memory, tmp_path, kind):
    origin = memory.context(SUBJECT)
    path = tmp_path / 'context.json'
    if kind == 'fifo':
        os.mkfifo(path)
    elif kind == 'directory':
        path.mkdir()
    elif kind == 'symlink':
        target = tmp_path / 'valid-context.json'
        target.write_text(origin.model_dump_json())
        path.symlink_to(target)
    else:
        with path.open('wb') as stream:
            stream.truncate(1024 * 1024 * 1024)
    result = cli(memory, 'remember', 'symbol_exists', SUBJECT, '--from-context', str(path),
                 '--request-id', 'bad-input')
    assert result.returncode == 4 and 'context_evidence_unavailable' in result.stderr
    assert not memory.context(SUBJECT).facts


def test_cas_permission_error_preserves_head_and_history(memory, monkeypatch):
    from cami.product import store

    origin = memory.context(SUBJECT)
    receipt = memory.remember('symbol_exists', SUBJECT, origin, 'claim')
    before = memory.history(receipt.memory_id)
    read = store._cache_open
    def denied(name, *args):
        if str(name) == origin.code[0].source.sha256:
            raise PermissionError('controlled evidence denial')
        return read(name, *args)
    with monkeypatch.context() as patch:
        patch.setattr(store, '_cache_open', denied)
        with pytest.raises(IncompleteError, match='source_evidence_unavailable'):
            memory.context(SUBJECT)
    assert memory.history(receipt.memory_id) == before


def test_cas_growth_is_bounded_and_rejected(memory, monkeypatch):
    from cami.product import store

    origin = memory.context(SUBJECT)
    source = origin.code[0].source
    path = memory.store.objects / source.sha256
    read = os.read
    count = 0
    def growing(fd, size):
        nonlocal count
        count += 1
        assert count <= 2
        result = read(fd, size)
        with path.open('ab') as stream:
            stream.write(b'x' * 1024)
        return result
    monkeypatch.setattr(store.os, 'read', growing)
    with pytest.raises(IncompleteError, match='source_evidence_corrupt'):
        memory.store.read_source(source)
    assert count == 2


def test_integrator_can_supply_trusted_compiler_location(tmp_path, monkeypatch):
    from cami.product.memory import adapters
    from cami.typescript_runtime import compiler_path

    raw = b'export function target(x = -1) {}'
    analysis = analyze_typescript({'api.ts': raw})
    compiler = compiler_path()
    view = ecma(raw.decode())
    monkeypatch.setattr(adapters, 'compiler_path', lambda: tmp_path / 'unused')
    actual = ecma_view(analysis, view.index, {'api.ts': raw}, view.coverage,
                       trusted_compiler=compiler)
    assert actual.definitions == view.definitions
