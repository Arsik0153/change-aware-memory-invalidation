from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description='Run checks into a new immutable evidence directory.')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    results = []
    for name, arguments in [('pytest', ['pytest', '-q']), ('ruff', ['ruff', 'check', '.']),
                            ('mypy', ['mypy', 'src/cami'])]:
        command = [sys.executable, '-m', *arguments]
        started = time.perf_counter()
        result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, check=False)
        (args.out / f'{name}.log').write_text(result.stdout)
        results.append({'command': command, 'exit_code': result.returncode,
                        'wall_seconds': time.perf_counter() - started, 'log': f'{name}.log'})
        print(result.stdout, end='', flush=True)
        summary = {'schema_version': 1, 'recorded_at': datetime.now(timezone.utc).isoformat(),
                   'python': sys.version, 'platform': platform.platform(),
                   'docker_image': os.environ.get('CAMI_TEST_IMAGE'), 'checks': results}
        (args.out / 'checks.json').write_text(json.dumps(summary, indent=2) + '\n')
    return 0 if all(row['exit_code'] == 0 for row in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
