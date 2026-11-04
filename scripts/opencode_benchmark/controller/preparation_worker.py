"""Trusted container entrypoint: source-only seed generation then one preparation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def cgroup():
    return {
        name: (Path("/sys/fs/cgroup") / name).read_text().strip()
        for name in ["cpu.stat", "cpu.max", "memory.current", "memory.peak", "memory.max"]
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["static", "cami"], required=True)
    parser.add_argument("--source-root", action="append", required=True)
    parser.add_argument("--seed-sha256", required=True)
    args = parser.parse_args()
    start = time.monotonic()
    report = {"status": "started", "cgroup_before": cgroup(), "commands": [], "model_calls": 0}
    try:
        env = dict(
            os.environ, PYTHONPATH="/opt/cami-src:/opt/cami-deps", PYTHONDONTWRITEBYTECODE="1"
        )
        commands = [
            ["python", "/opt/seed_source_notes.py", "--repo", "/workspace", "--out", "/memory/seed"]
            + [arg for root in args.source_root for arg in ["--source-root", root]]
        ]
        prepare = [
            "python",
            "/opt/memory-adapter/memory_adapter.py",
            "prepare",
            "--backend",
            args.backend,
            "--repo",
            "/workspace",
            "--seed-spec",
            "/memory/seed/seed-spec.json",
            "--out",
            "/memory/prepared",
        ]
        if args.backend == "cami":
            prepare += ["--state-home", "/memory/cami-state"]
        commands.append(prepare)
        for number, argv in enumerate(commands):
            tick = time.monotonic()
            result = subprocess.run(argv, cwd="/", env=env, capture_output=True, timeout=300)
            report["commands"].append(
                {
                    "argv": argv,
                    "returncode": result.returncode,
                    "stdout": result.stdout.decode(errors="replace"),
                    "stderr": result.stderr.decode(errors="replace"),
                    "wall_seconds": time.monotonic() - tick,
                }
            )
            if result.returncode:
                raise RuntimeError("memory construction failed")
            if (
                number == 0
                and hashlib.sha256(Path("/memory/seed/seed-spec.json").read_bytes()).hexdigest()
                != args.seed_sha256
            ):
                raise ValueError("generated origin seed differs from exact frozen seed bytes")
        report["status"] = "passed"
    except BaseException as error:
        report.update(status="failed", failure=type(error).__name__ + ": " + str(error))
        raise
    finally:
        report.update(cgroup_after=cgroup(), worker_wall_seconds=time.monotonic() - start)
        Path("/memory/preparation-operation.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n"
        )


if __name__ == "__main__":
    main()
