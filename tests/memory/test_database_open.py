from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys

import pytest

from cami.product.service import ProductMemory

SUBJECT = 'src/api.py:target'
SOURCE = b'def target(x):\n    return x\n'


@pytest.fixture
def memory(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    (root / 'src').mkdir(parents=True)
    (root / 'src/api.py').write_bytes(SOURCE)
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    return ProductMemory(root)


@pytest.mark.parametrize('replacement_kind', ['blank', 'unknown-schema', 'other-scope',
                                              'saved-empty-current'])
def test_cli_rejects_connection_to_replacement_with_restored_path(memory, tmp_path,
                                                                 replacement_kind):
    origin = memory.context(SUBJECT)
    saved_empty = memory.store.path.read_bytes()
    receipt = memory.remember('symbol_exists', SUBJECT, origin, 'original-claim')
    before = memory.context(SUBJECT)
    history = memory.history(receipt.memory_id)
    replacement = tmp_path / 'replacement.sqlite3'
    if replacement_kind == 'saved-empty-current':
        replacement.write_bytes(saved_empty)
    elif replacement_kind == 'other-scope':
        other = tmp_path / 'other'
        other.mkdir()
        (other / 'api.py').write_bytes(SOURCE)
        subprocess.run(['git', 'init', '-q', str(other)], check=True)
        other_memory = ProductMemory(other)
        other_memory.context('api.py:target')
        replacement.write_bytes(other_memory.store.path.read_bytes())
    elif replacement_kind == 'unknown-schema':
        with sqlite3.connect(replacement) as db:
            db.execute('CREATE TABLE precious(value TEXT)')
            db.execute("INSERT INTO precious VALUES('keep')")
    else:
        replacement.touch()
    original_bytes = memory.store.path.read_bytes()
    replacement_bytes = replacement.read_bytes()
    marker = memory.store.initialized.read_bytes()
    sources = {p.name: p.read_bytes() for p in memory.store.objects.iterdir()}
    trace = tmp_path / 'trace.json'
    script = '''
import json, os, sqlite3, sys
from pathlib import Path
from urllib.parse import unquote, urlsplit
from cami.cli import main
path, replacement, trace = map(Path, sys.argv[1:4])
held = path.with_name('held.sqlite3')
connect = sqlite3.connect
statements = []
opens = []
def interleaved(database, *args, **kwargs):
    opened = Path(unquote(urlsplit(str(database)).path))
    if opened.name == 'memory.sqlite3':
        held = opened.with_name('held.sqlite3')
        substitute = opened.with_name('substitute.sqlite3')
        substitute.write_bytes(replacement.read_bytes())
        os.replace(opened, held)
        os.replace(substitute, opened)
        try:
            db = connect(database, *args, **kwargs)
            db.set_trace_callback(statements.append)
            opens.append(str(database))
        finally:
            os.replace(opened, substitute)
            os.replace(held, opened)
        return db
    return connect(database, *args, **kwargs)
sqlite3.connect = interleaved
try:
    code = main(sys.argv[4:])
finally:
    trace.write_text(json.dumps({'opens': opens, 'statements': statements}))
raise SystemExit(code)
'''
    result = subprocess.run([sys.executable, '-B', '-c', script, str(memory.store.path),
                             str(replacement), str(trace), 'memory', 'context', SUBJECT,
                             '--repo', str(memory.root), '--format', 'json'],
                            text=True, capture_output=True, timeout=10)
    evidence = json.loads(trace.read_text())
    assert len(evidence['opens']) == 1
    assert memory.store.path.read_bytes() == original_bytes
    assert replacement.read_bytes() == replacement_bytes
    assert memory.store.initialized.read_bytes() == marker
    assert {p.name: p.read_bytes() for p in memory.store.objects.iterdir()} == sources
    assert memory.history(receipt.memory_id) == history
    after = memory.context(SUBJECT)
    assert len(after.facts) == 1
    assert after.memory_generation_id == before.memory_generation_id
    assert result.returncode == 4, result.stdout + result.stderr
    assert result.stdout == ''
    assert 'memory_' in result.stderr
    mutating = ('CREATE ', 'ALTER ', 'DROP ', 'INSERT ', 'UPDATE ', 'DELETE ',
                'REPLACE ', 'PRAGMA JOURNAL_MODE=', 'PRAGMA SYNCHRONOUS=')
    assert not [sql for sql in evidence['statements'] if sql.upper().startswith(mutating)]


def test_first_use_publication_never_overwrites_an_appearing_database(memory, monkeypatch):
    from cami.errors import IncompleteError

    link = os.link
    unknown = b'another owner database'
    def appeared(source, destination):
        assert destination == memory.store.path
        destination.write_bytes(unknown)
        return link(source, destination)
    monkeypatch.setattr(os, 'link', appeared)
    with pytest.raises(IncompleteError, match='appeared during initialization'):
        memory.context(SUBJECT)
    assert memory.store.path.read_bytes() == unknown
    assert not memory.store.initialized.exists()


def test_disappearance_during_sqlite_open_cannot_create_a_database(memory, monkeypatch):
    from cami.errors import IncompleteError

    origin = memory.context(SUBJECT)
    receipt = memory.remember('symbol_exists', SUBJECT, origin, 'persist')
    history = memory.history(receipt.memory_id)
    original = memory.store.path.read_bytes()
    connect = sqlite3.connect
    def vanished(database, *args, **kwargs):
        memory.store.path.unlink()
        return connect(database, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, 'connect', vanished)
        with pytest.raises(IncompleteError, match='memory_database_unavailable'):
            memory.context(SUBJECT)
    assert not memory.store.path.exists()
    memory.store.path.write_bytes(original)
    assert memory.history(receipt.memory_id) == history
    assert len(memory.context(SUBJECT).facts) == 1


def test_legacy_adoption_rejects_another_scope_before_publishing_proof(memory, tmp_path):
    from cami.errors import IncompleteError

    other_root = tmp_path / 'other'
    other_root.mkdir()
    (other_root / 'api.py').write_bytes(SOURCE)
    subprocess.run(['git', 'init', '-q', str(other_root)], check=True)
    other = ProductMemory(other_root)
    other.context('api.py:target')
    raw = other.store.path.read_bytes()
    memory.index_store.path.mkdir(parents=True)
    memory.store.path.write_bytes(raw)
    with pytest.raises(IncompleteError, match='scope_mismatch'):
        memory.context(SUBJECT)
    assert memory.store.path.read_bytes() == raw
    assert not memory.store.initialized.exists()


def test_sqlite_uri_quotes_state_path(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state # ? % ü'))
    root = tmp_path / 'repo'
    (root / 'src').mkdir(parents=True)
    (root / 'src/api.py').write_bytes(SOURCE)
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    memory = ProductMemory(root)
    origin = memory.context(SUBJECT)
    receipt = memory.remember('symbol_exists', SUBJECT, origin, 'quoted')
    assert memory.history(receipt.memory_id).revisions[0].memory_id == receipt.memory_id
    assert len(memory.context(SUBJECT).facts) == 1


def test_hot_journal_recovery_preserves_history_and_receipt(memory):
    origin = memory.context(SUBJECT)
    receipt = memory.remember('symbol_exists', SUBJECT, origin, 'durable')
    history = memory.history(receipt.memory_id)
    script = '''
import os, signal, sqlite3, sys
connection = sqlite3.connect(sys.argv[1], isolation_level=None)
connection.execute('PRAGMA cache_size=1')
connection.execute('BEGIN IMMEDIATE')
connection.execute('UPDATE index_view SET value=?', ('uncommitted' * 100000,))
os.kill(os.getpid(), signal.SIGKILL)
'''
    killed = subprocess.run([sys.executable, '-B', '-c', script, str(memory.store.path)],
                            text=True, capture_output=True, timeout=10)
    assert killed.returncode == -9, killed.stderr
    assert memory.store.path.with_name('memory.sqlite3-journal').exists()
    assert memory.history(receipt.memory_id) == history
    assert memory.remember('symbol_exists', SUBJECT, origin, 'durable') == receipt
    assert len(memory.context(SUBJECT).facts) == 1


def test_rejected_sqlite_open_preserves_original_hot_journal_and_next_cli_recovery(memory,
                                                                                tmp_path):
    origin = memory.context(SUBJECT)
    replacement = tmp_path / 'saved-empty.sqlite3'
    replacement.write_bytes(memory.store.path.read_bytes())
    receipt = memory.remember('symbol_exists', SUBJECT, origin, 'journal-claim')
    before = memory.context(SUBJECT)
    history = memory.history(receipt.memory_id)
    crash = '''
import os, signal, sqlite3, sys
c = sqlite3.connect(sys.argv[1], isolation_level=None)
c.execute('PRAGMA cache_size=1')
c.execute('BEGIN IMMEDIATE')
c.execute('UPDATE index_view SET value=?', ('uncommitted' * 100000,))
os.kill(os.getpid(), signal.SIGKILL)
'''
    killed = subprocess.run([sys.executable, '-B', '-c', crash, str(memory.store.path)],
                            text=True, capture_output=True, timeout=10)
    assert killed.returncode == -9, killed.stderr
    journal = memory.store.path.with_name('memory.sqlite3-journal')
    original_db, original_journal = memory.store.path.read_bytes(), journal.read_bytes()
    marker = memory.store.initialized.read_bytes()
    sources = {p.name: p.read_bytes() for p in memory.store.objects.iterdir()}
    trace = tmp_path / 'hot-trace.json'
    script = '''
import json, os, sqlite3, sys
from pathlib import Path
from urllib.parse import unquote, urlsplit
from cami.cli import main
replacement, trace = map(Path, sys.argv[1:3])
connect = sqlite3.connect
opens, statements = [], []
def interleaved(database, *args, **kwargs):
    path = Path(unquote(urlsplit(str(database)).path))
    if path.name != 'memory.sqlite3':
        return connect(database, *args, **kwargs)
    held = path.with_name('held.sqlite3')
    substitute = path.with_name('substitute.sqlite3')
    substitute.write_bytes(replacement.read_bytes())
    os.replace(path, held)
    os.replace(substitute, path)
    try:
        db = connect(database, *args, **kwargs)
        db.set_trace_callback(statements.append)
        opens.append(str(database))
    finally:
        os.replace(path, substitute)
        os.replace(held, path)
    return db
sqlite3.connect = interleaved
try:
    code = main(sys.argv[3:])
finally:
    trace.write_text(json.dumps({'opens': opens, 'statements': statements}))
raise SystemExit(code)
'''
    command = [sys.executable, '-B', '-c', script, str(replacement), str(trace),
               'memory', 'context', SUBJECT, '--repo', str(memory.root), '--format', 'json']
    result = subprocess.run(command, text=True, capture_output=True, timeout=10)
    assert len(json.loads(trace.read_text())['opens']) == 1
    assert result.returncode == 4 and not result.stdout, result.stdout + result.stderr
    assert memory.store.path.read_bytes() == original_db
    assert journal.exists(), 'rejected open consumed the original recovery journal'
    assert journal.read_bytes() == original_journal
    assert memory.store.initialized.read_bytes() == marker
    assert {p.name: p.read_bytes() for p in memory.store.objects.iterdir()} == sources
    normal = [sys.executable, '-B', '-m', 'cami.cli', 'memory']
    suffix = ['--repo', str(memory.root), '--format', 'json']
    recovered = subprocess.run([*normal, 'history', receipt.memory_id, *suffix],
                               text=True, capture_output=True, timeout=10)
    assert recovered.returncode == 0, recovered.stderr
    assert json.loads(recovered.stdout) == history.model_dump(mode='json')
    current = subprocess.run([*normal, 'context', SUBJECT, *suffix],
                             text=True, capture_output=True, timeout=10)
    assert current.returncode == 0, current.stderr
    value = json.loads(current.stdout)
    assert value['facts'] == before.model_dump(mode='json')['facts']
    assert value['memory_generation_id'] == before.memory_generation_id
