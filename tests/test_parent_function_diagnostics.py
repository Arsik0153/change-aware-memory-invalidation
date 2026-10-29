from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
checker = importlib.import_module('scripts.check_parent_functions')
IMAGE = 'test@sha256:' + '1' * 64
PROBE = "from _pytest.compat import safe_getattr\n\ndef test_frozen_case():\n    assert safe_getattr(object(), 'missing', 'fallback') == 'fallback'\n"


def payload():
    path = '/repo/src/_pytest/compat.py'
    return {'schema_version': 1, 'execution_mode': 'direct_frozen_function', 'python_version': '3.9.25',
        'python_flags': {'isolated': 1, 'optimize': 0, 'dont_write_bytecode': 1},
        'dependencies': {'attrs': '23.2.0', 'py': '1.11.0'}, 'probe_sha256': checker.PROBE_SHA256,
        'preloaded_framework_modules': [], 'status': 'returned',
        'target': {'path': path, 'sha256': 'a' * 64, 'function_filename': path},
        'module_origins': {'_pytest': {'path': '/repo/src/_pytest/__init__.py', 'sha256': 'b' * 64},
                           '_pytest.compat': {'path': path, 'sha256': 'a' * 64}}}


def classify(data, returncode=0, dependencies=None):
    process = subprocess.CompletedProcess([], returncode,
        b'CAMI_FUNCTION_RESULT=' + json.dumps(data).encode() + b'\n', b'')
    return checker.classify(process, 'a' * 64, {'/repo/src/_pytest/compat.py': 'a' * 64,
                                              '/repo/src/_pytest/__init__.py': 'b' * 64}, dependencies)


@pytest.mark.parametrize('status', ['returned', 'assertion_failed'])
def test_direct_observation_requires_bound_parent_origins(status):
    data = payload()
    data['status'] = status
    result = classify(data)
    assert result['status'] == status
    assert 'verdict' not in result


@pytest.mark.parametrize('fault', ['version', 'optimized', 'dependencies', 'probe', 'preloaded', 'target',
    'outside_origin', 'mixed_origin', 'missing_package', 'origins_list', 'origin_list', 'payload_list', 'exit'])
def test_rejects_wrong_runtime_or_source_attestation(fault):
    data = payload()
    if fault == 'version':
        data['python_version'] = '3.12.12'
    elif fault == 'optimized':
        data['python_flags']['optimize'] = 1
    elif fault == 'dependencies':
        data['dependencies']['attrs'] = 'different'
    elif fault == 'probe':
        data['probe_sha256'] = '0' * 64
    elif fault == 'preloaded':
        data['preloaded_framework_modules'] = ['_pytest.compat']
    elif fault == 'target':
        data['target']['sha256'] = '0' * 64
    elif fault == 'outside_origin':
        data['module_origins']['_pytest']['path'] = '/site-packages/_pytest/__init__.py'
    elif fault == 'mixed_origin':
        data['module_origins']['_pytest.compat'] = data['module_origins']['_pytest']
    elif fault == 'missing_package':
        del data['module_origins']['_pytest']
    elif fault == 'origins_list':
        data['module_origins'] = []
    elif fault == 'origin_list':
        data['module_origins']['_pytest'] = []
    elif fault == 'payload_list':
        data = []
    assert classify(data, returncode=1 if fault == 'exit' else 0)['status'] == 'technical_error'


def test_import_failure_is_not_a_contradicted_claim():
    data = payload()
    data.update(status='technical_error', target=None, module_origins={}, error_type='ImportError')
    assert classify(data)['reason'] == 'target_import_or_execution_error'


def prepare_fixture(repo):
    parent = repo.commit({'src/_pytest/compat.py': 'def safe_getattr(obj, name, default):\n    return getattr(obj, name, default)\n'})
    repo.commit({'src/_pytest/compat.py': 'raise RuntimeError("child must not run")\n'})
    root = repo.root.parent
    base = root / 'inputs/candidates/group'
    base.mkdir(parents=True)
    (base / 'test_frozen_probe.py').write_text(PROBE)
    assert checker.file_hash(base / 'test_frozen_probe.py') == checker.PROBE_SHA256
    claim = {'schema_version': 1, 'claim_id': 'fixture-behavior', 'kind': 'behavior_test',
        'repo_id': 'pytest', 'origin_commit': parent, 'text': 'Synthetic test fixture.',
        'scope': 'Frozen finite case only.', 'subject': {'path': 'src/_pytest/compat.py',
        'qualname': 'safe_getattr', 'node_kind': 'function'}, 'predicate': {'type': 'behavior_test',
        'probe_path': 'test_frozen_probe.py', 'probe_sha256': checker.PROBE_SHA256,
        'node_id': 'test_frozen_probe.py::test_frozen_case', 'environment_id': 'pending'}}
    checker.write_json(base / 'claims.jsonl', claim)
    parent_row = {'schema_version': 1, 'group_id': 'group', 'repo_id': 'pytest',
        'repo_path': str(repo.root), 'source_roots': ['src'], 'parent_commit': parent, 'seed': 1}
    checker.write_json(base / 'draft.json', {'parent_input': parent_row, 'claims_sha256': checker.file_hash(base / 'claims.jsonl')})
    parents = root / 'inputs/parents.jsonl'
    checker.write_json(parents, parent_row)
    plan = copy.deepcopy(checker.read_json(checker.PROTOCOL))
    plan.update(parent_inputs_sha256=checker.file_hash(parents), groups=['group'])
    protocol = root / 'protocol.json'
    checker.write_json(protocol, plan)
    return parents, base, protocol, parent


