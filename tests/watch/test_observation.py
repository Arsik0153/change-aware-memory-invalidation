from __future__ import annotations

import hashlib
import os
import subprocess

import pytest

from cami.errors import IncompleteError
from cami.product.memory.adapters import HybridIndexPort
from cami.product.service import ProductMemory


@pytest.fixture
def memory(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (repo / 'api.py').write_text('def user(x: str) -> str:\n    return x\n')
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    return ProductMemory(repo)


def image(memory):
    return {p.relative_to(memory.index_store.path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in memory.index_store.path.rglob('*') if p.is_file()}


def test_observe_before_first_refresh_does_not_initialize(memory):
    value = memory.observe()
    assert value.relation == 'changed' and value.reason == 'no_head'
    assert not memory.store.path.exists() and not memory.store.initialized.exists()
    assert not (memory.index_store.path / 'current.json').exists()
    assert not memory.store.objects.exists()


def test_observe_uses_canonical_probes_and_never_prepares_or_publishes(memory, monkeypatch):
    context = memory.context('api.py:user')
    memory.remember('symbol_exists', 'api.py:user', context, 'exists')
    memory.remember('note', 'api.py:user', context, 'note', note_key='contract', text='Reviewed.')
    expected = memory.refresh()
    before = image(memory)

    def forbidden(*args, **kwargs):
        raise AssertionError('observation must not analyze or publish')

    monkeypatch.setattr(HybridIndexPort, 'prepare_locked', forbidden)
    monkeypatch.setattr(memory.index_store, 'publish', forbidden)
    monkeypatch.setattr(memory.store, 'publish', forbidden)
    observation = memory.observe()
    assert observation.relation == 'matching'
    assert observation.index == expected.index
    assert observation.memory_generation_id == expected.memory_generation_id
    assert memory.observe().comparison_key == observation.comparison_key
    assert image(memory) == before
    (memory.root / 'api.py').write_text('def user(x: int) -> int:\n    return x\n')
    changed = memory.observe()
    assert changed.relation == 'changed' and changed.comparison_key != observation.comparison_key
    assert image(memory) == before


@pytest.mark.parametrize('damage', ['missing', 'corrupt', 'fifo'])
def test_observe_cannot_turn_damaged_database_into_empty_knowledge(memory, damage):
    context = memory.context('api.py:user')
    memory.remember('symbol_exists', 'api.py:user', context, 'exists')
    original = memory.store.path.read_bytes()
    memory.store.path.unlink()
    if damage == 'corrupt':
        memory.store.path.write_bytes(b'broken')
    elif damage == 'fifo':
        os.mkfifo(memory.store.path)
    with pytest.raises(IncompleteError):
        memory.observe()
    if damage == 'missing':
        assert not memory.store.path.exists()
    elif damage == 'corrupt':
        assert memory.store.path.read_bytes() == b'broken'
    memory.store.path.unlink(missing_ok=True)
    memory.store.path.write_bytes(original)
    assert memory.observe().relation == 'matching'


def test_observe_pending_recovery_never_completes_or_changes_live_image(memory):
    memory.refresh()
    original = image(memory)
    pending = memory.index_store.path / 'memory.pending'
    pending.mkdir()
    (pending / 'commit.json').write_bytes(b'bad')
    with pytest.raises(IncompleteError):
        memory.observe()
    assert (pending / 'commit.json').read_bytes() == b'bad'
    assert {k: v for k, v in image(memory).items() if not k.startswith('memory.pending/')} == original


def test_observe_catalog_and_declared_note_sources_join_shared_capture(memory):
    first = memory.refresh()
    empty = memory.observe()
    context = memory.context('api.py:user')
    memory.remember('note', 'api.py:user', context, 'note', note_key='review', text='Manual')
    observation = memory.observe()
    assert observation.relation == 'matching'
    assert observation.comparison_key != empty.comparison_key
    assert observation.memory_generation_id != first.memory_generation_id
    (memory.root / '.gitignore').write_text('api.py\n')
    assert memory.observe().relation == 'changed'
