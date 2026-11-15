"""Fixed five-pair comparison. Run once per new output directory."""

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

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/practical-20261115"


def stable(value):
    if isinstance(value, dict):
        return {k: stable(v) for k, v in value.items() if k not in {"observation"}}
    if isinstance(value, list):
        return [stable(v) for v in value]
    return value


def main():
    out = Path(sys.argv[1])
    out.mkdir(exist_ok=False)
    records = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for arm in ["baseline", "candidate"]:
            shutil.copytree(
                ROOT / "src", tmp / arm / "src", ignore=shutil.ignore_patterns("__pycache__")
            )
            shutil.copyfile(
                REPORT / f"worktree-{arm}.py", tmp / arm / "src/cami/product/worktree.py"
            )
        for case, args in [
            ("help", ["--help"]),
            (
                "found",
                [
                    "find",
                    "run_experiment",
                    "--repo",
                    str(ROOT),
                    "--source-root",
                    "src",
                    "--format",
                    "json",
                ],
            ),
            (
                "missing",
                [
                    "find",
                    "__cami_absent_20261115__",
                    "--repo",
                    str(ROOT),
                    "--source-root",
                    "src",
                    "--format",
                    "json",
                ],
            ),
        ]:
            for pair in range(5):
                for arm in (
                    ["baseline", "candidate"] if pair % 2 == 0 else ["candidate", "baseline"]
                ):
                    env = {
                        **os.environ,
                        "PYTHONPATH": str(tmp / arm / "src"),
                        "XDG_STATE_HOME": str(tmp / arm / "state"),
                        "PYTHONDONTWRITEBYTECODE": "1",
                    }
                    start = time.perf_counter()
                    proc = subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            "from cami.cli import main; import sys; sys.exit(main())",
                            *args,
                        ],
                        env=env,
                        capture_output=True,
                        timeout=120,
                    )
                    wall = time.perf_counter() - start
                    raw = proc.stdout
                    try:
                        value = stable(json.loads(raw))
                        raw = json.dumps(value, sort_keys=True).encode()
                    except ValueError:
                        pass
                    r = {
                        "case": case,
                        "pair": pair,
                        "arm": arm,
                        "wall_seconds": wall,
                        "exit": proc.returncode,
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "stderr": proc.stderr.decode(),
                    }
                    (out / f"{case}-{pair}-{arm}.json").write_bytes(proc.stdout)
                    records.append(r)
                    with (out / "attempts.jsonl").open("a") as f:
                        f.write(json.dumps(r) + "\n")
                        f.flush()
                        os.fsync(f.fileno())
        summary = {}
        for case in ["help", "found", "missing"]:
            group = [r for r in records if r["case"] == case]
            stats = {}
            for arm in ["baseline", "candidate"]:
                values = [r["wall_seconds"] for r in group if r["arm"] == arm]
                stats[arm] = {
                    "median": statistics.median(values),
                    "min": min(values),
                    "max": max(values),
                    "n": len(values),
                }
            valid = all(
                len({r["sha256"] for r in group if r["pair"] == i}) == 1 for i in range(5)
            ) and all(r["exit"] == (1 if case == "missing" else 0) for r in group)
            stats["outputs_equal_and_exits_correct"] = valid
            stats["accepted"] = (
                valid
                and stats["candidate"]["median"] <= 0.9 * stats["baseline"]["median"]
                and stats["candidate"]["max"] < stats["baseline"]["min"]
            )
            summary[case] = stats
        (out / "summary.json").write_text(
            json.dumps(
                {
                    "cases": summary,
                    "accepted": all(c["accepted"] for c in summary.values()),
                    "protocol_sha256": hashlib.sha256(
                        (REPORT / "protocol.json").read_bytes()
                    ).hexdigest(),
                },
                indent=2,
            )
        )
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
