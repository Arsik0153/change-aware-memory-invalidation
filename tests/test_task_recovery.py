"""Real parent SIGKILL with a local fake OpenCode API; no model or credential use."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.request

import pytest

from integrations.opencode import run_task as subject
from integrations.opencode import task_session as capture

CANDIDATE = Path(subject.__file__)


def test_parent_sigkill_stops_remote_work_and_recovers_once(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src/a.py").write_text("old")
    journal = tmp_path / "journal"
    prompted = threading.Event()
    interrupted = threading.Event()
    calls = []
    model = {"providerID": "openai", "id": "gpt-6.1-sol", "variant": "high"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            calls.append(("POST", self.path))
            if self.path == "/api/session":
                value = {
                    "data": {"id": "s1", "location": {"directory": str(workspace)}, "model": model}
                }
                assert data["location"]["directory"] == str(workspace)
            elif self.path.endswith("/prompt"):
                (workspace / "src/a.py").write_text("new")
                prompted.set()
                value = {"data": {}}
            else:
                assert self.path.endswith("/interrupt")
                interrupted.set()
                value = {"data": {}}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def do_GET(self):
            calls.append(("GET", self.path))
            if "/message?" in self.path:
                value = {"data": [{"id": "m1", "type": "assistant", "time": {}}], "cursor": {}}
            else:
                value = {
                    "data": {
                        "id": "s1",
                        "location": {"directory": str(workspace)},
                        "model": model,
                        "time": {"idle": 1} if interrupted.is_set() else {},
                        "outcome": "interrupted" if interrupted.is_set() else "running",
                    }
                }
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    client_code = f"""import sys,json,urllib.request,os
sys.path.insert(0,{str(CANDIDATE.parent)!r})
import run_task
url={url!r}
def request(method,path,payload=None):
 data=json.dumps(payload).encode() if payload is not None else None
 with urllib.request.urlopen(urllib.request.Request(url+path,data=data,method=method,headers={{'Content-Type':'application/json'}}),timeout=3) as response:return json.load(response)
run_task.api_client=lambda:request
run_task.forward('fake','openai/gpt-6.1-sol#high','task',os.getppid(),{str(journal)!r})
"""
    parent_code = f"""import sys,json
sys.path.insert(0,{str(CANDIDATE.parent)!r})
import task_session
result=task_session.run({str(journal)!r},{str(workspace)!r},'task',json.dumps({{'model':'openai/gpt-6.1-sol#high','origin':'admission'}}),{[sys.executable, "-c", client_code]!r},{[sys.executable, "-B", "-c", "from pathlib import Path; assert Path('src/a.py').read_text()=='new'"]!r})
"""
    process = subprocess.Popen(
        [sys.executable, "-c", parent_code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    binding = None
    try:
        assert prompted.wait(10)
        binding = json.loads((journal / "api-session.json").read_text())
        assert binding["owner_pid"] == process.pid
        os.kill(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
        assert interrupted.wait(5), "remote work must stop after parent death"

        def request(method, path, payload=None):
            data = json.dumps(payload).encode() if payload is not None else None
            with urllib.request.urlopen(
                urllib.request.Request(
                    url + path,
                    data=data,
                    method=method,
                    headers={"Content-Type": "application/json"},
                ),
                timeout=3,
            ) as r:
                return json.load(r)

        monkeypatch.setattr(subject, "api_client", lambda: request)
        result = subject.recover(journal)
        assert result["quality"] == "pass"
        assert result["execution"] == "failed_or_interrupted"
        assert result["telemetry"]["total"] is None
        assert result["cache_eligible"] is False
        count = len(calls)
        assert subject.recover(journal) == result
        assert len(calls) == count
        assert sum(method == "POST" and path.endswith("/prompt") for method, path in calls) == 1
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        if binding:
            try:
                os.killpg(binding["client_pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_recovery_refuses_active_launcher(tmp_path, monkeypatch):
    directory = tmp_path / "journal"
    directory.mkdir()
    journal = subject.task_session.Journal(directory / "events.sqlite")
    journal.append("prepared", {"workspace": str(tmp_path), "context": "{}"})
    journal.close()
    subject.persist_binding(
        directory,
        {
            "schema": "cami-opencode-session/1",
            "owner_pid": os.getpid(),
            "owner_token": subject.owner_token(os.getpid()),
        },
    )
    monkeypatch.setattr(subject, "api_client", lambda: pytest.fail("must not reach API"))
    with pytest.raises(ValueError, match="still running"):
        subject.recover(directory)


def test_cooperative_timeout_is_not_reported_success(tmp_path):
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    (work / "src/a.py").write_text("old")
    usage = {"input": 7, "output": 2, "reasoning": 0, "cache_read": 3, "cache_write": 0}
    code = """import sys,signal,time,json
