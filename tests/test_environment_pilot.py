from __future__ import annotations

import pytest

from cami.artifacts import file_hash, read_json, write_json
from cami.cli import main
from cami.environment_pilot import pilot_environments
from cami.errors import InputError, ResourceError
from cami.models import ValidationResult
import cami.environment_pilot as environment

IMAGE = 'cami-probes@sha256:' + 'a' * 64


def source_dataset(repo, core_path='src/click/core.py'):
    parent = repo.commit({'module.py': 'def f():\n    raise RuntimeError("must not execute on host")\n',
                         core_path: 'class Command:\n    def main(self): pass\n'})
    config_path = repo.config(parent, ['deliberately-unresolvable-child'])
    config = read_json(config_path)
    config['repo']['repo_id'] = 'click'
    config['dataset_kind'] = 'real'
    config['split'] = 'heldout'
    write_json(config_path, config)
    dataset = config_path.parent / 'dataset.json'
    write_json(dataset, {'schema_version': 1, 'dataset_id': 'synthetic-boundary-fixture',
        'protocol_version': '1.0', 'dataset_kind': 'real',
        'repositories': [{'repo_id': 'click', 'url': 'synthetic://fixture-only',
            'path': str(repo.root), 'source_roots': ['.'], 'environment_restoration': 'fixture'}],
        'runs': [{'run_id': 'fixture-parent', 'config_path': config_path.name,
                  'split': 'heldout', 'cluster_id': 'fixture'}],
        'labels_path': 'must-not-read-labels.jsonl'})
    return dataset, config_path, parent


@pytest.mark.parametrize('verdict,reason', [('supported', 'test_passed'),
    ('contradicted', 'assertion_failed'), ('insufficient_evidence', 'collection_error')])
@pytest.mark.parametrize('core_path', ['src/click/core.py', 'click/core.py'])
def test_environment_pilot_observes_only_parent_and_never_admits(repo, tmp_path, monkeypatch, verdict, reason, core_path):
    dataset, config, parent = source_dataset(repo, core_path)
    output = tmp_path.parent / (tmp_path.name + '-environment')
    original = config.read_bytes()
    calls = []
    monkeypatch.setattr(environment, 'check_docker', lambda profile: None)

    def observe(claim, context):
        calls.append(context.snapshot.revision)
        assert claim.origin_commit == parent and context.phase == 'preflight'
        assert claim.subject.path == core_path
        assert context.profile.image == IMAGE
        assert file_hash(context.base_dir / claim.predicate.probe_path) == claim.predicate.probe_sha256
        assert context.snapshot.revision == parent
        return ValidationResult(claim_id=claim.claim_id, commit=parent, validator='behavior',
            verdict=verdict, reason=reason, input_hash='fixture', test_executions=3, duration_seconds=0.01)

    monkeypatch.setattr(environment, 'execute_probe', observe)
    assert main(['pilot-environments', '--dataset', str(dataset), '--image', IMAGE, '--out', str(output)]) == 0
    report = read_json(output / 'environment_report.json')
    assert calls == [parent] and report['status'] == 'complete' and report['schema_version'] == 2
    assert report['parents'][0]['verdict'] == verdict and report['test_executions'] == 3
    assert report['evaluation_eligible'] is report['produces_parent_receipts'] is report['child_revisions_executed'] is False
    assert config.read_bytes() == original
    assert not list(output.rglob('*receipts*')) and not list(output.rglob('labels.jsonl'))
    assert not list(output.rglob('states.jsonl'))
    for name, expected in report['artifact_hashes'].items():
        assert file_hash(output / name) == expected
    parent_input = read_json(output / 'inputs/fixture-parent/parent_input.json')
    assert set(parent_input) == {'repo', 'parent_commit'}
    assert parent_input['parent_commit'] == parent


@pytest.mark.parametrize('damage', ['duplicate', 'escape', 'wrong_repo', 'wrong_parent'])
def test_environment_pilot_rejects_invalid_parent_inputs_before_output(repo, tmp_path, monkeypatch, damage):
    dataset, config, _ = source_dataset(repo)
    output = tmp_path.parent / (tmp_path.name + '-rejected')
    if damage in ('duplicate', 'escape'):
        value = read_json(dataset)
        if damage == 'duplicate':
            value['runs'].append(value['runs'][0])
        else:
            value['runs'][0]['run_id'] = '../escape'
        write_json(dataset, value)
    else:
        value = read_json(config)
        if damage == 'wrong_repo':
            value['repo']['repo_id'] = 'not-click'
        else:
            value['parent_commit'] = 'unresolvable-parent'
        write_json(config, value)
    monkeypatch.setattr(environment, 'check_docker', lambda profile: pytest.fail('Docker not expected'))
    with pytest.raises((InputError, ResourceError, ValueError)):
        pilot_environments(dataset, IMAGE, output)
    assert not output.exists()


def test_environment_pilot_docker_failure_does_not_claim_completion(repo, tmp_path, monkeypatch):
    dataset, _, _ = source_dataset(repo)
    output = tmp_path.parent / (tmp_path.name + '-missing-docker')
    def unavailable(profile):
        raise ResourceError('fixture missing Docker')
    monkeypatch.setattr(environment, 'check_docker', unavailable)
    with pytest.raises(ResourceError, match='missing Docker'):
        pilot_environments(dataset, IMAGE, output)
    assert not output.exists()


def test_environment_failure_retains_completed_parents_and_terminal_status(repo, tmp_path, monkeypatch):
    dataset, config, parent = source_dataset(repo)
    second_parent = repo.commit({'src/click/core.py': None})
    second = dict(read_json(config), parent_commit=second_parent)
    write_json(config.parent / 'second.json', second)
    value = read_json(dataset)
    value['runs'].append({'run_id': 'second-parent', 'config_path': 'second.json',
                          'split': 'heldout', 'cluster_id': 'fixture-second'})
    write_json(dataset, value)
    output = tmp_path.parent / (tmp_path.name + '-partial')
    monkeypatch.setattr(environment, 'check_docker', lambda profile: None)
    calls = []
    def observe(claim, context):
        calls.append(context.snapshot.revision)
        return ValidationResult(claim_id=claim.claim_id, commit=parent, validator='behavior',
            verdict='supported', reason='test_passed', input_hash='fixture', test_executions=3,
            duration_seconds=0.01)
    monkeypatch.setattr(environment, 'execute_probe', observe)
    with pytest.raises(InputError, match='unambiguous core module'):
        pilot_environments(dataset, IMAGE, output)
    report = read_json(output / 'environment_report.json')
    assert calls == [parent]
    assert report['status'] == 'failed' and report['failure']['run_id'] == 'second-parent'
    assert report['failure']['type'] == 'InputError'
    assert report['completed_parent_test_executions'] == 3
    assert report['test_executions'] is None
    assert len(report['parents']) == 1 and report['parents'][0]['parent_commit'] == parent
    for name, expected in report['artifact_hashes'].items():
        assert file_hash(output / name) == expected
