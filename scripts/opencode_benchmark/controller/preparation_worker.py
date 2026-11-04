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


def preparation_commands(backend, source_roots, seed_schema_version=1, environ=None):
    if type(seed_schema_version) is not int or seed_schema_version not in (1, 2):
        raise ValueError("unsupported seed schema version")
    adapter_pythonpath = "/opt/memory-adapter:/opt/cami-src:/opt/cami-deps"
    generator_pythonpath = adapter_pythonpath
    generator = "/opt/seed_source_notes.py"
    if seed_schema_version == 2:
        generator_pythonpath = "/opt/literal-generator:" + adapter_pythonpath
        generator = "/opt/literal-generator/seed_source_literals_v2.py"
    env = dict(os.environ if environ is None else environ)
    env.update(PYTHONPATH=adapter_pythonpath, PYTHONDONTWRITEBYTECODE="1", PYTHONSAFEPATH="1")
    generator_env = dict(env, PYTHONPATH=generator_pythonpath)
    generate = ["python", generator, "--repo", "/workspace", "--out", "/memory/seed"]
    generate += [arg for root in source_roots for arg in ["--source-root", root]]
    prepare = [
        "python",
        "/opt/memory-adapter/memory_adapter.py",
        "prepare",
        "--backend",
        backend,
        "--repo",
        "/workspace",
        "--seed-spec",
        "/memory/seed/seed-spec.json",
        "--out",
        "/memory/prepared",
    ]
    if backend == "cami":
        prepare += ["--state-home", "/memory/cami-state"]
    return [generate, prepare], [generator_env, env]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["static", "cami"], required=True)
    parser.add_argument("--source-root", action="append", required=True)
    parser.add_argument("--seed-sha256", required=True)
    parser.add_argument("--seed-schema-version", type=int, choices=[1, 2], default=1)
    args = parser.parse_args()
    start = time.monotonic()
    report = {"status": "started", "cgroup_before": cgroup(), "commands": [], "model_calls": 0}
    try:
        commands, environments = preparation_commands(
            args.backend, args.source_root, args.seed_schema_version
        )
        report["seed_schema_version"] = args.seed_schema_version
        for number, (argv, env) in enumerate(zip(commands, environments, strict=True)):
            tick = time.monotonic()
            result = subprocess.run(argv, cwd="/", env=env, capture_output=True, timeout=300)
            report["commands"].append(
                {
                    "argv": argv,
                    "trusted_python_environment": {
                        key: env[key]
                        for key in ["PYTHONPATH", "PYTHONSAFEPATH", "PYTHONDONTWRITEBYTECODE"]
                    },
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
