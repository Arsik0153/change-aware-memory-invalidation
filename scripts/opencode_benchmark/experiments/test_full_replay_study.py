"""Exercise empty-cache learning/hits and fail-closed stopping without models."""
import importlib.util
import json
from pathlib import Path
import tarfile

import pytest

spec = importlib.util.spec_from_file_location('full_replay_study', Path(__file__).with_name('full_replay_study.py'))
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)


@pytest.mark.parametrize('fail', [False, True])
def test_full_schedule_isolated_learning_and_failed_trials_not_retried(tmp_path, monkeypatch, fail):
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
    def model(spec, trial, workspace, memory, directory, prompt):
        calls.append(prompt)
        (workspace / 'src/code.py').write_text(f'value = {1 if prompt == "a" else 2}\n')
        return dict(input=100, cache_write=0, output=10, reasoning=5, cache_read=0), ['default']
    def grade(spec, task, candidate, out, allowance):
        grades.append(task['id'])
        assert (candidate / 'src/code.py').read_text() == f'value = {1 if task["id"] == "a" else 2}\n'
        return {'status': 'fail' if fail else 'pass'}
    monkeypatch.setattr(study, 'origin_memory', lambda *a: {})
    monkeypatch.setattr(study, 'verify_memory', lambda *a: {})
    monkeypatch.setattr(study, 'model_session', model)
    monkeypatch.setattr(study, 'grade', grade)
    out = tmp_path / 'run'
    study.run(freeze, out)
    summary = json.loads((out / 'summary.json').read_text())
    if fail:
        assert len(calls) == len(grades) == 70
        assert summary['direction_supported'] is False
        assert all(not b['complete'] for b in summary['blocks'])
    else:
        assert len(calls) == 70 and len(grades) == 80
        assert len(list((out / 'namespaces').iterdir())) == 20
        for block in summary['blocks']:
            assert block['token_work'] == (230 if block['condition'] == 'cami_replay' else 460)
    assert summary['terminal_attempts'] == 80
    assert len(summary['pairs']) == 15
    with pytest.raises(ValueError, match='no retries'):
        study.run(freeze, out)


def test_rotations_isolation_and_counts():
    rows = study.schedule({'normalized': {'sequence': ['a', 'a', 'b', 'b']}})
    assert len(rows) == len({r['id'] for r in rows}) == 80
    assert sum(r['expected_cache_hit'] for r in rows) == 10
    for repetition in range(1, 6):
        for stage in range(1, 5):
            group = [r for r in rows if r['repetition'] == repetition and r['stage'] == stage]
            assert len(group) == 4 and len({r['condition'] for r in group}) == 4
            assert all(r['arm'] == ('cami' if r['condition'] == 'cami_replay' else r['condition']) for r in group)


def test_success_requires_every_pair_both_metrics_and_all_quality():
    from copy import deepcopy
    rows = [{'trial': trial, 'status': 'passed', 'model_calls': int(not trial['expected_cache_hit']),
             'token_work': 10 if trial['condition'] == 'cami_replay' else 20,
             'wall_seconds': 1 if trial['condition'] == 'cami_replay' else 2,
             'provider_reported_tiers': ['default'] if not trial['expected_cache_hit'] else []}
            for trial in study.schedule({'normalized': {'sequence': ['a', 'a', 'b', 'b']}})]
    assert study.summarize(rows, 20)['direction_supported']
    for field, value in [('token_work', 1000), ('wall_seconds', 1000)]:
        changed = deepcopy(rows)
        next(r for r in changed if r['trial']['condition'] == 'cami_replay')[field] = value
        assert not study.summarize(changed, 20)['direction_supported']
    changed = deepcopy(rows)
    changed[0]['status'] = 'failed'
    assert not study.summarize(changed, 20)['eligible']
    changed = deepcopy(rows)
    changed[0]['provider_reported_tiers'] = ['priority']
    assert not study.summarize(changed, 20)['eligible']
