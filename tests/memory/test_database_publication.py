from __future__ import annotations

import hashlib
import json
import subprocess
import sys

import pytest

from cami.product.service import ProductMemory

SUBJECT = 'src/api.py:target'
SOURCE = b'def target(x):\n    return x\n'
CRASH = '''
import os, signal, sqlite3, sys
c = sqlite3.connect(sys.argv[1], isolation_level=None)
c.execute('PRAGMA cache_size=1')
c.execute('BEGIN IMMEDIATE')
c.execute('UPDATE index_view SET value=?', ('uncommitted' * 100000,))
os.kill(os.getpid(), signal.SIGKILL)
'''
INTERRUPT = '''
import json, os, signal, sys
from pathlib import Path
from cami.cli import main
from cami.product.memory import database
point, trace = sys.argv[1], Path(sys.argv[2])
phase = 'start'
events = []
def at(event):
    events.append(event)
    trace.write_text(json.dumps(events))
    if event == point:
        os.kill(os.getpid(), signal.SIGKILL)
rename, replace, unlink, sync = os.rename, os.replace, Path.unlink, database._sync_directory
fsync = os.fsync
def fsync_hook(fd):
    result = fsync(fd)
    events.append({'fsync': os.readlink('/proc/self/fd/' + str(fd))})
    trace.write_text(json.dumps(events))
    return result
def rename_hook(source, destination, *args, **kwargs):
    global phase
    if Path(destination).name == 'memory.pending':
        at('before-intent')
        result = rename(source, destination, *args, **kwargs)
        phase = 'intent'
        at('after-intent')
        return result
    return rename(source, destination, *args, **kwargs)
def replace_hook(source, destination, *args, **kwargs):
    global phase
    if Path(destination).name == 'memory.sqlite3':
        at('before-main')
        result = replace(source, destination, *args, **kwargs)
        phase = 'main'
        at('after-main')
        return result
    if Path(source).name == 'memory.pending':
        at('before-retire')
        result = replace(source, destination, *args, **kwargs)
        phase = 'retire'
        at('after-retire')
        return result
    return replace(source, destination, *args, **kwargs)
def unlink_hook(path, *args, **kwargs):
    global phase
    if path.name == 'memory.sqlite3-journal':
        at('before-journal-remove')
        result = unlink(path, *args, **kwargs)
        phase = 'journal-remove'
        at('after-journal-remove')
        return result
    return unlink(path, *args, **kwargs)
def sync_hook(path):
    if phase == 'intent' and point == 'fail-intent-sync':
        at('intent-sync-error')
        raise OSError('controlled publication directory fsync failure')
    if phase == 'retire' and point == 'fail-retire-sync':
        at('retire-sync-error')
        raise OSError('controlled publication directory fsync failure')
    result = sync(path)
    if phase in ('intent', 'journal-remove', 'main', 'retire'):
        at('after-' + phase + '-sync')
    return result
os.rename, os.replace, Path.unlink, database._sync_directory = (
    rename_hook, replace_hook, unlink_hook, sync_hook)
os.fsync = fsync_hook
raise SystemExit(main(sys.argv[3:]))
'''


@pytest.fixture
def memory(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    (root / 'src').mkdir(parents=True)
    (root / 'src/api.py').write_bytes(SOURCE)
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    return ProductMemory(root)


def hashes(directory):
    return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob('*') if p.is_file()}


def cli(memory, commands, *args, script=None, timeout=10):
    argv = [sys.executable, '-B', *(['-c', *script] if script else ['-m', 'cami.cli']),
            'memory', *map(str, args), '--repo', str(memory.root), '--format', 'json']
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    commands.append(dict(argv=argv, exit=result.returncode, stdout=result.stdout,
                         stderr=result.stderr))
    return result


