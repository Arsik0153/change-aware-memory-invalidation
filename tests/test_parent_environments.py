from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from cami.artifacts import digest, file_hash, read_json, write_json, write_jsonl
from cami.errors import InputError
from cami.models import ValidationResult

SPEC = importlib.util.spec_from_file_location(
    'check_parent_environments', Path(__file__).resolve().parents[1] / 'scripts/check_parent_environments.py')
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)
IMAGE = 'test@sha256:' + '1' * 64


def prepare(repo):
    parent = repo.commit({'module.py': 'def f(): return 1\n'})
    repo.commit({'module.py': 'def f(): return 2\n'})
    config = repo.config(parent, [])
    root = repo.root.parent
    base = root / 'candidates/group'
    base.mkdir(parents=True)
    probe = base / 'probe.py'
    probe.write_text('from module import f\ndef test_f(): assert f() == 1\n')
    claim = read_json(config.parent / 'claims.jsonl')
    claim.update(kind='behavior_test', predicate={'type': 'behavior_test', 'probe_path': probe.name,
                 'probe_sha256': file_hash(probe), 'node_id': 'probe.py::test_f',
                 'environment_id': 'pending'})
    write_jsonl(base / 'claims.jsonl', [claim])
    spec = {'schema_version': 1, 'group_id': 'group', 'repo_id': 'fixture',
            'repo_path': str(repo.root), 'source_roots': ['.'], 'parent_commit': parent, 'seed': 42}
    parents = root / 'parents.jsonl'
    write_jsonl(parents, [spec])
    write_json(base / 'draft.json', {'parent_input': spec,
        'claims_sha256': file_hash(base / 'claims.jsonl')})
    return parents, base, parent


@pytest.mark.parametrize('python_version', ['3.12.12', '3.9.25'])
def test_only_parent_snapshot_is_observed_without_receipts(repo, monkeypatch, python_version):
    parents, base, parent = prepare(repo)
    original = file_hash(parents), file_hash(base / 'claims.jsonl'), file_hash(base / 'probe.py')
    monkeypatch.setattr(checker, 'check_docker', lambda profile: None)

    def execute(claim, context):
        assert context.profile.python_version == python_version
        assert context.snapshot.revision == parent
        assert context.snapshot.by_path()['module.py'].content == b'def f(): return 1\n'
        return ValidationResult(claim_id=claim.claim_id, commit=parent, validator='behavior',
            verdict='supported', reason='test_passed', input_hash=digest(claim),
            duration_seconds=0, test_executions=3)

    monkeypatch.setattr(checker, 'execute_probe', execute)
    output = repo.root.parent / 'result'
    checker.check_parents(parents, base.parent, IMAGE, output, python_version=python_version)
    assert read_json(output / 'summary.json')['test_executions'] == 3
    manifest = read_json(output / 'manifest.json')
    assert manifest['status'] == 'complete'
    assert manifest['produces_independent_receipts'] is False
    assert manifest['produces_child_labels'] is False
    assert not list(output.rglob('parent_receipts.jsonl'))
    assert not list(output.rglob('labels.jsonl'))
    for name, expected in manifest['artifact_hashes'].items():
        assert file_hash(output / name) == expected
    assert original == (file_hash(parents), file_hash(base / 'claims.jsonl'), file_hash(base / 'probe.py'))


@pytest.mark.parametrize('corruption', ['child_fields', 'probe', 'claim_hash'])
def test_invalid_parent_inputs_rejected_before_execution(repo, monkeypatch, corruption):
    parents, base, _ = prepare(repo)
    if corruption == 'child_fields':
        spec = read_json(parents)
        spec['child_commits'] = ['leaked']
        write_jsonl(parents, [spec])
    elif corruption == 'probe':
        (base / 'probe.py').write_text('changed probe')
    else:
        (base / 'claims.jsonl').write_text('[]')

    def forbidden(profile):
        pytest.fail('Docker must not be invoked for invalid input')

    monkeypatch.setattr(checker, 'check_docker', forbidden)
    output = repo.root.parent / 'rejected'
    with pytest.raises((InputError, ValidationError)):
        checker.check_parents(parents, base.parent, IMAGE, output)
    assert not output.exists()


def test_explicit_capture_limit_preserves_full_large_blob(repo):
    from cami.models import RepoLocation
    from cami.repository import MAX_FILE_BYTES, materialize, read_snapshot

    content = 'x' * (MAX_FILE_BYTES + 1)
    revision = repo.commit({'module.py': 'def f(): return 1\n', 'asset.bin': content})
    location = RepoLocation(repo_id='fixture', path=str(repo.root))
    bounded = read_snapshot(location, revision)
    assert bounded.by_path()['asset.bin'].limitation == 'file_too_large'
    expanded = read_snapshot(location, revision, max_file_bytes=len(content))
    assert expanded.by_path()['asset.bin'].content == content.encode()
    assert expanded.by_path()['asset.bin'].limitation is None
    target = repo.root.parent / 'materialized'
    materialize(expanded, target)
    assert (target / 'asset.bin').read_bytes() == content.encode()
    assert read_snapshot(location, revision).by_path()['asset.bin'].limitation == 'file_too_large'
    with pytest.raises(InputError, match='positive'):
        read_snapshot(location, revision, max_file_bytes=0)
