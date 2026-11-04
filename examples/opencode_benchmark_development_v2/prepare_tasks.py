"""Build historical task fixtures without exposing upstream history to the agent."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import resource
import subprocess
import tarfile
import time


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize(repo: Path, commit: str, out: Path) -> dict:
    started = time.monotonic()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    resolved = subprocess.check_output(["git", "-C", str(repo), "rev-parse", commit], text=True).strip()
    raw = subprocess.check_output(["git", "-C", str(repo), "archive", "--format=tar", resolved])
    out.mkdir(parents=True, exist_ok=False)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        archive.extractall(out, filter="data")
    manifest = {p.relative_to(out).as_posix(): sha(p) for p in sorted(out.rglob("*"))
                if p.is_file() and not p.is_symlink()}
    environment = dict(os.environ, GIT_AUTHOR_DATE="2000-01-01T00:00:00+00:00",
                       GIT_COMMITTER_DATE="2000-01-01T00:00:00+00:00")
    for args in (["init", "-q"], ["add", "--all"],
                 ["-c", "user.name=CAMI benchmark", "-c", "user.email=benchmark@example.invalid",
                  "commit", "-q", "-m", "Canonical benchmark snapshot"]):
        subprocess.run(["git", "-C", str(out), *args], env=environment, check=True)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {"upstream_commit": resolved, "archive_sha256": hashlib.sha256(raw).hexdigest(),
            "files": manifest, "wall_seconds": time.monotonic() - started,
            "child_cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
            "history_exposed": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    result = materialize(args.repo.resolve(), args.commit, args.out.resolve())
    args.manifest.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