@pytest.mark.parametrize('point', [
    'before-intent', 'after-intent', 'after-intent-sync',
    'before-journal-remove', 'after-journal-remove', 'after-journal-remove-sync',
    'before-main', 'after-main', 'after-main-sync',
    'before-retire', 'after-retire', 'after-retire-sync',
])
def test_hot_journal_publication_crash_recovers_exact_history_and_context(memory, tmp_path, point):
    context = memory.context(SUBJECT)
    receipt = memory.remember('symbol_exists', SUBJECT, context, 'durable')
    before = memory.context(SUBJECT)
    history = memory.history(receipt.memory_id)
    original_sources = hashes(memory.store.objects)
    original_marker = memory.store.initialized.read_bytes()
    journal = memory.store.path.with_name('memory.sqlite3-journal')
    killed = subprocess.run([sys.executable, '-B', '-c', CRASH, str(memory.store.path)],
                            text=True, capture_output=True, timeout=10)
    assert killed.returncode == -9, killed.stderr
    hot, recovery = memory.store.path.read_bytes(), journal.read_bytes()
    (tmp_path / 'before-hot.sqlite3').write_bytes(hot)
    (tmp_path / 'before-hot-journal').write_bytes(recovery)
    commands = []
    interrupted = cli(memory, commands, 'history', receipt.memory_id,
                      script=[INTERRUPT, point, str(tmp_path / 'events.json')])
    assert interrupted.returncode == -9, interrupted.stdout + interrupted.stderr
    after = hashes(memory.store.path.parent)
    # New main bytes must never coexist with the old live recovery journal.
    if memory.store.path.read_bytes() != hot:
        assert not journal.exists()
    pending = memory.store.path.with_name('memory.pending')
    if point in ('before-intent', 'after-intent', 'after-intent-sync', 'before-journal-remove'):
        assert memory.store.path.read_bytes() == hot and journal.read_bytes() == recovery
    if pending.exists():
        assert (pending / 'original-journal').read_bytes() == recovery
        assert (pending / 'next.sqlite3').stat().st_size > 0
    events = json.loads((tmp_path / 'events.json').read_text())
    if 'before-journal-remove' in events:
        synced = [e['fsync'] for e in events[:events.index('before-journal-remove')]
                  if isinstance(e, dict)]
        for name in ('next.sqlite3', 'commit.json', 'original-journal'):
            assert any(p.endswith('/' + name) for p in synced)
        assert str(memory.store.path.parent) in synced
    result = cli(memory, commands, 'history', receipt.memory_id)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == history.model_dump(mode='json')
    result = cli(memory, commands, 'context', SUBJECT)
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    assert actual['facts'] == before.model_dump(mode='json')['facts']
    assert actual['memory_generation_id'] == before.memory_generation_id
    replay = tmp_path / 'context.json'
    replay.write_text(context.model_dump_json())
    result = cli(memory, commands, 'remember', 'symbol_exists', SUBJECT,
                 '--from-context', replay, '--request-id', 'durable')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == receipt.model_dump(mode='json')
    assert hashes(memory.store.objects) == original_sources
    assert memory.store.initialized.read_bytes() == original_marker
    assert not pending.exists() and not journal.exists()
    (tmp_path / 'evidence.json').write_text(json.dumps(dict(
        point=point, before_hot_sha256=hashlib.sha256(hot).hexdigest(),
        before_journal_sha256=hashlib.sha256(recovery).hexdigest(),
        after_interrupt=after, after_recovery=hashes(memory.store.path.parent),
        commands=commands), indent=2))


@pytest.mark.parametrize('point', ['before-intent', 'after-intent-sync',
                                   'after-journal-remove-sync', 'after-main-sync'])
