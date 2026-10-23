"""Real watch stop must reap its Node sidecar before confirming stopped.

Run outside the checkout against either development or relocated installed CAMI.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import time


def run(cami, out, expect_leak=False):
    out.mkdir(parents=True)
    # Adopt any leaked descendant so the failing-before proof can also reap it.
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    repo = out / 'repo'
    repo.mkdir()
    (repo / 'api.ts').write_text('export function api(x: string) { return x; }\n')
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    tools = out / 'tools'
    tools.mkdir()
    node = shutil.which('node')
    assert node is not None
    record = out / 'owned-node.json'
    script = ('require("fs").writeFileSync(' + json.dumps(str(record))
              + ', JSON.stringify({pid:process.pid,ppid:process.ppid}));setInterval(()=>{},1000);')
    wrapper = tools / 'node'
    wrapper.write_text(f'#!{sys.executable}\nimport os,sys\n'
                       f'node={node!r}\n'
                       'if sys.argv[1:]==["--version"]: os.execv(node,[node,"--version"])\n'
                       f'os.execv(node,[node,"-e",{script!r},"--",*sys.argv[1:]])\n')
    wrapper.chmod(0o700)
    state = out / 'state'
    env = {**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH'],
           'XDG_STATE_HOME': str(state), 'PYTHONDONTWRITEBYTECODE': '1'}
    env.pop('PYTHONPATH', None)
    streams = [(out / 'watch.stdout').open('wb'), (out / 'watch.stderr').open('wb')]
    watcher = subprocess.Popen([str(cami), 'watch', '--repo', str(repo), '--format', 'json'],
                               env=env, stdout=streams[0], stderr=streams[1])
    sentinel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    node_fd = None
    node_pid = None
    commands = []

    def control(action):
        argv = [str(cami), 'watch', action, '--repo', str(repo), '--format', 'json']
        result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=15)
        commands.append(dict(argv=argv, exit=result.returncode, stdout=result.stdout,
                             stderr=result.stderr))
        assert result.returncode == 0, commands[-1]
        return json.loads(result.stdout)

    def heads():
        result = {}
        for path in state.rglob('memory.sqlite3'):
            with sqlite3.connect(':memory:') as db:
                db.deserialize(path.read_bytes())
                result[str(path)] = db.execute('SELECT generation_id FROM product_head').fetchall()
        return result

    try:
        deadline = time.monotonic() + 20
        while not record.exists() and time.monotonic() < deadline:
            assert watcher.poll() is None
            time.sleep(0.02)
        owned = json.loads(record.read_text())
        node_pid = owned['pid']
        node_fd = os.pidfd_open(node_pid)
        assert Path(f'/proc/{node_pid}/exe').resolve() == Path(node).resolve()
        status = control('status')
        start = time.monotonic()
        stop = control('stop')
        # Inspect at the public confirmation, before waiting for the controller.
        alive_at_stop = Path(f'/proc/{node_pid}').exists()
        assert watcher.wait(timeout=5) == 0
        before = heads()
        time.sleep(0.1)
        assert heads() == before
        result = dict(status_phase=status['phase'], stop_lifecycle=stop['lifecycle'],
                      stop_seconds=time.monotonic() - start, watcher_exit=watcher.returncode,
                      actual_node=owned, node_alive_at_confirmed_stop=alive_at_stop,
                      node_alive_after_watcher_exit=Path(f'/proc/{node_pid}').exists(),
                      unrelated_sentinel_alive=sentinel.poll() is None,
                      no_later_head_publication=True, persisted_heads=before)
        (out / 'result.json').write_text(json.dumps(result, indent=2))
        assert stop['lifecycle'] == 'stopped' and result['unrelated_sentinel_alive']
        assert alive_at_stop == expect_leak, result
        assert result['node_alive_after_watcher_exit'] == expect_leak, result
        return result
    finally:
        if watcher.poll() is None:
            watcher.terminate()
        watcher.wait(timeout=15)
        if node_fd is not None:
            try:
                signal.pidfd_send_signal(node_fd, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.close(node_fd)
            try:
                os.waitpid(node_pid, 0)
            except ChildProcessError:
                pass
            assert not Path(f'/proc/{node_pid}').exists()
        sentinel.terminate()
        sentinel.wait(timeout=5)
        for stream in streams:
            stream.close()
        (out / 'commands.json').write_text(json.dumps(commands, indent=2))
        (out / 'cleanup.json').write_text(json.dumps(dict(watcher_reaped=True,
                                                          node_gone=node_pid is not None and
                                                          not Path(f'/proc/{node_pid}').exists(),
                                                          sentinel_reaped=True), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cami', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--expect-leak', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run(args.cami.resolve(), args.out.resolve(), args.expect_leak), indent=2))
