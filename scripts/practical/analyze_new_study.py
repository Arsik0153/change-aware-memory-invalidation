"""Recheck completed artifacts and apply the predeclared 72-session decision."""

import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "runs/practical-complete-20261115"
REPORT = ROOT / "reports/practical-complete-20261115"
sys.path.insert(0, str(ROOT / "integrations/opencode"))
from task_replay import inventory  # noqa: E402

COMPONENTS = ["input", "cache_read", "cache_write", "output", "reasoning"]


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_inventory(base):
    """Reproduce the pinned runner's copytree, including internal link materialization."""
    for path in base.rglob("*"):
        if ".git" in path.relative_to(base).parts:
            continue
        if path.is_symlink() and not path.resolve().is_relative_to(base.resolve()):
            raise ValueError("external link in canonical fixture")
    with tempfile.TemporaryDirectory(prefix="cami-input-audit-") as temporary:
        target = Path(temporary) / "input"
        shutil.copytree(
            base,
            target,
            ignore=lambda directory, names: [".git"] if Path(directory) == base else [],
        )
        return inventory(target)


def analyze():
    protocol = read(REPORT / "protocol.json")
    assert sha(REPORT / "protocol.json") == read(REPORT / "protocol-seal.json")["sha256"]
    tasks = {t["id"]: t for t in protocol["tasks"]}
    initial_inputs = {name: canonical_inventory(RUN / "tasks" / name / "base") for name in tasks}
    verified = []
    tool_counts = {arm: {} for arm in ["plain", "cami"]}
    backend_wall = 0.0
    for task in tasks.values():
        directory = RUN / "tasks" / task["id"]
        assert sha(directory / "prompt.txt") == task["prompt_sha256"]
        assert sha(directory / "gold.patch") == task["gold_patch_sha256"]
        for name, digest in task["evaluator_files"].items():
            assert sha(directory / "evaluation" / name) == digest
    for trial in protocol["schedule"]:
        d = RUN / "model" / trial["id"]
        terminal = read(d / "terminal.json")
        assert terminal["trial"] == trial
        assert inventory(d / "workspace/src") == terminal["solution_source"]
        connection = sqlite3.connect(f"file:{d / 'events.sqlite'}?mode=ro", uri=True)
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        events = [
            (kind, json.loads(data))
            for kind, data in connection.execute("select kind,data from events order by seq")
        ]
        connection.close()
        assert events[-1] == ("terminal", terminal)
        bound = next(data for kind, data in events if kind == "input_bound")
        assert bound["files"] == initial_inputs[trial["task"]]
        assert bound["context"] == protocol["runtime"]
        assert bound["task_sha256"] == tasks[trial["task"]]["prompt_sha256"]
        grade = read(d / "grade/grade.json")
        assert grade == terminal["quality"]
        assert grade["quality_pass"] == terminal["quality_pass"]
        if grade["counts"]:
            assert read(d / "grade/counts.json") == grade["counts"]
        session = (
            read(d / "session/manifest.json") if (d / "session/manifest.json").exists() else {}
        )
        if session:
            assert session["state_removed"] and not (d / "private-state").exists()
            for name, digest in session["artifact_hashes"].items():
                assert sha(d / "session" / name) == digest
            assert (
                session["runtime_sources"]["binary_sha256"] == protocol["runtime"]["binary_sha256"]
            )
            assert session["runtime_sources"]["cami_files"] == protocol["runtime"]["cami_files"]
            assert (
                session["runtime_sources"]["adapter_files"] == protocol["runtime"]["adapter_files"]
            )
            assert session["image_id"] == protocol["runtime"]["image_id"]
        messages_path = d / "session/evidence/messages.json"
        messages = read(messages_path) if messages_path.exists() else []
        users = [m for m in messages if m.get("type") == "user"]
        if session.get("status") == "passed":
            assert len(users) == 1
            assert (
                hashlib.sha256(users[0]["text"].encode()).hexdigest()
                == tasks[trial["task"]]["prompt_sha256"]
            )
        assistants = [m for m in messages if m.get("type") == "assistant"]
        for message in assistants:
            for part in message.get("content", []):
                if part.get("type") == "tool":
                    name = part["name"]
                    counts = tool_counts[trial["arm"]]
                    counts[name] = counts.get(name, 0) + 1
        trace = d / "session/evidence/memory-backend-trace.jsonl"
        if trace.exists() and trial["arm"] == "cami":
            backend_wall += sum(
                json.loads(line).get("wall_seconds", 0)
                for line in trace.read_text().splitlines()
                if line.strip()
            )
        expected = {"providerID": "openai", "id": "gpt-6.1-sol", "variant": "high"}
        assert all(m["model"] == expected for m in assistants)
        if terminal["usage_complete"]:
            assert assistants and not any(
                m.get("error") or not m.get("time", {}).get("completed") for m in assistants
            )
            sums = dict.fromkeys(COMPONENTS, 0)
            for m in assistants:
                t = m["tokens"]
                cache = t["cache"]
                for field in ["input", "output", "reasoning"]:
                    sums[field] += t[field]
                sums["cache_read"] += cache["read"]
                sums["cache_write"] += cache["write"]
            assert sums == terminal["usage"]
            assert terminal["token_work"] == sum(sums[k] for k in COMPONENTS if k != "cache_read")
        elif terminal["token_work"] is not None:
            raise ValueError("incomplete usage cannot be a complete token-work value")
        verified.append(
            {
                **terminal,
                "session_status": session.get("status"),
                "terminal_sha256": sha(d / "terminal.json"),
                "evaluated_source_files": len(terminal["solution_source"]),
            }
        )
    assert len(verified) == 72
    task_rows = []
    for task in tasks.values():
        row = {"task": task["id"], "repository": task["repository"]}
        for arm in ["plain", "cami"]:
            rows = [
                x for x in verified if x["trial"]["task"] == task["id"] and x["trial"]["arm"] == arm
            ]
            assert len(rows) == 3
            usage_complete = all(x["usage_complete"] for x in rows)
            row[arm] = {
                "quality_passes": sum(x["quality_pass"] for x in rows),
                "operational_passes": sum(
                    x["session_status"] == "passed" and x["session"]["returncode"] == 0
                    for x in rows
                ),
                "time_mean": statistics.mean(x["pipeline_wall_seconds"] for x in rows),
                "time_min": min(x["pipeline_wall_seconds"] for x in rows),
                "time_max": max(x["pipeline_wall_seconds"] for x in rows),
                "token_work_mean": statistics.mean(x["token_work"] for x in rows)
                if usage_complete
                else None,
                "token_work_min": min(x["token_work"] for x in rows) if usage_complete else None,
                "token_work_max": max(x["token_work"] for x in rows) if usage_complete else None,
                "known_token_components": {
                    key: sum(x["usage"][key] or 0 for x in rows) for key in COMPONENTS
                },
                "usage_complete": usage_complete,
                "memory_lookup_calls": sum(x["memory_lookup_calls"] for x in rows),
                "memory_errors": sum(x["memory_errors"] for x in rows),
                "preparation_seconds": sum(x["preparation"]["wall_seconds"] for x in rows),
            }
        row["time_ratio"] = row["cami"]["time_mean"] / row["plain"]["time_mean"]
        row["token_work_ratio"] = (
            row["cami"]["token_work_mean"] / row["plain"]["token_work_mean"]
            if row["plain"]["token_work_mean"] and row["cami"]["token_work_mean"] is not None
            else None
        )
        task_rows.append(row)
    qualities = {arm: sum(x[arm]["quality_passes"] for x in task_rows) for arm in ["plain", "cami"]}
    operational = all(
        x["session_status"] == "passed" and x["session"]["returncode"] == 0 for x in verified
    )
    usage_complete = all(x["usage_complete"] for x in verified)
    repo_quality = {
        repo: {
            arm: sum(x[arm]["quality_passes"] for x in task_rows if x["repository"] == repo)
            for arm in ["plain", "cami"]
        }
        for repo in sorted({x["repository"] for x in task_rows})
    }
    median_time_ratio = statistics.median(x["time_ratio"] for x in task_rows)
    token_ratios = [x["token_work_ratio"] for x in task_rows]
    median_token_ratio = (
        statistics.median(token_ratios)
        if usage_complete and all(value is not None for value in token_ratios)
        else None
    )
    gates = {
        "all_sessions_operational": operational,
        "all_usage_complete": usage_complete,
        "minimum_cami_quality_30_of_36": qualities["cami"] >= 30,
        "no_total_quality_regression": qualities["cami"] >= qualities["plain"],
        "no_repository_quality_regression": all(
            x["cami"] >= x["plain"] for x in repo_quality.values()
        ),
        "time_improves_at_least_10_percent": median_time_ratio <= 0.90,
        "token_work_improves_at_least_10_percent": median_token_ratio is not None
        and median_token_ratio <= 0.90,
    }
    result = {
        "status": "completed_and_verified",
        "attempts": 72,
        "tasks": 12,
        "repetitions_per_arm": 3,
        "protocol_sha256": sha(REPORT / "protocol.json"),
        "quality_passes": qualities,
        "repository_quality": repo_quality,
        "median_paired_task_time_ratio": median_time_ratio,
        "median_paired_task_token_work_ratio": median_token_ratio,
        "gates": gates,
        "recommend_cami_by_default": all(gates.values()),
        "decision": "enable_for_tested_workload"
        if all(gates.values())
        else "reject_default_recommendation_for_tested_workload",
        "task_results": task_rows,
        "tool_counts": tool_counts,
        "observed_cami_backend_wall_seconds": backend_wall,
        "backend_timing_scope": "Nested observed constructor/lookup spans; excludes parts of imports/transport/trace append. Not a complete CPU profile or a bound for a full-language rewrite.",
        "usage_scope": "Observed OpenCode assistant responses with raw normalized components; no actual invoice reconciliation or visibility into hidden unexported provider calls. Known values from incomplete attempts are lower bounds, never exact totals.",
        "statistics_scope": "Median of 12 ratios of paired task means across 3 independent fresh sessions per condition. Tasks are the analysis units. Observed min/max are not confidence intervals. Scope is this frozen historical task set.",
    }
    (REPORT / "model-summary.json").write_text(json.dumps(result, indent=2) + "\n")
    (REPORT / "model-audit.json").write_text(
        json.dumps(
            {
                "status": "verified",
                "attempts": len(verified),
                "terminal_hashes": {x["trial"]["id"]: x["terminal_sha256"] for x in verified},
                "verified": "Schedule, durable journals, preserved graded sources, canonical inputs and evaluators, session artifact hashes, source/runtime pins, assistant identities and token-component sums, original decision arithmetic.",
            },
            indent=2,
        )
        + "\n"
    )
    print(json.dumps({k: v for k, v in result.items() if k != "task_results"}, indent=2))


if __name__ == "__main__":
    analyze()
