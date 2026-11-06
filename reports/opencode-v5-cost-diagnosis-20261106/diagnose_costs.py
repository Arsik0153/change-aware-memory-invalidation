"""Read-only cost attribution for terminal v5 trials; no model, profiler, or source execution."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            value.update(block)
    return value.hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def merged(intervals):
    result = []
    for start, end in sorted(intervals):
        if not finite(start) or not finite(end) or end < start:
            raise ValueError("invalid interval")
        if result and start <= result[-1][1]:
            result[-1][1] = max(end, result[-1][1])
        else:
            result.append([start, end])
    return result


def duration(intervals):
    return sum(end - start for start, end in merged(intervals))


def stats(values):
    known = [value for value in values if value is not None]
    return {
        "n": len(known),
        "missing": len(values) - len(known),
        "sum": sum(known) if known else None,
        "median": statistics.median(known) if known else None,
        "min": min(known) if known else None,
        "max": max(known) if known else None,
    }


def is_memory(name):
    return name == "memory_lookup" or name.endswith("_memory_lookup")


def timing(tool):
    row = tool.get("time", {})
    if (
        all(finite(row.get(key)) for key in ("created", "ran", "completed"))
        and row["created"] <= row["ran"] <= row["completed"]
    ):
        return [row[key] / 1000 for key in ("created", "ran", "completed")]
    return None


def command_seconds(row):
    value = row.get("wall_seconds")
    return value if finite(value) and value >= 0 else None


def timeline(messages, trial_id):
    users = [m.get("time", {}).get("created") for m in messages if m.get("type") == "user"]
    idle = [m.get("time", {}).get("created") for m in messages if m.get("type") == "idle"]
    tools, assistants = [], []
    for message in messages:
        if message.get("type") == "assistant":
            t = message.get("time", {})
            if (
                finite(t.get("created"))
                and finite(t.get("completed"))
                and t["completed"] >= t["created"]
            ):
                assistants.append((t["created"] / 1000, t["completed"] / 1000))
            for part in message.get("content", []):
                if part.get("type") != "tool":
                    continue
                stamp = timing(part)
                tools.append(
                    {
                        "trial_id": trial_id,
                        "message_id": message["id"],
                        "call_id": part.get("id"),
                        "tool": part.get("name"),
                        "memory": is_memory(part.get("name", "")),
                        "status": part.get("state", {}).get("status"),
                        "timestamps_valid": stamp is not None,
                        "created": stamp[0] if stamp else None,
                        "ran": stamp[1] if stamp else None,
                        "completed": stamp[2] if stamp else None,
                        "execution_seconds": stamp[2] - stamp[1] if stamp else None,
                        "created_to_ran_seconds": stamp[1] - stamp[0] if stamp else None,
                    }
                )
        elif message.get("type") == "shell":
            # No such row is assumed. Preserve unsupported shapes instead of fabricating ran time.
            tools.append(
                {
                    "trial_id": trial_id,
                    "message_id": message.get("id"),
                    "call_id": message.get("id"),
                    "tool": "shell_message",
                    "memory": False,
                    "status": message.get("status"),
                    "timestamps_valid": False,
                    "created": None,
                    "ran": None,
                    "completed": None,
                    "execution_seconds": None,
                    "created_to_ran_seconds": None,
                }
            )
    if len({tool["call_id"] for tool in tools}) != len(tools):
        raise ValueError("duplicate tool call identity")
    valid = [tool for tool in tools if tool["timestamps_valid"]]
    memory = [(tool["ran"], tool["completed"]) for tool in valid if tool["memory"]]
    native = [(tool["ran"], tool["completed"]) for tool in valid if not tool["memory"]]
    all_exec = memory + native
    if not users or not idle or not all(finite(x) for x in users + idle):
        window = None
    else:
        window = (min(users) / 1000, max(idle) / 1000)
    issues = []
    if window is None or window[1] < window[0]:
        issues.append("missing_or_invalid_user_to_idle_window")
    elif any(start < window[0] or end > window[1] for start, end in all_exec + assistants):
        issues.append("recorded_span_outside_user_to_idle_window")
    if len(valid) != len(tools):
        issues.append("tool_timestamps_missing_or_invalid")
    union = duration(all_exec)
    mem_union, native_union = duration(memory), duration(native)
    tool_stats = {}
    for name in sorted({tool["tool"] for tool in tools}):
        rows = [tool for tool in tools if tool["tool"] == name]
        tool_stats[name] = {
            "count": len(rows),
            "status_counts": dict(Counter(tool["status"] for tool in rows)),
            "execution_sum_seconds_nonadditive": sum(
                tool["execution_seconds"] or 0 for tool in rows
            ),
            "execution_union_seconds_nonadditive": duration(
                [(tool["ran"], tool["completed"]) for tool in rows if tool["timestamps_valid"]]
            ),
            "created_to_ran_sum_seconds_nonadditive": sum(
                tool["created_to_ran_seconds"] or 0 for tool in rows
            ),
        }
    span = window[1] - window[0] if window and not issues else None
    result = {
        "clock": "published API epoch milliseconds; finite/order/window checks only; no separate monotonic/provider clock",
        "timestamp_issues": issues,
        "tool_count": len(tools),
        "valid_tool_timestamps": len(valid),
        "message_type_counts": dict(Counter(m.get("type") for m in messages)),
        "user_to_idle_seconds": span,
        "all_tool_execution_union_seconds": union,
        "memory_execution_union_seconds": mem_union,
        "native_execution_union_seconds": native_union,
        "cross_memory_native_execution_overlap_seconds": mem_union + native_union - union,
        "native_only_execution_seconds": union - mem_union,
        "non_tool_execution_seconds": span - union if span is not None else None,
        "assistant_message_union_seconds_nonadditive": duration(assistants),
        "preexecution_union_seconds_nonadditive": duration(
            [(tool["created"], tool["ran"]) for tool in valid]
        ),
        "preexecution_interpretation": "created-to-ran may contain streamed argument generation, scheduling and dispatch; not pure queue/tool/model wait",
        "non_tool_interpretation": "unattributed session API span outside recorded tool execution; model/provider streaming, waits and orchestration not separately identifiable",
        "tools": tool_stats,
    }
    return result, tools


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def diagnose(run, published, output):
    started = time.monotonic()
    study_path, plan_path = run / "frozen-study.json", run / "plan.json"
    study, plan = load(study_path), load(plan_path)["trials"]
    if (
        study["bundle_kind"] != "development"
        or len(plan) != 36
        or len({r["id"] for r in plan}) != 36
    ):
        raise ValueError("fixed development36 plan required")
    published_summary = load(published / "summary.json")
    if sha(study_path) != published_summary["study_sha256"]:
        raise ValueError("published study binding mismatch")
    consumed = {
        str(study_path): sha(study_path),
        str(plan_path): sha(plan_path),
        str(published / "summary.json"): sha(published / "summary.json"),
    }
    verified_count = 0
    results, tool_rows, preparations = [], [], []
    for trial in plan:
        directory = run / "trials" / trial["id"]
        terminal_path = directory / "terminal.json"
        terminal = load(terminal_path)
        if terminal["trial"] != trial:
            raise ValueError("terminal/plan mismatch")
        for name, expected in terminal["artifact_hashes"].items():
            relative = Path(name)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or any(
                    p in {"private-state", "server-private", "private-export-client"}
                    for p in relative.parts
                )
            ):
                raise ValueError("unsafe/private artifact reference")
            path = directory / relative
            if path.is_symlink() or not path.is_file() or sha(path) != expected:
                raise ValueError("terminal artifact mismatch: " + str(path))
            verified_count += 1
        actual_names = set()
        for folder, directories, files in os.walk(directory, followlinks=False):
            for name in directories + files:
                path = Path(folder) / name
                if (
                    name in {"private-state", "server-private", "private-export-client"}
                    or path.is_symlink()
                ):
                    raise ValueError("private/nonregular trial entry refused")
                if path.is_file() and path.name != "terminal.json":
                    actual_names.add(path.relative_to(directory).as_posix())
        if actual_names != set(terminal["artifact_hashes"]):
            raise ValueError("terminal artifact coverage mismatch")
        consumed[str(terminal_path)] = sha(terminal_path)

        def read_public(name):
            path = directory / name
            if name not in terminal["artifact_hashes"]:
                raise ValueError("public input not bound by terminal: " + name)
            consumed[str(path)] = terminal["artifact_hashes"][name]
            return load(path)

        costs = terminal["costs"]
        for name in [
            "charged_host_wall_seconds",
            "construction_host_wall_seconds",
            "session_host_wall_seconds",
            "guard_and_orchestration_host_wall_seconds",
            "infrastructure_host_wall_seconds",
            "controller_total_host_wall_seconds",
        ]:
            if not finite(costs.get(name)):
                raise ValueError("missing cost: " + name)
        if (
            abs(
                costs["charged_host_wall_seconds"]
                - sum(
                    costs[name]
                    for name in [
                        "construction_host_wall_seconds",
                        "session_host_wall_seconds",
                        "guard_and_orchestration_host_wall_seconds",
                    ]
                )
            )
            > 1e-6
        ):
            raise ValueError("top-level accounting mismatch")
        api, calls = timeline(read_public("session/evidence/messages.json"), trial["id"])
        tool_rows.extend(calls)
        worker = read_public("session/evidence/manifest.json")
        auth = read_public("session/credential-transfer.json")
        readiness = read_public("session/evidence/readiness.json")
        settling = read_public("session/evidence/tool-registry-stabilization.json")
        mcp = read_public("session/evidence/mcp-readiness.json")
        trace_name = "session/evidence/memory-backend-trace.jsonl"
        trace = []
        if trial["arm"] != "plain":
            path = directory / trace_name
            consumed[str(path)] = terminal["artifact_hashes"][trace_name]
            trace = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        lookup = [event for event in trace if event.get("event") == "memory_lookup"]
        starts = [event for event in trace if event.get("event") == "server_start"]
        if len(lookup) != sum(call["memory"] for call in calls):
            raise ValueError("lookup/API count mismatch")
        for event in lookup:
            if (
                event.get("backend") != trial["arm"]
                or event.get("error") is not None
                or command_seconds(event) is None
            ):
                raise ValueError("failed or unmeasured memory lookup")
        if trial["stage"] == 1 and trial["arm"] != "plain":
            operation = read_public("construction/preparation-operation.json")
            memory = run / "namespaces" / f"r{trial['repetition']}-{trial['arm']}" / "memory"
            relative = "prepared/construction-metrics.json"
            path = memory / relative
            if sha(path) != terminal["memory_files_after"][relative]:
                raise ValueError("namespace prepare metrics no longer match frozen terminal")
            consumed[str(path)] = sha(path)
            metrics = load(path)
            preparations.append(
                {
                    "trial_id": trial["id"],
                    "arm": trial["arm"],
                    "repetition": trial["repetition"],
                    "host_inclusive_seconds": costs["construction_host_wall_seconds"],
                    "seed_generation_process_seconds": operation["commands"][0]["wall_seconds"],
                    "adapter_prepare_process_seconds": operation["commands"][1]["wall_seconds"],
                    "worker_seconds": operation["worker_wall_seconds"],
                    "adapter_function_seconds": metrics["wall_seconds"],
                    "origin_authentication_seconds": metrics["literal_origin_reauthentication"][
                        "wall_seconds"
                    ],
                    "catalog_context_capture_seconds": metrics.get("catalog_capture", {}).get(
                        "wall_seconds"
                    ),
                    "registration_batch_seconds": metrics.get("registration_batch", {}).get(
                        "wall_seconds"
                    ),
                    "metrics": metrics,
                    "operation": operation,
                }
            )
        row = {
            "trial_id": trial["id"],
            "arm": trial["arm"],
            "repetition": trial["repetition"],
            "stage": trial["stage"],
            "status": terminal["status"],
            "operational_status": terminal["operational_status"],
            "quality": terminal["quality"],
            "accounting": costs,
            "api": api,
            "session_components_nested": {
                "worker_seconds": worker["worker_wall_seconds"],
                "credential_transfer_seconds": auth["wall_seconds"],
                "server_readiness_seconds": readiness["readiness_wall_seconds"],
                "registry_settling_seconds": settling["elapsed_seconds"],
                "mcp_readiness_last_observation_seconds": mcp.get("observations", [{}])[-1].get(
                    "elapsed_seconds"
                )
                if mcp.get("observations")
                else None,
                "worker_minus_api_window_seconds": worker["worker_wall_seconds"]
                - api["user_to_idle_seconds"]
                if api["user_to_idle_seconds"] is not None
                else None,
            },
            "memory_backend_nested": {
                "lookup_count": len(lookup),
                "lookup_seconds": sum(event["wall_seconds"] for event in lookup),
                "lookup_cpu_seconds": sum(
                    event["cpu_seconds_self_and_completed_children"] for event in lookup
                ),
                "server_constructor_seconds": sum(event["wall_seconds"] for event in starts),
                "generation_changed": [event.get("generation_changed") for event in lookup],
                "checked_state_type_counts_not_calls": [
                    event.get("states_checked_type") for event in lookup
                ],
                "lookup_events_without_full_payload": [
                    {k: v for k, v in event.items() if k != "response_audit"} for event in lookup
                ],
                "observe_refresh_separate_seconds": None,
                "observe_refresh_note": "No fine-grained timer in frozen traces; refresh/import/ranking/serialization/storage are nested in lookup. State types are not validator call counts.",
            },
            "session_cgroup": costs["session_cgroup"],
            "construction_cgroup": costs.get("construction_cgroup"),
        }
        results.append(row)

    def scalar(row):
        return {
            "charged_seconds": row["accounting"]["charged_host_wall_seconds"],
            "construction_seconds": row["accounting"]["construction_host_wall_seconds"],
            "session_seconds": row["accounting"]["session_host_wall_seconds"],
            "guard_seconds": row["accounting"]["guard_and_orchestration_host_wall_seconds"],
            "infrastructure_seconds_separate": row["accounting"][
                "infrastructure_host_wall_seconds"
            ],
            "session_cgroup_cpu_seconds": row["session_cgroup"]["cpu_seconds"],
            "api_span_seconds": row["api"]["user_to_idle_seconds"],
            "all_tool_execution_union_seconds": row["api"]["all_tool_execution_union_seconds"],
            "memory_tool_execution_union_seconds": row["api"]["memory_execution_union_seconds"],
            "native_tool_execution_union_seconds": row["api"]["native_execution_union_seconds"],
            "non_tool_execution_seconds": row["api"]["non_tool_execution_seconds"],
            "backend_lookup_seconds": row["memory_backend_nested"]["lookup_seconds"],
            "backend_lookup_cpu_seconds": row["memory_backend_nested"]["lookup_cpu_seconds"],
            "backend_server_constructor_seconds": row["memory_backend_nested"][
                "server_constructor_seconds"
            ],
            "credential_transfer_seconds_nested": row["session_components_nested"][
                "credential_transfer_seconds"
            ],
            "worker_minus_api_window_seconds_nested": row["session_components_nested"][
                "worker_minus_api_window_seconds"
            ],
            "native_tool_count": sum(
                value["count"] for name, value in row["api"]["tools"].items() if not is_memory(name)
            ),
            "memory_tool_count": row["memory_backend_nested"]["lookup_count"],
        }

    arms = {}
    blocks = []
    for arm in ["plain", "static", "cami"]:
        rows = [row for row in results if row["arm"] == arm]
        arms[arm] = {key: stats([scalar(row)[key] for row in rows]) for key in scalar(rows[0])}
        for repetition in range(1, 4):
            selected = [row for row in rows if row["repetition"] == repetition]
            blocks.append(
                {
                    "arm": arm,
                    "repetition": repetition,
                    **{
                        key: sum(scalar(row)[key] for row in selected)
                        if all(scalar(row)[key] is not None for row in selected)
                        else None
                        for key in scalar(rows[0])
                    },
                }
            )
    pairs = []
    for comparison in ["static", "plain"]:
        for repetition in range(1, 4):
            left = next(b for b in blocks if b["arm"] == "cami" and b["repetition"] == repetition)
            right = next(
                b for b in blocks if b["arm"] == comparison and b["repetition"] == repetition
            )
            pairs.append(
                {
                    "comparison": "cami_minus_" + comparison,
                    "repetition": repetition,
                    **{
                        key: left[key] - right[key]
                        if left[key] is not None and right[key] is not None
                        else None
                        for key in scalar(results[0])
                    },
                }
            )
    prepare_summary = {
        arm: {
            key: stats([row[key] for row in preparations if row["arm"] == arm])
            for key in [
                "host_inclusive_seconds",
                "seed_generation_process_seconds",
                "adapter_prepare_process_seconds",
                "worker_seconds",
                "adapter_function_seconds",
                "origin_authentication_seconds",
                "catalog_context_capture_seconds",
                "registration_batch_seconds",
            ]
        }
        for arm in ["static", "cami"]
    }
    top_preexecution = sorted(
        tool_rows, key=lambda row: row["created_to_ran_seconds"] or 0, reverse=True
    )[:15]
    output_report = {
        "status": "complete_read_only_diagnosis",
        "planned_and_terminal_trials": 36,
        "operational_status_counts": dict(Counter(row["operational_status"] for row in results)),
        "quality_counts": dict(Counter(row["quality"] for row in results)),
        "primary_efficiency_eligible": published_summary["primary_efficiency_eligible"],
        "excluded_trials": [],
        "verified_terminal_artifact_hashes": verified_count,
        "arm_trial_summaries": arms,
        "four_stage_blocks": blocks,
        "paired_descriptive_deltas": pairs,
        "preparation_summary_nested": prepare_summary,
        "preparation_records": preparations,
        "largest_tool_created_to_ran_intervals_nonadditive": top_preexecution,
        "trials": results,
        "inputs_sha256": consumed,
        "source_identity": {
            "study_pins": study["pins"],
            "model": study["model"],
            "image": study["image"],
        },
        "limitations": [
            "Observational3repetitions perarm; different generated tool sequences and provider behavior are not causal treatment attribution.",
            "One original operational failure is retained; all36-primary eligibility remains false.",
            "Top-level charged=construction+session+guard. Infrastructure separate; nested components never added again.",
            "Native/memory execution uses interval unions of ran-to-completed; created-to-ran may overlap provider argument streaming and is not tool execution or pure model wait.",
            "Non-tool API residual includes provider/model streaming, waits and coordination. No direct provider wait/compute meter exists.",
            "Standalone observe/refresh time cannot be isolated in original traces; first CAMI import is inside each session first lookup.",
            "Backend spans include serialization/storage observation, exclude JSON-RPC I/O/trace append; source-read state counts are not validator calls.",
            "Current host load is irrelevant to historical measurements; no new benchmark or live profile was executed.",
            "No performance improvements are measured here. Proposed optimizations need a separately authorized bounded profile/verification.",
        ],
        "evaluation_only_wall_seconds": time.monotonic() - started,
        "model_calls": 0,
        "Docker_calls": 0,
        "heldout_reads": False,
    }
    save(output / "report.json", output_report)
    write_csv(
        output / "trials.csv",
        [
            {
                "trial_id": row["trial_id"],
                "arm": row["arm"],
                "repetition": row["repetition"],
                "stage": row["stage"],
                "status": row["status"],
                **scalar(row),
            }
            for row in results
        ],
    )
    write_csv(output / "blocks.csv", blocks)
    write_csv(output / "paired-deltas.csv", pairs)
    write_csv(output / "tool-intervals.csv", tool_rows)
    return output_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--published", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("new output only; archived results must not be overwritten")
    args.out.mkdir(parents=True)
    try:
        result = diagnose(args.run.resolve(), args.published.resolve(), args.out.resolve())
    except BaseException as error:
        save(
            args.out / "failure.json",
            {"status": "failed_preserved", "error": type(error).__name__ + ": " + str(error)},
        )
        raise
    print(
        json.dumps(
            {
                "status": result["status"],
                "trials": len(result["trials"]),
                "verified_hashes": result["verified_terminal_artifact_hashes"],
            }
        )
    )


if __name__ == "__main__":
    main()
