import shutil
import subprocess
import sys

import pytest

from integrations.opencode import task_memory, task_session
from integrations.opencode.task_context import prepare

USAGE = dict(input=12, output=3, reasoning=2, cache_read=7, cache_write=0)


def project(tmp_path):
    work = tmp_path / 'work'
    (work / 'src').mkdir(parents=True)
    (work / 'src/math.py').write_text('def add(a, b):\n    return a - b\n')
    subprocess.run(['git', 'init', '-q', str(work)], check=True)
    grade = [sys.executable, '-B', '-c', "exec(open('src/math.py').read()); assert add(4, 2)==6"]
    return work, grade


def agent(usage=USAGE, code=0):
    script = "from pathlib import Path; import json; Path('src/math.py').write_text('def add(a, b):\\n    return a + b\\n');"
    script += f"print(json.dumps({{'type':'request_started','id':'a'}})); print(json.dumps({{'type':'request_finished','id':'a','usage':{usage!r}}})); raise SystemExit({code})"
    return [sys.executable, '-c', script]


@pytest.mark.parametrize('coverage,usage,code', [(True, USAGE, 0), (False, USAGE, 0), (True, {}, 0), (True, USAGE, 1)])
def test_integrated_learning_and_replay(tmp_path, coverage, usage, code):
    work, grade = project(tmp_path)
    state = task_memory.namespace(tmp_path / 'memory', work)
    first = task_session.run(tmp_path / 'one', work, 'Fix add sum', 'env', agent(usage, code), grade,
                             cache=state / 'replay', request_coverage=coverage, v2_state=state)
    eligible = coverage and usage == USAGE and code == 0
    assert first['method_recorded'] == eligible
    assert first['cache_recorded'] == eligible
    (work / 'src/math.py').write_bytes((tmp_path / 'one/before/src/math.py').read_bytes())
    second = task_session.run(tmp_path / 'two', work, 'Fix add sum', 'env', agent(), grade,
                              cache=state / 'replay', request_coverage=coverage, v2_state=state)
    assert second['replayed'] == eligible
    assert second['quality'] == 'pass'
    if eligible:
        assert second['telemetry']['requests'] == 0
        assert not (tmp_path / 'two/stderr.log').exists()
        assert 'cause_status' in task_memory.hints(state, 'Fix add sum')[0]
        # The user's workspace is not patched on replay.
        assert 'a - b' in (work / 'src/math.py').read_text()


def test_context_fresh_bounded_and_namespaced(tmp_path, monkeypatch):
    work, _ = project(tmp_path)
    legacy = tmp_path / 'legacy'
    monkeypatch.setenv('XDG_STATE_HOME', str(legacy))
    state = task_memory.namespace(tmp_path / 'memory', work)
    out = tmp_path / 'packet'
    first = prepare(work, 'Fix add sum', state, out)
    second = prepare(work, 'Fix add sum', state, out)
    assert '"cache_reused": true' in second
    assert 'a - b' in first and 'sha256=' in first
    assert len(second.encode()) <= 14000
    assert not legacy.exists()
    (work / 'src/math.py').write_text('def add(a,b):\n    return a * b\n')
    third = prepare(work, 'Fix add sum', state, out)
    assert 'a * b' in third and 'a - b' not in third
    assert task_memory.namespace(tmp_path / 'memory', tmp_path / 'other') != state


def test_unadmitted_replay_runs_agent(tmp_path):
    work, grade = project(tmp_path)
    state = task_memory.namespace(tmp_path / 'memory', work)
    state.mkdir(parents=True)
    after = tmp_path / 'bad'
    shutil.copytree(work, after)
    (after / 'src/math.py').write_text('def add(a,b):\n    return 0\n')
    task_session.replay.record(work, after, 'sum', 'env', state / 'replay')
    result = task_session.run(tmp_path / 'run', work, 'sum', 'env', agent(), grade,
                              cache=state / 'replay', v2_state=state)
    assert result['quality'] == 'pass' and not result['replayed']
    assert not (tmp_path / 'run/rejected-replay').exists()


def test_context_selects_suffix_and_omits_unrelated(tmp_path):
    work, _ = project(tmp_path)
    (work / 'src/math.py').write_text('def process_record(record):\n' + '    # filler\n' * 350 + '    return record.critical_suffix\n')
    packet = prepare(work, 'critical_suffix process_record', tmp_path / 'state', tmp_path / 'packet')
    assert 'return record.critical_suffix' in packet
    assert len(packet.encode()) <= 14000
    irrelevant = prepare(work, 'zzzzunmatchedzzzz', tmp_path / 'state', tmp_path / 'none')
    assert 'return record.critical_suffix' not in irrelevant


