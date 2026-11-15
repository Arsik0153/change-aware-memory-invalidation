"""Bounded new-task plain/CAMI study; all outputs are append-only per attempt."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "runs/practical-complete-20261115"
REPORT = ROOT / "reports/practical-complete-20261115"
sys.path[:0] = [
    str(ROOT / "scripts/opencode_benchmark/harness"),
    str(ROOT / "scripts/opencode_benchmark/controller"),
    str(ROOT / "scripts/opencode_benchmark/analysis"),
    str(ROOT / "integrations/opencode"),
]
from container_session import source_inventory, shared_service_url, chown_owned  # noqa: E402
from aggregate_metrics import token_fields  # noqa: E402
from task_replay import inventory  # noqa: E402
from task_session import Journal  # noqa: E402

IMAGE = "sha256:9e3b5290a54521f5c0e3cb4b4c8b75969ba025aac6ba6cd265b5372cdc4ca356"
BASE_IMAGE = "sha256:3e5f5aee66022082251b8cc1fb5c3ea9399ec9589ab98ba3d190a8b0ab46b387"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(argv, log, timeout=900):
    start = time.monotonic()
    with log.open("w") as f:
        try:
            r = subprocess.run(
                list(map(str, argv)), stdout=f, stderr=subprocess.STDOUT, timeout=timeout
            )
            code = r.returncode
        except subprocess.TimeoutExpired:
            code = 124
    return {"returncode": code, "wall_seconds": time.monotonic() - start}


def grade(task, workspace, out):
    out.mkdir(exist_ok=False)
    os.chown(out, 65534, 65534)
    argv = [
        "docker",
        "run",
        "--rm",
        "--network=none",
        "--memory=700m",
        "--cpus=1",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,size=128m",
        "--mount",
        f"type=bind,src={workspace},dst=/workspace,readonly",
        "--mount",
        f"type=bind,src={RUN / 'tasks' / task['id'] / 'evaluation'},dst=/evaluation,readonly",
        "--mount",
        f"type=bind,src={out},dst=/results",
        "--mount",
        f"type=bind,src={ROOT / 'scripts/opencode_benchmark/controller/fixed_grader.py'},dst=/grader.py,readonly",
        "--entrypoint",
        "python",
        IMAGE,
        "-I",
        "/grader.py",
        "--subject-module",
        task["package"],
        "--report",
        "/results/counts.json",
        "--",
        "-q",
        "-c",
        "/dev/null",
        "--confcutdir=/evaluation",
        "-p",
        "no:cacheprovider",
        "/evaluation",
    ]
    result = command(argv, out / "process.log", timeout=300)
    result["counts"] = read(out / "counts.json") if (out / "counts.json").exists() else None
    result["quality_pass"] = (
        result["returncode"] == 0
        and result["counts"] is not None
        and result["counts"]["counts"]["executed"] > 0
    )
    write(out / "grade.json", result)
    return result


def runtime_identity():
    return {
        "image_id": IMAGE,
        "binary_sha256": digest(Path("/root/.opencode/bin/opencode")),
        "cami_files": source_inventory(ROOT / "src"),
        "adapter_files": source_inventory(ROOT / "integrations/opencode"),
    }


def memory(workspace, dest, out):
    dest.mkdir()
    chown_owned(workspace)
    chown_owned(dest)
    script = """from pathlib import Path
