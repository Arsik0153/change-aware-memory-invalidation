"""Exercise empty-cache learning/hits and fail-closed stopping without models."""
import importlib.util
import json
from pathlib import Path
import tarfile

import pytest

spec = importlib.util.spec_from_file_location('replay_study', Path(__file__).with_name('task_replay_study.py'))
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)


@pytest.mark.parametrize('fail', [False, True])
def test_empty_cache_uses_six_models_and_grades_all_eight_or_stops(tmp_path, monkeypatch, fail):
    base = tmp_path / 'source'
    (base / 'src').mkdir(parents=True)
    (base / 'src/code.py').write_text('value = 0\n')
    archive = tmp_path / 'base.tar'
    with tarfile.open(archive, 'w') as stream:
        stream.add(base / 'src', arcname='src')
    tasks = [{'id': name, 'archive': archive.name, 'archive_sha256': study.digest(archive), 'prompt': name}
             for name in ('a', 'b')]
    runtime = {'image': 'authored', 'bundle_path': str(tmp_path), 'normalized': {'tasks': tasks, 'sequence': ['a', 'a', 'b', 'b']}}
    freeze = tmp_path / 'freeze'
    freeze.mkdir()
    study.write(freeze / 'protocol.json', {'rules': study.RULES, 'pins': {'binary': 'authored'}, 'runtime': runtime, 'schedule': study.schedule(runtime)})
    monkeypatch.setattr(study, 'pins', lambda: {'binary': 'authored'})
    monkeypatch.setattr(study, 'runtime', lambda: runtime)
    monkeypatch.setattr(study, 'regression_allowance', lambda *a: ({}, 'authored'))
    calls, grades = [], []
    def model(spec, workspace, directory, prompt, manifest):
        calls.append(prompt)
        (workspace / 'src/code.py').write_text(f'value = {1 if prompt == "a" else 2}\n')
        return dict(input=100, cache_write=0, output=10, reasoning=5, cache_read=0), ['default']
    def grade(spec, task, candidate, out, allowance):
        grades.append(task['id'])
        assert (candidate / 'src/code.py').read_text() == f'value = {1 if task["id"] == "a" else 2}\n'
        return {'status': 'fail' if fail else 'pass'}
    monkeypatch.setattr(study, 'model_session', model)
    monkeypatch.setattr(study, 'grade', grade)
    out = tmp_path / 'run'
    study.run(freeze, out)
    summary = json.loads((out / 'summary.json').read_text())
    if fail:
        assert len(calls) == len(grades) == 1
        assert summary['direction_supported'] is False
        assert all(not b['complete'] for b in summary['blocks'].values())
    else:
        assert len(calls) == 6 and len(grades) == 8
        assert sum(r['cache_hit'] for r in summary['records']) == 2
        assert summary['blocks']['plain']['token_work'] == 460
        assert summary['blocks']['exact_replay']['token_work'] == 230
    with pytest.raises(ValueError, match='no retries'):
        study.run(freeze, out)
