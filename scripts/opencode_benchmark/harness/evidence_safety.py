"""Host-side fail-closed publication of text evidence from an owned state mount."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import sqlite3
import stat

from container_common import sanitize_artifact


def collect_private_values(state, *, expect_credential):
    secrets, credential_seen = set(), False
    def gather(item):
        if isinstance(item, dict):
            for value in item.values():
                gather(value)
        elif isinstance(item, list):
            for value in item:
                gather(value)
        elif isinstance(item, str) and len(item) >= 16 and not item.startswith(("http://", "https://")):
            secrets.add(item)
    dbpath = state / "data/opencode/session.db"
    password = state / "server-private/server-password.private"
    for selected in [dbpath, password, *[Path(str(dbpath) + suffix) for suffix in ["-wal", "-shm", "-journal"]]]:
        current = state
        for part in selected.relative_to(state).parts:
            current /= part
            if current.is_symlink():
                raise ValueError("private-state path must not traverse a symlink")
        try:
            info = selected.lstat()
        except FileNotFoundError:
            continue
        ceiling = 4096 if selected == password else 256 * 1024**2
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > ceiling:
            raise ValueError("private-state file must be bounded ordinary single-link regular file")
    if dbpath.exists():
        if dbpath.is_symlink():
            raise ValueError("private credential DB must not be a symlink")
        connection = sqlite3.connect(f"file:{dbpath}?mode=ro", uri=True)
        try:
            if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='credential'").fetchone():
                for raw, in connection.execute("SELECT value FROM credential WHERE integration_id='openai'"):
                    credential_seen = True
                    gather(json.loads(raw))
        finally:
            connection.close()
    if expect_credential and not credential_seen:
        raise ValueError("private credential unavailable for final publication scrub")
    if password.exists():
        if password.is_symlink():
            raise ValueError("server secret path must not be a symlink")
        value = password.read_text()
        secrets.update([value, base64.b64encode(("opencode:" + value).encode()).decode()])
    return secrets


def scrub_state_evidence(state, *, expect_credential, initial_private_values=()):
    evidence = state / "evidence"
    try:
        root_info = evidence.lstat()
    except FileNotFoundError:
        return {"status": "no_evidence"}
    if not stat.S_ISDIR(root_info.st_mode):
        raise ValueError("evidence root must be an ordinary directory, not a symlink")
    secrets = collect_private_values(state, expect_credential=expect_credential) | set(initial_private_values)
    paths, total = [], 0
    for path in evidence.rglob("*"):
        if any(value in str(path.relative_to(evidence)) for value in secrets):
            raise ValueError("known private value in artifact name")
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise ValueError("unsafe evidence filesystem entry")
        if stat.S_ISDIR(info.st_mode):
            continue
        if info.st_nlink != 1 or path.suffix not in {".json", ".jsonl", ".txt"}:
            raise ValueError("evidence must be ordinary unlinked text artifacts")
        total += info.st_size
        if total > 128 * 1024**2:
            raise ValueError("evidence publication safety ceiling128MiB reached")
        paths.append(path)
    changed, rejected = [], []
    for path in paths:
        try:
            if sanitize_artifact(path, secrets):
                changed.append(str(path.relative_to(evidence)))
        except (ValueError, UnicodeError, RecursionError) as error:
            # No raw text/exception body is exported. Other safe artifacts survive.
            path.unlink()
            rejected.append({"artifact": str(path.relative_to(evidence)), "error_type": type(error).__name__})
    return {"status": "partial" if rejected else "passed", "files_checked": len(paths), "bytes_before_scrub": total,
        "changed_artifact_names": changed, "rejected_artifacts": rejected, "secret_bodies_exported": False,
        "publication_limit_bytes": 128 * 1024**2}
