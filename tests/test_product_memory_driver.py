from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

SPEC = importlib.util.spec_from_file_location('check_product_memory',
    Path(__file__).resolve().parents[1] / 'scripts/check_product_memory.py')
assert SPEC and SPEC.loader
memory_driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(memory_driver)


@pytest.fixture
def fixture_repo(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'subject.py').write_text('def sample(value):\n    return value\n')
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture',
                    '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
    return repo


def profile_for(repo):
    return dict(schema_version=1, subject='subject.py:sample',
        repo_head=subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD']).decode().strip(),
        source_sha256=hashlib.sha256((repo / 'subject.py').read_bytes()).hexdigest(),
        source_roots=['.'], body={'old': 'return value', 'new': 'return None'},
        signature={'old': 'sample(value)', 'new': 'sample(value, extra=None)'},
        parse_suffix='\ndef invalid(:\n')


@pytest.mark.parametrize('placement', ['output', 'cache'])
def test_rejects_experiment_artifacts_inside_repository(fixture_repo, tmp_path, placement):
    out = fixture_repo / 'evidence' if placement == 'output' else tmp_path / 'evidence'
    kwargs = {'cache_dir': fixture_repo / 'cache'} if placement == 'cache' else {}
    with pytest.raises(ValueError, match='outside'):
        memory_driver.run(fixture_repo, 'subject.py:sample', out, **kwargs)
    assert not out.exists()
    assert not subprocess.check_output(['git', '-C', str(fixture_repo), 'status', '--porcelain'])


@pytest.mark.parametrize('path', ['../outside.py', '/tmp/outside.py', 'link.py'])
def test_rejects_paths_outside_fixture_before_any_mutation(fixture_repo, tmp_path, path):
    outside = tmp_path / 'outside.py'
    outside.write_text('def sample(value):\n    return value\n')
    if path == 'link.py':
        (fixture_repo / path).symlink_to(outside)
        subprocess.run(['git', '-C', str(fixture_repo), 'add', path], check=True)
        subprocess.run(['git', '-C', str(fixture_repo), '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'link'], check=True)
    out = tmp_path / 'evidence'
    with pytest.raises(ValueError, match='paths'):
        memory_driver.run(fixture_repo, path + ':sample', out)
    assert not out.exists()
    assert outside.read_text() == 'def sample(value):\n    return value\n'


@pytest.mark.parametrize('fault', ['hash', 'head', 'anchor', 'root', 'empty_root', 'schema', 'null'])
def test_rejects_invalid_mutation_profile_without_creating_evidence(fixture_repo, tmp_path, fault):
    profile = profile_for(fixture_repo)
    if fault in ('hash', 'head'):
        profile['source_sha256' if fault == 'hash' else 'repo_head'] = '0' * 64
    elif fault == 'anchor':
        profile['body']['old'] = 'nonexistent statement'
    elif fault == 'root':
        profile['source_roots'] = ['../']
    elif fault == 'empty_root':
        profile['source_roots'] = []
    elif fault == 'schema':
        profile['schema_version'] = True
    else:
        profile = None
    spec = tmp_path / 'profile.json'
    spec.write_text(json.dumps(profile))
    out = tmp_path / 'evidence'
    with pytest.raises(ValueError):
        memory_driver.run(fixture_repo, 'subject.py:sample', out, mutation_spec=spec)
    assert not out.exists()
    assert (fixture_repo / 'subject.py').read_text() == 'def sample(value):\n    return value\n'
    assert not subprocess.check_output(['git', '-C', str(fixture_repo), 'status', '--porcelain'])


@pytest.mark.parametrize("executable", [False, True])
def test_python_cli_lifecycle_and_restoration(fixture_repo, tmp_path, executable):
    if executable:
        (fixture_repo / "subject.py").chmod(0o755)
        subprocess.run(["git", "-C", str(fixture_repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(fixture_repo), "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@example.invalid", "commit", "-qm", "executable"],
                       check=True)
    result = memory_driver.run(fixture_repo, 'subject.py:sample', tmp_path / 'evidence')
    assert result['status'] == 'passed'
    assert len(result['commands']) == 18
    assert len(result['phases']) == 6
    assert result['original_source_sha256'] == result['restored_source_sha256']
    assert result['final_git_status'] == ''
    for command in result['commands']:
        for stream, suffix in [('stdout', 'json'), ('stderr', 'txt')]:
            path = tmp_path / 'evidence' / f"{command['label']}.{stream}.{suffix}"
            assert hashlib.sha256(path.read_bytes()).hexdigest() == command[f'{stream}_sha256']
