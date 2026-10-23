"""Installed CLI regression for static member identity and scoped uncertainty."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess


CASES = (
    ('object-quoted', 'createUser', '"createUser"', None),
    ('object-field', 'createUser', '"createUser": wrap(() => 1)', 'binding_unresolved'),
    ('quoted', 'createUser', '"createUser"', None),
    ('escaped', 'createUser', '"create\\u0055ser"', None),
    ('computed-string', 'createUser', '["createUser"]', None),
    ('numeric', '16', '0x10', None),
    ('quoted-numeric', '16', '"16"', None),
    ('computed-number', '16', '[16]', None),
    ('private', '#createUser', '#create\\u0055ser', None),
    ('quoted-field', 'createUser', '"createUser" = wrap(() => 1);', 'binding_unresolved'),
    ('computed-field', 'createUser', '["createUser"] = wrap(() => 1);', 'binding_unresolved'),
    ('accessor', 'createUser', 'get "createUser"() { return 1; }', 'binding_unresolved'),
    ('dynamic', 'createUser', '[key]() {}', 'binding_unresolved'),
    ('duplicate', 'createUser', 'createUser() {} "createUser"() {}', 'ambiguous_binding'),
)


def run(cami: Path, out: Path) -> dict:
    out.mkdir(parents=True)
    commands = []
    try:
        for label, original, replacement, reason in CASES:
            case = out / label
            root = case / 'repo'
            root.mkdir(parents=True)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            source = root / 'api.ts'
            is_object = label.startswith('object-')
            symbol = 'api.ts:' + ('' if is_object else 'Users.') + original

            def program(member):
                container = f'const api = {{ {member} }};' if is_object else f'class Users {{ {member} }}'
                return 'function unrelated() {}\n' + container

            base = program(original + '() {}')
            source.write_text(base)
            env = {**os.environ, 'XDG_STATE_HOME': str(case / 'state'),
                   'PYTHONDONTWRITEBYTECODE': '1'}
            env.pop('PYTHONPATH', None)

            def cli(phase, *args, exit_code=0):
                argv = [str(cami), 'memory', *args, '--repo', str(root), '--format', 'json']
                result = subprocess.run(argv, env=env, cwd=case, text=True,
                                        capture_output=True, timeout=90)
                commands.append(dict(case=label, phase=phase, argv=argv,
                                     exit_code=result.returncode))
                (case / (phase + '.json')).write_text(result.stdout)
                (case / (phase + '.stderr')).write_text(result.stderr)
                assert result.returncode == exit_code, (label, phase, result.stderr)
                return json.loads(result.stdout) if result.stdout else None

            origin = cli('origin', 'context', symbol)
            assert len(origin['code']) == 1, (label, origin)
            receipt = cli('remember', 'remember', 'symbol_exists', symbol,
                          '--from-context', str(case / 'origin.json'), '--request-id', label)
            cli('signature', 'remember', 'signature_equals', symbol,
                '--from-context', str(case / 'origin.json'), '--request-id', label + '-sig',
                exit_code=2)
            if reason is None:
                replacement += '() {}'
            source.write_text(program(replacement))
            value = cli('changed', 'context', symbol)
            database = case / 'state/cami/repos' / value['index']['worktree_key'] / 'memory.sqlite3'
            # Observe committed state before any refresh/history query can repair it.
            with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
                assert db.execute('SELECT generation_id FROM product_head').fetchone() == (
                    value['memory_generation_id'],)
            if reason:
                assert not value['facts'] and value['withheld'][0]['reason'] == reason, (label, value)
                assert value['withheld'][0]['state']['check']['verdict'] == 'insufficient_evidence'
            else:
                assert len(value['facts']) == 1 and not value['withheld'], (label, value)
                assert value['code'][0]['subject'] == origin['code'][0]['subject']
                assert value['code'][0]['signature'] is None
            head = cli('refresh', 'refresh')
            history = cli('history', 'history', receipt['memory_id'])
            assert head['memory_generation_id'] == value['memory_generation_id']
            assert history['generations'][-1]['memory_generation_id'] == value['memory_generation_id']
            assert not any(c['verdict'] == 'contradicted' for c in history['checks'])
            assert cli('unrelated', 'context', 'api.ts:unrelated')['code']
            source.write_text(program(''))
            deleted = cli('deleted', 'context', symbol)
            assert deleted['withheld'][0]['reason'] == 'subject_absent'
            check = deleted['withheld'][0]['state']['check']
            assert check['verdict'] == 'contradicted' and check['evidence']
            source.write_text(base)
            reverted = cli('reverted', 'context', symbol)
            assert len(reverted['facts']) == 1 and not reverted['withheld']
            final = cli('final-history', 'history', receipt['memory_id'])
            assert final['checks'][-2]['verdict'] == 'contradicted'
            assert final['checks'][-1]['verdict'] == 'supported'
        result = dict(status='passed', cases=len(CASES), commands=len(commands))
        (out / 'result.json').write_text(json.dumps(result, indent=2))
        return result
    finally:
        (out / 'commands.json').write_text(json.dumps(commands, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cami', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.cami.resolve(), args.out.resolve()), indent=2))
