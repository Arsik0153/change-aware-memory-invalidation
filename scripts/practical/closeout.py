"""Fail closed unless every required deliverable has actual completion evidence."""

import hashlib
import json
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/practical-complete-20261115"
OUTPUT = ROOT / "output/practical-complete-20261115"


def read(name):
    return json.loads((REPORT / name).read_text())


def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def passed_log(name):
    text = (REPORT / name).read_text()
    assert not re.search(r"\b(?:failed|errors?)\b", text, re.I), name
    match = re.search(r"(\d+) passed", text)
    assert match, name
    return int(match[1])


def main():
    result, audit = read("model-summary.json"), read("model-audit.json")
    assert result["status"] == "completed_and_verified" and result["attempts"] == 72
    assert len(audit["terminal_hashes"]) == 72
    assert result["quality_passes"] == {"plain": 36, "cami": 36}
    assert result["recommend_cami_by_default"] is False
    assert digest(REPORT / "protocol.json") == read("protocol-seal.json")["sha256"]
    tasks = read("task-admission.json")
    assert len(tasks) == 12
    assert all(not row["base"]["quality_pass"] and row["gold"]["quality_pass"] for row in tasks)
    local = read("local-comparison-v3/summary.json")
    assert local["attempts"] == 50 and local["accepted"] is False
    assert all(row["correct"] for row in local["cases"].values())
    assert digest(ROOT / "src/cami/product/worktree.py") == digest(
        ROOT / "reports/practical-20261115/worktree-baseline.py"
    )
    admission = read("installed-task-accounting-admission.json")
    assert admission["status"] == "verified" and admission["usage"]["complete"]
    accounting = read("all-opencode-attempt-accounting.json")
    assert accounting["observed_accounting_complete"]
    assert accounting["primary_terminal_attempts"] == 72
    assert accounting["admission_attempts"] == 5
    assert read("admission-origin-exclusion-final.json")["observed_exact_repeat_fraction"] is None
    assert read("publication-tail-audit.json")["status"] == "verified"
    members = set((REPORT / "raw-evidence-members.txt").read_text().splitlines())
    for trial in read("protocol.json")["schedule"]:
        assert f"runs/practical-complete-20261115/model/{trial['id']}/terminal.json" in members
    for admission_record in accounting["admission_records"]:
        assert admission_record["journal"] in members
    checks = {
        "general_non_docker": passed_log("full-tests-final.log"),
        "latest_capture_and_contract": passed_log("final-capture-tests.log"),
        "docker": passed_log("docker-tests-pinned-final.log"),
    }
    assert checks["latest_capture_and_contract"] == 33 and checks["docker"] == 4
    assert "All checks passed!" in (REPORT / "final-ruff.log").read_text()
    assert "Success: no issues found" in (REPORT / "final-mypy.log").read_text()
    source_paths = [
        "src",
        "integrations/opencode",
        "scripts/practical",
        "scripts/opencode_benchmark",
        "tests/test_task_session.py",
        "tests/test_task_recovery.py",
        "tests/test_opencode_task_entrypoint.py",
        "tests/test_practical_fixture_inventory.py",
        "tests/test_practical_output_contract.py",
        "tests/test_task_journal_summary.py",
        "runs/practical-complete-20261115/runtime",
        "README.md",
        "pyproject.toml",
        "uv.lock",
    ]
    with tarfile.open(OUTPUT / "final-source.tar.xz", "w:xz", preset=3) as tar:
        for path in source_paths:
            tar.add(
                ROOT / path,
                arcname=path,
                filter=lambda info: None
                if any(part in {"__pycache__", "node_modules"} for part in info.name.split("/"))
                else info,
            )
    archives = {}
    for name in ["runtime.tar.gz", "raw-evidence.tar.xz", "final-source.tar.xz"]:
        path = OUTPUT / name
        assert path.is_file() and path.stat().st_size > 0
        archives[name] = {"sha256": digest(path), "bytes": path.stat().st_size}
    manifest = {
        "status": "complete",
        "required_deliverables": {
            "runtime": "runtime-manifest.json; task-admission.json; runtime.tar.gz; pinned recipes",
            "predeclared_full_model_comparison": "protocol.json; protocol-seal.json; 72 preserved terminal attempts; model-audit.json",
            "output_contract_and_separate_rerun": "output_contract.py; local-comparison-v3: 50 completed trials, all semantic outputs match",
            "ordinary_task_capture": "installed-task-accounting-admission.json; real installed cami task; original prompt/source; 5 completed observed requests",
            "failure_accounting_and_recovery": "33 focused checks; provider-error partial usage, duplicates, timeout, parent SIGKILL and idempotent recovery; all admission failures in accounting ledger",
            "all_attempts_and_decisions": "72/72 primary plus all 5 admissions preserved; default CAMI recommendation and local candidate rejected by fixed gates; Python retained",
        },
        "decisions": {
            "default_cami_for_tested_workload": "reject",
            "local_candidate": "reject; product worktree implementation still equals baseline",
            "durable_task_entrypoint": "include",
            "rust_rewrite": "do not undertake",
        },
        "checks": checks,
        "check_scope": "General suite, latest changed capture/contract suite, and Docker suite are separate runs with overlap; counts must not be added as independent tests.",
        "historical_missing_input_policy": "No reconstructed input snapshots and no fabricated production repeat rate. Admission/model runs excluded from user-frequency denominator.",
        "billing_scope": accounting["scope"],
        "primary_protocol_sha256": digest(REPORT / "protocol.json"),
        "frozen_experiment_source_sha256": digest(REPORT / "frozen-source.tar.xz"),
        "final_wheel_sha256": admission["wheel_sha256"],
        "archives": archives,
    }
    (REPORT / "completion-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (REPORT / "execution-state.json").write_text(
        json.dumps(
            {"state": "complete", "remaining": [], "manifest": "completion-manifest.json"}, indent=2
        )
        + "\n"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
