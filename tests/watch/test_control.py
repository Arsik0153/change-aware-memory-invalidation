from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

import pytest

from cami.product.watch.control import Lease, WatchControlError


def command(repo, *args, env=None):
    return subprocess.run([sys.executable, '-m', 'cami.cli', 'watch', *args,
                           '--repo', str(repo), '--format', 'json'],
                          env=env, capture_output=True, text=True, timeout=15)


def wait_status(repo, predicate):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = command(repo, 'status')
        if result.stdout:
            value = json.loads(result.stdout)
            if predicate(value):
                return value
        time.sleep(0.05)
    raise AssertionError('watcher status deadline')


@pytest.fixture
def running(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (repo / 'api.py').write_text('def api():\n    return 1\n')
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    output = (tmp_path / 'watch.stdout').open('wb')
    errors = (tmp_path / 'watch.stderr').open('wb')
    process = subprocess.Popen([sys.executable, '-m', 'cami.cli', 'watch', '--repo', str(repo),
                                '--format', 'json'], stdout=output, stderr=errors)
    try:
        status = wait_status(repo, lambda s: s['latest_successful'] is not None)
        yield repo, process, status, tmp_path
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGCONT)
            process.terminate()
        process.wait(timeout=15)
        output.close()
        errors.close()


def test_foreground_lifetime_and_pinned_restart(running):
    repo, process, status, tmp_path = running
    duplicate = command(repo)
    assert duplicate.returncode == 0
    assert json.loads(duplicate.stdout)['session_id'] == status['session_id']
    other = command(repo, env={**os.environ, 'XDG_STATE_HOME': str(tmp_path / 'other-state')})
    assert other.returncode == 2
    assert json.loads(other.stdout)['reason'] == 'watch_configuration_conflict'
    stopped = command(repo, 'stop')
    assert stopped.returncode == 0, stopped.stderr + stopped.stdout
    assert json.loads(stopped.stdout)['lifecycle'] == 'stopped'
    assert process.wait(timeout=10) == 0
    assert command(repo, 'stop').returncode == 0
    replacement = subprocess.Popen([sys.executable, '-m', 'cami.cli', 'watch', 'restart',
                                    '--repo', str(repo), '--format', 'json'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        restarted = wait_status(repo, lambda s: s['latest_successful'] is not None
                                and s['session_id'] != status['session_id'])
        assert restarted['session_id'] != status['session_id']
        replacement.send_signal(signal.SIGINT)
        assert replacement.wait(timeout=10) == 0
    finally:
        if replacement.poll() is None:
            replacement.terminate()
        replacement.wait(timeout=10)


@pytest.mark.parametrize('damage', ['missing', 'replace', 'symlink', 'fifo', 'bytes'])
def test_established_lifetime_lease_is_never_recreated_or_quarantined(running, damage):
    repo, process, _, _ = running
    lease = Lease.open(repo)
    assert lease is not None
    path = lease.directory / 'lease'
    identity = (lease.directory / 'identity.json').read_bytes()
    held_inode = os.fstat(lease.fd).st_ino
    lease.close()
    if damage == 'bytes':
        path.write_bytes(b'damaged')
    else:
        path.unlink()
        if damage == 'replace':
            path.touch(mode=0o600)
        elif damage == 'symlink':
            path.symlink_to('identity.json')
        elif damage == 'fifo':
            os.mkfifo(path, 0o600)
    status = command(repo, 'status')
    assert status.returncode == 4 and json.loads(status.stdout)['lifecycle'] == 'unknown'
    second = command(repo)
    assert second.returncode == 4
    assert (path.parent / 'identity.json').read_bytes() == identity
    if damage == 'missing':
        assert not path.exists()
    elif damage == 'replace':
        assert path.stat().st_ino != held_inode
    assert process.wait(timeout=15) == 4


@pytest.mark.parametrize('damage', ['missing', 'fifo', 'symlink', 'oversized', 'malformed', 'stale-pid'])
def test_discovery_damage_cannot_authorize_control_or_pid_signals(running, damage):
    repo, process, _, _ = running
    lease = Lease.open(repo)
    assert lease is not None
    path = lease.directory / 'session.json'
    session = lease.session()
    lease.close()
    process.send_signal(signal.SIGSTOP)
    path.unlink()
    if damage == 'fifo':
        os.mkfifo(path, 0o600)
    elif damage == 'symlink':
        path.symlink_to('identity.json')
    elif damage == 'oversized':
        path.write_bytes(b'x' * 20000)
    elif damage == 'malformed':
        path.write_bytes(b'{}')
    elif damage == 'stale-pid':
        path.write_text(session.model_copy(update={'pid_hint': os.getpid()}).model_dump_json())
        path.chmod(0o600)
    start = time.monotonic()
    result = command(repo, 'stop')
    assert result.returncode == 4
    assert json.loads(result.stdout)['lifecycle'] == 'unknown'
    assert time.monotonic() - start < 4
    # Runtime itself fails closed if discovery is stolen; this process remains alive.
    assert os.getpid() > 0
    process.send_signal(signal.SIGCONT)
    assert process.wait(timeout=15) == 4


def test_unrelated_socket_and_capability_cannot_control_active_session(running):
    repo, process, status, _ = running
    lease = Lease.open(repo)
    assert lease is not None
    session = lease.session()
    before = Path(session.endpoint).lstat()
    wrong = dict(schema_version=1, session_id=session.session_id, capability='0' * 64,
                 nonce='1' * 32, action='stop')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(1)
        client.connect(session.endpoint)
        client.sendall(json.dumps(wrong).encode() + b'\n')
        assert client.recv(1) == b''
    assert command(repo, 'status').returncode == 0 and process.poll() is None
    process.send_signal(signal.SIGSTOP)
    Path(session.endpoint).unlink()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as unrelated:
        unrelated.bind(session.endpoint)
        Path(session.endpoint).chmod(0o600)
        assert Path(session.endpoint).lstat().st_ino != before.st_ino
        result = command(repo, 'stop')
        assert result.returncode == 4 and json.loads(result.stdout)['lifecycle'] == 'unknown'
    lease.close()
    process.send_signal(signal.SIGCONT)
    assert process.wait(timeout=15) == 4


def test_initial_lease_installation_crash_fails_closed(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    directory = repo / '.git/cami-watch'
    directory.mkdir(mode=0o700)
    with pytest.raises((WatchControlError, OSError)):
        Lease.open(repo, create=True)
    assert not (directory / 'lease').exists()
