"""Independent new protocol: find optimization with implementation-bound IDs."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

from output_contract import semantic_payload

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/practical-complete-20261115"


def main():
    out = REPORT / "local-comparison-v3"
    out.mkdir(exist_ok=False)
    old = ROOT / "reports/practical-20261115"
    protocol = {
        "version": 3,
        "scope": "complete find CLI, cold and verified warm index; help is a nonregression control",
        "pairs_per_case": 5,
        "cases": ["help", "found-cold", "found-warm", "missing-cold", "missing-warm"],
        "correctness": "All payload fields equal except observation and two implementation IDs at snapshot.fingerprint and snapshot.generation_id. Both IDs validated, generation must bind fingerprint+unchanged snapshot. No recursive field stripping.",
        "acceptance": "All find cases: >=10% lower median and candidate max<baseline min; help median <=110% baseline; all outputs/exits match. Otherwise do not deploy candidate. No reruns or extension.",
        "limiter": "Previously profiled repeated PurePosixPath parent construction; same capture, file reads, hash guards and index contract retained.",
        "source_sha256": {
            arm: hashlib.sha256((old / f"worktree-{arm}.py").read_bytes()).hexdigest()
            for arm in ["baseline", "candidate"]
        },
        "load": os.getloadavg(),
    }
    (out / "protocol.json").write_text(json.dumps(protocol, indent=2))
    rows = []
    with tempfile.TemporaryDirectory(prefix="cami-find-v2-") as temporary:
        tmp = Path(temporary)
        for arm in ["baseline", "candidate"]:
            shutil.copytree(
                ROOT / "src", tmp / arm / "src", ignore=shutil.ignore_patterns("__pycache__")
            )
            shutil.copyfile(old / f"worktree-{arm}.py", tmp / arm / "src/cami/product/worktree.py")
        for case in protocol["cases"]:
            for pair in range(5):
                for arm in (
                    ["baseline", "candidate"] if pair % 2 == 0 else ["candidate", "baseline"]
                ):
                    state = tmp / arm / f"{case}-{pair}"
                    env = {
                        **os.environ,
                        "PYTHONPATH": str(tmp / arm / "src"),
                        "XDG_STATE_HOME": str(state),
                        "PYTHONDONTWRITEBYTECODE": "1",
                    }
                    args = (
                        ["--help"]
                        if case == "help"
                        else [
                            "find",
                            "run_experiment" if case.startswith("found") else "__cami_absent_v2__",
                            "--repo",
                            str(ROOT),
                            "--source-root",
                            "src",
                            "--format",
                            "json",
                        ]
                    )
                    argv = [
                        sys.executable,
                        "-c",
                        "from cami.cli import main; import sys; sys.exit(main())",
                        *args,
                    ]
                    if case.endswith("warm"):
                        subprocess.run(argv, env=env, capture_output=True, timeout=120)
                    tick = time.perf_counter()
                    result = subprocess.run(argv, env=env, capture_output=True, timeout=120)
                    wall = time.perf_counter() - tick
                    (out / f"{case}-{pair}-{arm}.stdout").write_bytes(result.stdout)
                    payload = result.stdout
                    if case != "help":
                        payload = json.dumps(
                            semantic_payload(json.loads(payload)), sort_keys=True
                        ).encode()
                    row = {
                        "case": case,
                        "pair": pair,
                        "arm": arm,
                        "wall_seconds": wall,
                        "exit": result.returncode,
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "stderr": result.stderr.decode(),
                    }
                    rows.append(row)
                    with (out / "attempts.jsonl").open("a") as stream:
                        stream.write(json.dumps(row) + "\n")
                        stream.flush()
                        os.fsync(stream.fileno())
    results = {}
    for case in protocol["cases"]:
        group = [r for r in rows if r["case"] == case]
        stats = {}
        for arm in ["baseline", "candidate"]:
            values = [r["wall_seconds"] for r in group if r["arm"] == arm]
            stats[arm] = {
                "median": statistics.median(values),
                "min": min(values),
                "max": max(values),
            }
        correct = all(
            len({r["sha256"] for r in group if r["pair"] == pair}) == 1 for pair in range(5)
        ) and all(r["exit"] == 0 for r in group)
        stats["correct"] = correct
        stats["accepted"] = correct and (
            stats["candidate"]["median"] <= 1.1 * stats["baseline"]["median"]
            if case == "help"
            else stats["candidate"]["median"] <= 0.9 * stats["baseline"]["median"]
            and stats["candidate"]["max"] < stats["baseline"]["min"]
        )
        results[case] = stats
    summary = {
        "cases": results,
        "accepted": all(x["accepted"] for x in results.values()),
        "attempts": len(rows),
        "protocol_sha256": hashlib.sha256((out / "protocol.json").read_bytes()).hexdigest(),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