@pytest.mark.parametrize('boundary', ['task_prompt', 'replay_materialized'])
def test_v2_parent_death_recovery_without_second_agent(tmp_path, boundary):
    work, grade = project(tmp_path)
    state = task_memory.namespace(tmp_path / 'memory', work)
    if boundary == 'replay_materialized':
        task_session.run(tmp_path / 'seed', work, 'sum', 'env', agent(), grade,
                         cache=state / 'replay', v2_state=state, request_coverage=True)
        (work / 'src/math.py').write_bytes((tmp_path / 'seed/before/src/math.py').read_bytes())
    directory = tmp_path / 'crashed'
    script = f'''import os,signal
from integrations.opencode import task_session as m
original = m.Journal.append
def append(self,kind,data):
    original(self,kind,data)
    if kind == {boundary!r}: os.kill(os.getpid(),signal.SIGKILL)
m.Journal.append = append
m.run({str(directory)!r},{str(work)!r},'sum','env',{agent()!r},{grade!r},cache={str(state / 'replay')!r},v2_state={str(state)!r})
'''
    result = subprocess.run([sys.executable, '-c', script])
    assert result.returncode == -9
    journal = task_session.Journal(directory / 'events.sqlite')
    try:
        recovered = task_session.finish(directory, journal)
        assert recovered['quality'] == ('pass' if boundary == 'replay_materialized' else 'fail')
        assert not recovered['cache_recorded']
        assert task_session.finish(directory, journal) == recovered
    finally:
        journal.close()


def test_existing_legacy_database_unchanged_by_v2(tmp_path, monkeypatch):
    from cami.product.service import ProductMemory
    work, _ = project(tmp_path)
    legacy = tmp_path / 'legacy-state'
    monkeypatch.setenv('XDG_STATE_HOME', str(legacy))
    initial = ProductMemory(work).context('add')
    original = {str(p.relative_to(legacy)): p.read_bytes() for p in legacy.rglob('*') if p.is_file()}
    prepare(work, 'Fix add sum', tmp_path / 'new-state', tmp_path / 'packet')
    after = {str(p.relative_to(legacy)): p.read_bytes() for p in legacy.rglob('*') if p.is_file()}
    assert after == original
    restored = ProductMemory(work).context('add')
    assert restored.code == initial.code
    assert restored.index == initial.index


def test_fresh_replay_failure_falls_back(tmp_path):
    work, _ = project(tmp_path)
    counter = tmp_path / 'grade-count'
    grade = [sys.executable, '-B', '-c', f"from pathlib import Path; p=Path({str(counter)!r}); n=int(p.read_text())+1 if p.exists() else 1; p.write_text(str(n)); exec(open('src/math.py').read()); assert add(4,2)==6; assert n != 2"]
    state = task_memory.namespace(tmp_path / 'memory', work)
    task_session.run(tmp_path / 'seed', work, 'sum', 'env', agent(), grade,
                     v2_state=state, request_coverage=True)
    (work / 'src/math.py').write_bytes((tmp_path / 'seed/before/src/math.py').read_bytes())
    result = task_session.run(tmp_path / 'fallback', work, 'sum', 'env', agent(), grade, v2_state=state)
    assert result['quality'] == 'pass' and not result['replayed']
    assert result['telemetry']['requests'] == 1
    assert (tmp_path / 'fallback/rejected-replay').exists()


def test_recovery_after_method_publication(tmp_path):
    work, grade = project(tmp_path)
    state = task_memory.namespace(tmp_path / 'memory', work)
    directory = tmp_path / 'crashed'
    script = f'''import os,signal
from integrations.opencode import task_session as m, task_memory
original = task_memory.remember
def remember(*args):
    original(*args)
    os.kill(os.getpid(),signal.SIGKILL)
task_memory.remember = remember
m.run({str(directory)!r},{str(work)!r},'sum','env',{agent()!r},{grade!r},v2_state={str(state)!r},request_coverage=True)
'''
    result = subprocess.run([sys.executable, '-c', script])
    assert result.returncode == -9
    journal = task_session.Journal(directory / 'events.sqlite')
    try:
        recovered = task_session.finish(directory, journal)
        assert recovered['quality'] == 'pass' and recovered['cache_recorded']
        assert task_memory.reusable(state, recovered['input_key'], 'env')
        assert task_session.finish(directory, journal) == recovered
    finally:
        journal.close()


def test_state_cannot_be_shared_between_worktrees(tmp_path):
    work, grade = project(tmp_path)
    state = tmp_path / 'bound-state'
    task_session.run(tmp_path / 'one', work, 'sum', 'env', agent(), grade, v2_state=state)
    other = tmp_path / 'other'
    shutil.copytree(work, other)
    with pytest.raises(ValueError, match='different result'):
        task_session.run(tmp_path / 'two', other, 'sum', 'env', agent(), grade, v2_state=state)


def test_similar_task_only_receives_hint(tmp_path):
    work, grade = project(tmp_path)
    state = task_memory.namespace(tmp_path / 'memory', work)
    task_session.run(tmp_path / 'seed', work, 'Fix add sum', 'env', agent(), grade,
                     v2_state=state, request_coverage=True)
    (work / 'src/math.py').write_text('def add(a,b):\n    return a * b\n')
    result = task_session.run(tmp_path / 'similar', work, 'Fix add sum again', 'env', agent(), grade, v2_state=state)
    assert not result['replayed'] and result['telemetry']['requests'] == 1
    journal = task_session.Journal(tmp_path / 'similar/events.sqlite')
    try:
        prompt = next(d['text'] for k,d in journal.events() if k == 'task_prompt')
        assert 'hint only' in prompt and 'verified-method/1' in prompt
        assert 'a * b' in prompt
    finally:
        journal.close()
