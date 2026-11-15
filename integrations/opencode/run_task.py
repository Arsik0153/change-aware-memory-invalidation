"""Run captured tasks through a local Linux OpenCode service, or recover their journals."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid

try:
    from . import task_session
except ImportError:
    import task_session


def service_url():
    candidates = set()
    for path in Path("/proc").iterdir():
        try:
            if not path.name.isdigit() or (path / "comm").read_text().strip() != "opencode":
                continue
            if b"--service" not in (path / "cmdline").read_bytes().split(b"\0"):
                continue
            sockets = {str(p.readlink()) for p in (path / "fd").iterdir() if p.is_symlink()}
            for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
                fields = line.split()
                if (
                    fields[3] == "0A"
                    and fields[1].startswith("0100007F:")
                    and f"socket:[{fields[9]}]" in sockets
                ):
                    candidates.add("http://127.0.0.1:" + str(int(fields[1].split(":")[1], 16)))
        except OSError:
            continue
    if len(candidates) != 1:
        raise ValueError("one local OpenCode service required")
    return candidates.pop()


def api_client():
    password = json.loads((Path.home() / ".config/opencode/service.json").read_text())["password"]
    auth = base64.b64encode(("opencode:" + password).encode()).decode()
    url = service_url()

    def request(method, path, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            url + path,
            data=body,
            method=method,
            headers={"Authorization": "Basic " + auth, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    return request


def model_ref(model):
    provider, identifier = model.split("/", 1)
    identifier, _, variant = identifier.partition("#")
    return {"providerID": provider, "id": identifier, **({"variant": variant} if variant else {})}


def owner_token(pid):
    try:
        # starttime is stable across CPU/memory changes and distinguishes PID reuse.
        return Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[19]
    except (OSError, IndexError):
        return None


def owner_alive(pid):
    if os.getppid() != pid:
        raise RuntimeError("capturing launcher exited; stop its model session")


def emit(event):
    print(json.dumps(event), flush=True)


def public_response(message):
    hidden = {
        "native",
        "authorization",
        "access_token",
        "refresh_token",
        "id_token",
        "api_key",
        "apikey",
        "password",
    }

    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items() if key.lower() not in hidden}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    result = {
        key: clean(message[key])
        for key in ["id", "type", "time", "model", "agent", "finish", "cost", "tokens", "error"]
        if key in message
    }
    if "content" in message:
        result["content"] = [
            clean(part) for part in message["content"] if part.get("type") in {"text", "tool"}
        ]
    return result


def observe_requests(request, sid, seen, finished, send=emit, parent_pid=None, observations=None):
    observations = {} if observations is None else observations
    cursor = None
    cursors = set()
    for _ in range(10000):
        if parent_pid is not None:
            owner_alive(parent_pid)
        query = {"limit": "200", **({"cursor": cursor} if cursor else {"order": "asc"})}
        page = request("GET", f"/api/session/{sid}/message?" + urllib.parse.urlencode(query))
        for message in page["data"]:
            if message.get("type") != "assistant":
                continue
            mid = message["id"]
            public = public_response(message)
            fingerprint = hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()
            if observations.get(mid) != fingerprint:
                send({"type": "assistant_observation", "id": mid, "message": public})
                observations[mid] = fingerprint
            if mid not in seen:
                send({"type": "request_started", "id": mid})
                seen.add(mid)
            if mid in finished or not message.get("time", {}).get("completed"):
                continue
            tokens = message.get("tokens", {})
            cache = tokens.get("cache", {})
            usage = {
                "input": tokens.get("input"),
                "output": tokens.get("output"),
                "reasoning": tokens.get("reasoning"),
                "cache_read": cache.get("read"),
                "cache_write": cache.get("write"),
            }
            if not message.get("error"):
                send({"type": "request_finished", "id": mid, "usage": usage})
            else:
                send({"type": "provider_error", "id": mid, "usage": usage})
            finished.add(mid)
        cursor = page.get("cursor", {}).get("next")
        if not cursor:
            return
        if cursor in cursors:
            raise ValueError("message pagination repeated a cursor")
        cursors.add(cursor)
    raise ValueError("message pagination exceeded limit")


def persist_binding(directory, binding):
    path = Path(directory) / "api-session.json"
    with path.open("x") as stream:
        os.chmod(path, 0o600)
        json.dump(binding, stream)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def forward(binary, model, prompt, parent_pid=None, journal_dir=None):
    parent_pid = int(parent_pid) if parent_pid is not None else os.getppid()
    owner_alive(parent_pid)
    request = api_client()
    expected = model_ref(model)
    workspace = str(Path.cwd().resolve())
    created = request(
        "POST",
        "/api/session",
        {"location": {"directory": workspace}, "model": expected, "title": "CAMI captured task"},
    )["data"]
    if created["location"]["directory"] != workspace or created["model"] != expected:
        raise ValueError("OpenCode session binding differs from captured inputs")
    sid = created["id"]
    binding = {
        "schema": "cami-opencode-session/1",
        "type": "session_bound",
        "session_id": sid,
        "workspace": workspace,
        "model": expected,
        "owner_pid": parent_pid,
        "client_pid": os.getpid(),
        "owner_token": owner_token(parent_pid),
    }
    owner_alive(parent_pid)
    if journal_dir is not None:
        persist_binding(journal_dir, binding)
    # The receipt is durable before prompt admission, independently of stdout.
    emit(binding)
    seen, finished = set(), set()
    observations = {}

    def interrupted(signum, frame):
        raise RuntimeError("captured task interrupted")

    handlers = {s: signal.getsignal(s) for s in [signal.SIGTERM, signal.SIGINT]}
    for s in handlers:
        signal.signal(s, interrupted)
    try:
        owner_alive(parent_pid)
        request("POST", f"/api/session/{sid}/prompt", {"text": prompt})
        deadline = time.monotonic() + 850
        while time.monotonic() < deadline:
            owner_alive(parent_pid)
            observe_requests(
                request, sid, seen, finished, parent_pid=parent_pid, observations=observations
            )
            session = request("GET", f"/api/session/{sid}")["data"]
            if session.get("outcome") in ["succeeded", "failed", "interrupted"] and session.get(
                "time", {}
            ).get("idle"):
                observe_requests(
                    request, sid, seen, finished, parent_pid=parent_pid, observations=observations
                )
                if session["location"]["directory"] != workspace or session["model"] != expected:
                    raise ValueError("session identity changed")
                return 0 if session["outcome"] == "succeeded" else 1
            time.sleep(0.25)
        raise TimeoutError("task deadline")
    except BaseException:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        # Stop remote work before writing to a possibly closed or failed pipe.
        try:
            request("POST", f"/api/session/{sid}/interrupt", {})
        except Exception:
            pass
        try:
            emit({"type": "request_started", "id": "unknown-after-failure-" + uuid.uuid4().hex})
        except (BrokenPipeError, OSError):
            pass
        raise
    finally:
        for s, handler in handlers.items():
            signal.signal(s, handler)


def recover(directory):
    directory = Path(directory).resolve()
    journal = task_session.Journal(directory / "events.sqlite")
    try:
        events = journal.events()
        if any(kind == "terminal" for kind, _ in events):
            return task_session.finish(directory, journal)
        config = next(data for kind, data in events if kind == "prepared")
        path = directory / "api-session.json"
        if path.exists():
            binding = json.loads(path.read_text())
            if binding.get("schema") != "cami-opencode-session/1":
                raise ValueError("unsupported session receipt")
            token = binding.get("owner_token")
            if token is not None and owner_token(binding["owner_pid"]) == token:
                raise ValueError("launcher is still running; stop it before recovery")
            context = json.loads(config["context"])
            if binding["workspace"] != str(Path(config["workspace"]).resolve()) or binding[
                "model"
            ] != model_ref(context["model"]):
                raise ValueError("session receipt differs from captured task")
            request = api_client()
            session = request("GET", f"/api/session/{binding['session_id']}")["data"]
            if (
                session["location"]["directory"] != binding["workspace"]
                or session["model"] != binding["model"]
            ):
                raise ValueError("remote session differs from receipt")
            if not session.get("time", {}).get("idle"):
                request("POST", f"/api/session/{binding['session_id']}/interrupt", {})
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    session = request("GET", f"/api/session/{binding['session_id']}")["data"]
                    if session.get("time", {}).get("idle"):
                        break
                    time.sleep(0.25)
                else:
                    raise TimeoutError("session writers did not stop; solution not captured")
            seen, finished = set(), set()
            for kind, data in events:
                if kind != "response":
                    continue
                try:
                    value = json.loads(data["line"])
                except ValueError:
                    continue
                if value.get("type") == "request_started":
                    seen.add(value["id"])
                if value.get("type") in {"request_finished", "provider_error"}:
                    finished.add(value["id"])
            observe_requests(
                request,
                binding["session_id"],
                seen,
                finished,
                send=lambda event: journal.append("response", {"line": json.dumps(event)}),
            )
            journal.append("remote_session_stopped", {"session_id": binding["session_id"]})
        return task_session.finish(directory, journal)
    finally:
        journal.close()


def forward_recorded(binary, model, parent_pid, directory):
    owner_alive(int(parent_pid))
    directory = Path(directory).resolve()
    connection = sqlite3.connect(f"file:{directory / 'events.sqlite'}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "select data from events where kind='prepared' order by seq"
        ).fetchall()
    finally:
        connection.close()
    if len(rows) != 1:
        raise ValueError("one durable task input required")
    config = json.loads(rows[0][0])
    if config["key"] != task_session.replay.identity(
        config["files"], config["task"], config["context"]
    ):
        raise ValueError("recorded input key differs")
    if (
        str(Path.cwd().resolve()) != config["workspace"]
        or json.loads(config["context"])["model"] != model
    ):
        raise ValueError("recorded workspace or model differs")
    journal = task_session.Journal(directory / "events.sqlite")
    try:
        prompts = [data["text"] for kind, data in journal.events() if kind == "task_prompt"]
    finally:
        journal.close()
    return forward(binary, model, prompts[-1] if prompts else config["task"], parent_pid, str(directory))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_forward_recorded"]:
        return forward_recorded(*argv[1:])
    if argv[:1] == ["recover"]:
        parser = argparse.ArgumentParser(prog="cami task recover")
        parser.add_argument("--directory", type=Path, required=True)
        args = parser.parse_args(argv[1:])
        result = recover(args.directory)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["quality"] == "pass" else 1
    parser = argparse.ArgumentParser(prog="cami task", description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--task-file", type=Path, required=True)
    parser.add_argument(
        "--context-file",
        type=Path,
        required=True,
        help="Declared meaningful external inputs and toolchain identity",
    )
    parser.add_argument("--grade-json", required=True, help="Fixed test argv as JSON; no shell")
    parser.add_argument(
        "--journal-root",
        type=Path,
        default=Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "cami-tasks",
    )
    parser.add_argument("--model", default="openai/gpt-6.1-sol#high")
    parser.add_argument("--opencode-binary", default="opencode")
    parser.add_argument("--origin", choices=["user", "admission", "experiment"], default="user")
    parser.add_argument("--mode", choices=["legacy", "v2"], default="legacy")
    parser.add_argument("--memory-root", type=Path, default=Path.home() / ".local/state/cami-task-memory")
    args = parser.parse_args(argv)
    binary = shutil.which(args.opencode_binary)
    if binary is None:
        parser.error("OpenCode binary not found")
    workspace = args.workspace.resolve()
    root = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if root.returncode or Path(root.stdout.strip()).resolve() != workspace:
        parser.error("workspace must be the Git repository root")
    journal_root = args.journal_root.resolve()
    if journal_root.is_relative_to(workspace):
        parser.error("journal root must be outside workspace")
    journal_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = journal_root / uuid.uuid4().hex
    task = args.task_file.read_bytes().decode("utf-8")
    external = args.context_file.read_bytes().decode("utf-8")
    grade = json.loads(args.grade_json)
    v2_inputs = {}
    if args.mode == "v2":
        try:
            from . import task_context, task_memory
        except ImportError:
            import task_context
            import task_memory
        v2_inputs = {"v2_module_sha256": {
            module.__name__.rsplit(".", 1)[-1]: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (task_context, task_memory)}}
    context = json.dumps(
        {
            **v2_inputs,
            "origin": args.origin,
            "external": external,
            "model": args.model,
            "python": sys.version,
            "platform": sys.platform,
            "binary_sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "replay_sha256": hashlib.sha256(
                Path(task_session.replay.__file__).read_bytes()
            ).hexdigest(),
            "capture_sha256": hashlib.sha256(Path(task_session.__file__).read_bytes()).hexdigest(),
            "grade": grade,
        },
        sort_keys=True,
    )
    try:
        from .task_memory import namespace
    except ImportError:
        from task_memory import namespace
    state = namespace(args.memory_root, workspace) if args.mode == "v2" else None
    if state and (state.is_relative_to(workspace) or workspace.is_relative_to(state)):
        parser.error("memory namespace must be outside workspace")
    result = task_session.run(
        directory,
        workspace,
        task,
        context,
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "_forward_recorded",
            binary,
            args.model,
            str(os.getpid()),
            str(directory),
        ],
        grade,
        cache=state / "replay" if state else None,
        v2_state=state,
        request_coverage=False,
    )
    print(json.dumps({"journal": str(directory), **result}, sort_keys=True))
    return 0 if result["quality"] == "pass" and result["execution"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
