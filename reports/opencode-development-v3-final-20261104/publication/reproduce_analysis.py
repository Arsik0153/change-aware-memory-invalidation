"""Verify the unpacked public v3 record and rerun only its offline analyses."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

RUN = 'runs/opencode-development-v3-20261104'


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
    out.mkdir(exist_ok=False)
    started = time.monotonic()
    run = root / RUN
    binding = read(run / 'run.json')
    assert sha(run / 'frozen-study.json') == binding['study_sha256']
    # Preserve original raw caveat. Only this derived path binding is changed.
    timing = read(run / 'timing-caveats.json')
    original_root = Path('/root/apps/change-aware-memory-invalidation')
    for row in timing['caveats']:
        old = Path(row['evidence_path'])
        evidence = root / old.relative_to(original_root)
        assert sha(evidence) == row['evidence_sha256']
        row['evidence_path'] = str(evidence)
    (out / 'timing-caveats-relocated.json').write_text(json.dumps(timing, indent=2) + '\n')
    commands = [
        [sys.executable, str(root / 'scripts/opencode_benchmark/analysis/aggregate_study.py'),
         '--run', str(run), '--protocol', str(root / 'reports/opencode-study-design-20261104/protocol.json'),
         '--study', str(run / 'frozen-study.json'), '--study-sha256', binding['study_sha256'],
         '--timing-caveats', str(out / 'timing-caveats-relocated.json'), '--out', str(out / 'aggregate')],
        [sys.executable, str(root / 'scripts/opencode_benchmark/analysis/summarize_terminal_staleness.py'),
         '--run', str(run), '--analyzer', str(root / 'scripts/analyze_opencode_staleness.py'),
         '--catalog', str(run / 'namespaces/r1-static/memory/prepared/catalog.json'),
         '--origin', str(root / 'runs/opencode-development-v3-staleness-20261104/origin-and-stage1'),
         '--stage1', str(root / 'runs/opencode-development-v3-staleness-20261104/origin-and-stage1'),
         '--stage3', str(root / 'runs/opencode-development-v3-staleness-20261104/stage3'),
         '--out', str(out / 'staleness')],
    ]
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONDONTWRITEBYTECODE': '1', 'LC_ALL': 'C.UTF-8'}
    results = []
    for index, command in enumerate(commands):
        result = subprocess.run(command, env=env, capture_output=True, timeout=120)
        (out / f'command-{index}.stdout.txt').write_bytes(result.stdout)
        (out / f'command-{index}.stderr.txt').write_bytes(result.stderr)
        results.append({'argv': command, 'returncode': result.returncode})
        assert result.returncode == 0, f'Offline analysis {index} failed; diagnostics retained'
    original = read(root / 'runs/opencode-development-v3-final-analysis-20261104/report.json')
    rebuilt = read(out / 'aggregate/report.json')
    assert rebuilt['summary'] == original['summary']
    assert rebuilt['integrity']['terminal_artifact_hashes_verified'] == original['integrity']['terminal_artifact_hashes_verified']
    assert rebuilt['integrity']['terminal_sha256'] == original['integrity']['terminal_sha256']
    before = read(root / 'runs/opencode-development-v3-final-staleness-20261104/report.json')
    after = read(out / 'staleness/report.json')
    for key in ('counts', 'complete_36', 'unsupported_trial_ids', 'unsupported_call_count', 'all_assessed_evidence_supported'):
        assert before[key] == after[key], key
    report = {'status': 'passed', 'offline_analysis_commands': results,
              'aggregate_summary_exact': True, 'terminal_hashes_and_coverage_exact': True,
              'staleness_counts_coverage_exact': True,
              'timing_caveat': 'Original untouched; derived evidence-path-only rebinding with matching content SHA for relocation.',
              'source_or_model_execution': False, 'model_calls': 0, 'docker_calls': 0, 'network_calls': 0,
              'wall_seconds': time.monotonic() - started,
              'scope': 'Publication/evaluation overhead only, not trial cost; absolute output paths differ.'}
    (out / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'offline_analysis_commands'}))


if __name__ == '__main__':
    main()
