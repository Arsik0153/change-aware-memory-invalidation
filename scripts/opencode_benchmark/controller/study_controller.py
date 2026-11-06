"""Generic, explicitly gated sequential maintenance study. Default: plan only."""

from __future__ import annotations

import argparse
from pathlib import Path
import resource
import time

from study_common import bytes_used, digest, file_hashes, inventory, read, write
from study_ledger import complete, next_trials, summarize, terminals, verify_binding
from study_runtime import grade, origin_memory, regression_allowance, session, verify_memory
from study_schema import make_study, plan, validate
from study_workspace import capture, create_namespace, reset, verify_namespace

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "src/cami").is_dir())


def owned_output(path):
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("output ownership path must not contain symlinks")
    path = path.absolute()
    if not path.is_relative_to(ROOT / "runs") or path == ROOT / "runs":
        raise ValueError("controller output must be explicitly owned beneath runs/")
    return path


def cgroup_delta(directory, before_name, after_name):
    def load(name):
        item = read(directory / name)
        value = read_cgroup(item)
        return dict(line.split() for line in value["cpu.stat"].splitlines()), value

    try:
        before, _ = load(before_name)
        after, raw = load(after_name)
        return {
            "cpu_seconds": (int(after["usage_usec"]) - int(before["usage_usec"])) / 1e6,
            "peak_memory_bytes": int(raw["memory.peak"]),
            "raw_after": raw,
        }
    except (FileNotFoundError, KeyError, ValueError):
        return {"unavailable": True, "reason": "incomplete cgroup evidence; never imputed as zero"}


def read_cgroup(item):
    import json

    return json.loads(item["stdout"])


