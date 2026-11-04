from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATHS = ('src', 'integrations', 'tests', 'scripts', 'schemas', 'docker', 'pyproject.toml',
                'uv.lock', '.python-version', 'conftest.py', 'pytest.ini', 'setup.cfg',
                'tox.ini', 'mypy.ini', '.mypy.ini', 'ruff.toml', '.ruff.toml', '.gitignore')


def source_snapshot(root: Path) -> dict[str, object]:
    def git(*args: str) -> bytes:
        return subprocess.check_output(['git', '-C', str(root), *args])

    paths = git('ls-files', '-z', '--cached', '--others', '--exclude-standard',
                '--', *SOURCE_PATHS).split(b'\0')
    files: dict[str, str | None] = {}
    for raw_path in sorted(set(paths) - {b''}):
        name = os.fsdecode(raw_path)
        path = root / name
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    encoded = json.dumps(files, sort_keys=True, ensure_ascii=True).encode()
    return {
        'git_head': git('rev-parse', 'HEAD').decode().strip(),
        'source_status': git('status', '--porcelain=v1', '--untracked-files=all',
                             '--', *SOURCE_PATHS).decode(errors='replace'),
        'scope': list(SOURCE_PATHS),
        'files': files,
        'sha256': hashlib.sha256(encoded).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Run checks into a new immutable evidence directory.')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    before = source_snapshot(ROOT)
    args.out.mkdir(parents=True, exist_ok=False)
    results = []
    summary: dict[str, object] = {
        'schema_version': 2, 'started_at': datetime.now(timezone.utc).isoformat(),
        'python': sys.version, 'platform': platform.platform(),
        'docker_image': os.environ.get('CAMI_TEST_IMAGE'),
        'source_before': before, 'checks': results, 'status': 'running',
    }

    def save() -> None:
        (args.out / 'checks.json').write_text(json.dumps(summary, indent=2) + '\n')

    save()
    for name, arguments in [('pytest', ['pytest', '-q']), ('ruff', ['ruff', 'check', '.']),
                            ('mypy', ['mypy', 'src/cami'])]:
        command = [sys.executable, '-m', *arguments]
        started = time.perf_counter()
        result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, check=False)
        log = result.stdout.encode('utf-8')
        (args.out / f'{name}.log').write_bytes(log)
        results.append({'command': command, 'exit_code': result.returncode,
                        'wall_seconds': time.perf_counter() - started, 'log': f'{name}.log',
                        'log_sha256': hashlib.sha256(log).hexdigest()})
        print(result.stdout, end='', flush=True)
        save()
    after = source_snapshot(ROOT)
    unchanged = before == after
    passed = unchanged and all(row['exit_code'] == 0 for row in results)
    summary.update({'recorded_at': datetime.now(timezone.utc).isoformat(),
                    'source_after': after, 'source_snapshots_match': unchanged,
                    'status': 'passed' if passed else 'failed'})
    save()
    if not unchanged:
        print('Source changed during verification; rerun against stable inputs.', file=sys.stderr)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
