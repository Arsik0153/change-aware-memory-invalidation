from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from scripts import check_product_watch as driver


def setup(repo, monkeypatch):
    original = 'export function f(count: number) { return count; }\n'
    head = repo.commit({'src/module.ts': original})
    root = repo.root.parent
    profile = {'repo_head': head, 'subject': 'src/module.ts:f',
               'source_sha256': hashlib.sha256(original.encode()).hexdigest(),
               'body': {'old': 'return count;', 'new': 'return 0;'},
               'signature': {'old': 'count: number', 'new': 'count: string'},
               'parse_suffix': '\nexport function broken(:\n'}
    mutation = root / 'mutation.json'
    mutation.write_text(json.dumps(profile))
    plan = {**{key: profile[key] for key in ('repo_head', 'subject', 'source_sha256')},
            'schema_version': 1, 'phases': driver.PHASES, 'source_roots': ['src'],
            'check_persisted_before_query': True, 'mutation_profile_path': str(mutation),
            'mutation_profile_sha256': driver.sha(mutation), 'purpose': 'test',
            'foreground_command_timeout_seconds': 1, 'wait_seconds_per_phase': 1}
    protocol = root / 'protocol.json'
    protocol.write_text(json.dumps(plan))
    return protocol, root / 'evidence', root / 'cache', original


@pytest.mark.parametrize('corruption', ['head', 'source_hash', 'profile_hash', 'scope', 'phases'])
def test_protocol_or_fixture_mismatch_rejected_before_output(repo, monkeypatch, corruption):
    protocol, out, cache, _ = setup(repo, monkeypatch)
    data = json.loads(protocol.read_text())
    key, value = {'head': ('repo_head', '0' * 40), 'source_hash': ('source_sha256', '0' * 64),
                  'profile_hash': ('mutation_profile_sha256', '0' * 64), 'scope': ('source_roots', ['.']),
                  'phases': ('phases', ['initial'])}[corruption]
    data[key] = value
    protocol.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        driver.prepare(repo.root, protocol, out, cache)
    assert not out.exists()


@pytest.mark.parametrize('location', ['output', 'cache'])
def test_evidence_and_cache_cannot_mutate_fixture(repo, monkeypatch, location):
    protocol, out, cache, _ = setup(repo, monkeypatch)
    if location == 'output':
        out = repo.root / 'out'
    else:
        cache = repo.root / 'cache'
    with pytest.raises(ValueError, match='outside'):
        driver.prepare(repo.root, protocol, out, cache)
    assert not out.exists()


def test_timeout_preserves_output_and_restores_source(repo, monkeypatch):
    protocol, out, cache, original = setup(repo, monkeypatch)
    monkeypatch.setattr(driver, 'source_snapshot', lambda root: {'source_status': '', 'head': 'test'})
    real_run = subprocess.run

    def interrupted(argv, **kwargs):
        if '-m' in argv and 'cami.cli' in argv:
            # Model a partially completed foreground operation before timeout.
            (repo.root / 'src/module.ts').write_text('changed during injected failure')
            raise subprocess.TimeoutExpired(argv, 1, output=b'partial output', stderr=b'partial error')
        return real_run(argv, **kwargs)

    monkeypatch.setattr(driver.subprocess, 'run', interrupted)
    with pytest.raises(subprocess.TimeoutExpired):
        driver.run(repo.root, protocol, out, cache)
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['status'] == 'failed'
    assert manifest['failure']['type'] == 'TimeoutExpired'
    assert manifest['commands'][0]['timed_out'] is True
    assert manifest['commands'][0]['exit_code'] is None
    assert (out / manifest['commands'][0]['stdout']).read_bytes() == b'partial output'
    assert (out / manifest['commands'][0]['stderr']).read_bytes() == b'partial error'
    assert (repo.root / 'src/module.ts').read_text() == original
    assert manifest['final_git_status'] == ''
    assert manifest['source_before'] == manifest['source_after']
    for path, expected in manifest['artifact_hashes'].items():
        assert driver.sha(out / path) == expected


