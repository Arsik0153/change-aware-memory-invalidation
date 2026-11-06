"""Verify extracted v6 public evidence and reproduce frozen analysis with caveats."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import resource
import stat
import subprocess
import sys
import time

RUN = "runs/opencode-development-v6-20261106"
ANALYSIS = "runs/opencode-development-v6-final-analysis-20261106"
PROTOCOL = "reports/opencode-study-design-v6-20261106/protocol.json"
CAVEAT = "runs/opencode-development-v6-timing-caveats-20261106.json"
ORIGINAL_ROOT = Path("/root/apps/change-aware-memory-invalidation")


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def portable(report, root):
    """Only three explicit path fields are allowed to change after extraction."""
    result = copy.deepcopy(report)
    result["run"] = str(Path(result["run"]).relative_to(root))
    caveats = result["timing_caveats"]
    caveats["source_path"] = str(Path(caveats["source_path"]).relative_to(root))
    for row in caveats["entries"]:
        row["evidence_path"] = str(Path(row["evidence_path"]).relative_to(root))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.root.absolute(), args.out.absolute()
    assert not root.is_relative_to(out) and not out.is_relative_to(root)
    out.mkdir(exist_ok=False)
    started = time.monotonic()
    cpu_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    inventory = read(root / "PUBLICATION-MANIFEST.json")["files"]
    for name, expected in inventory.items():
        relative = Path(name)
        assert not relative.is_absolute() and ".." not in relative.parts
        path = root / relative
        assert not any(p.is_symlink() for p in [path, *path.parents])
        info = path.lstat()
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        assert sha(path) == expected["sha256"] and info.st_size == expected["size"]
        assert stat.S_IMODE(info.st_mode) == expected["mode"]
    run = root / RUN
    binding = read(run / "run.json")
    assert (
        binding["study_sha256"]
        == sha(run / "frozen-study.json")
        == "b66e4d557b7b7cdf0800b4c9121e793659f3a02029a74b026c7f7c4d75243cdd"
    )
    assert (
        sha(root / ANALYSIS / "report.json")
        == "632953c9879fb1f4f05c059d2dde747e0d4d8ead7724a13c1d7d7805faa1100b"
    )
    caveat_before = sha(root / CAVEAT)
    maintenance_before = sha(root / "runs/space-maintenance-20261106/report.json")
    command = [
        sys.executable,
        str(root / "scripts/opencode_benchmark/analysis/aggregate_study.py"),
        "--run",
        str(run),
        "--protocol",
        str(root / PROTOCOL),
        "--study",
        str(run / "frozen-study.json"),
        "--study-sha256",
        binding["study_sha256"],
        "--timing-caveats",
        str(root / CAVEAT),
        "--out",
        str(out / "aggregate"),
    ]
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "LC_ALL": "C.UTF-8",
    }
    result = subprocess.run(command, env=env, capture_output=True, timeout=120)
    (out / "command.stdout.txt").write_bytes(result.stdout)
    (out / "command.stderr.txt").write_bytes(result.stderr)
    assert result.returncode == 0, "offline analysis failed; diagnostics retained"
    original = read(root / ANALYSIS / "report.json")
    rebuilt = read(out / "aggregate/report.json")
    assert portable(original, ORIGINAL_ROOT) == portable(rebuilt, root)
    for name in ["trials.csv", "paired.csv", "blocks.csv"]:
        assert (root / ANALYSIS / name).read_bytes() == (out / "aggregate" / name).read_bytes()
    assert len(rebuilt["trials"]) == 36 and all(
        t["status"] == "passed" and t["quality"] == "pass" for t in rebuilt["trials"]
    )
    assert rebuilt["integrity"]["terminal_artifact_hashes_verified"] == 8130
    assert rebuilt["summary"]["charged_wall_disqualified_by_timing_caveats"] is True
    assert rebuilt["timing_caveats"]["affected_trial_ids"] == [
        "r2-cami-s3",
        "r2-plain-s3",
        "r2-static-s3",
    ]
    assert rebuilt["timing_caveats"]["trials_excluded"] == []
    assert rebuilt["summary"]["primary_superiority"] == "not_established"
    assert (
        sha(root / CAVEAT) == caveat_before
        and sha(root / "runs/space-maintenance-20261106/report.json") == maintenance_before
    )
    cpu_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    report = {
        "status": "passed",
        "argv": command,
        "returncode": result.returncode,
        "verified_public_payload_files": len(inventory),
        "all36_original_terminals_retained": True,
        "all8130_terminal_artifact_hashes_exact": True,
        "full_aggregate_equal_after_explicit_path_normalization": True,
        "portable_difference_allowlist": [
            "run",
            "timing_caveats.source_path",
            "timing_caveats.entries[*].evidence_path",
        ],
        "raw_caveat_and_maintenance_bytes_unchanged": True,
        "caveat_sha256": caveat_before,
        "maintenance_report_sha256": maintenance_before,
        "three_csv_files_byte_exact": True,
        "cohort_primary_wall_claim_disqualified": True,
        "trial_exclusions": [],
        "primary_superiority": "not_established",
        "model_calls": 0,
        "Docker_calls": 0,
        "network_calls": 0,
        "target_source_execution": False,
        "wall_seconds": time.monotonic() - started,
        "cpu_seconds_completed_children": cpu_after.ru_utime
        + cpu_after.ru_stime
        - cpu_before.ru_utime
        - cpu_before.ru_stime,
        "scope": "Publication/offline evaluation overhead only, never trial cost. Frozen analysis code only; no source/model/fixture execution.",
    }
    (out / "verification.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "argv"}))


if __name__ == "__main__":
    main()
