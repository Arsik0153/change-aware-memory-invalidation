"""Run the frozen real-source watcher development protocol in a disposable clone.

The persisted-state oracle is the stdlib-only reader in tests/watch/cli_driver.py.
No target application code is executed. Use python -m scripts.check_product_watch.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import time

from scripts.verify_cami import source_snapshot

ROOT = Path(__file__).resolve().parents[1]
PHASES = ['initial', 'unchanged', 'untracked_create', 'untracked_rename', 'untracked_delete',
          'body', 'signature', 'parse', 'delete', 'revert', 'note_review', 'stopped']
PUBLICATIONS = {phase: ('foreground_explicit_update' if phase == 'note_review' else
                       'owned_process_exit' if phase == 'stopped' else 'watcher_verified')
                for phase in PHASES}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def runtime_identity(env):
    return json.loads(subprocess.check_output([
        sys.executable, '-c', 'import json; from cami.typescript_runtime import runtime_identity; '
        'print(json.dumps(runtime_identity()))'], cwd=ROOT, env=env, timeout=15))


def prepare(repo, protocol, out, cache):
    repo, protocol, out, cache = (p.resolve() for p in (repo, protocol, out, cache))
    if out.exists() or out.is_relative_to(repo) or cache.is_relative_to(repo):
        raise ValueError('New output and cache must be outside the fixture repository')
    plan = json.loads(protocol.read_text())
    if (type(plan['schema_version']) is not int or plan['schema_version'] not in (1, 2)
            or plan['phases'] != PHASES
            or plan['source_roots'] != ['src'] or not plan['check_persisted_before_query']):
        raise ValueError('Unsupported watcher protocol')
    if plan['schema_version'] == 2 and plan.get('publication_expectations') != PUBLICATIONS:
        raise ValueError('Only explicit note update may bypass watcher publication attestation')
    if plan['schema_version'] == 1 and 'publication_expectations' in plan:
        raise ValueError('Publication attribution requires protocol version 2')
    mutation_path = ROOT / plan['mutation_profile_path']
    if sha(mutation_path) != plan['mutation_profile_sha256']:
        raise ValueError('Mutation profile hash differs from protocol')
    profile = json.loads(mutation_path.read_text())
    for key in ('repo_head', 'subject', 'source_sha256'):
        if profile[key] != plan[key]:
            raise ValueError(f'Mutation profile differs at {key}')
    top = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', '--show-toplevel']).decode().strip()
    if Path(top).resolve() != repo:
        raise ValueError('Fixture must be repository root')
    if subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain']):
        raise ValueError('Fixture must be clean')
    head = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD']).decode().strip()
    if head != plan['repo_head']:
        raise ValueError('Fixture HEAD differs from protocol')
    relative = plan['subject'].split(':')[0]
    source = repo / relative
    if (Path(relative).is_absolute() or '..' in Path(relative).parts
            or source.resolve() != source or not source.is_relative_to(repo / 'src')):
        raise ValueError('Source must be a regular path inside fixture src')
    subprocess.check_output(['git', '-C', str(repo), 'ls-files', '--error-unmatch', '--', relative])
    if sha(source) != plan['source_sha256']:
        raise ValueError('Source bytes differ from protocol')
    original = source.read_bytes()
    text = original.decode()
    changes = {}
    for phase in ('body', 'signature'):
        old, new = profile[phase]['old'], profile[phase]['new']
        if not old or old == new or text.count(old) != 1:
            raise ValueError('Mutation anchor must occur exactly once and change bytes')
        changes[phase] = text.replace(old, new, 1).encode()
    changes.update(parse=(text + profile['parse_suffix']).encode(), delete=None, revert=original)
    for name in ('cami_watch_development.ts', 'cami_watch_renamed.ts'):
        path = repo / 'src' / name
        if path.exists() or path.is_symlink():
            raise ValueError('Untracked development path already exists')
    return plan, profile, source, original, changes


def run(repo: Path, protocol: Path, out: Path, cache: Path):
    repo, protocol, out, cache = (p.resolve() for p in (repo, protocol, out, cache))
    plan, profile, source, original, changes = prepare(repo, protocol, out, cache)
    before = source_snapshot(ROOT)
    if before['source_status']:
        raise ValueError('Commit source changes before the real run')
    reader_path = ROOT / 'tests/watch/cli_driver.py'
    spec = importlib.util.spec_from_file_location('watch_persisted_reader', reader_path)
    assert spec and spec.loader
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    mode = stat.S_IMODE(source.stat().st_mode)
    state = out / 'state'
    env = {**os.environ, 'XDG_STATE_HOME': str(state), 'XDG_CACHE_HOME': str(cache),
           'PYTHONDONTWRITEBYTECODE': '1'}
    env.pop('PYTHONPATH', None)
    out.mkdir(parents=True)
    write(out / 'protocol.json', plan)
    write(out / 'mutation_profile.json', profile)
    commands, phases = [], []
    process = None
    owned_session = None
    streams = []
    manifest = dict(status='running', purpose=plan['purpose'], repo=str(repo),
                    subject=plan['subject'], repo_head=plan['repo_head'], source_roots=['src'],
                    protocol_sha256=sha(protocol), driver_sha256=sha(Path(__file__)),
                    persisted_reader_sha256=sha(reader_path), source_before=before,
                    commands=commands, phases=phases, original_source_mode=mode)
    input_hashes = {str(protocol): sha(protocol),
                    str(ROOT / plan['mutation_profile_path']): sha(ROOT / plan['mutation_profile_path'])}
    manifest['input_hashes'] = input_hashes
    relative = source.relative_to(repo).as_posix()
    untracked = repo / 'src/cami_watch_development.ts'
    renamed = repo / 'src/cami_watch_renamed.ts'

    def save():
        write(out / 'manifest.json', manifest)

    def cli(label, *args, scope=True):
        argv = [sys.executable, '-m', 'cami.cli', *args, '--repo', str(repo), '--format', 'json']
        if scope:
            argv.extend(['--source-root', 'src'])
        timeout = None
        try:
            result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True,
                                    timeout=plan['foreground_command_timeout_seconds'])
            raw_stdout, raw_stderr, code = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired as exc:
            timeout = exc
            raw_stdout, raw_stderr, code = exc.stdout or b'', exc.stderr or b'', None
        prefix = f'{len(commands):03d}-{label}'
        stdout, stderr = out / (prefix + '.stdout.json'), out / (prefix + '.stderr.log')
        stdout.write_bytes(raw_stdout)
        stderr.write_bytes(raw_stderr)
        commands.append(dict(label=label, argv=argv, exit_code=code, timed_out=timeout is not None,
                             stdout=stdout.name, stderr=stderr.name,
                             stdout_sha256=sha(stdout), stderr_sha256=sha(stderr)))
        save()
        if timeout is not None:
            raise timeout
        assert code == 0, (label, code, raw_stderr)
        return json.loads(raw_stdout), stdout

    def wait(label, predicate):
        deadline = time.monotonic() + plan['wait_seconds_per_phase']
        last = None
        while time.monotonic() < deadline:
            assert process is not None and process.poll() is None, ('watcher exited', label)
            try:
                proof = reader.persisted(state, repo)
                if predicate(proof):
                    write(out / (label + '.persisted.json'), proof)
                    return proof
            except (OSError, AssertionError, TypeError, sqlite3.Error) as exc:
                last = repr(exc)
            time.sleep(.2)
        raise AssertionError((label, 'persisted-state deadline', last))

    def record(proof, kind):
        return next(s for s in proof['head']['states'] if s['record']['payload']['type'] == kind)

    def completed(label, proof):
        actor = plan.get('publication_expectations', {}).get(label, 'watcher_verified')
        deadline = time.monotonic() + plan['wait_seconds_per_phase']
        while time.monotonic() < deadline:
            status, _ = cli(label + '-status', 'watch', 'status', scope=False)
            assert status['session_id'] == owned_session
            assert status['ownership'] == 'lease_and_session_verified'
            success = status['latest_successful']
            if (actor == 'foreground_explicit_update' or
                    (success and success['memory_generation_id'] == proof['head']['memory_generation_id'])):
                break
            time.sleep(.2)
        else:
            raise AssertionError((label, 'watcher did not attest persisted generation'))
        context, path = cli(label + '-context', 'memory', 'context', plan['subject'])
        assert context['memory_generation_id'] == proof['head']['memory_generation_id']
        assert context['index'] == proof['head']['index']
        expected_facts = {kind for kind in ('symbol_exists', 'signature_equals')
                          if record(proof, kind)['state']['check']['verdict'] == 'supported'}
        assert {f['record']['payload']['type'] for f in context['facts']} == expected_facts
        note_available = record(proof, 'note')['state']['review_state'] == 'not_requested'
        assert len(context['notes']) == int(note_available)
        assert len(context['withheld']) == 3 - len(expected_facts) - int(note_available)
        for entry in [*context['facts'], *context['notes'], *context['withheld']]:
            persisted_record = record(proof, entry['record']['payload']['type'])
            assert entry['record'] == persisted_record['record']
            assert entry['state'] == persisted_record['state']
        after = reader.persisted(state, repo)
        assert after['head'] == proof['head'] and after['counts'] == proof['counts']
        phases.append(dict(label=label, sequence=proof['head']['sequence'],
                           generation=proof['head']['memory_generation_id'],
                           persisted_before_query=True, publication_actor=actor,
                           watcher_latest_successful_generation=(success['memory_generation_id'] if success else None),
                           counts=proof['counts']))
        save()
        print(f'{label}: {actor}, persisted before query, generation {proof["head"]["sequence"]}', flush=True)
        return context, path

    save()
    try:
        previous_status, _ = cli('before-start', 'watch', 'status', scope=False)
        if previous_status['lifecycle'] != 'stopped' or previous_status['ownership'] != 'lease_free':
            raise ValueError('Fixture already has a watcher or unverified ownership')
        manifest['runtime_before'] = runtime_identity(env)
        assert manifest['runtime_before']['compiler'] and manifest['runtime_before']['node_version']
        _, origin = cli('origin', 'memory', 'context', plan['subject'])
        ids = {}
        for kind in ('symbol_exists', 'signature_equals', 'note'):
            extra = ['--note-key', 'watch-development', '--text',
                     'Development-only manual note on the pinned source.'] if kind == 'note' else []
            receipt, _ = cli('remember-' + kind, 'memory', 'remember', kind, plan['subject'],
                             '--from-context', str(origin), '--request-id', 'watch-' + kind, *extra)
            ids[kind] = receipt['memory_id']
        stdout, stderr = (out / 'watch.stdout.log').open('wb'), (out / 'watch.stderr.log').open('wb')
        streams.extend([stdout, stderr])
        argv = [sys.executable, '-m', 'cami.cli', 'watch', '--repo', str(repo),
                '--source-root', 'src', '--format', 'json']
        process = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=stdout, stderr=stderr)
        manifest['watcher'] = dict(argv=argv, owned_pid=process.pid)
        save()
        deadline = time.monotonic() + plan['wait_seconds_per_phase']
        while time.monotonic() < deadline:
            assert process.poll() is None, ('owned watcher exited during startup', process.returncode)
            events = (out / 'watch.stdout.log').read_text().splitlines()
            for line in events:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get('event') == 'started':
                    owned_session = event['session_id']
                    break
            if owned_session is not None:
                break
            time.sleep(.2)
        assert owned_session is not None, 'Owned watcher emitted no session identity'
        manifest['watcher']['session_id'] = owned_session
        save()
        initial = wait('initial', lambda p: len(p['head']['states']) == 3)
        completed('initial', initial)
        checks = {k: record(initial, k)['state']['check'] for k in ('symbol_exists', 'signature_equals')}
        assert all(c['verdict'] == 'supported' for c in checks.values())
        time.sleep(2.5)
        unchanged = reader.persisted(state, repo)
        assert unchanged['head'] == initial['head'] and unchanged['counts'] == initial['counts']
        write(out / 'unchanged.persisted.json', unchanged)
        completed('unchanged', unchanged)
        previous = unchanged
        untracked_bytes = b'export function camiWatchDevelopment() { return 1; }\n'
        for phase in ('untracked_create', 'untracked_rename', 'untracked_delete'):
            if phase == 'untracked_create':
                untracked.write_bytes(untracked_bytes)
                expected_paths = {'src/cami_watch_development.ts'}
            elif phase == 'untracked_rename':
                untracked.rename(renamed)
                expected_paths = {'src/cami_watch_renamed.ts'}
            else:
                renamed.unlink()
                expected_paths = set()
            owned_paths = {'src/cami_watch_development.ts', 'src/cami_watch_renamed.ts'}
            proof = wait(phase, lambda p: p['head']['sequence'] > previous['head']['sequence']
                         and set(p['sources']) & owned_paths == expected_paths)
            for path in expected_paths:
                assert proof['sources'][path]['sha256'] == hashlib.sha256(untracked_bytes).hexdigest()
            for kind in checks:
                assert record(proof, kind)['state']['check'] == checks[kind]
            assert record(proof, 'note')['state']['review_state'] == 'not_requested'
            completed(phase, proof)
            previous = proof
        for phase, content in changes.items():
            if content is None:
                source.unlink()
            else:
                source.write_bytes(content)
                source.chmod(mode)
            expected_hash = hashlib.sha256(content).hexdigest() if content is not None else None
            proof = wait(phase, lambda p: p['sources'].get(relative, {}).get('sha256') == expected_hash
                         and p['head']['sequence'] > previous['head']['sequence'])
            for kind in checks:
                check = record(proof, kind)['state']['check']
                if phase == 'body':
                    assert check == checks[kind]
                elif phase == 'parse':
                    assert (check['verdict'], check['reason']) == ('insufficient_evidence', 'parse_error')
                elif phase == 'delete':
                    assert (check['verdict'], check['reason']) == ('contradicted', 'subject_absent')
                elif phase == 'signature' and kind == 'signature_equals':
                    assert (check['verdict'], check['reason']) == ('contradicted', 'signature_mismatch')
                else:
                    assert check['verdict'] == 'supported'
            assert record(proof, 'note')['state']['review_state'] == 'needs_review'
            _, context_path = completed(phase, proof)
            previous = proof
        receipt, _ = cli('review-note', 'memory', 'update', ids['note'], '--if-revision', '1',
                         '--from-context', str(context_path), '--text', 'Development review after revert.',
                         '--request-id', 'watch-note-review')
        assert receipt['revision'] == 2
        reviewed = wait('note_review', lambda p: record(p, 'note')['record']['revision'] == 2)
        assert record(reviewed, 'note')['state']['review_state'] == 'not_requested'
        completed('note_review', reviewed)
        manifest['status'] = 'checks_passed_cleanup_pending'
    except (Exception, KeyboardInterrupt) as exc:
        manifest.update(status='failed', failure={'type': type(exc).__name__, 'message': str(exc)})
        raise
    finally:
        cleanup_errors = []
        if process is not None:
            try:
                assert owned_session is not None, 'No verified owned watcher session'
                # The public stop command discovers the current session. A replacement
                # could win that race; signal only the Popen child this driver owns.
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=40)
                assert process.returncode == 0, process.returncode
                stopped, _ = cli('stopped-status', 'watch', 'status', scope=False)
                assert stopped['lifecycle'] == 'stopped' and stopped['ownership'] == 'lease_free'
                phases.append({'label': 'stopped', 'watcher_exit_code': process.returncode,
                               'ownership': stopped['ownership']})
            except (Exception, KeyboardInterrupt) as exc:
                cleanup_errors.append(f'watcher cleanup: {type(exc).__name__}: {exc}')
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=35)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            manifest['watcher']['exit_code'] = process.returncode
            manifest['watcher']['stop_method'] = 'SIGTERM to owned subprocess, then verified status'
        for stream in streams:
            stream.close()
        try:
            source.write_bytes(original)
            source.chmod(mode)
            untracked.unlink(missing_ok=True)
            renamed.unlink(missing_ok=True)
            manifest['restored_source_sha256'] = sha(source)
            manifest['restored_source_mode'] = stat.S_IMODE(source.stat().st_mode)
            manifest['final_git_status'] = subprocess.check_output(
                ['git', '-C', str(repo), 'status', '--porcelain']).decode()
            assert sha(source) == plan['source_sha256'] and not manifest['final_git_status']
            assert manifest['restored_source_mode'] == mode
            manifest['source_after'] = source_snapshot(ROOT)
            assert manifest['source_after'] == before
            assert input_hashes == {name: sha(Path(name)) for name in input_hashes}
            if 'runtime_before' in manifest:
                manifest['runtime_after'] = runtime_identity(env)
                assert manifest['runtime_before'] == manifest['runtime_after']
        except Exception as exc:
            cleanup_errors.append(f'fixture/source cleanup: {type(exc).__name__}: {exc}')
        manifest['cleanup_errors'] = cleanup_errors
        if manifest['status'] == 'checks_passed_cleanup_pending' and [p['label'] for p in phases] != PHASES:
            cleanup_errors.append('Incomplete phase schedule')
        success = manifest['status'] == 'checks_passed_cleanup_pending' and not cleanup_errors
        manifest['status'] = 'passed' if success else 'failed'
        manifest['artifact_hashes'] = {p.name: sha(p) for p in sorted(out.iterdir())
                                       if p.is_file() and p.name != 'manifest.json'}
        save()
        if cleanup_errors:
            raise RuntimeError('; '.join(cleanup_errors))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cache-dir', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.repo, args.protocol, args.out, args.cache_dir)
    print(json.dumps({'status': result['status'], 'phases': len(result['phases'])}))
