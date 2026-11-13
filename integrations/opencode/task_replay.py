"""Exact-input source-change replay into a NEW workspace; no model or script execution.

This is result memoization, not semantic reuse across changed repositories. Callers
must grade the materialized candidate before accepting it. Context identifies the
external toolchain/environment contract; repository bytes alone cannot bind it.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import zlib

SCHEMA = "cami-exact-task-replay/2"
MAX_BYTES = 64 * 1024 * 1024
MAX_FILES = 10000


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def encode(content):
    return base64.b64encode(zlib.compress(content)).decode()


def decode(value):
    try:
        compressed = base64.b64decode(value, validate=True)
        inflater = zlib.decompressobj()
        content = inflater.decompress(compressed, MAX_BYTES + 1)
        if len(content) > MAX_BYTES or not inflater.eof or inflater.unused_data:
            raise ValueError("oversized or malformed compressed source")
        return content
    except (zlib.error, TypeError) as error:
        raise ValueError("invalid compressed source") from error


def publish(target, encoded):
    """Publish a complete durable file without replacing a concurrent winner."""
    descriptor, temporary = tempfile.mkstemp(prefix=".replay-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink() or target.read_bytes() != encoded:
                raise ValueError("different result already recorded for exact inputs") from None
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def inventory(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("regular workspace directory required")
    result, total = {}, 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts[0] == ".git":
            continue
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) > 0o777:
            raise ValueError("nonregular or hardlinked workspace entry")
        total += info.st_size
        if total > MAX_BYTES or len(result) >= MAX_FILES:
            raise ValueError("workspace exceeds replay bound")
        content = path.read_bytes()
        if len(content) != info.st_size:
            raise ValueError("workspace changed during capture")
        result[relative.as_posix()] = {"sha256": digest(content), "mode": stat.S_IMODE(info.st_mode)}
    return result


def identity(files, task, context):
    if not isinstance(task, str) or not task.strip() or not isinstance(context, str) or not context:
        raise ValueError("exact task and external context identity required")
    return digest(canonical({"schema": SCHEMA, "files": files,
                             "task_sha256": digest(task.encode()), "context": context}))


def record(before, after, task, context, cache):
    """Store source-only changes; no prior quality claim is inferred from recording."""
    before, after, cache = Path(before).resolve(), Path(after).resolve(), Path(cache).resolve()
    if cache.is_relative_to(before) or cache.is_relative_to(after):
        raise ValueError("cache must be outside workspaces")
    initial, final = inventory(before), inventory(after)
    key = identity(initial, task, context)
    changes = {}
    for name in sorted(set(initial) | set(final)):
        if not name.startswith("src/") or initial.get(name) == final.get(name):
            continue
        changes[name] = None if name not in final else {
            **final[name], "content": encode((after / name).read_bytes())}
        if changes[name] is not None and digest(decode(changes[name]["content"])) != final[name]["sha256"]:
            raise ValueError("candidate changed during capture")
    if not changes:
        raise ValueError("no source changes to remember")
    if inventory(before) != initial or inventory(after) != final:
        raise ValueError("inputs changed during capture")
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (key + ".json")
    value = {"schema": SCHEMA, "key": key, "base_files_sha256": digest(canonical(initial)), "changes": changes,
             "quality": "not_inferred; caller must grade materialization"}
    encoded = canonical(value)
    publish(target, encoded)
    return {"key": key, "changed_files": len(changes), "stored_bytes": len(encoded)}


def materialize(workspace, task, context, cache, output):
    """Return a miss without writes, or create a fresh candidate for mandatory grading."""
    workspace, cache, output = Path(workspace).resolve(), Path(cache).resolve(), Path(output).resolve()
    if output.is_relative_to(workspace) or output.is_relative_to(cache) or output.exists():
        raise ValueError("output must be a new path outside input and cache")
    before = inventory(workspace)
    key = identity(before, task, context)
    path = cache / (key + ".json")
    if not path.is_file():
        return {"status": "miss", "reason": "no exact task, repository and context match", "key": key}
    if path.is_symlink() or path.stat().st_size > 2 * MAX_BYTES:
        raise ValueError("invalid replay artifact")
    value = json.loads(path.read_bytes())
    if value.get("schema") != SCHEMA or value.get("key") != key or value.get("base_files_sha256") != digest(canonical(before)):
        raise ValueError("invalid replay binding")
    changes = value.get("changes")
    if not isinstance(changes, dict) or not changes or len(changes) > MAX_FILES:
        raise ValueError("invalid replay changes")
    decoded, expected, total = {}, dict(before), 0
    for name, change in changes.items():
        rel = Path(name)
        if (not name.startswith("src/") or rel.is_absolute() or str(rel) != name
                or ".." in rel.parts or ".git" in rel.parts or "\\" in name):
            raise ValueError("unsafe replay source path")
        if change is None:
            if name not in before:
                raise ValueError("cannot delete absent source")
            expected.pop(name)
            decoded[name] = None
            continue
        content = decode(change["content"])
        total += len(content)
        mode = change.get("mode")
        if total > MAX_BYTES or digest(content) != change["sha256"] or type(mode) is not int or not 0 <= mode <= 0o777:
            raise ValueError("invalid replay content or mode")
        decoded[name] = content
        expected[name] = {"sha256": change["sha256"], "mode": mode}
    # Only publish a new workspace. A failed attempt is removed, never partially
    # applied to a user's working directory.
    output.mkdir(parents=False, exist_ok=False)
    try:
        shutil.copytree(workspace, output, dirs_exist_ok=True, ignore=lambda directory, names: [".git"] if Path(directory) == workspace else [])
        if inventory(workspace) != before or inventory(output) != before:
            raise ValueError("workspace changed during copy")
        for name, content in decoded.items():
            target = output / name
            if content is None:
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                target.chmod(expected[name]["mode"])
        if inventory(output) != expected:
            raise ValueError("materialized candidate differs")
    except BaseException:
        shutil.rmtree(output)
        raise
    return {"status": "candidate_requires_grading", "key": key, "model_calls": 0,
            "changed_files": len(changes), "output": str(output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    remember = commands.add_parser("record", help="Remember source changes; this does not certify quality")
    remember.add_argument("--before", type=Path, required=True)
    remember.add_argument("--after", type=Path, required=True)
    reuse = commands.add_parser("materialize", help="Create a new candidate that still requires grading")
    reuse.add_argument("--workspace", type=Path, required=True)
    reuse.add_argument("--out", type=Path, required=True)
    for command in (remember, reuse):
        command.add_argument("--task-file", type=Path, required=True)
        command.add_argument("--context-id", required=True, help="Caller-bound external environment/toolchain identity")
        command.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    task = args.task_file.read_text()
    if args.command == "record":
        result = record(args.before, args.after, task, args.context_id, args.cache)
    else:
        result = materialize(args.workspace, task, args.context_id, args.cache, args.out)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
