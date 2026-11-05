"""Verify the extracted v5 public record and reproduce its unchanged offline aggregate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import stat
import subprocess
import sys
import time

RUN = 'runs/opencode-development-v5-20261104'
ANALYSIS = 'runs/opencode-development-v5-final-analysis-20261105'
PROTOCOL = 'reports/opencode-study-design-v5-20261104/protocol.json'
STALENESS = 'runs/opencode-development-v5-final-staleness-20261105'


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True, help='Owned extracted public-evidence root')
    parser.add_argument('--out', type=Path, required=True, help='New separate analysis output')
    args = parser.parse_args()
    root, out = args.root.absolute(), args.out.absolute()
    assert not root.is_relative_to(out) and not out.is_relative_to(root)
    out.mkdir(exist_ok=False)
    started = time.monotonic()
    cpu_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    inventory = read(root / 'PUBLICATION-MANIFEST.json')['files']
    for name, expected in inventory.items():
        relative = Path(name)
        assert not relative.is_absolute() and '..' not in relative.parts
        path = root / relative
        assert not any(x.is_symlink() for x in [path, *path.parents])
        observed = path.lstat()
        assert stat.S_ISREG(observed.st_mode) and observed.st_nlink == 1
        assert sha(path) == expected['sha256'] and observed.st_size == expected['size']
        assert stat.S_IMODE(observed.st_mode) == expected['mode']
    run = root / RUN
    binding = read(run / 'run.json')
    assert sha(run / 'frozen-study.json') == binding['study_sha256']
    command = [sys.executable, str(root / 'scripts/opencode_benchmark/analysis/aggregate_study.py'),
               '--run', str(run), '--protocol', str(root / PROTOCOL),
               '--study', str(run / 'frozen-study.json'), '--study-sha256', binding['study_sha256'],
               '--out', str(out / 'aggregate')]
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
           'PYTHONDONTWRITEBYTECODE': '1', 'LC_ALL': 'C.UTF-8'}
    result = subprocess.run(command, env=env, capture_output=True, timeout=120)
    (out / 'command.stdout.txt').write_bytes(result.stdout)
    (out / 'command.stderr.txt').write_bytes(result.stderr)
    assert result.returncode == 0, 'Offline aggregate failed; diagnostics preserved'
    original = read(root / ANALYSIS / 'report.json')
    rebuilt = read(out / 'aggregate/report.json')
    assert {k: v for k, v in rebuilt.items() if k != 'run'} == {
        k: v for k, v in original.items() if k != 'run'}
    for name in ['trials.csv', 'paired.csv', 'blocks.csv']:
        assert (out / 'aggregate' / name).read_bytes() == (root / ANALYSIS / name).read_bytes()
    failed = [r for r in rebuilt['trials'] if r['status'] != 'passed']
    assert len(failed) == 1 and failed[0]['id'] == 'r3-static-s1'
    assert failed[0]['quality'] == 'pass' and failed[0]['session_status'] == 'failed'
    assert failed[0]['runtime_manifest_status'] == 'passed'
    assert failed[0]['runtime_passed_controller_admission_failed']
    assert len(rebuilt['trials']) == 36
    stale_command = [sys.executable, str(root / 'scripts/opencode_benchmark/analysis/summarize_literal_staleness.py'),
                     '--run', str(run), '--catalog', str(run / 'namespaces/r1-static/memory/prepared/catalog.json'),
                     '--origin', str(root / 'runs/opencode-development-v3-staleness-20261104/origin-and-stage1'),
                     '--stage1', str(root / 'runs/opencode-development-v3-staleness-20261104/origin-and-stage1'),
                     '--stage3', str(root / 'runs/opencode-development-v3-staleness-20261104/stage3'),
                     '--controls', str(root / 'scripts/opencode_benchmark/analysis/summarize_terminal_staleness.py'),
                     '--analyzer', str(root / 'scripts/analyze_opencode_staleness.py'),
                     '--out', str(out / 'staleness')]
    stale_result = subprocess.run(stale_command, env=env, capture_output=True, timeout=120)
    (out / 'staleness.stdout.txt').write_bytes(stale_result.stdout)
    (out / 'staleness.stderr.txt').write_bytes(stale_result.stderr)
    assert stale_result.returncode == 0, 'Offline staleness replay failed; diagnostics preserved'
    stale_before, stale_after = read(root / STALENESS / 'report.json'), read(out / 'staleness/report.json')
    for key in ['counts', 'complete_36', 'terminal_snapshot_ids', 'unassessed_trial_ids',
                'unsupported_call_count', 'unsupported_call_count_complete', 'all_assessed_evidence_supported']:
        assert stale_before[key] == stale_after[key], key
    cpu_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    report = {'status': 'passed', 'argv': command, 'returncode': result.returncode,
              'verified_archive_files': len(inventory),
              'aggregate_exact_except_relocated_run_path': True, 'three_csv_files_byte_exact': True,
              'all_36_terminal_hashes_and_artifact_coverage_exact': True,
              'staleness_counts_coverage_exact': True,
              'staleness_argv': stale_command,
              'original_failed_trial_preserved': 'r3-static-s1',
              'original_quality_pass_count': 36, 'original_operational_pass_count': 35,
              'primary_superiority': rebuilt['summary']['primary_superiority'],
              'model_calls': 0, 'docker_calls': 0, 'network_calls': 0, 'target_source_execution': False,
              'wall_seconds': time.monotonic() - started,
              'cpu_seconds_children': cpu_after.ru_utime + cpu_after.ru_stime - cpu_before.ru_utime - cpu_before.ru_stime,
              'scope': 'Offline publication/evaluation overhead, never trial cost. Only existing analysis code executed.'}
    (out / 'verification.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'argv'}))


if __name__ == '__main__':
    main()
