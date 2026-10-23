"""Rerunnable installed-CLI acceptance; no CAMI imports or target execution.

Run: python hybrid_cli_driver.py --cami /installed/bin/cami --out /new/evidence
The executable must have a trusted compiler in its user cache.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

SYMBOL = 'src/lib/users.ts:createUser'
BASE = 'export function createUser(name: string): string { return name; }\n'
EXPECTED = {
    'format': 'ecma.syntax-signature/2',
    'parameters': [{'pattern': '["Identifier","name"]', 'optional': False, 'rest': False,
                    'default': None, 'annotation': '["StringKeyword","string"]'}],
    'type_parameters': [], 'return_annotation': '["StringKeyword","string"]',
    'is_async': False, 'generator': False,
}


def run(cami: Path, out: Path) -> dict:
    out.mkdir(parents=True)
    repo = out / 'next-app'
    (repo / 'src/lib').mkdir(parents=True)
    (repo / 'src/app').mkdir()
    path = repo / 'src/lib/users.ts'
    path.write_text(BASE)
    (repo / 'src/lib/importer.ts').write_text(
        'import {createUser} from "./users"; export const user = createUser("Ada");\n')
    (repo / 'src/app/page.tsx').write_text(
        'import {createUser} from "../lib/users"; '
        'export function Page() { return <div>{createUser("Ada")}</div>; }\n')
    (repo / 'src/helper.py').write_text('def helper(name: str) -> str:\n    return name\n')
    # These inputs would fail if a query evaluated either language's target code.
    (repo / 'src/trap.ts').write_text('throw new Error("TARGET EXECUTED");\n')
    (repo / 'src/trap.py').write_text('raise RuntimeError("TARGET EXECUTED")\n')
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    environment = {**os.environ, 'XDG_STATE_HOME': str(out / 'state'),
                   'PYTHONDONTWRITEBYTECODE': '1'}
    environment.pop('PYTHONPATH', None)
    commands = []
    phases = []
    ids = {}
    step = 0

    def cli(label, *args, expected_exit=0, extra_env=None, options=()):
        nonlocal step
        step += 1
        command = [str(cami), *args, '--repo', str(repo), '--format', 'json', *options]
        process = subprocess.run(command, env={**environment, **(extra_env or {})},
                                 cwd=out, text=True, capture_output=True, timeout=90)
        prefix = out / f'{step:03d}-{label}'
        prefix.with_suffix('.json').write_text(process.stdout)
        prefix.with_suffix('.stderr').write_text(process.stderr)
        commands.append(dict(label=label, argv=command, exit_code=process.returncode,
                             stdout=str(prefix.with_suffix('.json')),
                             environment=extra_env or {}, options=options))
        (out / 'commands.json').write_text(json.dumps(commands, indent=2))
        assert process.returncode == expected_exit, (label, process.returncode, process.stderr)
        return json.loads(process.stdout) if process.stdout else None

    def context(label, symbol=SYMBOL, **kwargs):
        return cli(label, 'memory', 'context', symbol, **kwargs)

    def save(label, value):
        target = out / (label + '.context.json')
        target.write_text(json.dumps(value))
        return str(target)

    def states(value):
        result = {x['record']['payload']['type']: 'available' for x in value['facts']}
        result.update({x['record']['payload']['type']: x['reason'] for x in value['withheld']
                       if x['record']['payload']['type'] != 'note'})
        return result

    def persisted(label, value, *, transient=False, **kwargs):
        database = out / 'state/cami/repos' / value['index']['worktree_key'] / 'memory.sqlite3'
        with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
            assert db.execute('SELECT generation_id FROM product_head WHERE singleton=1').fetchone() == (
                value['memory_generation_id'],)
        head = cli(label + '-refresh', 'memory', 'refresh', **kwargs)
        if not transient:
            assert head['memory_generation_id'] == value['memory_generation_id'], label
            assert head['index'] == value['index'], label
        elif head['memory_generation_id'] != value['memory_generation_id']:
            assert head['parent_memory_generation_id'] == value['memory_generation_id'], label
        for kind, memory_id in ids.items():
            history = cli(label + '-history-' + kind, 'memory', 'history', memory_id)
            assert history['generations'][-1]['memory_generation_id'] == head['memory_generation_id']
            current = next(x for x in head['states'] if x['record']['memory_id'] == memory_id)
            if kind != 'note':
                check = current['state']['check']
                assert any(c == check for c in history['checks']), (label, kind)
        database = out / 'state/cami/repos' / value['index']['worktree_key'] / 'memory.sqlite3'
        # Read-only persisted truth supplements actual history/refresh JSON.
        with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
            row = db.execute('SELECT generation_id FROM product_head WHERE singleton=1').fetchone()
            assert row == (head['memory_generation_id'],)
        phases.append(dict(label=label, memory_generation_id=head['memory_generation_id'],
                           sequence=head['sequence'], states=states(value)))
        return head

    found = cli('find', 'find', SYMBOL)
    assert found['schema_version'] == 3 and found['typescript']['status'] == 'ready'
    assert found['matches'][0]['language'] == 'ts'
    same_capture = context('same-capture', 'createUser')
    assert same_capture['index']['generation_id'] == found['snapshot']['generation_id']
    assert same_capture['index']['snapshot_id'] == found['snapshot']['snapshot_id']
    origin = context('origin')
    fact = origin['code'][0]
    assert fact['signature'] == EXPECTED
    assert fact['source']['sha256'] == hashlib.sha256(BASE.encode()).hexdigest()
    assert fact['source']['index'] == origin['index']
    # Probe differences permit distinct IDs; identical captures still share source bytes.
    assert found['matches'][0]['syntax_hash'] == hashlib.sha256(BASE.strip().encode()).hexdigest()
    origin_file = save('origin', origin)
    for kind in ('symbol_exists', 'signature_equals', 'note'):
        extra = ['--note-key', 'users-contract', '--text', 'Returns the supplied name.'] \
            if kind == 'note' else []
        args = ('memory', 'remember', kind, SYMBOL, '--from-context', origin_file,
                '--request-id', 'initial-' + kind, *extra)
        receipt = cli('remember-' + kind, *args)
        assert cli('retry-' + kind, *args) == receipt
        ids[kind] = receipt['memory_id']
    python_origin = context('python-origin', 'src/helper.py:helper')
    cli('remember-python', 'memory', 'remember', 'symbol_exists', 'src/helper.py:helper',
        '--from-context', save('python-origin', python_origin), '--request-id', 'python')
    initial = context('initial')
    assert states(initial) == {'symbol_exists': 'available', 'signature_equals': 'available'}
    assert len(initial['notes']) == 1 and not initial['withheld']
    persisted('initial', initial)
    checks = {x['record']['payload']['type']: x['state']['check'] for x in initial['facts']}
    stable = context('unchanged')
    assert stable['memory_generation_id'] == initial['memory_generation_id']
    assert stable['facts'] == initial['facts']
    persisted('unchanged', stable)
    (repo / 'src/unrelated.ts').write_text('export function unrelated() { return 42; }\n')
    unrelated = context('unrelated')
    assert unrelated['notes'] and not unrelated['withheld']
    for item in unrelated['facts']:
        assert item['state']['check'] == checks[item['record']['payload']['type']]
    persisted('unrelated', unrelated)

    variants = [
        ('body', BASE.replace('return name', 'return "user"'), 'available', 'available'),
        ('signature', BASE.replace('name: string', 'name: string, active = true'),
         'available', 'signature_mismatch'),
        ('rename', BASE.replace('createUser', 'renamedUser'), 'subject_absent', 'subject_absent'),
        ('deleted', None, 'subject_absent', 'subject_absent'),
        ('parse', 'export function createUser(: {}', 'parse_error', 'parse_error'),
        ('ambiguous', BASE + BASE, 'ambiguous_binding', 'ambiguous_binding'),
        ('conditional', 'if (true) { ' + BASE.removeprefix('export ') + ' }',
         'ambiguous_binding', 'ambiguous_binding'),
        ('declaration', 'export declare function createUser(name: string): string;',
         'binding_unresolved', 'binding_unresolved'),
        ('unsupported-binding', 'export const createUser = wrap((name: string) => name);',
         'binding_unresolved', 'binding_unresolved'),
        ('namespace', 'export namespace createUser { export function inner() {} }',
         'binding_unresolved', 'binding_unresolved'),
        ('reassigned', BASE + 'createUser = other;', 'ambiguous_binding', 'ambiguous_binding'),
        ('unresolved-call', BASE + 'unknownExternal();', 'available', 'available'),
        ('revert', BASE, 'available', 'available'),
    ]
    for label, source, exists, signature in variants:
        if source is None:
            path.unlink()
        else:
            path.write_text(source)
        value = context(label)
        assert states(value) == {'symbol_exists': exists, 'signature_equals': signature}, (label, value)
        assert not value['notes']
        assert any(x['reason'] == 'manual_review_required' for x in value['withheld'])
        if label == 'body':
            for item in value['facts']:
                assert item['state']['check'] == checks[item['record']['payload']['type']]
            cas = (out / 'state/cami/repos' / origin['index']['worktree_key'] /
                   'source-objects' / hashlib.sha256(BASE.encode()).hexdigest())
            assert cas.read_bytes() == BASE.encode()
        if label in ('rename', 'deleted'):
            for item in value['withheld']:
                if item['record']['payload']['type'] != 'note':
                    witness = item['state']['check']['evidence'][0]
                    assert witness['reason'] == ('path_absent_in_scope' if label == 'deleted'
                                                  else 'symbol_absent_in_parsed_file')
        if label == 'revert':
            assert all(x['state']['check']['check_id'] != checks[x['record']['payload']['type']]['check_id']
                       for x in value['facts'])
        persisted(label, value)
    reviewed_origin = save('review', value)
    cli('review-note', 'memory', 'update', ids['note'], '--if-revision', '1',
        '--from-context', reviewed_origin, '--request-id', 'review', '--text', 'Reviewed source.')
    reviewed = context('reviewed')
    assert reviewed['notes'][0]['record']['revision'] == 2 and not reviewed['withheld']
    cli('review-cas-conflict', 'memory', 'update', ids['note'], '--if-revision', '1',
        '--from-context', reviewed_origin, '--request-id', 'bad-cas', '--text', 'Conflicting review.',
        expected_exit=2)
    cli('request-conflict', 'memory', 'remember', 'note', SYMBOL, '--from-context', origin_file,
        '--request-id', 'initial-note', '--note-key', 'users-contract', '--text', 'Different text',
        expected_exit=2)
    persisted('reviewed', reviewed)

    # Canonical expectations are compared via actual CLI JSON, never adapter imports.
    pairs = [
        ('comments', BASE, '/* hello */ export function createUser( name /*x*/ : string ) : string { return name; }', True),
        ('operator', 'function createUser(x = -1) {}', 'function createUser(x = +1) {}', False),
        ('literal', 'function createUser(x = "a") {}', 'function createUser(x = "b") {}', False),
        ('regex-flags', 'function createUser(x = /a/g) {}', 'function createUser(x = /a/i) {}', False),
        ('optional', 'function createUser(x?: string) {}', 'function createUser(x: string) {}', False),
        ('readonly', 'function createUser(x: readonly string[]) {}', 'function createUser(x: string[]) {}', False),
        ('keyof', 'function createUser<T>(x: keyof T) {}', 'function createUser<T>(x: T) {}', False),
        ('mapped', 'function createUser<T>(x: {readonly [K in keyof T]?: T[K]}) {}',
         'function createUser<T>(x: {[K in keyof T]-?: T[K]}) {}', False),
        ('order', 'function createUser(x: string, y: number) {}',
         'function createUser(y: number, x: string) {}', False),
        ('async', 'async function createUser() {}', 'function createUser() {}', False),
        ('generator', 'function* createUser() {}', 'function createUser() {}', False),
    ]
    for label, left, right, equal in pairs:
        path.write_text(left)
        a = context('canonical-' + label + '-a')
        path.write_text(right)
        b = context('canonical-' + label + '-b')
        assert (a['code'][0]['signature'] == b['code'][0]['signature']) is equal, label
        persisted('canonical-' + label, b)
    path.write_text(BASE)
    current = context('before-unavailable')
    # An empty cache is a truthful unavailable runtime; no query installs anything.
    empty_cache = out / 'empty-cache'
    empty_cache.mkdir()
    unavailable = context('missing-compiler', extra_env={'XDG_CACHE_HOME': str(empty_cache)})
    assert not unavailable['code'] and not unavailable['facts']
    assert states(unavailable) == {'symbol_exists': 'compiler_unavailable',
                                   'signature_equals': 'compiler_unavailable'}
    persisted('missing-compiler', unavailable, transient=True, extra_env={'XDG_CACHE_HOME': str(empty_cache)})
    py = context('python-with-compiler-missing', 'src/helper.py:helper',
                 extra_env={'XDG_CACHE_HOME': str(empty_cache)})
    assert len(py['facts']) == 1 and not py['withheld']
    assert not any(empty_cache.iterdir()), 'query must not install a compiler'
    # An untrusted user-cache file must never be loaded as executable compiler code.
    actual_cache = Path(environment.get('XDG_CACHE_HOME', str(Path.home() / '.cache')))
    runtimes = [p for p in (actual_cache / 'cami/typescript').glob('6.0.3-*')
                if p.is_dir() and (p / 'ready.json').is_file()]
    assert len(runtimes) >= 1
    fake = empty_cache / 'cami/typescript' / runtimes[0].name
    (fake / 'node_modules/typescript/lib').mkdir(parents=True)
    (fake / 'node_modules/typescript/lib/typescript.js').write_text(
        'require("node:fs").writeFileSync("EXECUTED", "bad"); throw new Error("untrusted")')
    for name in ('package.json', 'package-lock.json'):
        shutil.copyfile(runtimes[0] / name, fake / name)
    (fake / 'ready.json').write_text('{}')
    untrusted = context('untrusted-compiler', extra_env={'XDG_CACHE_HOME': str(empty_cache)})
    assert not untrusted['code'] and not untrusted['facts']
    assert not (fake / 'node_modules/typescript/lib/EXECUTED').exists()
    persisted('untrusted-compiler', untrusted, transient=True, extra_env={'XDG_CACHE_HOME': str(empty_cache)})
    recovered = context('compiler-recovered')
    assert recovered['code'] and len(recovered['facts']) == 2
    assert recovered['index'] == current['index']
    assert recovered['memory_generation_id'] != current['memory_generation_id']
    persisted('compiler-recovered', recovered)
    no_node = out / 'no-node-bin'
    no_node.mkdir()
    for binary in ('git',):
        (no_node / binary).symlink_to(shutil.which(binary))
    missing_node = context('missing-node', extra_env={'PATH': str(no_node)})
    assert not missing_node['code'] and not missing_node['facts']
    persisted('missing-node', missing_node, transient=True, extra_env={'PATH': str(no_node)})
    assert context('node-recovered')['facts']

    # A captured active config under an excluded build directory still affects identity.
    (repo / 'build').mkdir()
    (repo / 'tsconfig.json').write_text('{"extends":"./build/active.json"}')
    config = repo / 'build/active.json'
    config.write_text('{"compilerOptions":{"strict":true}}')
    valid = context('config-valid', options=('--exclude', 'build'))
    config.write_text('{"compilerOptions":')
    invalid = context('config-invalid', options=('--exclude', 'build'))
    assert valid['index'] != invalid['index']
    assert states(invalid) == {'symbol_exists': 'scope_uncovered', 'signature_equals': 'scope_uncovered'}
    persisted('config-invalid', invalid, options=('--exclude', 'build'))
    config.unlink()
    missing = context('config-deleted', options=('--exclude', 'build'))
    assert states(missing)['symbol_exists'] == 'scope_uncovered'
    persisted('config-deleted', missing, options=('--exclude', 'build'))
    config.write_text('{"compilerOptions":{"strict":false}}')
    assert context('config-recovered')['facts']
    (repo / '.gitignore').write_text('src/lib/users.ts\n')
    ignored = context('ignored')
    assert states(ignored) == {'symbol_exists': 'scope_uncovered', 'signature_equals': 'scope_uncovered'}
    assert next(c for c in ignored['coverage'] if c['path'] == 'src/lib/users.ts')['status'] == 'ignored'
    persisted('ignored', ignored)
    (repo / '.gitignore').unlink()
    narrow = context('narrow', options=('--source-root', 'src/app'))
    assert states(narrow) == {'symbol_exists': 'scope_uncovered', 'signature_equals': 'scope_uncovered'}
    persisted('narrow', narrow, options=('--source-root', 'src/app'))
    final = context('final-recovery')
    assert len(final['facts']) == 2
    persisted('final', final)
    result = dict(status='passed', commands=len(commands), phases=phases, ids=ids,
                  known_storage_R3='pending parent overlay; not tested or fixed here')
    (out / 'result.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cami', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.cami.resolve(), args.out.resolve()), indent=2))
