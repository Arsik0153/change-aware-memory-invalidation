"""Source excerpt lifecycle, storage, CLI and actual legacy-reader contracts."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile

import pytest
from pydantic import ValidationError

from cami.errors import IncompleteError, InputError
from cami.product.memory.adapters import HybridIndexPort
from cami.product.memory.models import (
    AgentContext, CarriedClaim, CheckedClaim, NoteState, RememberInput, SourceExcerptPayload,
)
from cami.product.service import ProductMemory

SOURCE = 'GLOBAL = 1\n\ndef f():\n    return GLOBAL\n\ndef other():\n    return 1\n'
SELECTOR = 'src/api.py:f'


@pytest.fixture
def owner(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    (repo / 'src').mkdir(parents=True)
    subprocess.run(['git', 'init', '-q', str(repo)], check=True, capture_output=True)
    (repo / 'src/api.py').write_text(SOURCE)
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    return ProductMemory(repo, ('src',))


def write(owner, text):
    (owner.root / 'src/api.py').write_text(text)


def selected(generation, memory_id):
    return next(item for item in generation.states if item.record.memory_id == memory_id)


def pin(owner):
    return owner.context(SELECTOR)


def test_server_mint_unrelated_file_change_and_manual_note_compatibility(owner):
    context = pin(owner)
    excerpt = owner.remember('source_excerpt_equals', SELECTOR, context, 'excerpt')
    note = owner.remember('note', SELECTOR, context, 'note', note_key='manual', text='Arbitrary behavior prose.')
    assert isinstance(selected(owner.refresh(), excerpt.memory_id).record.payload, SourceExcerptPayload)
    write(owner, SOURCE.replace('return 1', 'return 2'))
    generation = owner.refresh()
    literal, manual = selected(generation, excerpt.memory_id), selected(generation, note.memory_id)
    assert isinstance(literal.state, CarriedClaim) and literal.state.check.verdict == 'supported'
    assert isinstance(manual.state, NoteState) and manual.state.review_state == 'needs_review'
    write(owner, SOURCE)
    assert selected(owner.refresh(), note.memory_id).state.review_state == 'needs_review'


def test_stale_origin_mints_old_literal_and_recovery_checks_again(owner):
    context = pin(owner)
    write(owner, SOURCE.replace('return GLOBAL', 'return 2'))
    receipt = owner.remember('source_excerpt_equals', SELECTOR, context, 'stale')
    item = selected(owner.refresh(), receipt.memory_id)
    assert item.record.origin == context.index and item.record.payload.expected.text == 'def f():\n    return GLOBAL\n'
    assert item.state.check.reason == 'source_excerpt_mismatch'
    write(owner, SOURCE)
    recovered = selected(owner.refresh(), receipt.memory_id)
    assert isinstance(recovered.state, CheckedClaim) and recovered.state.check.verdict == 'supported'
    assert recovered.state.check.index != item.state.check.index


def test_retry_update_and_provenance_only_registration(owner):
    context = pin(owner)
    receipt = owner.remember('source_excerpt_equals', SELECTOR, context, 'first')
    assert owner.remember('source_excerpt_equals', SELECTOR, context, 'first') == receipt
    write(owner, '# line shift\n' + SOURCE)
    newer = pin(owner)
    same = owner.remember('source_excerpt_equals', SELECTOR, newer, 'same-predicate')
    assert not same.changed and same.revision == 1
    assert selected(owner.refresh(), receipt.memory_id).record.origin == context.index
    with pytest.raises(InputError, match='request_id_conflict'):
        owner.remember('source_excerpt_equals', SELECTOR, newer, 'first')
    write(owner, SOURCE.replace('return GLOBAL', 'return 3'))
    fresh = pin(owner)
    with pytest.raises(InputError, match='semantic_identity_conflict'):
        owner.remember('source_excerpt_equals', SELECTOR, fresh, 'changed')
    updated = owner.update(receipt.memory_id, 1, fresh, 'update')
    assert updated.revision == 2
    assert selected(owner.refresh(), receipt.memory_id).state.check.verdict == 'supported'
    assert len(owner.history(receipt.memory_id).revisions) == 2


@pytest.mark.parametrize('keyword', [{'text': 'caller expected excerpt'}, {'text': ''}, {'note_key': 'not-allowed'}])
def test_no_caller_expected_note_fields(owner, keyword):
    context = pin(owner)
    with pytest.raises(InputError, match='does not accept'):
        owner.remember('source_excerpt_equals', SELECTOR, context, 'bad', **keyword)
    with pytest.raises(ValidationError, match='does not accept'):
        RememberInput(kind='source_excerpt_equals', query=SELECTOR, context=context, request_id='bad-batch', **keyword)


def test_context_tampering_and_freeform_update_rejected(owner):
    context = pin(owner)
    raw = context.model_dump(mode='json')
    raw['code'][0]['python_excerpt']['prefix_sha256'] = 'f' * 64
    forged = AgentContext.model_validate_json(json.dumps(raw))
    with pytest.raises(InputError, match='context_mismatch'):
        owner.remember('source_excerpt_equals', SELECTOR, forged, 'forged')
    receipt = owner.remember('source_excerpt_equals', SELECTOR, context, 'good')
    with pytest.raises(InputError, match='does not accept'):
        owner.update(receipt.memory_id, 1, context, 'bad-update', text='arbitrary replacement')


def test_batch_same_receipt_and_atomic_conflict(owner):
    context = pin(owner)
    old = owner.remember('source_excerpt_equals', SELECTOR, context, 'old')
    result = owner.remember_batch((RememberInput(kind='source_excerpt_equals', query=SELECTOR, context=context, request_id='old'),
        RememberInput(kind='note', query=SELECTOR, context=context, request_id='new', note_key='one', text='manual')))
    assert result[0] == old and result[1].memory_generation_id != old.memory_generation_id
    before = owner.refresh()
    with pytest.raises(InputError, match='semantic_identity_conflict'):
        owner.remember_batch((RememberInput(kind='note', query=SELECTOR, context=context, request_id='would-add', note_key='two', text='manual'),
            RememberInput(kind='note', query=SELECTOR, context=context, request_id='conflict', note_key='one', text='different')))
    assert owner.refresh().memory_generation_id == before.memory_generation_id
    assert all(not (item.record.payload.type == 'note' and item.record.payload.note_key == 'two') for item in owner.refresh().states)


def test_final_source_race_rolls_back_and_preserves_receipt(owner, monkeypatch):
    context = pin(owner)
    before = owner.refresh()
    original = HybridIndexPort.verify
    def mutate(self, *args):
        write(owner, SOURCE.replace('return GLOBAL', 'return 8'))
        original(self, *args)
    monkeypatch.setattr(HybridIndexPort, 'verify', mutate)
    with pytest.raises(IncompleteError, match='inputs changed'):
        owner.remember('source_excerpt_equals', SELECTOR, context, 'race')
    monkeypatch.setattr(HybridIndexPort, 'verify', original)
    write(owner, SOURCE)
    assert owner.refresh().memory_generation_id == before.memory_generation_id
    assert owner.refresh().states == ()
    assert owner.remember('source_excerpt_equals', SELECTOR, context, 'race').changed


def test_origin_cas_corruption_after_file_change_is_not_hidden_by_new_evidence(owner):
    context = pin(owner)
    receipt = owner.remember('source_excerpt_equals', SELECTOR, context, 'old')
    origin = selected(owner.refresh(), receipt.memory_id).record.payload.origin_source
    write(owner, SOURCE.replace('return GLOBAL', 'return 4'))
    owner.refresh()  # Current source is distinct; old origin still must be checked.
    (owner.store.objects / origin.sha256).write_bytes(b'authored corrupt origin')
    with pytest.raises(IncompleteError, match='source_evidence_corrupt'):
        owner.refresh()


@pytest.mark.parametrize('change,reason', [
    ('delete', 'subject_absent'), ('exclude', 'scope_uncovered'), ('ignore', 'scope_uncovered'),
    ('parse', 'parse_error'), ('duplicate', 'ambiguous_binding'), ('conditional', 'ambiguous_binding'),
    ('encoding', 'unsupported_encoding'),
])
def test_scope_binding_and_unavailability(owner, change, reason):
    context = pin(owner)
    receipt = owner.remember('source_excerpt_equals', SELECTOR, context, 'scope')
    if change == 'delete':
        (owner.root / 'src/api.py').unlink()
    elif change == 'exclude':
        owner.excludes = ('src',)
    elif change == 'ignore':
        (owner.root / '.gitignore').write_text('src/\n')
    elif change == 'parse':
        write(owner, 'def f(:\n')
    elif change == 'duplicate':
        write(owner, SOURCE + '\ndef f(): return 1\n')
    elif change == 'conditional':
        write(owner, 'if flag:\n    def f(): return 1\n')
    else:
        write(owner, '# coding: latin-1\n' + SOURCE)
    item = selected(owner.refresh(), receipt.memory_id)
    assert item.state.check.reason == reason
    assert item.state.check.verdict == ('contradicted' if change == 'delete' else 'insufficient_evidence')


def test_cli_new_kind_and_strict_text_boundary(owner, tmp_path):
    context = pin(owner)
    path = tmp_path / 'context.json'
    path.write_text(context.model_dump_json())
    base = [sys.executable, '-m', 'cami.cli', 'memory', 'remember', 'source_excerpt_equals', SELECTOR,
            '--repo', str(owner.root), '--source-root', 'src', '--format', 'json', '--from-context', str(path)]
    import cami
    env = dict(os.environ, PYTHONPATH=str(Path(cami.__file__).resolve().parent.parent))
    good = subprocess.run([*base, '--request-id', 'cli'], env=env, capture_output=True, text=True)
    assert good.returncode == 0, good.stderr
    bad = subprocess.run([*base, '--request-id', 'bad-cli', '--text', 'caller assertion'], env=env, capture_output=True, text=True)
    assert bad.returncode != 0 and 'does not accept text or note_key' in bad.stderr
    with sqlite3.connect(owner.store.path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2


@pytest.fixture(scope="session")
def baseline_runtime(tmp_path_factory):
    root = next(parent for parent in Path(__file__).resolve().parents
                if (parent / 'pyproject.toml').is_file() and (parent / 'src/cami').is_dir())
    archive = root / 'reports/opencode-development-study-v1-20261104/runtime-source.tar'
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == 'ae91cb887e222bcd8f71c4acd897ec1eaeb453ecf1510de293a3c98e97187087'
    directory = tmp_path_factory.mktemp('pre-excerpt-runtime')
    with tarfile.open(archive) as stream:
        for member in stream.getmembers():
            if not member.name.startswith('src/') or member.isdir():
                continue
            relative = Path(member.name)
            assert member.isfile() and not relative.is_absolute() and '..' not in relative.parts
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            content = stream.extractfile(member)
            assert content is not None
            with target.open('xb') as output:
                output.write(content.read())
    assert (directory / 'src/cami/product/memory/models.py').is_file()
    return directory / 'src'


def test_actual_old_reader_rejects_new_projection_without_sql_migration(owner, baseline_runtime, legacy_database):
    pin(owner)
    legacy_database(owner.store.path)
    env = dict(os.environ, PYTHONPATH=str(baseline_runtime))
    code = 'from pathlib import Path;from cami.product.service import ProductMemory;ProductMemory(Path(__import__("sys").argv[1])).observe()'
    result = subprocess.run([sys.executable, '-c', code, str(owner.root)], env=env, capture_output=True, text=True)
    assert result.returncode != 0 and 'memory_database_error' in result.stderr
    with sqlite3.connect(owner.store.path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1


def test_new_reader_accepts_actual_old_note_and_context(owner, baseline_runtime):
    # The fixture has made no CAMI call yet. The preserved binary writes schema1.
    env = dict(os.environ, PYTHONPATH=str(baseline_runtime))
    code = ('from pathlib import Path;import sys;from cami.product.service import ProductMemory;'
            'm=ProductMemory(Path(sys.argv[1]),("src",));c=m.context("src/api.py:f");'
            'm.remember("note","src/api.py:f",c,"legacy-note",note_key="legacy",text="Manual assertion");'
            'print(c.model_dump_json())')
    old = subprocess.run([sys.executable, '-c', code, str(owner.root)], env=env, capture_output=True, text=True)
    assert old.returncode == 0, old.stderr
    context = AgentContext.model_validate_json(old.stdout)
    assert context.schema_version == 1 and context.code[0].python_excerpt is None
    with pytest.raises(InputError, match='refresh_context_required'):
        owner.remember('source_excerpt_equals', SELECTOR, context, 'cannot-mint-legacy')
    same = owner.remember('note', SELECTOR, context, 'same-legacy', note_key='legacy', text='Manual assertion')
    assert not same.changed
    modern = pin(owner)
    assert modern.schema_version == 2 and modern.notes[0].record.payload.type == 'note'
    assert modern.notes[0].record.payload.text == 'Manual assertion'
    assert owner.remember('source_excerpt_equals', SELECTOR, modern, 'modern').changed


def test_batch_prepares_each_origin_once_and_final_phase_is_fresh(owner, monkeypatch):
    import cami.product.service as service
    import cami.product.memory.adapters as adapters
    write(owner, '\n'.join(f'def f{i}():\n    return {i}\n' for i in range(8)))
    selectors = tuple(f'src/api.py:f{i}' for i in range(8))
    contexts = owner.context_many(selectors)
    service_calls, adapter_calls = [], []
    service_prepare, adapter_prepare = service.prepare_python_excerpt_source, adapters.prepare_python_excerpt_source
    def mint_or_verify(raw):
        service_calls.append(len(raw))
        return service_prepare(raw)
    def project(raw, **kwargs):
        adapter_calls.append(len(raw))
        return adapter_prepare(raw, **kwargs)
    monkeypatch.setattr(service, 'prepare_python_excerpt_source', mint_or_verify)
    monkeypatch.setattr(adapters, 'prepare_python_excerpt_source', project)
    receipts = owner.remember_batch(tuple(RememberInput(kind='source_excerpt_equals', query=query,
        context=context, request_id=f'excerpt-{i}') for i, (query, context) in enumerate(zip(selectors, contexts))))
    assert len(receipts) == 8 and len(adapter_calls) == 1
    assert len(service_calls) == 2  # Once for minting; once again for final verification.
    assert len({receipt.memory_generation_id for receipt in receipts}) == 1
