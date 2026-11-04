"""Reusable bounded local OpenCode smoke utilities; credential bodies never logged."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import secrets
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request

BINARY = Path("/opt/opencode")
EXPECTED_BINARY_SHA = "8d060e1d2fbb9bb44cf09ae6ed1f3f6a7cff070b5227e2f90970132b23a92050"


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def child_cpu():
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def tree_bytes(path):
    return sum(p.stat().st_size for p in path.rglob("*") if not p.is_symlink() and p.is_file())


def redact(text):
    text = re.sub(r"(?<![A-Za-z0-9._%+-])(?=[A-Za-z0-9._%+-]*[A-Za-z0-9][A-Za-z0-9._%+-]*@)[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", text)
    text = re.sub(r"(?i)(authorization[\s\"':=]+)(?:bearer|basic)\s+[A-Za-z0-9+/=._-]+", r"\1[REDACTED_AUTH]", text)
    text = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED_JWT]", text)
    text = re.sub(r'(?i)(["\']?(?:access_token|refresh_token|id_token|api_key|account_id)["\']?\s*[:=]\s*)["\'][^"\']+["\']', r'\1"[REDACTED]"', text)
    return text


def bounded(argv, *, cwd, env, timeout=120, capture=True):
    started, cpu = time.monotonic(), child_cpu()
    process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL, start_new_session=True)
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
    return {"argv": [str(x) for x in argv], "returncode": process.returncode, "timed_out": timed_out,
        "wall_seconds": time.monotonic() - started, "reaped_child_cpu_seconds": child_cpu() - cpu,
        "child_cpu_scope": "process and reaped descendants; persistent server accounted separately",
        "stdout": redact((stdout or b"").decode(errors="replace")),
        "stderr": redact((stderr or b"").decode(errors="replace"))}


class PrivateServer:
    def __init__(self, environment, cwd, private):
        self.environment, self.cwd, self.private = dict(environment), cwd, private
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.password = secrets.token_urlsafe(32)
        self.environment["OPENCODE_PASSWORD"] = self.password
        self.started, self.cpu = time.monotonic(), child_cpu()
        self.log = (private / "server.log").open("wb")
        self.argv = [str(BINARY), "serve", "--hostname", "127.0.0.1", "--port", str(self.port)]
        self.process = subprocess.Popen(self.argv, cwd=cwd, env=self.environment,
            stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log, start_new_session=True)
        self.max_tree_rss_kib = 0
        self.poll_samples = 0

    def request(self, method, path, data=None, timeout=15):
        authorization = "Basic " + base64.b64encode(("opencode:" + self.password).encode()).decode()
        request = urllib.request.Request(self.url + path, method=method,
            headers={"Authorization": authorization, "Content-Type": "application/json"},
            data=None if data is None else json.dumps(data).encode())
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status == 204:
                return None
            return json.load(response)

    def wait_ready(self, seconds=60):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("Isolated server exited before readiness; private logs retained")
            try:
                result = self.request("GET", "/api/info", timeout=1)
                return {"info": result, "readiness_wall_seconds": time.monotonic() - self.started}
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(0.1)
        raise TimeoutError("Isolated server readiness deadline")

    def sample_rss(self):
        descendants = {self.process.pid}
        rows = []
        for path in Path("/proc").iterdir():
            if not path.name.isdigit():
                continue
            try:
                stat = (path / "stat").read_text().rsplit(")", 1)[1].split()
                status = (path / "status").read_text()
                rss = next((int(line.split()[1]) for line in status.splitlines() if line.startswith("VmRSS:")), 0)
                rows.append((int(path.name), int(stat[1]), rss))
            except (OSError, ValueError):
                continue
        for _ in range(10):
            before = len(descendants)
            descendants.update(pid for pid, ppid, _ in rows if ppid in descendants)
            if len(descendants) == before:
                break
        total = sum(rss for pid, _, rss in rows if pid in descendants)
        self.max_tree_rss_kib = max(total, self.max_tree_rss_kib)
        self.poll_samples += 1

    def stop(self):
        self.sample_rss()
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
        self.log.close()
        return {"argv": self.argv, "returncode": self.process.returncode,
            "wall_seconds": time.monotonic() - self.started,
            "reaped_child_cpu_seconds": child_cpu() - self.cpu,
            "cpu_scope": "all children reaped during server lifetime; includes separately recorded CLI clients, do not sum twice",
            "sampled_peak_server_tree_rss_kib": self.max_tree_rss_kib, "rss_samples": self.poll_samples,
            "rss_limitations": "sampled RSS sum; shared pages may be double counted; no cgroup peak guarantee",
            "private_state_bytes_at_stop": tree_bytes(self.private)}