def test_hot_journal_mutation_crash_and_retry_has_one_receipt(memory, tmp_path, point):
    context = memory.context(SUBJECT)
    original = memory.remember('symbol_exists', SUBJECT, context, 'original')
    history = memory.history(original.memory_id)
    pin = tmp_path / 'pin.json'
    pin.write_text(context.model_dump_json())
    killed = subprocess.run([sys.executable, '-B', '-c', CRASH, str(memory.store.path)],
                            text=True, capture_output=True, timeout=10)
    assert killed.returncode == -9, killed.stderr
    args = ('remember', 'signature_equals', SUBJECT, '--from-context', pin,
            '--request-id', 'hot-mutation')
    commands = []
    interrupted = cli(memory, commands, *args,
                      script=[INTERRUPT, point, str(tmp_path / 'events.json')])
    assert interrupted.returncode == -9, interrupted.stderr
    first = cli(memory, commands, *args)
    second = cli(memory, commands, *args)
    assert first.returncode == second.returncode == 0, first.stderr + second.stderr
    assert first.stdout == second.stdout
    receipt = json.loads(first.stdout)
    result = cli(memory, commands, 'history', receipt['memory_id'])
    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)['revisions']) == 1
    assert len(json.loads(result.stdout)['checks']) == 1
    assert memory.history(original.memory_id).revisions == history.revisions
    assert memory.history(original.memory_id).checks == history.checks
    result = cli(memory, commands, 'context', SUBJECT)
    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)['facts']) == 2
    (tmp_path / 'evidence.json').write_text(json.dumps(dict(point=point, commands=commands), indent=2))


