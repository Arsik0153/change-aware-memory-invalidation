"""Actual long-lived installed CLI watcher acceptance, with independent persisted-state proofs.

python tests/watch/cli_driver.py --cami /installed/bin/cami --out /new/evidence
No CAMI imports, application execution, services or external test targets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import stat
import subprocess
import time

BASE = 'export function createUser(name: string): string { return name; }\n'
BODY = 'export function createUser(name: string): string { return name.trim(); }\n'
SIG = 'export function createUser(name: number): string { return String(name); }\n'
SYMBOL = 'src/lib/users.ts:createUser'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def bounded(path, limit=256 * 1024 * 1024):
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_size <= limit, path
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(fd)
        assert (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino)
        raw = bytearray()
        while len(raw) <= before.st_size:
            chunk = os.read(fd, min(131072, before.st_size + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(fd)
        linked = path.lstat()
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        assert all(getattr(before, f) == getattr(i, f) for i in (after, linked) for f in fields)
        assert len(raw) == before.st_size
        return bytes(raw)
    finally:
        os.close(fd)


def persisted(state, repo):
    # Product publication replaces the main atomically. Copy bytes; never open live SQLite.
    key = sha(json.dumps(str(repo.resolve()), ensure_ascii=True,
                         separators=(',', ':'), sort_keys=True).encode())
    directory = state / 'cami/repos' / key
    path = directory / 'memory.sqlite3'
    assert not (directory / 'memory.pending').exists()
    assert not path.with_name(path.name + '-journal').exists()
    raw = bounded(path)
    with sqlite3.connect(':memory:') as db:
        db.deserialize(raw)
        db.execute('PRAGMA query_only=ON')
        head = json.loads(db.execute('SELECT g.value FROM product_head h JOIN memory_generation g '
                                     'ON g.id=h.generation_id WHERE h.singleton=1').fetchone()[0])
        index_id = head['index']['generation_id']
        view = json.loads(db.execute('SELECT value FROM index_view WHERE id=?', (index_id,)).fetchone()[0])
        sources = {p: {'sha256': h, 'size': n} for p, h, n in db.execute(
            'SELECT path,sha256,size FROM source_reference WHERE index_id=?', (index_id,))}
        counts = {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in
                  ('memory_generation', 'validation_event', 'record_revision', 'operation_receipt')}
        states = [json.loads(row[0]) for row in db.execute(
            'SELECT value FROM record_state WHERE generation_id=? ORDER BY record_id',
            (head['memory_generation_id'],))]
        assert states == head['states']
        assert view['index'] == head['index']
    artifacts = None
    manifest_path = directory / 'generations' / index_id / 'manifest.json'
    if manifest_path.exists():
        manifest = json.loads(bounded(manifest_path))
        index = bounded(manifest_path.with_name('index.json'))
        assert sha(index) == manifest['index_sha256']
        assert manifest['generation_id'] == index_id
        artifacts = {'manifest_sha256': sha(bounded(manifest_path)), 'index_sha256': sha(index),
                     'entries': manifest['entries']}
    else:
        assert any(reason == 'compiler_unavailable' for _, reason in view['path_errors'])
    for source in sources.values():
        content = bounded(directory / 'source-objects' / source['sha256'])
        assert sha(content) == source['sha256'] and len(content) == source['size']
    return {'head': head, 'view': view, 'sources': sources, 'counts': counts,
            'database_sha256': sha(raw), 'artifacts': artifacts}


def run(cami, out):
    out.mkdir(parents=True)
    repo = out / 'next-app'
    (repo / 'src/lib').mkdir(parents=True)
    (repo / 'app').mkdir()
    (repo / 'build').mkdir()
    source = repo / 'src/lib/users.ts'
    source.write_text(BASE)
    (repo / 'app/page.tsx').write_text('import {createUser} from "@/lib/users"; '
                                    'export function Page() { return <div>{createUser("Ada")}</div>; }\n')
    (repo / 'src/helper.py').write_text('def helper(x: str) -> str:\n    return x\n')
    (repo / 'src/trap.ts').write_text('throw new Error("TARGET EXECUTED");\n')
    (repo / 'src/trap.py').write_text('raise RuntimeError("TARGET EXECUTED")\n')
    (repo / 'tsconfig.json').write_text('{"extends":"./build/base.json","compilerOptions":'
                                       '{"jsx":"preserve","baseUrl":".","paths":{"@/*":["src/*"]}}}')
    (repo / 'build/base.json').write_text('{"compilerOptions":{"strict":true}}')
    (repo / 'package.json').write_text('{"name":"passive-watch-fixture","type":"module"}')
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    state = out / 'state'
    env = {**os.environ, 'XDG_STATE_HOME': str(state), 'PYTHONDONTWRITEBYTECODE': '1'}
    env.pop('PYTHONPATH', None)
    cache = out / 'cache'
    prior_cache = Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache')))
    shutil.copytree(prior_cache / 'cami/typescript', cache / 'cami/typescript')
    env['XDG_CACHE_HOME'] = str(cache)
    commands, phases, handles, streams = [], [], [], []
    counter = 0
    current = None

    def cli(label, *args, expected=0, extra_env=None, options=()):
        nonlocal counter
        counter += 1
        argv = [str(cami), *args, '--repo', str(repo), '--format', 'json', *options]
        start = time.monotonic()
        result = subprocess.run(argv, cwd=out, env={**env, **(extra_env or {})},
                                text=True, capture_output=True, timeout=45)
        prefix = out / f'{counter:03d}-{label}'
        prefix.with_suffix('.stdout').write_text(result.stdout)
        prefix.with_suffix('.stderr').write_text(result.stderr)
        commands.append({'label': label, 'argv': argv, 'exit_code': result.returncode,
                         'seconds': time.monotonic() - start, 'extra_env': extra_env,
                         'stdout': str(prefix.with_suffix('.stdout'))})
        (out / 'commands.json').write_text(json.dumps(commands, indent=2))
        assert result.returncode == expected, (label, result.returncode, result.stdout, result.stderr)
        return json.loads(result.stdout) if result.stdout else None

    def launch(label, action=None, options=()):
        nonlocal current
        output = (out / (label + '.stdout')).open('wb')
        errors = (out / (label + '.stderr')).open('wb')
        streams.extend([output, errors])
        argv = [str(cami), 'watch', *([action] if action else []), '--repo', str(repo),
                '--format', 'json', *options]
        current = subprocess.Popen(argv, cwd=out, env=env, stdout=output, stderr=errors)
        handles.append(current)
        commands.append({'label': label, 'argv': argv, 'pid_owned': current.pid})
        return current

    def wait(label, predicate, timeout=40):
        deadline, last = time.monotonic() + timeout, None
        while time.monotonic() < deadline:
            assert current is None or current.poll() is None, (label, current.returncode)
            try:
                proof = persisted(state, repo)
                if predicate(proof):
                    (out / (label + '.persisted.json')).write_text(json.dumps(proof, indent=2))
                    phases.append({'label': label, 'generation': proof['head']['memory_generation_id'],
                                   'sequence': proof['head']['sequence'], 'counts': proof['counts']})
                    (out / 'phases.json').write_text(json.dumps(phases, indent=2))
                    return proof
            except (OSError, AssertionError, TypeError, sqlite3.Error) as exc:
                last = repr(exc)
            time.sleep(0.15)
        raise AssertionError((label, 'persisted deadline', last))

    def source_is(value):
        expected_hash = sha(value.encode())
        return lambda p: p['sources'].get('src/lib/users.ts', {}).get('sha256') == expected_hash

    def record(proof, kind):
        return next(s for s in proof['head']['states'] if s['record']['payload']['type'] == kind
                    and s['record']['payload']['subject']['path'] == 'src/lib/users.ts')

    def watcher_completed(proof):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            status = cli('completed-status', 'watch', 'status')
            success = status['latest_successful']
            if success and success['memory_generation_id'] == proof['head']['memory_generation_id']:
                return status
            time.sleep(0.2)
        raise AssertionError('no watcher completion for persisted proof')

    def context_after(label, proof):
        value = cli(label + '-context', 'memory', 'context', SYMBOL)
        assert value['memory_generation_id'] == proof['head']['memory_generation_id'], label
        assert value['index'] == proof['head']['index'], label
        after = persisted(state, repo)
        assert after['head'] == proof['head'] and after['counts'] == proof['counts'], label
        return value

    try:
        assert cli('never-started', 'watch', 'status')['lifecycle'] == 'stopped'
        launch('watch-initial')
        first = wait('initial', source_is(BASE))
        watcher_completed(first)
        assert first['artifacts'] is not None
        # No exact-path query yet: no records/probes in initial canonical inputs.
        initial_context = cli('initial-context-no-probes', 'memory', 'context', 'createUser')
        assert initial_context['memory_generation_id'] == first['head']['memory_generation_id']
        assert persisted(state, repo)['counts'] == first['counts']
        context_path = out / 'origin.json'
        context_path.write_text(json.dumps(initial_context))
        ids = {}
        for kind in ('symbol_exists', 'signature_equals', 'note'):
            extra = ['--note-key', 'users-contract', '--text', 'Reviewed manual contract.'] if kind == 'note' else []
            receipt = cli('remember-' + kind, 'memory', 'remember', kind, SYMBOL,
                          '--from-context', str(context_path), '--request-id', 'initial-' + kind, *extra)
            ids[kind] = receipt['memory_id']
        catalog = wait('catalog-joined', lambda p: len(p['head']['states']) == 3)
        context_after('catalog', catalog)
        checks = {k: record(catalog, k)['state']['check'] for k in ('symbol_exists', 'signature_equals')}
        before = catalog
        time.sleep(2.5)
        unchanged = persisted(state, repo)
        assert unchanged['head'] == before['head'] and unchanged['counts'] == before['counts']
        (out / 'unchanged.persisted.json').write_text(json.dumps(unchanged, indent=2))
        assert cli('duplicate-start', 'watch')['reason'] == 'already_running'
        assert cli('different-xdg', 'watch', expected=2,
                   extra_env={'XDG_STATE_HOME': str(out / 'other-state')})['reason'] == 'watch_configuration_conflict'
        # Active config inside excluded build still belongs to effective readset.
        (repo / 'build/base.json').write_text('{"compilerOptions":{"strict":false}}')
        config = wait('excluded-active-config', lambda p: p['head']['sequence'] > before['head']['sequence'])
        assert any(e['path'] == 'build/base.json' for e in config['artifacts']['entries'])
        context_after('active-config', config)
        # Untracked create -> atomic rename -> delete, each persisted before query.
        new = repo / 'src/untracked.ts'
        new.write_text('export function added() { return 1; }\n')
        wait('untracked-created', lambda p: 'src/untracked.ts' in p['sources'])
        new.rename(repo / 'src/renamed.ts')
        renamed = wait('untracked-renamed', lambda p: 'src/renamed.ts' in p['sources']
                       and 'src/untracked.ts' not in p['sources'])
        (repo / 'src/renamed.ts').unlink()
        deleted = wait('untracked-deleted', lambda p: 'src/renamed.ts' not in p['sources']
                       and p['head']['sequence'] > renamed['head']['sequence'])
        context_after('untracked', deleted)
        for kind in checks:
            # Config may recheck; capture checks before body edit for carry oracle.
            checks[kind] = record(deleted, kind)['state']['check']
        temporary = source.with_suffix('.tmp')
        temporary.write_text(BODY)
        temporary.replace(source)
        body = wait('atomic-body', source_is(BODY))
        for kind in checks:
            assert record(body, kind)['state']['check'] == checks[kind]
        assert record(body, 'note')['state']['review_state'] == 'needs_review'
        watcher_completed(body)
        context_after('body', body)
        source.write_text(SIG)
        changed = wait('signature-change', source_is(SIG))
        assert record(changed, 'symbol_exists')['state']['check']['verdict'] == 'supported'
        assert record(changed, 'signature_equals')['state']['check']['reason'] == 'signature_mismatch'
        context_after('signature', changed)
        source.write_text('export function createUser( {\n')
        broken = wait('parse-error', source_is('export function createUser( {\n'))
        assert record(broken, 'symbol_exists')['state']['check']['verdict'] == 'insufficient_evidence'
        assert record(broken, 'symbol_exists')['state']['check']['reason'] == 'parse_error'
        source.unlink()
        absent = wait('subject-delete', lambda p: 'src/lib/users.ts' not in p['sources'])
        check = record(absent, 'symbol_exists')['state']['check']
        assert check['reason'] == 'subject_absent' and check['evidence'][0]['reason'] == 'path_absent_in_scope'
        context_after('absence', absent)
        source.write_text(BASE)
        reverted = wait('reversion', source_is(BASE))
        assert record(reverted, 'symbol_exists')['state']['check']['verdict'] == 'supported'
        assert record(reverted, 'symbol_exists')['state']['check']['check_id'] != checks['symbol_exists']['check_id']
        assert record(reverted, 'note')['state']['review_state'] == 'needs_review'
        reviewed = context_after('reversion', reverted)
        context_path.write_text(json.dumps(reviewed))
        cli('review-note', 'memory', 'update', ids['note'], '--if-revision', '1', '--from-context',
            str(context_path), '--text', 'Reviewed current source.', '--request-id', 'review-note')
        review = wait('note-reviewed', lambda p: record(p, 'note')['record']['revision'] == 2)
        assert record(review, 'note')['state']['review_state'] == 'not_requested'
        # A new fact registered during watch enters subsequent catalog capture/probes.
        py_context = cli('python-context', 'memory', 'context', 'src/helper.py:helper')
        context_path.write_text(json.dumps(py_context))
        cli('remember-python', 'memory', 'remember', 'symbol_exists', 'src/helper.py:helper',
            '--from-context', str(context_path), '--request-id', 'python-late')
        (repo / 'src/helper.py').write_text('def helper(x: str) -> str:\n    return x.strip()\n')
        pyhash = sha((repo / 'src/helper.py').read_bytes())
        python = wait('late-catalog-python-edit', lambda p: p['sources']['src/helper.py']['sha256'] == pyhash
                      and len(p['head']['states']) == 4)
        context_after('late-catalog', python)
        # Ignore policy uncertainty, then recovery without retargeting old record.
        (repo / '.gitignore').write_text('src/lib/users.ts\n')
        ignored = wait('ignored', lambda p: p['head']['sequence'] > python['head']['sequence'])
        assert record(ignored, 'symbol_exists')['state']['check']['reason'] == 'scope_uncovered'
        context_after('ignored', ignored)
        (repo / '.gitignore').unlink()
        restored = wait('ignore-recovered', source_is(BASE))
        # Tool output, logs and generated inputs have no semantic effect.
        (repo / 'node_modules').mkdir()
        (repo / 'node_modules/noise.ts').write_text('export const noisy = 1;')
        (repo / 'build/noise.ts').write_text('export const noisy = 2;')
        (repo / 'watch.log').write_text('external agent log\n')
        time.sleep(2)
        assert persisted(state, repo)['counts'] == restored['counts']
        # Compiler loss and recovery without any source edit, through watch alone.
        compiler = next((cache / 'cami/typescript').glob('6.0.3-*/node_modules/typescript/lib/typescript.js'))
        compiler_saved = compiler.with_suffix('.saved')
        compiler.rename(compiler_saved)
        unavailable = wait('compiler-missing', lambda p: record(p, 'symbol_exists')['state']['check']['reason']
                           == 'compiler_unavailable')
        assert unavailable['sources'] == restored['sources']
        unavailable_counts = unavailable['counts']
        time.sleep(2)
        assert persisted(state, repo)['counts'] == unavailable_counts
        compiler_saved.rename(compiler)
        compiler_recovered = wait('compiler-recovered', lambda p: record(p, 'symbol_exists')['state']['check']['verdict']
                                  == 'supported' and p['head']['sequence'] > unavailable['head']['sequence'])
        assert compiler_recovered['sources'] == restored['sources']
        context_after('compiler-recovery', compiler_recovered)
        # Rapid edits coalesce; eventual literal bytes and counters survive duplicate events.
        for i in range(12):
            source.write_text(BODY.replace('name.trim()', f'name.trim() + "{i}"'))
            time.sleep(0.03)
        source.write_text(BODY)
        burst = wait('burst', source_is(BODY))
        context_after('burst', burst)
        # Continued edits exceed max deferral; there must be an intermediate persisted head.
        baseline_sequence = burst['head']['sequence']
        event_offset = len((out / 'watch-initial.stdout').read_text().splitlines())
        intermediate = []
        until = time.monotonic() + 4.5
        i = 0
        while time.monotonic() < until:
            text = BODY.replace('name.trim()', f'name.trim() + "continuous-{i}"')
            source.write_text(text)
            try:
                p = persisted(state, repo)
                if p['head']['sequence'] > baseline_sequence:
                    intermediate.append(p['head']['memory_generation_id'])
            except (OSError, AssertionError):
                pass
            i += 1
            time.sleep(0.12)
        events = [json.loads(line) for line in (out / 'watch-initial.stdout').read_text().splitlines()[event_offset:]]
        # Unstable writes can legitimately prevent publication; max deferral bounds attempts.
        assert any(e['event'] == 'refresh_started' for e in events), 'no bounded refresh attempt'
        during = persisted(state, repo)
        (out / 'continuous-during.persisted.json').write_text(json.dumps(during, indent=2))
        source.write_text(BASE)
        continuous = wait('continuous-final', source_is(BASE))
        (out / 'continuous.json').write_text(json.dumps({'writes': i, 'intermediate_heads': intermediate}))
        # Service writer blocked by an unrelated owned process: status remains responsive.
        lock_path = state / 'cami/repos' / continuous['head']['index']['worktree_key'] / 'writer.lock'
        locker = subprocess.Popen([shutil.which('python3') or 'python3', '-c',
            'import fcntl,sys,time; f=open(sys.argv[1],"r+"); fcntl.flock(f,fcntl.LOCK_EX); '
            'print("locked",flush=True); time.sleep(30)', str(lock_path)], stdout=subprocess.PIPE)
        handles.append(locker)
        assert locker.stdout.readline() == b'locked\n'
        source.write_text(BODY)
        time.sleep(1)
        slow_status = cli('status-during-writer-lock', 'watch', 'status')
        assert slow_status['lifecycle'] == 'running'
        assert commands[-1]['seconds'] < 3
        stopped = cli('stop-during-writer-lock', 'watch', 'stop')
        assert stopped['lifecycle'] == 'stopped'
        assert current.wait(timeout=10) == 0
        locker.terminate()
        locker.wait(timeout=5)
        assert cli('stop-again', 'watch', 'stop')['lifecycle'] == 'stopped'
        # Catch up after stopped edits. Restart itself is a real foreground process.
        source.write_text(SIG)
        assert persisted(state, repo)['head'] == continuous['head']
        launch('watch-restart', 'restart')
        catchup = wait('restart-catchup', source_is(SIG))
        watcher_completed(catchup)
        context_after('catchup', catchup)
        current.send_signal(signal.SIGTERM)
        assert current.wait(timeout=15) == 0
        assert cli('sigterm-stopped', 'watch', 'status')['lifecycle'] == 'stopped'
        # Restart with explicit scope exclusion: missing input is uncertainty, never absence.
        launch('watch-scope', options=('--exclude', 'src/lib'))
        narrowed = wait('scope-excluded', lambda p: record(p, 'symbol_exists')['state']['check']['reason']
                        == 'scope_uncovered' and 'src/lib/users.ts' not in p['sources'])
        assert narrowed['head']['sequence'] > catchup['head']['sequence']
        cli('stop-scope', 'watch', 'stop')
        assert current.wait(timeout=10) == 0
        launch('watch-roots', options=('--source-root', 'src/lib'))
        roots = wait('explicit-source-roots', lambda p: 'app/page.tsx' not in p['sources']
                     and 'src/lib/users.ts' in p['sources'] and any(
                         s['record']['payload']['subject']['path'] == 'src/helper.py'
                         and s['state']['check']['reason'] == 'scope_uncovered'
                         for s in p['head']['states']))
        assert roots['head']['sequence'] > narrowed['head']['sequence']
        cli('stop-roots', 'watch', 'stop')
        assert current.wait(timeout=10) == 0
        # Persisted corruption must not manufacture empty memory. Restore only saved bytes.
        directory = lock_path.parent
        database = directory / 'memory.sqlite3'
        saved = bounded(database)
        database.write_bytes(b'not SQLite')
        launch('watch-corrupt')
        time.sleep(1.8)
        status = cli('corrupt-status', 'watch', 'status')
        assert status['last_error'] and status['data_freshness'] == 'unknown'
        assert bounded(database) == b'not SQLite'
        database.write_bytes(saved)
        recovered = wait('database-restored', source_is(SIG))
        assert len(recovered['head']['states']) == 4
        database.unlink()
        time.sleep(1.5)
        status = cli('missing-database-status', 'watch', 'status')
        assert status['last_error'] and not database.exists()
        database.write_bytes(saved)
        recovered = wait('missing-database-restored', source_is(SIG))
        cli('stop-final', 'watch', 'stop')
        assert current.wait(timeout=10) == 0
        result = {'commands': len(commands), 'phases': len(phases), 'owned_processes': len(handles),
                  'final_head': recovered['head']['memory_generation_id'], 'all_owned_reaped': True}
        (out / 'result.json').write_text(json.dumps(result, indent=2))
        return result
    finally:
        for process in handles:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    raise AssertionError('owned process required SIGKILL cleanup')
        for stream in streams:
            stream.close()
        (out / 'processes.json').write_text(json.dumps([
            {'pid_owned': p.pid, 'exit_code': p.poll()} for p in handles], indent=2))
        (out / 'commands.json').write_text(json.dumps(commands, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cami', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.cami.resolve(), args.out.resolve()), indent=2))
