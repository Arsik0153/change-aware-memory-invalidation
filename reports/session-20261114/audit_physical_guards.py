"""Inspect actual changed-input bytes and positive-control sources after a full run."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'integrations/opencode'))
from task_replay import inventory  # noqa: E402


def audit(root):
    protocol = json.loads((root / 'protocol.json').read_text())
    summary = json.loads((root / 'summary.json').read_text())
    design = protocol['rules']['design']
    if design not in {'full-cami-result-memory-heldout-v1', 'result-memory-ablation-development-v1'}:
        raise ValueError('unsupported registered design')
    if summary['terminal_attempts'] != protocol['rules']['attempts']:
        raise ValueError('complete schedule required')
    recorded = json.loads((root / 'guard-probes.json').read_text())['probes']
    sequence = protocol['runtime']['normalized']['sequence']
    rows = []
    for probe in recorded:
        rep, task = probe['repetition'], probe['task']
        condition = probe.get('condition', 'cami_replay')
        name = f'r{rep}-{condition}-{task}' if design.startswith('result-memory-ablation') else f'r{rep}-{task}'
        path = root / 'guard-probes' / name
        base = root / ('base-' + task)
        original, changed = inventory(base), inventory(path / 'changed-input')
        source = next(iter(sorted((base / 'src').rglob('*.py'))))
        relative = source.relative_to(base).as_posix()
        content = source.read_bytes() + b'\n# explicit changed-input rejection probe\n'
        expected = {**original, relative: {**original[relative], 'sha256': hashlib.sha256(content).hexdigest()}}
        if changed != expected or (path / 'changed-input' / relative).read_bytes() != content:
            raise ValueError('physical changed-input probe differs')
        output_absent = not (path / 'must-not-exist').exists()
        if output_absent != probe['output_absent']:
            raise ValueError('rejected output existence differs from receipt')
        control = path / 'unchanged-control'
        control_verified = False
        if probe['control_status'] == 'candidate_requires_grading':
            stage = sequence.index(task) + 1
            learned = root / 'trials' / f'r{rep}-{condition}-s{stage}' / 'candidate/src'
            expected_control = {name: row for name, row in original.items() if not name.startswith('src/')}
            expected_control.update({'src/' + name: row for name, row in inventory(learned).items()})
            if inventory(control) != expected_control:
                raise ValueError('positive control differs from learned source and original non-source files')
            control_verified = True
        elif control.exists():
            raise ValueError('unexpected positive-control output')
        rows.append({'repetition': rep, 'condition': condition, 'task': task,
                     'physical_changed_input_verified': True, 'rejected_output_absent': output_absent,
                     'positive_control_verified': control_verified, 'recorded_status': probe['status']})
    expected_count = 20 if design.startswith('result-memory-ablation') else 10
    if len(rows) != expected_count:
        raise ValueError('physical probe count differs')
    return {'status': 'verified_physical_artifacts', 'rows': rows,
            'all_guards_passed': all(r['rejected_output_absent'] and r['positive_control_verified'] and r['recorded_status'] == 'miss' for r in rows),
            'scope': 'Post-run correctness inspection; no model calls, timing claim, replaced primary attempt or changed eligibility.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('out', type=Path)
    args = parser.parse_args()
    with args.out.open('x') as stream:
        json.dump(audit(args.run), stream, indent=2, sort_keys=True)
        stream.write('\n')
