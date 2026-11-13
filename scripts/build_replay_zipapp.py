"""Build a deterministic stdlib-only zipapp from the unchanged exact-task replay module."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    source = (ROOT / "integrations/opencode/task_replay.py").read_bytes()
    files = {"__main__.py": b"from task_replay import main\nmain()\n", "task_replay.py": source}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content, compresslevel=9)
    data = b"#!/usr/bin/env python3\n" + buffer.getvalue()
    with output.open("xb") as stream:
        stream.write(data)
    output.chmod(0o755)
    return {
        "artifact": output.name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "source": "integrations/opencode/task_replay.py",
        "source_bytes": len(source),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "python": "3.12+",
        "external_python_dependencies": [],
        "python_runtime_included": False,
        "build_python": sys.version,
        "build_zlib_runtime": zlib.ZLIB_RUNTIME_VERSION,
        "model_calls": 0,
        "scope": "Packaging only. Exact production module bytes, no algorithm or performance change.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    receipt = build(args.out)
    with args.receipt.open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(receipt))
