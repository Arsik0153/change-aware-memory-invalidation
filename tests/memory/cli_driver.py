"""Literal acceptance scenario. Run with Python from an installed CAMI environment."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BASELINE = 'def create_user(name: str) -> str:\n    return name\n'
BODY = 'def create_user(name: str) -> str:\n    return "user"\n'
SIGNATURE = 'def create_user(name: str, enabled: bool = True) -> str:\n    return name\n'
PARSE = 'def create_user(:\n'
AMBIGUITY = BASELINE + '\n' + BASELINE
SYMBOL = 'src/api.py:create_user'
EXPECTED_SIGNATURE = {
    'format': 'python.ast-signature/1',
    'parameters': [{'name': 'name', 'kind': 'positional_or_keyword',
                    'annotation': "Name(id='str', ctx=Load())", 'default': None}],
    'returns': "Name(id='str', ctx=Load())", 'decorators': [], 'type_parameters': [],
    'is_async': False,
}


def run(out: Path) -> dict:
    out.mkdir(parents=True)
    repo = out / 'repo'
    repo.mkdir()
    (repo / 'src').mkdir()
    path = repo / 'src/api.py'
    path.write_text(BASELINE)
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    state = out / 'state'
    environment = {**os.environ, 'XDG_STATE_HOME': str(state)}
    commands = []

    def cli(label, *args, expected_exit=0):
        command = [sys.executable, '-m', 'cami.cli', 'memory', *args,
                   '--repo', str(repo), '--format', 'json']
        process = subprocess.run(command, capture_output=True, text=True, env=environment)
        (out / f'{label}.stdout.json').write_text(process.stdout)
        (out / f'{label}.stderr.txt').write_text(process.stderr)
        commands.append(dict(label=label, command=command, exit_code=process.returncode))
        (out / 'commands.json').write_text(json.dumps(commands, indent=2))
        assert process.returncode == expected_exit, (label, process.returncode, process.stderr)
        return json.loads(process.stdout) if process.stdout else None

    context = cli('origin', 'context', SYMBOL)
    assert context['code'][0]['signature'] == EXPECTED_SIGNATURE
    origin = out / 'origin.stdout.json'
    ids = {}
    for kind in ('symbol_exists', 'signature_equals', 'note'):
        extra = ['--note-key', 'return-contract', '--text', 'Returns the input name unchanged.'] \
            if kind == 'note' else []
        receipt = cli(f'remember-{kind}', 'remember', kind, SYMBOL, '--from-context', str(origin),
                      '--request-id', f'initial-{kind}', *extra)
        ids[kind] = receipt['memory_id']
        duplicate = cli(f'retry-{kind}', 'remember', kind, SYMBOL, '--from-context', str(origin),
                        '--request-id', f'initial-{kind}', *extra)
        assert duplicate == receipt
    initial = cli('initial', 'context', SYMBOL)
    checks = {x['record']['payload']['type']: x['state']['check'] for x in initial['facts']}
    assert set(checks) == {'symbol_exists', 'signature_equals'}
    assert all(c['verdict'] == 'supported' for c in checks.values())
    assert len(initial['notes']) == 1 and not initial['withheld']
    assert initial['notes'][0]['state']['label'] == 'manual_assertion'
    stable = cli('no-change', 'context', SYMBOL)
    assert stable['memory_generation_id'] == initial['memory_generation_id']
    assert stable['facts'] == initial['facts']

    phases = [
        ('unrelated', BASELINE, {'symbol_exists': 'fact', 'signature_equals': 'fact'}, False),
        ('body', BODY, {'symbol_exists': 'fact', 'signature_equals': 'fact'}, True),
        ('signature', SIGNATURE, {'symbol_exists': 'fact',
                                 'signature_equals': 'signature_mismatch'}, True),
        ('delete', None, {'symbol_exists': 'subject_absent',
                          'signature_equals': 'subject_absent'}, True),
        ('parse', PARSE, {'symbol_exists': 'parse_error', 'signature_equals': 'parse_error'}, True),
        ('ambiguity', AMBIGUITY, {'symbol_exists': 'ambiguous_binding',
                                 'signature_equals': 'ambiguous_binding'}, True),
        ('revert', BASELINE, {'symbol_exists': 'fact', 'signature_equals': 'fact'}, True),
    ]
    for phase, source, expected, note_withheld in phases:
        if source is None:
            path.unlink()
        else:
            path.write_text(source)
        if phase == 'unrelated':
            (repo / 'src/other.py').write_text('def other():\n    return 2\n')
        result = cli(phase, 'context', SYMBOL)
        actual = {x['record']['payload']['type']: 'fact' for x in result['facts']}
        actual.update({x['record']['payload']['type']: x['reason'] for x in result['withheld']
                       if x['record']['payload']['type'] != 'note'})
        assert actual == expected, (phase, actual)
        assert bool(result['notes']) is not note_withheld, phase
        if note_withheld:
            note = next(x for x in result['withheld'] if x['record']['payload']['type'] == 'note')
            assert note['reason'] == 'manual_review_required'
        if phase in ('unrelated', 'body'):
            for fact in result['facts']:
                assert fact['state']['type'] == 'carried'
                assert fact['state']['check'] == checks[fact['record']['payload']['type']]
        if phase == 'body':
            old_hash = hashlib.sha256(BASELINE.encode()).hexdigest()
            raw = state / 'cami/repos' / context['index']['worktree_key'] / 'source-objects' / old_hash
            assert raw.read_bytes() == BASELINE.encode()
        if phase == 'revert':
            assert all(f['state']['type'] == 'checked' for f in result['facts'])
            assert all(f['state']['check']['check_id'] != checks[f['record']['payload']['type']]
                       ['check_id'] for f in result['facts'])
    updated = cli('note-review', 'update', ids['note'], '--if-revision', '1',
                  '--from-context', str(out / 'revert.stdout.json'), '--request-id', 'review-note',
                  '--text', 'Reviewed against the restored source.')
    assert updated['revision'] == 2
    reviewed = cli('reviewed', 'context', SYMBOL)
    assert len(reviewed['notes']) == 1 and not reviewed['withheld']
    assert reviewed['notes'][0]['state']['label'] == 'manual_assertion'
    history = cli('signature-history', 'history', ids['signature_equals'])
    assert [c['reason'] for c in history['checks']] == [
        'predicate_matches', 'signature_mismatch', 'subject_absent', 'parse_error',
        'ambiguous_binding', 'predicate_matches']
    assert len(history['revisions']) == 1
    note_history = cli('note-history', 'history', ids['note'])
    assert len(note_history['revisions']) == 2 and not note_history['checks']
    summary = dict(status='passed', phases=['initial', *[p[0] for p in phases], 'explicit-note-review'],
                   commands=len(commands), ids=ids, languages=['python'], hybrid_driver='hybrid_cli_driver.py')
    (out / 'result.json').write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    print(json.dumps(run(parser.parse_args().out.resolve()), indent=2))