def run_trial(study, study_sha, output, trial, previous):
    directory = output / "trials" / trial["id"]
    directory.mkdir(parents=True, exist_ok=False)
    write(
        directory / "attempt.json", {"trial": trial, "study_sha256": study_sha, "run_model": True}
    )
    started, cpu = time.monotonic(), time.process_time()
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    record = {
        "trial": trial,
        "status": "failed",
        "memory_usable": False,
        "failures": [],
        "session_status": "not_started",
        "quality": "not_evaluated",
        "usage": {"session_tokens": None, "status": "not_available"},
        "operational_status": "failed",
        "costs": {
            "complete": False,
            "construction_host_wall_seconds": 0,
            "session_host_wall_seconds": 0,
            "infrastructure_host_wall_seconds": 0,
        },
    }
    namespace = output / "namespaces" / f"r{trial['repetition']}-{trial['arm']}"
    (task,) = [t for t in study["normalized"]["tasks"] if t["id"] == trial["task"]]
    workspace = memory = None
    phase = "preflight"
    try:
        validate(study, execute=True)
        if previous and not previous["memory_usable"]:
            raise ValueError("predecessor left unusable memory namespace; dependent trial blocked")
        if trial["stage"] == 1:
            create_namespace(namespace, study_sha)
        workspace, memory = verify_namespace(namespace, study_sha)
        if previous:
            if file_hashes(memory) != previous["memory_files_after"]:
                raise ValueError("persistent memory differs from prior terminal state")
        phase = "canonical_reset"
        fixture_start = time.monotonic()
        canonical = reset(
            namespace,
            Path(study["bundle_path"]) / task["archive"],
            task["archive_sha256"],
            study_sha,
        )
        write(directory / "canonical-reset.json", canonical)
        record["costs"]["infrastructure_host_wall_seconds"] += time.monotonic() - fixture_start
        if trial["stage"] == 1 and trial["arm"] != "plain":
            phase = "origin_construction"
            tick = time.monotonic()
            try:
                immutable = origin_memory(
                    study, workspace, memory, directory / "construction", trial["arm"]
                )
            finally:
                record["costs"]["construction_host_wall_seconds"] = time.monotonic() - tick
        else:
            immutable = verify_memory(
                study, memory, trial["arm"], previous.get("immutable_memory") if previous else None
            )
        if inventory(workspace, omit_git=True) != canonical["canonical_files"]:
            raise ValueError("canonical working source changed during preparation")
        phase = "baseline_regression_infrastructure"
        baseline_started = time.monotonic()
        try:
            allowance, baseline_sha = regression_allowance(study, task, workspace, output)
            record["regression_allowance_sha256"] = baseline_sha
        finally:
            record["costs"]["infrastructure_host_wall_seconds"] += (
                time.monotonic() - baseline_started
            )
        record["immutable_memory"] = immutable
        record["memory_usable"] = True
        write(directory / "memory-before.json", file_hashes(memory))
        prompt = directory / "prompt.txt"
        prompt.write_text(task["prompt"])
        phase = "model_session"
        session_start = time.monotonic()
        try:
            manifest = session(study, trial, workspace, memory, prompt, directory / "session")
            record["session_manifest_sha256"] = digest(directory / "session/manifest.json")
            record["session_status"] = manifest["status"]
        except Exception as error:
            record["session_status"] = "failed"
            record["failures"].append(
                {"phase": phase, "failure": type(error).__name__ + ": " + str(error)}
            )
        finally:
            usage_path = directory / "session/evidence/usage.json"
            if usage_path.exists():
                try:
                    record["usage"] = read(usage_path)
                except (OSError, ValueError) as usage_error:
                    record["usage"] = {
                        "session_tokens": None,
                        "status": "unreadable",
                        "failure": type(usage_error).__name__ + ": " + str(usage_error),
                    }
            record["costs"]["session_host_wall_seconds"] = time.monotonic() - session_start
        phase = "memory_integrity"
        verify_memory(study, memory, trial["arm"], immutable)
        phase = "source_export_and_fixed_grading"
        infra_start = time.monotonic()
        try:
            record["patch"] = capture(
                workspace, canonical["canonical_files"], directory / "candidate"
            )
            quality = grade(
                study, task, directory / "candidate", directory / "evaluation", allowance=allowance
            )
            record["quality"] = quality["status"]
        finally:
            record["costs"]["infrastructure_host_wall_seconds"] += time.monotonic() - infra_start
        validate(study, execute=True)
        record["operational_status"] = "passed" if not record["failures"] else "failed"
        record["status"] = (
            "passed" if record.get("quality") == "pass" and not record["failures"] else "failed"
        )
        record["costs"]["complete"] = True
    except BaseException as error:
        record["failures"].append(
            {"phase": phase, "failure": type(error).__name__ + ": " + str(error)}
        )
        if phase not in {"model_session", "source_export_and_fixed_grading"}:
            record["memory_usable"] = False
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
    finally:
        if memory and memory.exists():
            try:
                record["memory_files_after"] = file_hashes(memory)
                record["memory_bytes_after"] = bytes_used(memory)
            except BaseException as error:
                record["memory_usable"] = False
                record["failures"].append(
                    {"phase": "final_memory_inventory", "failure": str(error)}
                )
        total_wall = time.monotonic() - started
        record["costs"]["controller_total_host_wall_seconds"] = total_wall
        record["costs"]["charged_host_wall_seconds"] = max(
            0, total_wall - record["costs"]["infrastructure_host_wall_seconds"]
        )
        record["costs"]["guard_and_orchestration_host_wall_seconds"] = max(
            0,
            record["costs"]["charged_host_wall_seconds"]
            - record["costs"]["construction_host_wall_seconds"]
            - record["costs"]["session_host_wall_seconds"],
        )
        record["costs"]["controller_self_cpu_seconds"] = time.process_time() - cpu
        usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        record["costs"]["host_child_cpu_seconds"] = (
            usage_after.ru_utime
            + usage_after.ru_stime
            - usage_before.ru_utime
            - usage_before.ru_stime
        )
        if (directory / "construction").exists():
            record["costs"]["construction_cgroup"] = cgroup_delta(
                directory / "construction", "before.json", "after.json"
            )
        if (directory / "session").exists():
            record["costs"]["session_cgroup"] = cgroup_delta(
                directory / "session", "cgroup-before-auth.json", "cgroup-after-worker.json"
            )
        result = complete(directory, record)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path)
    parser.add_argument("--study-sha256")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-model", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--one-trial", help="Only the next planned trial ID, development bundle only"
    )
    parser.add_argument("--make-study", action="store_true")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--kind", choices=["development", "heldout"], default="development")
    parser.add_argument("--harness", type=Path)
    parser.add_argument("--image")
    parser.add_argument("--runtime-manifest", type=Path)
    parser.add_argument("--cami-source", type=Path, default=ROOT / "src")
    parser.add_argument("--adapter", type=Path, default=ROOT / "integrations/opencode")
    parser.add_argument("--memory-response-format", choices=["full", "compact", "readable"])
    parser.add_argument("--service-tier", choices=["auto", "priority"])
    args = parser.parse_args()
    if args.make_study:
        if args.run_model or args.resume or not all([args.bundle, args.harness, args.image]):
            parser.error("--make-study requires bundle/harness/image, never run-model/resume")
        output = owned_output(args.out)
        output.mkdir(parents=True, exist_ok=False)
        data = make_study(
            args.bundle.resolve(),
            args.kind,
            args.harness.resolve(),
            args.image,
            args.cami_source.resolve(),
            args.adapter.resolve(),
            Path(__file__).parent,
            args.runtime_manifest.resolve() if args.runtime_manifest else None,
            args.memory_response_format or "full",
            args.service_tier,
        )
        write(output / "study.json", data)
        print(output / "study.json")
        return
    if args.memory_response_format is not None:
        parser.error("memory response format is frozen in --study; select it only with --make-study")
    if args.service_tier is not None:
        parser.error("service tier is frozen in --study; select it only with --make-study")
    if not args.study:
        parser.error("--study is required")
    study_sha = digest(args.study)
    if args.study_sha256 and args.study_sha256 != study_sha:
        parser.error("study SHA mismatch")
    if args.run_model and not args.study_sha256:
        parser.error("--run-model requires exact --study-sha256")
    study = validate(read(args.study), execute=args.run_model)
    if args.one_trial and (not args.run_model or study["bundle_kind"] != "development"):
        parser.error("--one-trial is only for explicit development execution")
    planned = plan(study)
    output = owned_output(args.out)
    if args.resume:
        verify_binding(output, study_sha, args.run_model)
    else:
        output.mkdir(parents=True, exist_ok=False)
        (output / "trials").mkdir()
        (output / "namespaces").mkdir()
        write(output / "frozen-study.json", study)
        write(
            output / "run.json",
            {
                "study_path": str(args.study.absolute()),
                "study_sha256": study_sha,
                "mode": "model" if args.run_model else "plan",
            },
        )
        write(
            output / "plan.json",
            {"trials": planned, "model_calls": 0, "default_plan_only": not args.run_model},
        )
    if not args.run_model:
        print("Plan only:36 trials; zero containers, zero model calls.")
        return
    records = terminals(output, planned, recover=args.resume)
    pending = list(next_trials(planned, records))
    if args.one_trial and (not pending or args.one_trial != pending[0]["id"]):
        parser.error("--one-trial must name the next planned pending trial")
    for trial in pending:
        previous = records.get(trial["predecessor"])
        if trial["predecessor"] and previous is None:
            raise ValueError("missing prior stage; no out-of-order memory initialization")
        records[trial["id"]] = run_trial(study, study_sha, output, trial, previous)
        if args.one_trial:
            break
    report_dir = output / "summaries"
    report_dir.mkdir(exist_ok=True)
    write(
        report_dir / f"summary-{len(list(report_dir.iterdir())) + 1:04d}.json", summarize(records)
    )
    print(f"{len(records)}/36 terminal trials; no retries.")


if __name__ == "__main__":
    main()
