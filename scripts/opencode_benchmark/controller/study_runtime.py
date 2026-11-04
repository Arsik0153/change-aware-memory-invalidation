"""Bounded Docker construction, native session, and independent fixed-test grading."""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import shutil
import sys
import time

from study_common import (
    DOCKER,
    bytes_used,
    chown,
    command,
    digest,
    verify_files,
    file_hashes,
    read,
    require_success,
    write,
)
from study_workspace import evaluation_workspace


def container(
    study,
    mounts,
    argv,
    out,
    *,
    network="none",
    timeout=900,
    pythonpath="/opt/cami-src:/opt/cami-deps",
    workdir="/",
):
    """Record launch, complete cgroup work, observed storage, and cleanup even on failure."""
    out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    report = {"status": "started", "image": study["image"], "model_calls": 0}
    cid = None
    base = [
        *DOCKER,
        "run",
        "--detach",
        "--pull=never",
        "--init",
        "--user",
        "65534:65534",
        "--network",
        network,
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--read-only",
        "--memory=2g",
        "--cpus=2",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=512m",
        "--workdir",
        workdir,
        "--env",
        "PYTHONPATH=" + pythonpath,
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
        "--env",
        "HOME=/tmp",
        "--label",
        "cami.research.owned=true",
    ]
    for source, target, readonly in mounts:
        base += [
            "--mount",
            f"type=bind,src={source},dst={target}" + (",readonly" if readonly else ""),
        ]
    try:
        launch = command(
            [
                *base,
                "--entrypoint",
                "python",
                study["image"],
                "-I",
                "-c",
                "import time;time.sleep(86400)",
            ]
        )
        write(out / "launch.json", launch)
        require_success(launch)
        cid = launch["stdout"].strip()
        report["container_id"] = cid
        cg = "import json;from pathlib import Path;print(json.dumps({n:(Path('/sys/fs/cgroup')/n).read_text().strip() for n in ['cpu.stat','cpu.max','memory.current','memory.peak','memory.max']}))"
        for label, operation in [
            ("before", ["python", "-I", "-c", cg]),
            ("work", argv),
            ("after", ["python", "-I", "-c", cg]),
        ]:
            result = command(
                [*DOCKER, "exec", cid, *operation], timeout=timeout if label == "work" else 30
            )
            write(out / (label + ".json"), result)
            if label != "work":
                require_success(result)
            else:
                report["work_passed"] = result["returncode"] == 0 and not result["timeout"]
        report["status"] = "passed" if report["work_passed"] else "failed"
    except BaseException as error:
        report.update(status="failed", failure=type(error).__name__ + ": " + str(error))
        raise
    finally:
        if cid:
            cleanup = command([*DOCKER, "rm", "--force", cid])
            write(out / "cleanup.json", cleanup)
            report["cleanup_passed"] = cleanup["returncode"] == 0
            if not report["cleanup_passed"]:
                report["status"] = "failed"
        report.update(
            total_host_wall_seconds=time.monotonic() - start,
            limits={"cpus": 2, "memory_bytes": 2147483648, "network": network},
            artifact_hashes=file_hashes(out),
        )
        write(out / "report.json", report)
    return report


def origin_memory(study, workspace, memory, out, backend):
    if any(memory.iterdir()):
        raise ValueError("origin memory must be new and empty")
    bundle = Path(study["bundle_path"])
    chown(workspace)
    chown(memory)
    seed = study["normalized"]["seed"]
    mounts = [
        (workspace, "/workspace", False),
        (memory, "/memory", False),
        (Path(study["cami_source"]), "/opt/cami-src", True),
        (Path(study["adapter"]), "/opt/memory-adapter", True),
        (bundle / "seed_source_notes.py", "/opt/seed_source_notes.py", True),
        (Path(__file__).parent / "preparation_worker.py", "/opt/preparation_worker.py", True),
    ]
    # Backend supplied by caller; every memory arm pays its own identical source generation.
    if backend not in {"static", "cami"}:
        raise ValueError("unexpected memory namespace")
    argv = [
        "python",
        "/opt/preparation_worker.py",
        "--backend",
        backend,
        "--seed-sha256",
        digest(bundle / seed),
    ]
    argv += [arg for root in study["normalized"]["source_roots"] for arg in ["--source-root", root]]
    report = container(study, mounts, argv, out, timeout=660)
    if (memory / "preparation-operation.json").exists():
        shutil.copyfile(memory / "preparation-operation.json", out / "preparation-operation.json")
    if report["status"] != "passed":
        raise RuntimeError("origin preparation failed; evidence retained")
    hashes = verify_memory(study, memory, backend)
    for record in read(memory / "prepared/catalog.json")["records"]:
        source = record["source"]
        path = workspace / source["path"]
        if source["sha256"] != digest(path) or source["size"] != path.stat().st_size:
            raise ValueError("catalog source is not the canonical origin byte binding")
    return hashes


