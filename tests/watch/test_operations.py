from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

from cami.product.watch.models import WatchSettings
from cami.product.watch.runtime import Operation


def test_operation_deadline_reaps_its_actual_subprocess(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    tools = tmp_path / 'tools'
    tools.mkdir()
    pid_file = tmp_path / 'owned-git.pid'
    wrapper = tools / 'git'
    wrapper.write_text(f'#!{sys.executable}\nimport os,time\n'
                       f'open({str(pid_file)!r},"w").write(str(os.getpid()))\n'
                       'time.sleep(60)\n')
    wrapper.chmod(0o700)
    monkeypatch.setenv('PATH', str(tools) + os.pathsep + os.environ['PATH'])
    settings = WatchSettings(canonical_repo=str(repo), state_base=str(tmp_path / 'state'),
                             operation_seconds=0.5)
    operation = Operation.start(settings, 'refresh')
    try:
        deadline = time.monotonic() + 5
        while operation.process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert operation.process.poll() is not None
        result = operation.finish()
        assert result.error is not None and result.error.code == 'watch_operation_timeout'
        owned_pid = int(pid_file.read_text())
        assert not Path(f'/proc/{owned_pid}').exists()
        assert not (tmp_path / 'state').exists()
    finally:
        if operation.process.poll() is None:
            operation.cancel()
            operation.process.wait(timeout=5)
        operation.output.close()
        operation.errors.close()


def test_cancelled_refresh_preserves_committed_product_head(tmp_path, monkeypatch):
    import json
    import sqlite3

    from cami.product.service import ProductMemory

    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    source = repo / 'api.py'
    source.write_text('def api():\n    return 1\n')
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    memory = ProductMemory(repo)
    initial = memory.refresh()
    before = memory.store.path.read_bytes()
    source.write_text('def api():\n    return 2\n')
    checkpoint = tmp_path / 'verified'
    # Pause at the actual final verification, after private transaction work but before COMMIT.
    script = f'''
import sys,time
from pathlib import Path
from cami.product.memory.adapters import HybridIndexPort
from cami.product.watch.worker import main
original = HybridIndexPort.verify
def verify(self,*args):
    original(self,*args)
    Path({str(checkpoint)!r}).write_text('verified')
    time.sleep(60)
HybridIndexPort.verify=verify
sys.argv=['worker','refresh']
main()
'''
    settings = WatchSettings(canonical_repo=str(repo), state_base=str(tmp_path / 'state'),
                             operation_seconds=1.0)
    result = subprocess.run([sys.executable, '-c', script],
                            input=settings.model_dump_json(), capture_output=True, text=True,
                            timeout=5)
    assert result.returncode == 0, result.stderr
    assert checkpoint.read_text() == 'verified'
    assert json.loads(result.stdout)['error']['code'] == 'watch_operation_timeout'
    assert memory.store.path.read_bytes() == before
    with sqlite3.connect(':memory:') as db:
        db.deserialize(before)
        assert db.execute('SELECT generation_id FROM product_head').fetchone()[0] == initial.memory_generation_id
        assert db.execute('SELECT count(*) FROM memory_generation').fetchone()[0] == 1
    recovered = memory.refresh()
    assert recovered.sequence == initial.sequence + 1