from seed_source_literals_v2 import build
from memory_backend import prepare
import json
seed,metrics=build(Path('/workspace'),['src'])
Path('/memory/seed.json').write_text(json.dumps(seed))
Path('/memory/seed-metrics.json').write_text(json.dumps(metrics))
prepare('cami',Path('/workspace'),Path('/memory/prepared'),spec_path=Path('/memory/seed.json'),state_home=Path('/memory/cami-state'))
"""
    argv = [
        "docker",
        "run",
        "--rm",
        "--user",
        "65534:65534",
        "--network=none",
        "--memory=900m",
        "--cpus=1",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,size=128m",
        "-w",
        "/workspace",
        "-e",
        "PYTHONPATH=/opt/memory-adapter:/opt/cami-src:/opt/cami-deps",
        "--mount",
        f"type=bind,src={workspace},dst=/workspace",
        "--mount",
        f"type=bind,src={dest},dst=/memory",
        "--mount",
        f"type=bind,src={ROOT / 'src'},dst=/opt/cami-src,readonly",
        "--mount",
        f"type=bind,src={ROOT / 'integrations/opencode'},dst=/opt/memory-adapter,readonly",
        "--entrypoint",
        "python",
        IMAGE,
        "-c",
        script,
    ]
    return command(argv, out, timeout=600)


def admission():
    tasks = read(RUN / "tasks/manifest.json")
    out = RUN / "admission-v3"
    out.mkdir(exist_ok=False)
    receipts = []
    for task in tasks:
        base = RUN / "tasks" / task["id"] / "base"
        candidate = out / task["id"]
        candidate.mkdir()
        shutil.copytree(base, candidate / "gold")
        subprocess.run(
            [
                "git",
                "-C",
                str(candidate / "gold"),
                "apply",
                str(RUN / "tasks" / task["id"] / "gold.patch"),
            ],
            check=True,
        )
        b = grade(task, base, candidate / "base-grade")
        g = grade(task, candidate / "gold", candidate / "gold-grade")
        receipts.append({"task": task["id"], "base": b, "gold": g})
        print(task["id"], b["returncode"], g["returncode"], flush=True)
    write(REPORT / "task-admission.json", receipts)
    assert all(not x["base"]["quality_pass"] and x["gold"]["quality_pass"] for x in receipts), (
        "base must fail behavioral tests, gold must pass all fixed tests"
    )


def freeze():
    tasks = read(RUN / "tasks/manifest.json")
    admission_results = read(REPORT / "task-admission.json")
    assert len(admission_results) == 12 and all(
        not x["base"]["quality_pass"] and x["gold"]["quality_pass"] for x in admission_results
    )
    schedule = []
    for repetition in range(1, 4):
        for index, task in enumerate(tasks):
            arms = ["plain", "cami"] if (repetition + index) % 2 else ["cami", "plain"]
            for arm in arms:
                schedule.append(
                    {
                        "id": f"r{repetition}-{task['id']}-{arm}",
                        "task": task["id"],
                        "arm": arm,
                        "repetition": repetition,
                    }
                )
    protocol = {
        "design": "new-historical-task-plain-cami-v1",
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tasks": tasks,
        "schedule": schedule,
        "model": "openai/gpt-6.1-sol#high",
        "attempts": 72,
        "repeats_per_task_arm": 3,
        "memory": "Fresh source-only literal catalog per attempt; no task-specific notes, previous solutions, result replay or shared conversation. Readable format, lexical ranking. Native tools unchanged.",
        "quality": "All acceptance and full fixed upstream regression module must pass. Test edits made by model do not enter grading. Only candidate src replaces canonical source for grading.",
        "decision": "Enable recommendation only if all scheduled sessions pass operational admission, CAMI passes at least 30 of its 36 tasks and has at least as many quality passes as plain, no repository has fewer passes, complete observed usage for all attempts, and median across 12 paired per-task mean total pipeline-time ratios <=0.90 AND token-work ratios <=0.90. Otherwise reject default recommendation for tested workload. Operational and telemetry defects reported separately, never described as proof of zero efficacy.",
        "budget": {
            "maximum_model_sessions": 72,
            "seconds_per_session": 600,
            "observed_disjoint_token_limit_per_session": 250000,
            "hard_invoice_limit": None,
            "authorization": "User explicitly authorized existing model access; no executor-imposed zero-call limit. No session replacement or performance-based extension.",
        },
        "timing": "Starts before input capture/reset and source-memory construction; ends after source preservation and fresh fixed grading including durable quality journal, immediately before terminal receipt publication. Shared admission cost split equally over 72 attempts. Model-session time and preparation separately retained. Final report/chart work excluded.",
        "scope": "12 public historical tasks, 3 previously studied Python repositories, 3 fresh repetitions; new task prompts compared with previous model studies, not unseen model training data, not production hit rate. Host is shared, resource state recorded before every attempt.",
        "shared_admission_wall_seconds": sum(
            x[side]["wall_seconds"] for x in admission_results for side in ["base", "gold"]
        ),
        "runtime": runtime_identity(),
        "base_image_id": BASE_IMAGE,
        "source_pins": {
            str(p.relative_to(ROOT)): digest(p)
            for folder in [
                "scripts/practical",
                "scripts/opencode_benchmark/harness",
                "scripts/opencode_benchmark/controller",
            ]
            for p in (ROOT / folder).glob("*.py")
        },
    }
    write(REPORT / "runtime-manifest.json", protocol["runtime"])
    target = REPORT / "protocol.json"
    if target.exists():
        raise ValueError("protocol already frozen")
    write(target, protocol)
    write(REPORT / "protocol-seal.json", {"sha256": digest(target), "attempts": 72})


def resource_state():
    return {
        "time_ns": time.time_ns(),
        "load": os.getloadavg(),
        "meminfo": Path("/proc/meminfo").read_text(),
        "disk_free": shutil.disk_usage(RUN).free,
    }


def run():
    protocol = read(REPORT / "protocol.json")
    assert digest(REPORT / "protocol.json") == read(REPORT / "protocol-seal.json")["sha256"]
    assert runtime_identity() == protocol["runtime"]
    for name, sha in protocol["source_pins"].items():
        assert digest(ROOT / name) == sha, name
    tasks = {t["id"]: t for t in protocol["tasks"]}
    out = RUN / "model"
    out.mkdir(exist_ok=True)
    shared_url = shared_service_url()
    for trial in protocol["schedule"]:
        directory = out / trial["id"]
        if (directory / "terminal.json").exists():
            continue
        if directory.exists():
            raise ValueError("interrupted attempt needs explicit recovery; cannot rerun model")
        directory.mkdir()
        start = time.monotonic()
        resources = resource_state()
        write(directory / "resources.json", resources)
        if resources["disk_free"] < 5 * 1024**3:
            raise RuntimeError(
                "disk reserve breached; clean only own disposable work before continuing"
            )
        task = tasks[trial["task"]]
        taskdir = RUN / "tasks" / trial["task"]
        journal = Journal(directory / "events.sqlite")
        journal.append("attempt_started", trial)
        workspace = directory / "workspace"
        shutil.copytree(taskdir / "base", workspace)
        before = inventory(workspace)
        journal.append(
            "input_bound",
            {"files": before, "task_sha256": task["prompt_sha256"], "context": protocol["runtime"]},
        )
        mem = directory / "memory"
        prep = {"returncode": 0, "wall_seconds": 0}
        if trial["arm"] == "cami":
            prep = memory(workspace, mem, directory / "memory-preparation.log")
        else:
            mem.mkdir()
        write(directory / "memory-preparation.json", prep)
        journal.append("memory_prepared", prep)
        result = {"returncode": 1, "wall_seconds": 0}
        if prep["returncode"] == 0:
            argv = [
                sys.executable,
                str(ROOT / "scripts/opencode_benchmark/harness/container_session.py"),
                "--workspace",
                workspace,
                "--memory-dir",
                mem,
                "--state-dir",
                directory / "private-state",
                "--out",
                directory / "session",
                "--arm",
                trial["arm"],
                "--prompt-file",
                taskdir / "prompt.txt",
                "--run-model",
                "--runtime-manifest",
                REPORT / "runtime-manifest.json",
                "--timeout-seconds",
                "600",
                "--reported-token-budget",
                "250000",
                "--image",
                IMAGE,
                "--shared-server",
                shared_url,
                "--memory-response-format",
                "readable",
            ]
            if trial["arm"] == "cami":
                argv += ["--binding-relative", "prepared/binding.json"]
            journal.append("session_launching", {"argv": list(map(str, argv))})
            result = command(argv, directory / "session-host.log", timeout=850)
            journal.append("session_finished", result)
        # Grade even after failed sessions; evaluator/config/tests are canonical.
        evaluation = directory / "evaluation-workspace"
        shutil.copytree(taskdir / "base", evaluation)
        shutil.rmtree(evaluation / "src")
        shutil.copytree(workspace / "src", evaluation / "src")
        source = inventory(evaluation / "src")
        journal.append("solution_preserved", {"source": source})
        grading = grade(task, evaluation, directory / "grade")
        journal.append("quality", grading)
        usage_path = directory / "session/evidence/usage.json"
        usage = (
            token_fields(read(usage_path))
            if usage_path.exists()
            else dict.fromkeys(["input", "output", "reasoning", "cache_read", "cache_write"])
        )
        messages_path = directory / "session/evidence/messages.json"
        messages = read(messages_path) if messages_path.exists() else []
        assistants = [m for m in messages if m.get("type") == "assistant"]
        missing = [
            m["id"] for m in assistants if m.get("error") or not m.get("time", {}).get("completed")
        ]
        complete = bool(assistants) and not missing and all(x is not None for x in usage.values())
        trace = directory / "session/evidence/memory-backend-trace.jsonl"
        calls = (
            [json.loads(line) for line in trace.read_text().splitlines() if line.strip()]
            if trace.exists()
            else []
        )
        terminal = {
            "trial": trial,
            "session": result,
            "preparation": prep,
            "quality_pass": grading["quality_pass"],
            "quality": grading,
            "usage": usage,
            "usage_complete": complete,
            "incomplete_assistant_ids": missing,
            "token_work": sum(usage[k] for k in ["input", "output", "reasoning", "cache_write"])
            if complete
            else None,
            "pipeline_wall_seconds": time.monotonic()
            - start
            + protocol["shared_admission_wall_seconds"] / 72,
            "solution_source": source,
            "memory_lookup_calls": sum(x.get("event") == "memory_lookup" for x in calls),
            "memory_errors": sum(
                x.get("event") == "memory_lookup" and x.get("error") is not None for x in calls
            ),
        }
        journal.append("terminal", terminal)
        journal.close()
        write(directory / "terminal.json", terminal)
        with (REPORT / "progress.jsonl").open("a") as f:
            f.write(
                json.dumps(
                    {k: v for k, v in terminal.items() if k not in ["solution_source", "quality"]}
                )
                + "\n"
            )
            f.flush()
            os.fsync(f.fileno())
        print(
            trial["id"],
            "quality",
            grading["quality_pass"],
            "usage",
            complete,
            "seconds",
            round(terminal["pipeline_wall_seconds"], 1),
            flush=True,
        )
        # Discard only duplicated evaluation tree and transient bytecode; source/evidence remain.
        shutil.rmtree(evaluation)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["admission", "freeze", "run"])
    action = parser.parse_args().action
    {"admission": admission, "freeze": freeze, "run": run}[action]()


if __name__ == "__main__":
    main()
