"""Installed CLI member coverage, concurrent requests, and authenticated stale origins."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess

BASE = 'export class Users { createUser(name: string) { return name; } }\n'
SYMBOL = 'src/users.ts:Users.createUser'


def run(cami: Path, out: Path) -> dict:
    out.mkdir(parents=True)
    repo = out / 'repo'
    (repo / 'src').mkdir(parents=True)
    source = repo / 'src/users.ts'
    source.write_text(BASE)
    (repo / 'src/other.ts').write_text('export function other() {}\n')
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    env = {**os.environ, 'XDG_STATE_HOME': str(out / 'state'), 'PYTHONDONTWRITEBYTECODE': '1'}
    env.pop('PYTHONPATH', None)
    commands = []

    def cli(label, *args, expected_exit=0):
        command = [str(cami), 'memory', *args, '--repo', str(repo), '--format', 'json']
        result = subprocess.run(command, cwd=out, env=env, capture_output=True, text=True, timeout=90)
        (out / (label + '.json')).write_text(result.stdout)
        (out / (label + '.stderr')).write_text(result.stderr)
        commands.append(dict(label=label, argv=command, exit_code=result.returncode))
        assert result.returncode == expected_exit, (label, result.returncode, result.stderr)
        return json.loads(result.stdout) if result.stdout else None

    def pin(label, value):
        path = out / (label + '.context.json')
        path.write_text(json.dumps(value))
        return str(path)

    origin = cli('origin', 'context', SYMBOL)
    assert len(origin['code']) == 1 and origin['code'][0]['signature'] is None
    origin_file = pin('origin', origin)
    request = ('remember', 'symbol_exists', SYMBOL, '--from-context', origin_file,
               '--request-id', 'concurrent-identical')
    with ThreadPoolExecutor(2) as pool:
        receipts = list(pool.map(lambda label: cli(label, *request), ('remember-a', 'remember-b')))
    assert receipts[0] == receipts[1]
    memory_id = receipts[0]['memory_id']
    cli('unsupported-signature', 'remember', 'signature_equals', SYMBOL,
        '--from-context', origin_file, '--request-id', 'unsupported-signature', expected_exit=2)
    history = cli('initial-history', 'history', memory_id)
    assert len(history['checks']) == len(history['revisions']) == 1
    first_check = history['checks'][0]
    for label, raw, reason in (
        ('computed', 'export class Users { [key](name: string) { return name; } }', 'binding_unresolved'),
        ('property', 'export class Users { createUser = wrap((name: string) => name); }', 'binding_unresolved'),
        ('parameter-property', 'export class Users { constructor(public createUser: (name: string) => string) {} }', 'binding_unresolved'),
        ('declaration', 'export class Users { createUser(name: string): string; }', 'binding_unresolved'),
        ('deleted', 'export class Users {}', 'subject_absent'),
        ('revert', BASE, None),
    ):
        source.write_text(raw)
        value = cli(label, 'context', SYMBOL)
        if reason:
            assert not value['facts'] and value['withheld'][0]['reason'] == reason
        else:
            assert len(value['facts']) == 1 and not value['withheld']
            assert value['facts'][0]['state']['check']['check_id'] != first_check['check_id']
        head = cli(label + '-refresh', 'refresh')
        assert head['memory_generation_id'] == value['memory_generation_id']
        history = cli(label + '-history', 'history', memory_id)
        assert history['generations'][-1]['memory_generation_id'] == value['memory_generation_id']
        check = next(s for s in head['states'] if s['record']['memory_id'] == memory_id)['state']['check']
        assert check in history['checks']
        assert cli(label + '-unrelated', 'context', 'other')['code']
    # Old immutable contexts remain authentic after edits; new checks use current sources.
    source.write_text('export class Users {}')
    stale = cli('stale-note', 'remember', 'note', SYMBOL, '--from-context', origin_file,
                '--request-id', 'stale-note', '--note-key', 'stale', '--text', 'Old source note.')
    assert stale['revision'] == 1
    value = cli('stale-current', 'context', SYMBOL)
    note = next(x for x in value['withheld'] if x['record']['payload']['type'] == 'note')
    assert note['reason'] == 'manual_review_required'
    assert note['record']['origin'] == origin['index']
    forged = json.loads(json.dumps(origin))
    forged['code'][0]['source']['sha256'] = '0' * 64
    cli('forged-origin', 'remember', 'symbol_exists', SYMBOL,
        '--from-context', pin('forged', forged), '--request-id', 'forged', expected_exit=2)
    # Concurrent context and mutation must each expose their own coherent committed head.
    source.write_text(BASE)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(cli, 'parallel-context', 'context', SYMBOL),
                   pool.submit(cli, 'parallel-retry', *request)]
        parallel = [f.result() for f in futures]
    assert parallel[1] == receipts[0]
    value = parallel[0]
    assert all(x['source']['index'] == value['index'] for x in value['code'])
    assert all(x['state']['check']['index'] == value['index'] or x['state']['type'] == 'carried'
               for x in value['facts'])
    history = cli('final-history', 'history', memory_id)
    assert len(history['revisions']) == 1
    assert [c['reason'] for c in history['checks']] == [
        'predicate_matches', 'binding_unresolved', 'binding_unresolved', 'binding_unresolved',
        'binding_unresolved', 'subject_absent', 'predicate_matches', 'subject_absent', 'predicate_matches']
    default_source = repo / 'src/default.ts'
    default_source.write_text('export default () => 1;')
    default_origin = cli('default-origin', 'context', 'src/default.ts:<default>')
    default_receipt = cli('default-remember', 'remember', 'symbol_exists', 'src/default.ts:<default>',
                          '--from-context', pin('default', default_origin), '--request-id', 'default')
    default_source.write_text('export default wrap(() => 1);')
    default_current = cli('default-wrapped', 'context', 'src/default.ts:<default>')
    assert default_current['withheld'][0]['reason'] == 'binding_unresolved'
    default_history = cli('default-history', 'history', default_receipt['memory_id'])
    assert [c['reason'] for c in default_history['checks']] == ['predicate_matches', 'binding_unresolved']
    (out / 'commands.json').write_text(json.dumps(commands, indent=2))
    result = dict(status='passed', commands=len(commands), memory_id=memory_id,
                  check_count=len(history['checks']))
    (out / 'result.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cami', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.cami.resolve(), args.out.resolve()), indent=2))