def test_existing_watcher_rejected_without_mutation_or_stop(repo, monkeypatch):
    protocol, out, cache, original = setup(repo, monkeypatch)
    monkeypatch.setattr(driver, 'source_snapshot', lambda root: {'source_status': '', 'head': 'test'})
    real_run = subprocess.run
    calls = []

    def existing(argv, **kwargs):
        if '-m' in argv and 'cami.cli' in argv:
            calls.append(argv)
            assert argv[3:5] == ['watch', 'status'], 'An existing watcher must not be stopped or mutated'
            return subprocess.CompletedProcess(argv, 0, json.dumps({
                'lifecycle': 'running', 'ownership': 'lease_and_session_verified',
                'session_id': 'existing'}).encode(), b'')
        return real_run(argv, **kwargs)

    monkeypatch.setattr(driver.subprocess, 'run', existing)
    with pytest.raises(ValueError, match='already has a watcher'):
        driver.run(repo.root, protocol, out, cache)
    assert len(calls) == 1
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['status'] == 'failed' and 'watcher' not in manifest
    assert (repo.root / 'src/module.ts').read_text() == original
    assert manifest['final_git_status'] == ''


def test_lost_start_race_never_stops_another_session(repo, monkeypatch):
    protocol, out, cache, _ = setup(repo, monkeypatch)
    monkeypatch.setattr(driver, 'source_snapshot', lambda root: {'source_status': '', 'head': 'test'})
    monkeypatch.setattr(driver, 'runtime_identity', lambda env: {'compiler': 'fixture', 'node_version': 'fixture'})
    real_run, real_popen = subprocess.run, subprocess.Popen
    calls = []

    def commands(argv, **kwargs):
        if '-m' not in argv or 'cami.cli' not in argv:
            return real_run(argv, **kwargs)
        calls.append(argv)
        assert argv[3:5] != ['watch', 'stop']
        if argv[3:5] == ['watch', 'status']:
            assert len(calls) == 1
            value = {'lifecycle': 'stopped', 'ownership': 'lease_free'}
        elif argv[3:5] == ['memory', 'remember']:
            value = {'memory_id': argv[5]}
        else:
            value = {}
        return subprocess.CompletedProcess(argv, 0, json.dumps(value).encode(), b'')

    class LostRace:
        pid = 99999999
        returncode = 0

        def poll(self):
            return 0

        def terminate(self):
            pytest.fail('Exited child must not receive a signal')

    def launch(argv, **kwargs):
        if '-m' in argv and 'cami.cli' in argv:
            assert argv[3] == 'watch'
            return LostRace()
        return real_popen(argv, **kwargs)

    monkeypatch.setattr(driver.subprocess, 'run', commands)
    monkeypatch.setattr(driver.subprocess, 'Popen', launch)
    with pytest.raises(RuntimeError, match='No verified owned watcher session'):
        driver.run(repo.root, protocol, out, cache)
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['status'] == 'failed'
    assert 'owned watcher exited during startup' in manifest['failure']['message']
    assert manifest['watcher']['exit_code'] == 0
    assert not manifest['phases']
    assert manifest['final_git_status'] == ''


@pytest.mark.parametrize('weakened_phase', [None, 'signature', 'note_review'])
def test_v2_only_separates_explicit_note_publication(repo, monkeypatch, weakened_phase):
    protocol, out, cache, _ = setup(repo, monkeypatch)
    plan = json.loads(protocol.read_text())
    plan.update(schema_version=2, publication_expectations=dict(driver.PUBLICATIONS))
    if weakened_phase:
        plan['publication_expectations'][weakened_phase] = 'skip'
    protocol.write_text(json.dumps(plan))
    if weakened_phase:
        with pytest.raises(ValueError, match='Only explicit note update'):
            driver.prepare(repo.root, protocol, out, cache)
    else:
        driver.prepare(repo.root, protocol, out, cache)
    assert not out.exists()
