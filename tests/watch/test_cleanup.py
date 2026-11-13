from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest

from cami.product.watch.control import Lease
from cami.product.watch.models import WatchSettings
from cami.product.watch.runtime import Operation, Watcher


@pytest.mark.parametrize('publication', ['write', 'flush', 'cancel', 'after_flush', 'exited', 'resists'])
def test_failed_start_reaps_child_and_preserves_error(tmp_path, monkeypatch, publication):
    real_popen = subprocess.Popen
    children = []
    streams = []
    checkpoint = tmp_path / 'ready'
    sentinel = real_popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    original = KeyboardInterrupt('cancel request')

    def spawn(*args, **kwargs):
        if publication == 'after_flush':
            code = ('import sys,time; from pathlib import Path; sys.stdin.buffer.read(); '
                    f'Path({str(checkpoint)!r}).touch(); time.sleep(60)')
        else:
            code = ('import os,time,signal; from pathlib import Path; '
                    + ('signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                       if publication == 'resists' else '') + 'os.close(0); '
                    f'Path({str(checkpoint)!r}).touch(); '
                    + ('' if publication == 'exited' else 'time.sleep(60)'))
        child = real_popen([sys.executable, '-c', code], **kwargs)
        children.append(child)
        streams.extend([child.stdin, kwargs['stdout'], kwargs['stderr']])
        if publication != 'after_flush':
            deadline = time.monotonic() + 5
            while not checkpoint.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert checkpoint.exists()
        if publication == 'exited':
            child.wait(timeout=5)
        if publication in ('cancel', 'after_flush'):
            stream = child.stdin

            class RequestStream:
                def write(self, data):
                    if publication == 'cancel':
                        raise original
                    return stream.write(data)

                def close(self):
                    closed = stream.closed
                    stream.close()
                    if closed:
                        raise OSError('secondary close failure')
                    if publication == 'cancel':
                        return
                    deadline = time.monotonic() + 5
                    while not checkpoint.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    assert checkpoint.exists()
                    raise original

            child.stdin = RequestStream()
        return child

    monkeypatch.setattr(subprocess, 'Popen', spawn)
    settings = WatchSettings(canonical_repo=str(tmp_path), state_base=str(tmp_path / 'state'),
                             excluded_paths=('x' * 20000,) if publication == 'write' else ())
    try:
        with pytest.raises((BrokenPipeError, KeyboardInterrupt)) as caught:
            Operation.start(settings, 'observe')
        if publication in ('cancel', 'after_flush'):
            assert caught.value is original
        child = children[0]
        # waitpid must find nothing left to reap, including an exited zombie.
        with pytest.raises(ChildProcessError):
            os.waitpid(child.pid, os.WNOHANG)
        assert not Path(f'/proc/{child.pid}').exists()
        assert all(stream.closed for stream in streams)
        assert sentinel.poll() is None
    finally:
        for child in [*children, sentinel]:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)


@pytest.mark.parametrize('replacement', [False, True])
@pytest.mark.parametrize('failure', ['publication', 'cancel', 'normal'])
def test_endpoint_cleanup_preserves_replacement(tmp_path, monkeypatch, replacement, failure):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    lease = Lease.open(repo, create=True)
    assert lease is not None and lease.acquire()
    unrelated = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    endpoint = None
    original = KeyboardInterrupt('cancel constructor') if failure == 'cancel' else OSError('publish failed')

    def replace(path):
        path.unlink()
        unrelated.bind(str(path))
        unrelated.listen(1)
        path.chmod(0o600)
        return path.lstat()

    def publish(session):
        nonlocal endpoint
        endpoint = Path(session.endpoint)
        if replacement:
            replace(endpoint)
        raise original

    if failure != 'normal':
        monkeypatch.setattr(lease, 'publish', publish)
    try:
        settings = WatchSettings(canonical_repo=str(repo), state_base=str(tmp_path / 'state'))
        if failure == 'normal':
            watcher = Watcher(lease, settings, 'json')
            endpoint = Path(watcher.session.endpoint)
            if replacement:
                replace(endpoint)
            watcher.stop('test_stop')
            watcher.run()
        else:
            with pytest.raises((OSError, KeyboardInterrupt)) as caught:
                Watcher(lease, settings, 'json')
            assert caught.value is original
        assert endpoint is not None
        if replacement:
            before = endpoint.lstat()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1)
                client.connect(str(endpoint))
                accepted, _ = unrelated.accept()
                accepted.close()
            assert endpoint.lstat() == before
        else:
            assert not endpoint.exists()
    finally:
        unrelated.close()
        if endpoint is not None:
            endpoint.unlink(missing_ok=True)
        lease.close()


@pytest.mark.parametrize('failure', ['cancel', 'error', 'timeout', 'exited'])
def test_analyzer_wait_failure_reaps_node(tmp_path, monkeypatch, failure):
    from cami.typescript_analyzer import TypeScriptAnalyzerError, analyze_typescript

    real_popen = subprocess.Popen
    children = []
    original = KeyboardInterrupt('cancel analyzer') if failure == 'cancel' else OSError('wait failed')

    def spawn(*args, **kwargs):
        child = real_popen(['node', '-e', 'setInterval(()=>{},1000);'], **kwargs)
        children.append(child)
        wait = child.wait
        if failure == 'exited':
            child.kill()
            wait(timeout=5)
        if failure != 'timeout':
            def interrupt(*args, **kwargs):
                child.wait = wait
                raise original
            child.wait = interrupt
        return child

    monkeypatch.setattr(subprocess, 'Popen', spawn)
    try:
        with pytest.raises((OSError, KeyboardInterrupt, TypeScriptAnalyzerError)) as caught:
            analyze_typescript({'api.ts': 'export function api() {}'}, timeout=0.05)
        if failure != 'timeout':
            assert caught.value is original
        else:
            assert isinstance(caught.value, TypeScriptAnalyzerError)
            assert isinstance(caught.value.__cause__, subprocess.TimeoutExpired)
        assert len(children) == 1
        child = children[0]
        with pytest.raises(ChildProcessError):
            os.waitpid(child.pid, os.WNOHANG)
        assert not Path(f'/proc/{child.pid}').exists()
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux subreaper and pidfd acceptance driver")
def test_watch_stop_reaps_real_node(tmp_path):
    driver = Path(__file__).with_name('node_cleanup_driver.py')
    result = subprocess.run([sys.executable, str(driver), '--cami',
                             str(Path(sys.executable).parent / 'cami'),
                             '--out', str(tmp_path / 'node-stop')],
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr


def test_unprovable_bound_endpoint_is_preserved(tmp_path, monkeypatch):
    from cami.product.watch import runtime

    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    lease = Lease.open(repo, create=True)
    assert lease is not None and lease.acquire()
    monkeypatch.chdir(tmp_path)
    endpoint = Path('unverifiable.sock')
    monkeypatch.setattr(runtime, 'prepare_endpoint', lambda session_id: endpoint)
    lstat = Path.lstat
    original = PermissionError('cannot establish endpoint ownership')

    def denied(path):
        if path == endpoint:
            raise original
        return lstat(path)

    monkeypatch.setattr(Path, 'lstat', denied)
    try:
        with pytest.raises(PermissionError) as caught:
            Watcher(lease, WatchSettings(canonical_repo=str(repo), state_base=str(tmp_path)), 'json')
        assert caught.value is original
        assert lstat(endpoint).st_ino > 0
    finally:
        endpoint.unlink(missing_ok=True)
        lease.close()