@pytest.mark.parametrize('transaction', ['read', 'write'])
def test_active_external_sqlite_transaction_is_bounded_and_preserves_recovery(memory, transaction):
    origin = memory.context(SUBJECT)
    receipt = memory.remember('symbol_exists', SUBJECT, origin, 'original')
    history = memory.history(receipt.memory_id)
    script = '''
import sqlite3, sys
c = sqlite3.connect(sys.argv[1], isolation_level=None)
if sys.argv[2] == 'write':
    c.execute('PRAGMA cache_size=1')
    c.execute('BEGIN IMMEDIATE')
    c.execute('UPDATE index_view SET value=?', ('uncommitted' * 100000,))
else:
    c.execute('BEGIN')
    c.execute('SELECT value FROM index_view').fetchall()
print('ready', flush=True)
sys.stdin.read()
c.execute('ROLLBACK')
c.close()
'''
    external = subprocess.Popen([sys.executable, '-B', '-c', script, str(memory.store.path),
                                 transaction], text=True, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert external.stdout.readline() == 'ready\n'
        before = hashes(memory.store.path.parent)
        commands = []
        result = cli(memory, commands, 'history', receipt.memory_id, timeout=3)
        assert result.returncode == 4 and not result.stdout, result.stdout + result.stderr
        assert 'memory_database_busy' in result.stderr
        assert hashes(memory.store.path.parent) == before
    finally:
        external.communicate(timeout=10)
    assert external.returncode == 0
    assert memory.history(receipt.memory_id) == history
    assert len(memory.context(SUBJECT).facts) == 1


@pytest.mark.parametrize('kind', ['super-journal', 'unknown-journal', 'oversized-recovery'])
def test_unsupported_recovery_keeps_every_byte_for_control_recovery(memory, tmp_path, kind):
    origin = memory.context(SUBJECT)
    receipt = memory.remember('symbol_exists', SUBJECT, origin, 'original')
    history = memory.history(receipt.memory_id)
    killed = subprocess.run([sys.executable, '-B', '-c', CRASH, str(memory.store.path)],
                            text=True, capture_output=True, timeout=10)
    assert killed.returncode == -9, killed.stderr
    journal = memory.store.path.with_name('memory.sqlite3-journal')
    original = journal.read_bytes()
    raw = bytearray(original)
    external = tmp_path / 'external-master-journal'
    external.write_bytes(b'keep this unrelated recovery evidence')
    if kind == 'super-journal':
        name = str(external).encode()
        raw.extend(name + len(name).to_bytes(4, 'big') + sum(name).to_bytes(4, 'big')
                   + bytes.fromhex('d9d505f920a163d7'))
    elif kind == 'unknown-journal':
        raw[:8] = b'unknown!'
    else:
        raw[16:20] = (0xffffffff).to_bytes(4, 'big')
    journal.write_bytes(raw)
    before = hashes(memory.store.path.parent)
    commands = []
    result = cli(memory, commands, 'history', receipt.memory_id)
    assert result.returncode == 4 and not result.stdout, result.stdout + result.stderr
    assert 'memory_database_unavailable' in result.stderr
    assert hashes(memory.store.path.parent) == before
    assert external.read_bytes() == b'keep this unrelated recovery evidence'
    journal.write_bytes(original)
    assert memory.history(receipt.memory_id) == history
    assert len(memory.context(SUBJECT).facts) == 1


def test_damaged_pending_publication_does_not_overwrite_original_and_can_retry(memory, tmp_path):
    origin = memory.context(SUBJECT)
    receipt = memory.remember('symbol_exists', SUBJECT, origin, 'original')
    history = memory.history(receipt.memory_id)
    killed = subprocess.run([sys.executable, '-B', '-c', CRASH, str(memory.store.path)],
                            text=True, capture_output=True, timeout=10)
    assert killed.returncode == -9, killed.stderr
    commands = []
    result = cli(memory, commands, 'history', receipt.memory_id,
                 script=[INTERRUPT, 'after-journal-remove-sync', str(tmp_path / 'events.json')])
    assert result.returncode == -9, result.stderr
    pending = memory.store.path.with_name('memory.pending')
    next_image = pending / 'next.sqlite3'
    raw = next_image.read_bytes()
    next_image.write_bytes(b'corrupt next image')
    before = hashes(memory.store.path.parent)
    result = cli(memory, commands, 'history', receipt.memory_id)
    assert result.returncode == 4 and not result.stdout, result.stdout + result.stderr
    assert 'memory_publication_error' in result.stderr
    assert hashes(memory.store.path.parent) == before
    next_image.write_bytes(raw)
    assert memory.history(receipt.memory_id) == history
    assert len(memory.context(SUBJECT).facts) == 1
    assert not pending.exists()


def test_retirement_sync_failure_keeps_intact_intent_and_next_query_works(memory, tmp_path):
    origin = memory.context(SUBJECT)
    receipt = memory.remember('symbol_exists', SUBJECT, origin, 'original')
    history = memory.history(receipt.memory_id)
    killed = subprocess.run([sys.executable, '-B', '-c', CRASH, str(memory.store.path)],
                            text=True, capture_output=True, timeout=10)
    assert killed.returncode == -9, killed.stderr
    journal = memory.store.path.with_name('memory.sqlite3-journal').read_bytes()
    commands = []
    result = cli(memory, commands, 'history', receipt.memory_id,
                 script=[INTERRUPT, 'fail-retire-sync', str(tmp_path / 'events.json')])
    assert result.returncode == 4 and not result.stdout, result.stdout + result.stderr
    assert 'fsync failure' in result.stderr
    retired = list(memory.store.path.parent.glob('.memory-retired-*'))
    assert len(retired) == 1
    assert (retired[0] / 'original-journal').read_bytes() == journal
    assert (retired[0] / 'next.sqlite3').read_bytes() == memory.store.path.read_bytes()
    assert (retired[0] / 'commit.json').is_file()
    assert memory.history(receipt.memory_id) == history
    assert len(memory.context(SUBJECT).facts) == 1


def test_intent_sync_failure_keeps_original_pair_and_retry_completes(memory, tmp_path):
    origin = memory.context(SUBJECT)
    receipt = memory.remember('symbol_exists', SUBJECT, origin, 'original')
    history = memory.history(receipt.memory_id)
    killed = subprocess.run([sys.executable, '-B', '-c', CRASH, str(memory.store.path)],
                            text=True, capture_output=True, timeout=10)
    assert killed.returncode == -9, killed.stderr
    journal = memory.store.path.with_name('memory.sqlite3-journal')
    main, recovery = memory.store.path.read_bytes(), journal.read_bytes()
    commands = []
    result = cli(memory, commands, 'history', receipt.memory_id,
                 script=[INTERRUPT, 'fail-intent-sync', str(tmp_path / 'events.json')])
    assert result.returncode == 4 and not result.stdout, result.stdout + result.stderr
    assert 'fsync failure' in result.stderr
    assert memory.store.path.read_bytes() == main and journal.read_bytes() == recovery
    assert memory.store.path.with_name('memory.pending').is_dir()
    assert memory.history(receipt.memory_id) == history
    assert len(memory.context(SUBJECT).facts) == 1
    assert not journal.exists() and not memory.store.path.with_name('memory.pending').exists()
