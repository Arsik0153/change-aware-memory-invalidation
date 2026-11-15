"""Durable prospective task capture around an agent command.

Agent stdout may emit request_started/request_finished JSON objects with unique id
and five disjoint integer token fields. Opaque tools remain telemetry-incomplete.
The context file must bind *all* meaningful external inputs, including the grader.
No provider request is retried by this runner. Recovery only preserves and grades.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
import signal
import threading

try:
    from . import task_replay as replay
except ImportError:  # direct adapter invocation
    import task_replay as replay

FIELDS = ("input", "output", "reasoning", "cache_read", "cache_write")


class Journal:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, time_ns INTEGER NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL)"
        )
        self.db.commit()

    def append(self, kind, data):
        with self.db:
            self.db.execute(
                "INSERT INTO events(time_ns,kind,data) VALUES(?,?,?)",
                (time.time_ns(), kind, json.dumps(data, sort_keys=True)),
            )

    def events(self):
        if self.db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("journal integrity check failed")
        return [
            (kind, json.loads(data))
            for kind, data in self.db.execute("SELECT kind,data FROM events ORDER BY seq")
        ]

    def close(self):
        self.db.close()


def snapshot(source, target):
    before = replay.inventory(source)
    temporary = target.with_name(target.name + ".partial")
    if temporary.exists():
        shutil.rmtree(temporary)
    shutil.copytree(
        source, temporary, ignore=lambda d, names: [".git"] if Path(d) == source else []
    )
    if replay.inventory(source) != before or replay.inventory(temporary) != before:
        raise ValueError("workspace changed during snapshot")
    for path in temporary.rglob("*"):
        if path.is_file():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
    # Persist directory entries bottom-up before publishing.
    for path in [*sorted((p for p in temporary.rglob("*") if p.is_dir()), reverse=True), temporary]:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    os.rename(temporary, target)
    fd = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return before


def telemetry(events):
    started, finished, errors = {}, {}, []
    observed, reported = {}, set()
    for kind, data in events:
        if kind != "response":
            continue
        try:
            item = json.loads(data["line"])
        except ValueError:
            continue  # ordinary text is retained, never interpreted as usage
        if not isinstance(item, dict):
            continue
        if item.get("type") == "request_started":
            key = item.get("id")
            if not isinstance(key, str) or not key or key in started:
                errors.append("invalid_or_duplicate_request_start")
            else:
                started[key] = item
        if item.get("type") in {"request_finished", "provider_error"}:
            key, usage = item.get("id"), item.get("usage")
            if not isinstance(key, str) or key not in started or key in reported:
                errors.append("unbound_or_duplicate_request_finish")
                continue
            reported.add(key)
            if isinstance(usage, dict):
                known = {k: usage[k] for k in FIELDS if type(usage.get(k)) is int and usage[k] >= 0}
                if known:
                    observed[key] = known
            if item["type"] == "provider_error":
                errors.append("provider_error")
            elif (
                not isinstance(usage, dict)
                or set(usage) != set(FIELDS)
                or any(type(usage[k]) is not int or usage[k] < 0 for k in FIELDS)
            ):
                errors.append("missing_or_invalid_usage")
            else:
                finished[key] = usage
    missing = sorted(set(started) - set(finished))
    complete = bool(started) and not missing and not errors
    return {
        "complete": complete,
        "scope": "adapter-declared requests only; opaque provider retries cannot be certified",
        "requests": len(started),
        "missing_usage": missing,
        "errors": errors,
        "known_component_requests": {k: sum(k in u for u in observed.values()) for k in FIELDS},
        "known_subtotal": {k: sum(u.get(k, 0) for u in observed.values()) for k in FIELDS}
        if observed
        else None,
        "total": {k: sum(u[k] for u in finished.values()) for k in FIELDS} if complete else None,
        "billing_reconciliation": "unavailable; no invoice source configured",
    }


def finish(directory, journal):
    events = journal.events()
    config = next(data for kind, data in events if kind == "prepared")
    terminal = [d for k, d in events if k == "terminal"]
    if terminal:
        return terminal[-1]
    # Caller must stop any orphan agent before recovery. Never repeat a provider call.
    journal.append("capture_started", {})
    replayed = any(k == "replay_materialized" for k, _ in events)
    candidate = directory / "solution"
    if not candidate.exists():
        snapshot(Path(config["workspace"]), candidate)
    files = replay.inventory(candidate)
    journal.append("solution_preserved", {"files": files})
    journal.append("grade_started", {"argv": config["grade"]})
    with (directory / "grade.log").open("ab") as log:
        try:
            result = subprocess.run(
                config["grade"],
                cwd=candidate,
                stdout=log,
                stderr=log,
                timeout=300,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
        except (subprocess.TimeoutExpired, OSError) as error:
            journal.append("grade_error", {"type": type(error).__name__})
            result = subprocess.CompletedProcess(config["grade"], 124)
        log.flush()
        os.fsync(log.fileno())
    quality = result.returncode == 0
    if replay.inventory(candidate) != files:
        quality = False  # grader must not alter the submitted artifact
    journal.append("grade_finished", {"returncode": result.returncode, "quality": quality})
    events = journal.events()
    exits = [d["returncode"] for k, d in events if k == "agent_finished"]
    usage = telemetry(events)
    if replayed:
        usage = {**usage, "complete": True, "requests": 0,
                 "total": {k: 0 for k in FIELDS}, "scope": "exact replay; no provider invocation"}
    execution = bool(exits) and exits[-1] == 0 and not any(k == "agent_timeout" for k, _ in events)
    # An explicit caller declaration is required, and does not prove foreign API coverage.
    eligible = quality and execution and usage["complete"] and config["request_coverage"]
    terminal = {
        "quality": "pass" if quality else "fail",
        "execution": "success" if execution else "failed_or_interrupted",
        "telemetry": usage,
        "cache_eligible": eligible,
        "cache_recorded": False,
        "input_key": config["key"],
        "solution_files": files,
    }
    if eligible and config["cache"] and not replayed:
        journal.append("cache_record_started", {})
        replay.record(
            directory / "before", candidate, config["task"], config["context"], config["cache"]
        )
        terminal["cache_recorded"] = True
    if config.get("v2_state") and not replayed:
        try:
            from . import task_memory
        except ImportError:
            import task_memory
        terminal["method_recorded"] = task_memory.remember(directory, config, terminal)
    terminal["replayed"] = replayed
    journal.append("terminal", terminal)
    return terminal


def run(
    directory,
    workspace,
    task,
    context,
    agent,
    grade,
    cache=None,
    request_coverage=False,
    timeout=900,
    v2_state=None,
):
    directory, workspace = Path(directory).resolve(), Path(workspace).resolve()
    if directory.is_relative_to(workspace):
        raise ValueError("journal must be outside input")
    if v2_state:
        v2_state = Path(v2_state).resolve()
        if v2_state.is_relative_to(workspace) or workspace.is_relative_to(v2_state):
            raise ValueError("v2 memory must be outside workspace")
        if cache and Path(cache).resolve() != v2_state / "replay":
            raise ValueError("v2 cache must use its own replay namespace")
        cache = v2_state / "replay"
    directory.mkdir(exist_ok=False, mode=0o700)
    journal = Journal(directory / "events.sqlite")
    try:
        journal.append("capture_input_started", {})
        files = snapshot(workspace, directory / "before")
        key = replay.identity(files, task, context)
        journal.append(
            "prepared",
            {
                "workspace": str(workspace),
                "task": task,
                "context": context,
                "key": key,
                "files": files,
                "agent": agent,
                "grade": grade,
                "cache": str(Path(cache).resolve()) if cache else None,
                "request_coverage": request_coverage,
                "v2_state": str(v2_state) if v2_state else None,
            },
        )
        if v2_state:
            try:
                from . import task_context, task_memory
            except ImportError:
                import task_context
                import task_memory
            state = Path(v2_state)
            state.mkdir(parents=True, exist_ok=True)
            replay.publish(state / "binding.json", replay.canonical({
                "schema": "cami-task-state/2", "workspace": str(workspace)}))
            if task_memory.reusable(state, key, context):
                hit = replay.materialize(directory / "before", task, context, state / "replay", directory / "solution")
            else:
                hit = {"status": "miss", "reason": "no committed eligible exact solution", "key": key}
            journal.append("replay_decision", hit)
            if hit["status"] == "candidate_requires_grading":
                candidate_files = replay.inventory(directory / "solution")
                with (directory / "replay-grade.log").open("ab") as log:
                    try:
                        checked = subprocess.run(grade, cwd=directory / "solution", stdout=log,
                                                 stderr=log, timeout=300,
                                                 env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
                        valid = checked.returncode == 0 and replay.inventory(directory / "solution") == candidate_files
                    except (OSError, subprocess.TimeoutExpired):
                        valid = False
                    log.flush()
                    os.fsync(log.fileno())
                journal.append("replay_checked", {"valid": valid})
                if valid:
                    journal.append("replay_materialized", hit)
                    journal.append("agent_finished", {"returncode": 0})
                    return finish(directory, journal)
                (directory / "solution").rename(directory / "rejected-replay")
            packet = task_context.prepare(workspace, task, state, directory / "context.txt")
            methods = json.dumps(task_memory.hints(state, task), sort_keys=True)
            prompt = task + "\n\nCurrent source packet (read more with native tools as needed):\n" + packet
            prompt += "\nVerified previous methods, hints only; reassess applicability:\n" + methods
            if replay.inventory(workspace) != files:
                raise ValueError("workspace changed after capture; model not admitted")
            journal.append("task_prompt", {"text": prompt})
        journal.append("agent_started", {"argv": agent})
        with (directory / "stderr.log").open("ab") as stderr:
            try:
                process = subprocess.Popen(
                    agent,
                    cwd=workspace,
                    stdout=subprocess.PIPE,
                    stderr=stderr,
                    start_new_session=True,
                )
            except OSError as error:
                journal.append("agent_launch_error", {"type": type(error).__name__})
                return finish(directory, journal)

            timed_out = threading.Event()

            def terminate():
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=35)
                    except subprocess.TimeoutExpired:
                        pass
                    # Reap any remaining members of this owned process group.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                except ProcessLookupError:
                    pass

            def expire():
                timed_out.set()
                terminate()

            timer = threading.Timer(timeout, expire)
            timer.start()
            try:
                for raw in iter(lambda: process.stdout.readline(1024 * 1024), b""):
                    journal.append("response", {"line": raw.decode("utf-8", errors="replace")})
                code = process.wait()
            finally:
                timer.cancel()
                timer.join()
                process.stdout.close()
                if process.poll() is None:
                    terminate()
                    process.wait()
            stderr.flush()
            os.fsync(stderr.fileno())
        if timed_out.is_set():
            journal.append("agent_timeout", {"seconds": timeout, "cleanup_grace_seconds": 35})
        journal.append("agent_finished", {"returncode": code})
        return finish(directory, journal)
    finally:
        journal.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["run", "recover"])
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--workspace", type=Path)
    p.add_argument("--task-file", type=Path)
    p.add_argument("--context-file", type=Path)
    p.add_argument("--agent-json", help="JSON argv; no shell evaluation")
    p.add_argument("--grade-json", help="JSON argv; runs in preserved solution")
    p.add_argument("--cache", type=Path)
    p.add_argument("--declared-request-coverage", action="store_true")
    args = p.parse_args()
    if args.action == "recover":
        journal = Journal(args.directory / "events.sqlite")
        try:
            result = finish(args.directory, journal)
        finally:
            journal.close()
    else:
        if not all(
            [args.workspace, args.task_file, args.context_file, args.agent_json, args.grade_json]
        ):
            p.error("run requires workspace, task-file, context-file, agent-json and grade-json")
        result = run(
            args.directory,
            args.workspace,
            args.task_file.read_bytes().decode("utf-8"),
            args.context_file.read_bytes().decode("utf-8"),
            json.loads(args.agent_json),
            json.loads(args.grade_json),
            args.cache,
            args.declared_request_coverage,
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
