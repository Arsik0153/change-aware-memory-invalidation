from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "verification" / "cami" / "final"
OUT.mkdir(parents=True, exist_ok=True)
results = []
for name, arguments in [("pytest", ["pytest", "-q"]), ("ruff", ["ruff", "check", "."]),
                        ("mypy", ["mypy", "src/cami"])]:
    command = [sys.executable, "-m", *arguments]
    started = time.perf_counter()
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=False)
    (OUT / f"{name}.log").write_text(result.stdout)
    results.append({"command":command,"exit_code":result.returncode,
                    "wall_seconds":time.perf_counter()-started,"log":f"{name}.log"})
    print(result.stdout, end="", flush=True)
summary = {"schema_version":1,"recorded_at":datetime.now(timezone.utc).isoformat(),
           "python":sys.version,"docker_image":os.environ.get("CAMI_TEST_IMAGE"),"checks":results}
(OUT / "checks.json").write_text(json.dumps(summary,indent=2)+"\n")
raise SystemExit(0 if all(row["exit_code"] == 0 for row in results) else 1)
