from __future__ import annotations

import concurrent.futures
import json
import sqlite3
import subprocess

import pytest

from cami.errors import IncompleteError
from cami.product.service import ProductMemory

SUBJECT = 'src/api.py:target'


@pytest.fixture
def legacy_memory(tmp_path, monkeypatch, legacy_database):
    root = tmp_path / 'repo'
    (root / 'src').mkdir(parents=True)
    (root / 'src/api.py').write_text('def target(x: int) -> int:\n    return x\n')
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    memory = ProductMemory(root)
    context = memory.context(SUBJECT)
    receipt = memory.remember('signature_equals', SUBJECT, context, 'signature')
    memory.remember('note', SUBJECT, memory.context(SUBJECT), 'note',
                    note_key='review', text='Preserve this manual observation')
    (root / 'src/api.py').write_text('def target(x: int) -> int:\n    return x + 1\n')
    head = memory.refresh()
    history = memory.history(receipt.memory_id)
    legacy_database(memory.store.path)
    return memory, head, history, receipt


def test_legacy_observation_and_upgrade_preserve_history_and_idempotency(legacy_memory):
    memory, head, history, receipt = legacy_memory
    original = memory.store.path.read_bytes()
    with memory.store.observation_connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
        assert memory.store.head(db) == head
        assert memory.store.history(db, receipt.memory_id) == history
    assert memory.store.path.read_bytes() == original
    with memory.store.connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 3
        assert memory.store.head(db) == head
        assert memory.store.history(db, receipt.memory_id) == history
    upgraded = memory.store.path.read_bytes()
    assert upgraded != original
    assert memory.history(receipt.memory_id) == history
    assert memory.store.path.read_bytes() == upgraded
    context = memory.context(SUBJECT)
    first = memory.remember('note', SUBJECT, context, 'after-upgrade', note_key='new', text='New note')
    assert memory.remember('note', SUBJECT, context, 'after-upgrade', note_key='new', text='New note') == first
    assert memory.history(receipt.memory_id).revisions == history.revisions


def test_failure_after_private_compaction_does_not_publish_partial_upgrade(legacy_memory):
    memory, head, history, receipt = legacy_memory
    original = memory.store.path.read_bytes()
    with pytest.raises(RuntimeError, match='caller interrupted'):
        with memory.store.connection() as db:
            assert db.execute('PRAGMA user_version').fetchone()[0] == 3
            raise RuntimeError('caller interrupted')
    assert memory.store.path.read_bytes() == original
    assert memory.history(receipt.memory_id) == history
    with memory.store.observation_connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 3
        assert memory.store.head(db) == head


@pytest.mark.parametrize('corruption', ['different-copy', 'missing-index'])
def test_divergent_legacy_copy_is_never_discarded(legacy_memory, corruption):
    memory, _, _, _ = legacy_memory
    with sqlite3.connect(memory.store.path) as db:
        rowid, raw = db.execute('SELECT rowid,value FROM record_state LIMIT 1').fetchone()
        if corruption == 'different-copy':
            value = json.loads(raw)
            value['invalidation_scopes'].append('authored-divergent-evidence')
            db.execute('UPDATE record_state SET value=? WHERE rowid=?', (json.dumps(value), rowid))
        else:
            db.execute('DELETE FROM record_state WHERE rowid=?', (rowid,))
    original = memory.store.path.read_bytes()
    with pytest.raises(IncompleteError, match='memory_database_corrupt'):
        with memory.store.connection():
            pytest.fail('divergent legacy evidence accepted')
    assert memory.store.path.read_bytes() == original


def test_concurrent_legacy_readers_publish_one_equivalent_upgrade(legacy_memory):
    memory, _, history, receipt = legacy_memory
    with concurrent.futures.ThreadPoolExecutor(3) as pool:
        histories = list(pool.map(lambda _: memory.history(receipt.memory_id), range(3)))
    assert histories == [history] * 3
    with memory.store.observation_connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 3


