from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest


def verifier() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'verify_cami.py'
    spec = importlib.util.spec_from_file_location('verify_cami', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / 'repo'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    (root / 'src').mkdir()
    (root / 'src' / 'sample.py').write_text('value = 1\n')
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test',
                    '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture'], check=True)
    return root


def test_source_snapshot_tracks_edits_additions_deletions(repo: Path) -> None:
    module = verifier()
    original = module.source_snapshot(repo)
    assert module.source_snapshot(repo) == original
    path = repo / 'src' / 'sample.py'
    path.write_text('value = 2\n')
    assert module.source_snapshot(repo)['sha256'] != original['sha256']
    path.write_text('value = 1\n')
    assert module.source_snapshot(repo) == original
    extra = repo / 'src' / 'new.py'
    extra.write_text('value = 3\n')
    assert module.source_snapshot(repo)['sha256'] != original['sha256']
    extra.unlink()
    path.unlink()
    deleted = module.source_snapshot(repo)
    assert deleted['files']['src/sample.py'] is None
    assert deleted['sha256'] != original['sha256']


@pytest.mark.parametrize('mutate,exit_code', [(False, 0), (True, 0), (False, 1)])
def test_manifest_rejects_changed_sources_and_failed_checks(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutate: bool, exit_code: int,
) -> None:
    import hashlib

    module = verifier()
    output = tmp_path / 'evidence'
    monkeypatch.setattr(module, 'ROOT', repo)
    monkeypatch.setattr('sys.argv', ['verify_cami.py', '--out', str(output)])
    real_run = subprocess.run

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[0] == 'git':
            return real_run(command, **kwargs)  # type: ignore[call-overload,no-any-return]
        if mutate:
            (repo / 'src' / 'sample.py').write_text('changed = True\n')
        return subprocess.CompletedProcess(command, exit_code, stdout='check output\n')

    monkeypatch.setattr(module.subprocess, 'run', run)
    expected = 1 if mutate or exit_code else 0
    assert module.main() == expected
    report = json.loads((output / 'checks.json').read_text())
    assert report['status'] == ('failed' if expected else 'passed')
    assert report['source_snapshots_match'] is (not mutate)
    assert len(report['checks']) == 3
    for check in report['checks']:
        assert check['log_sha256'] == hashlib.sha256(
            (output / check['log']).read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        module.main()


def test_root_configuration_is_part_of_snapshot(repo: Path) -> None:
    module = verifier()
    original = module.source_snapshot(repo)
    for name in ('conftest.py', 'pytest.ini', 'ruff.toml', 'mypy.ini'):
        path = repo / name
        path.write_text('# configuration\n')
        assert module.source_snapshot(repo)['sha256'] != original['sha256']
        path.unlink()
    assert module.source_snapshot(repo) == original