def verify_memory(study, memory, backend, expected=None):
    if backend == "plain":
        if any(memory.iterdir()):
            raise ValueError("plain dummy memory must remain empty")
        return {}
    bundle = Path(study["bundle_path"])
    spec = read(bundle / study["normalized"]["seed"])
    if digest(memory / "seed/seed-spec.json") != digest(bundle / study["normalized"]["seed"]):
        raise ValueError("memory origin seed changed")
    catalog = read(memory / "prepared/catalog.json")
    binding = read(memory / "prepared/binding.json")
    if (
        binding["backend"] != backend
        or binding["repo"] != "/workspace"
        or binding["catalog_path"] != "/memory/prepared/catalog.json"
    ):
        raise ValueError("binding backend/workspace/catalog identity changed")
    if binding["state_home"] != ("/memory/cami-state" if backend == "cami" else None):
        raise ValueError("binding state identity changed")
    semantic_sha = hashlib.sha256(
        json.dumps(
            catalog, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    if binding["catalog_sha256"] != semantic_sha:
        raise ValueError("canonical catalog binding changed")
    originals = {r["id"]: r for r in spec["records"]}
    if len(catalog["records"]) != len(originals) or {r["id"] for r in catalog["records"]} != set(
        originals
    ):
        raise ValueError("catalog coverage differs from frozen origin seed")
    for record in catalog["records"]:
        original, payload = originals[record["id"]], record["payload"]
        if original["kind"] != "note" or any(
            payload[key] != original[key] for key in ["subject", "note_key", "text"]
        ):
            raise ValueError("catalog altered seed note payload")
        source = record["source"]
        if source != payload["sources"][0] or len(payload["sources"]) != 1:
            raise ValueError("catalog source inconsistency")
    if backend == "cami" and set(binding["mapping"]) != set(originals):
        raise ValueError("CAMI mapping does not cover exact catalog")
    hashes = {
        name: digest(memory / name)
        for name in ["seed/seed-spec.json", "prepared/catalog.json", "prepared/binding.json"]
    }
    if expected is not None and expected != hashes:
        raise ValueError("immutable memory payload/binding changed during trial")
    return hashes


def session(study, trial, workspace, memory, prompt, out):
    argv = [
        sys.executable,
        study["harness"],
        "--workspace",
        workspace,
        "--memory-dir",
        memory,
        "--state-dir",
        out.parent / "private-state",
        "--out",
        out,
        "--arm",
        trial["arm"],
        "--prompt-file",
        prompt,
        "--run-model",
        "--runtime-manifest",
        study["runtime_manifest_path"],
        "--timeout-seconds",
        "900",
        "--reported-token-budget",
        str(study["reported_token_budget"]),
        "--image",
        study["image"],
        "--cami-source",
        study["cami_source"],
        "--adapter-dir",
        study["adapter"],
    ]
    if trial["arm"] != "plain":
        argv += ["--binding-relative", "prepared/binding.json"]
    result = command(argv, timeout=1200)
    write(out.parent / "session-process.json", result)
    require_success(result)
    manifest = read(out / "manifest.json")
    if (
        manifest["status"] != "passed"
        or manifest["image_id"] != study["image"]
        or not manifest["model_requested"]
    ):
        raise ValueError("session identity or status mismatch")
    config = read(out / "effective-input-config.json")
    if config["model"] != study["model"] or config["agents"]["research"]["steps"] != 20:
        raise ValueError("effective model/config mismatch")
    for name, expected_sha in manifest["artifact_hashes"].items():
        if digest(out / name) != expected_sha:
            raise ValueError("session evidence hash mismatch")
    return manifest


def quality_valid(check, outcomes, allowance=None):
    if (
        outcomes["exit_code"] != 0
        or outcomes["counts"]["executed"] == 0
        or outcomes["counts"]["errors"]
    ):
        return False
    if check == "acceptance":
        return not any(outcomes["counts"][key] for key in ["skipped", "xfailed", "xpassed"])
    allowance = allowance or {
        "collected": 1,
        "node_ids": {key: [] for key in ["skipped", "xfailed", "xpassed"]},
    }
    return outcomes["collected"] >= allowance["collected"] and all(
        set(outcomes["node_ids"][key]) <= set(allowance["node_ids"][key])
        for key in ["skipped", "xfailed", "xpassed"]
    )


def grade(study, task, candidate, out, *, checks=("acceptance", "regression"), allowance=None):
    out.mkdir(parents=True, exist_ok=False)
    target = evaluation_workspace(Path(study["bundle_path"]), task, candidate, out)
    reports = []
    outcomes = {}
    for check in checks:
        names = task["acceptance"] if check == "acceptance" else [task["regression"]]
        metrics = out / (check + "-outcomes")
        metrics.mkdir()
        chown(metrics)
        argv = [
            "python",
            "-I",
            "/opt/fixed_grader.py",
            *[
                arg
                for source_root in study["normalized"]["source_roots"]
                for arg in ["--subject-module", source_root.split("/")[1]]
            ],
            "--report",
            "/grade-results/outcomes.json",
            "--",
            "-q",
            "-c",
            "/dev/null",
            "--rootdir",
            "/workspace",
            "--confcutdir",
            "/workspace/"
            + (
                task["oracle_root"]
                if check == "acceptance" and not task["replace_regression_tests"]
                else task["regression"]
            ),
            "-p",
            "no:cacheprovider",
            *["/workspace/" + n for n in names],
        ]
        if check == "acceptance" and task["pytest_selection"]:
            argv += ["-k", task["pytest_selection"]]
        report = container(
            study,
            [
                (target, "/workspace", True),
                (Path(__file__).parent / "fixed_grader.py", "/opt/fixed_grader.py", True),
                (metrics, "/grade-results", False),
            ],
            argv,
            out / check,
            timeout=900,
            pythonpath="/opt/cami-deps",
            workdir="/",
        )
        path = metrics / "outcomes.json"
        if path.exists():
            outcomes[check] = read(path)
            report["quality_valid"] = quality_valid(check, outcomes[check], allowance)
        else:
            report["quality_valid"] = False
        reports.append(report)
    report = {
        "status": "pass"
        if all(r["status"] == "passed" and r["quality_valid"] for r in reports)
        else "fail",
        "checks": reports,
        "outcomes": outcomes,
        "fixed_tests_restored": True,
        "agent_tests_scored": False,
        "network": "none",
        "grader_mounts": [
            "readonly evaluation-workspace",
            "trusted grader",
            "writable outcome report only",
        ],
        "workspace_bytes": bytes_used(target),
        "source_files": file_hashes(candidate / "src"),
    }
    write(out / "report.json", report)
    return report


def regression_allowance(study, task, canonical_workspace, output):
    directory = output / "baselines" / task["id"]
    binding = directory / "allowance.json"
    if not binding.exists():
        if directory.exists():
            raise ValueError("incomplete baseline preflight retained; no hidden retry")
        result = grade(study, task, canonical_workspace, directory, checks=("regression",))
        outcomes = result["outcomes"].get("regression")
        if not outcomes or outcomes["counts"]["executed"] == 0 or outcomes["counts"]["errors"]:
            raise ValueError("canonical-base regression collection/execution invalid")
        expected_failures = (
            []
            if study["bundle_kind"] == "development"
            else study.get("baseline_failure_allowances", {}).get(task["id"])
        )
        if expected_failures is None:
            raise ValueError("heldout baseline requires a frozen expected failure-node allowance")
        if set(outcomes["node_ids"]["failed"]) != set(expected_failures) or outcomes[
            "exit_code"
        ] != (1 if expected_failures else 0):
            raise ValueError(
                "canonical-base regression has unexpected failures; model admission denied"
            )
        write(
            binding,
            {
                "task": task["id"],
                "canonical_archive_sha256": task["archive_sha256"],
                "outcomes": outcomes,
                "expected_failed_nodes": expected_failures,
                "artifact_hashes": file_hashes(directory),
                "infrastructure_only": True,
                "model_calls": 0,
            },
        )
    baseline = read(binding)
    verify_files(directory, baseline["artifact_hashes"])
    if (
        baseline["task"] != task["id"]
        or baseline["canonical_archive_sha256"] != task["archive_sha256"]
    ):
        raise ValueError("canonical-base allowance identity mismatch")
    expected = (
        []
        if study["bundle_kind"] == "development"
        else study.get("baseline_failure_allowances", {}).get(task["id"])
    )
    if (
        expected is None
        or set(baseline.get("expected_failed_nodes", [])) != set(expected)
        or set(baseline["outcomes"]["node_ids"]["failed"]) != set(expected)
        or baseline["outcomes"]["exit_code"] != (1 if expected else 0)
    ):
        raise ValueError("stored baseline failure allowance differs from frozen policy")
    return baseline["outcomes"], digest(binding)
