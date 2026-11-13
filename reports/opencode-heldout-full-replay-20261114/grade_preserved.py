"""Grade preserved failed-trial sources after all primary attempts terminate.

Run inside the controller with the immutable runtime-v14 volume mounted at its
original path. These diagnostic grades never replace primary trial outcomes.
"""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path('/var/lib/docker/volumes/cami-local-study-20261113/_data/runtime-v14')
sys.path.insert(0, str(ROOT / 'scripts/opencode_benchmark/experiments'))
import full_replay_study as frozen  # noqa: E402


def main():
    run = ROOT / 'runs/full-model'
    summary = frozen.read(run / 'summary.json')
    if summary['terminal_attempts'] != 80:
        raise ValueError('finish all primary attempts first')
    terminals = {p.parent.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (run / 'trials').glob('*/terminal.json')}
    if len(terminals) != 80:
        raise ValueError('all80 primary terminals required')
    protocol = frozen.read(run / 'protocol.json')
    spec = protocol['runtime']
    if protocol['pins'] != frozen.pins():
        raise ValueError('frozen implementation differs')
    report = {'scope': 'Post-run forensic quality only. No primary outcome, timing, telemetry, cache or decision is changed.',
              'model_calls': 0, 'trials': []}
    destination = run / 'diagnostics/forensic-quality.json'
    if destination.exists():
        raise ValueError('diagnostic already exists; no replacement')
    for trial_id in ('r3-static-s1', 'r3-static-s3'):
        record = frozen.read(run / 'trials' / trial_id / 'terminal.json')
        if record['status'] != 'failed' or 'quality' in record:
            raise ValueError('expected original ungraded primary failure')
        task = next(t for t in spec['normalized']['tasks'] if t['id'] == record['trial']['task'])
        candidate = run / 'diagnostics' / (trial_id + '-source')
        capture = frozen.read(candidate / 'source-patch.json')
        if frozen.inventory(candidate / 'src') != capture['source_files']:
            raise ValueError('preserved candidate changed')
        frozen.validate_source_scope(spec, run / ('base-' + task['id']), candidate)
        baseline = frozen.read(run / 'baselines' / task['id'] / 'allowance.json')
        quality = frozen.grade(spec, task, candidate,
                               run / 'diagnostics' / (trial_id + '-evaluation'),
                               allowance=baseline['outcomes'])
        if quality['source_files'] != frozen.file_hashes(candidate / 'src'):
            raise ValueError('graded source differs')
        strict_pass = quality['status'] == 'pass' and all(
            not outcome['exit_code'] and not outcome['counts']['failed']
            and not outcome['counts']['errors'] and outcome['counts']['executed']
            for outcome in quality['outcomes'].values())
        report['trials'].append({'trial': trial_id, 'primary_status': 'failed',
            'primary_terminal_sha256': terminals[trial_id], 'forensic_quality': 'pass' if strict_pass else 'fail',
            'source_files': quality['source_files'],
            'outcomes': quality['outcomes']})
    if terminals != {p.parent.name: hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (run / 'trials').glob('*/terminal.json')}:
        raise ValueError('primary terminals changed')
    report['primary_terminal_hashes_unchanged'] = True
    frozen.write(destination, report)
    print(json.dumps({'scope': report['scope'], 'model_calls': 0,
                      'results': [(r['trial'], r['forensic_quality']) for r in report['trials']]}))


if __name__ == '__main__':
    main()