from pathlib import Path
signal.signal(signal.SIGTERM,lambda *args:sys.exit(0))
Path('src/a.py').write_text('new')
print(json.dumps({'type':'request_started','id':'m1'}),flush=True)
print(json.dumps({'type':'request_finished','id':'m1','usage':USAGE}),flush=True)
while True:time.sleep(1)
""".replace("USAGE", repr(usage))
    result = capture.run(
        tmp_path / "journal",
        work,
        "task",
        "context",
        [sys.executable, "-c", code],
        [
            sys.executable,
            "-B",
            "-c",
            "from pathlib import Path;assert Path('src/a.py').read_text()=='new'",
        ],
        request_coverage=True,
        timeout=1,
    )
    assert result["quality"] == "pass"
    assert result["telemetry"]["complete"] is True
    assert result["execution"] == "failed_or_interrupted"
    assert result["cache_eligible"] is False


def test_entrypoint_preserves_exact_prompt_and_declared_context(tmp_path, monkeypatch, capsys):
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    prompt = tmp_path / "task.txt"
    prompt.write_bytes(b"exact\r\nprompt\r\n")
    context = tmp_path / "context.txt"
    context.write_bytes(b"external\r\ncontext")
    binary = tmp_path / "fake-opencode"
    binary.write_bytes(b"authored fake binary")
    binary.chmod(0o700)
    received = {}

    def capture(directory, workspace, task, bound_context, agent, grade, **kwargs):
        received.update(task=task, context=json.loads(bound_context), agent=agent)
        return {"quality": "pass", "execution": "success"}

    monkeypatch.setattr(subject.task_session, "run", capture)
    assert (
        subject.main(
            [
                "--workspace",
                str(work),
                "--task-file",
                str(prompt),
                "--context-file",
                str(context),
                "--journal-root",
                str(tmp_path / "journals"),
                "--grade-json",
                '["true"]',
                "--opencode-binary",
                str(binary),
            ]
        )
        == 0
    )
    assert received["task"] == "exact\r\nprompt\r\n"
    assert received["task"] not in received["agent"]
    assert received["agent"][2] == "_forward_recorded"
    assert received["context"]["external"] == "external\r\ncontext"
    assert received["context"]["origin"] == "user"
    assert received["context"]["runner_sha256"]


def test_response_capture_keeps_visible_text_without_native_credentials():
    value = subject.public_response(
        {
            "id": "m1",
            "type": "assistant",
            "time": {"created": 1},
            "native": {"access_token": "authored-secret"},
            "content": [
                {"type": "text", "text": "visible partial answer"},
                {"type": "reasoning", "text": "private internal text"},
                {
                    "type": "tool",
                    "name": "read",
                    "native": {"id_token": "authored-secret"},
                    "state": {"status": "completed"},
                },
            ],
        }
    )
    serialized = json.dumps(value)
    assert "visible partial answer" in serialized
    assert "authored-secret" not in serialized
    assert "private internal text" not in serialized