@pytest.mark.parametrize('point', ['before-main', 'after-main'])
def test_killed_schema_upgrade_recovers_identical_history(legacy_memory, tmp_path, point):
    from test_database_publication import INTERRUPT, cli

    memory, head, history, receipt = legacy_memory
    interrupted = cli(memory, [], 'history', receipt.memory_id,
                      script=[INTERRUPT, point, str(tmp_path / 'upgrade-events.json')])
    assert interrupted.returncode == -9, interrupted.stderr
    recovered = cli(memory, [], 'history', receipt.memory_id)
    assert recovered.returncode == 0, recovered.stderr
    assert json.loads(recovered.stdout) == history.model_dump(mode='json')
    assert not memory.store.path.with_name('memory.pending').exists()
    with memory.store.observation_connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 3
        assert memory.store.head(db) == head


def test_schema2_observation_upgrade_and_new_writes(legacy_memory, legacy_database):
    memory, head, history, receipt = legacy_memory
    legacy_database(memory.store.path, version=2)
    original = memory.store.path.read_bytes()
    with memory.store.observation_connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2
        assert memory.store.head(db) == head
        assert memory.store.history(db, receipt.memory_id) == history
    assert memory.store.path.read_bytes() == original
    with memory.store.connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 3
        assert memory.store.head(db) == head
        assert memory.store.history(db, receipt.memory_id) == history
    context = memory.context(SUBJECT)
    new = memory.remember('note', SUBJECT, context, 'compressed-write', note_key='compressed', text='New observation')
    assert memory.history(new.memory_id).revisions[-1].payload.text == 'New observation'
    assert memory.history(receipt.memory_id).revisions == history.revisions


@pytest.mark.parametrize('point', ['before-main', 'after-main'])
def test_killed_schema2_upgrade_recovers(legacy_memory, legacy_database, tmp_path, point):
    from test_database_publication import INTERRUPT, cli

    memory, head, history, receipt = legacy_memory
    legacy_database(memory.store.path, version=2)
    interrupted = cli(memory, [], 'history', receipt.memory_id,
                      script=[INTERRUPT, point, str(tmp_path / 'upgrade-schema2-events.json')])
    assert interrupted.returncode == -9, interrupted.stderr
    recovered = cli(memory, [], 'history', receipt.memory_id)
    assert recovered.returncode == 0, recovered.stderr
    assert json.loads(recovered.stdout) == history.model_dump(mode='json')
    with memory.store.observation_connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 3
        assert memory.store.head(db) == head


def test_failed_schema2_private_upgrade_preserves_original(legacy_memory, legacy_database):
    memory, _, _, _ = legacy_memory
    legacy_database(memory.store.path, version=2)
    original = memory.store.path.read_bytes()
    with pytest.raises(RuntimeError, match='interrupted'):
        with memory.store.connection() as db:
            assert db.execute('PRAGMA user_version').fetchone()[0] == 3
            raise RuntimeError('interrupted')
    assert memory.store.path.read_bytes() == original


@pytest.mark.parametrize('corruption', ['plain-json', 'body', 'aggregate-budget'])
def test_encoded_database_corruption_is_not_published(legacy_memory, corruption):
    memory, _, history, receipt = legacy_memory
    assert memory.history(receipt.memory_id) == history
    with sqlite3.connect(memory.store.path) as db:
        generation_id = db.execute('SELECT generation_id FROM product_head').fetchone()[0]
        if corruption == 'aggregate-budget':
            # Two individually legal declared lengths must fail before head decompression.
            ids = [row[0] for row in db.execute('SELECT id FROM memory_generation LIMIT 2')]
            assert len(ids) == 2
            for ident in ids:
                db.execute('UPDATE memory_generation SET value=? WHERE id=?',
                           ('cami-json-zlib/1:134217729:eA==', ident))
        else:
            raw = '{}' if corruption == 'plain-json' else 'cami-json-zlib/1:1:eA=='
            db.execute('UPDATE memory_generation SET value=? WHERE id=?', (raw, generation_id))
    original = memory.store.path.read_bytes()
    message = 'decoded generations exceed' if corruption == 'aggregate-budget' else 'memory_generation_encoding_error'
    with pytest.raises(IncompleteError, match=message):
        with memory.store.connection():
            pytest.fail('corrupt compressed state accepted')
    assert memory.store.path.read_bytes() == original