@pytest.mark.parametrize('partial', [False, True])
def test_parent_only_orchestration_preserves_partial_progress(repo, monkeypatch, partial):
    parents, base, protocol, parent = prepare_fixture(repo)
    monkeypatch.setattr(checker, 'check_docker', lambda profile: None)

    def observe(snapshot, profile, probe, output, *, dependencies):
        assert dependencies == checker.BASE_DEPENDENCIES
        assert snapshot.revision == parent
        assert b'child must not run' not in snapshot.by_path()['src/_pytest/compat.py'].content
        assert profile.python_version == '3.9.25'
        if partial:
            checker.write_json(output / 'attempts.json', [{'status': 'returned'}])
            raise OSError('injected failure after first attempt')
        return [{'status': 'returned'}] * 3

    monkeypatch.setattr(checker, 'observe', observe)
    out = repo.root.parent / 'result'
    result = checker.check(parents, base.parent, IMAGE, out, protocol)
    assert result['status'] == 'complete'
    assert result['summary']['container_attempts'] == (1 if partial else 3)
    assert result['groups'][0]['status'] == ('technical_error' if partial else 'attempts_recorded')
    assert result['source_inputs_unchanged'] and result['source_snapshots_match']
    assert not result['child_data_used'] and not result['real_experiment_eligible']
    assert not result['produces_independent_receipts']
    assert not list(out.rglob('parent_receipts.jsonl'))


@pytest.mark.parametrize('fault', ['probe', 'claim_hash', 'parent_binding', 'output', 'repo_output'])
def test_invalid_inputs_rejected_before_output(repo, fault):
    parents, base, protocol, _ = prepare_fixture(repo)
    out = repo.root.parent / 'result'
    if fault == 'probe':
        (base / 'test_frozen_probe.py').write_text('assert True\n')
    elif fault == 'claim_hash':
        (base / 'claims.jsonl').write_text((base / 'claims.jsonl').read_text() + '\n')
    elif fault == 'parent_binding':
        draft = checker.read_json(base / 'draft.json')
        draft['parent_input']['parent_commit'] = '0' * 40
        checker.write_json(base / 'draft.json', draft)
    elif fault == 'output':
        out = base / 'new-output'
    else:
        out = repo.root / 'new-output'
    with pytest.raises(checker.InputError):
        checker.check(parents, base.parent, IMAGE, out, protocol)
    assert not out.exists()


def test_cleanup_timeout_retains_each_attempt_and_partial_stdout(repo, monkeypatch):
    parents, base, protocol, parent = prepare_fixture(repo)
    snapshot = checker.read_snapshot(checker.RepoLocation(repo_id='pytest', path=str(repo.root), source_roots=('src',)), parent)
    output = repo.root.parent / 'attempts'
    output.mkdir()

    def time_out(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 1, output=b'partial stdout', stderr=b'partial stderr')

    monkeypatch.setattr(checker.subprocess, 'run', time_out)
    attempts = checker.observe(snapshot, checker.EnvironmentProfile(image=IMAGE, python_version='3.9.25'),
                               base / 'test_frozen_probe.py', output)
    assert len(attempts) == 3
    assert all(a['status'] == 'technical_error' and a['reason'] == 'timeout' and a['cleanup_error'] for a in attempts)
    assert (output / 'repeat-0.stdout.log').read_bytes() == b'partial stdout'
    assert (output / 'repeat-0.stderr.log').read_bytes() == b'partial stderr'
    assert len(checker.read_json(output / 'attempts.json')) == 3


def test_all_technical_errors_are_not_reported_as_successful_observations(repo, monkeypatch):
    parents, base, protocol, _ = prepare_fixture(repo)
    monkeypatch.setattr(checker, 'check_docker', lambda profile: None)
    monkeypatch.setattr(checker, 'observe', lambda *args, **kwargs: [{'status': 'technical_error'}] * 3)
    result = checker.check(parents, base.parent, IMAGE, repo.root.parent / 'out', protocol)
    assert result['status'] == 'complete'
    assert result['summary']['container_attempts'] == 3
    assert result['summary']['groups_with_all_calls_returned'] == 0
    assert result['summary']['groups_with_no_function_observation'] == 1
    assert result['summary']['groups_with_incomplete_attempt_schedule'] == 0


def test_dependency_profile_is_bound_to_actual_runtime_metadata():
    data = payload()
    upgraded = {**checker.BASE_DEPENDENCIES, 'packaging': '26.0'}
    assert classify(data, dependencies=upgraded)['status'] == 'technical_error'
    data['dependencies'] = upgraded
    assert classify(data, dependencies=upgraded)['status'] == 'returned'
    assert classify(data)['status'] == 'technical_error'
