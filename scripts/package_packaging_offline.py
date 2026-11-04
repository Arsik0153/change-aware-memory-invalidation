#!/usr/bin/env python3
"""Package/verify only the frozen 72 authorized Packaging snapshots, offline."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile

ACQUISITION_SHA = "8886a00a8488447274369c4b69966660b3417395ab288927c76445fa90ac2fc4"
RUN_SHA = "93f8ba40cc44320e28d82aaaed965a518e291e2fd37d85a25a99006c47baf508"
PROTOCOL_SHA = "aec4f1fd0b863bb875deb2e1808285a3359461ecd7e4403eced8cb23e235190e"
CONFIG = b"""[core]
\trepositoryformatversion = 0
\tbare = false
\tlogallrefupdates = false
\thooksPath = /dev/null
[protocol]
\tallow = never
[gc]
\tauto = 0
[maintenance]
\tauto = false
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    return digest(path.read_bytes())


def check(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def save(path, value):
    path.write_bytes(encoded(value))


def inventory(root):
    result = {}
    for path in sorted(root.rglob("*")):
        check(not path.is_symlink(), f"unexpected original filesystem symlink: {path.name}")
        if path.is_file():
            result[str(path.relative_to(root))] = {"sha256": sha(path), "size": path.stat().st_size,
                                                 "mode": stat.S_IMODE(path.stat().st_mode)}
    return result


def git(repo, arguments, log, input_bytes=None):
    # Actual network namespace, no inherited Git config/environment and no lazy fetch.
    environment = {"PATH": os.defpath, "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
                   "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_NO_LAZY_FETCH": "1",
                   "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1",
                   "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": ""}
    command = ["unshare", "--net", "--", "git", "-c", "protocol.allow=never", "-c", "gc.auto=0",
               "-c", "maintenance.auto=false", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *arguments]
    result = subprocess.run(command, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=environment, timeout=120, check=False)
    with log.open("ab") as stream:
        stream.write((json.dumps({"argv": command, "returncode": result.returncode,
                              "stdin_sha256": digest(input_bytes) if input_bytes is not None else None,
                              "stdout_sha256": digest(result.stdout), "stdout_bytes": len(result.stdout),
                              "stderr_sha256": digest(result.stderr), "stderr": result.stderr.decode("utf-8", "replace"),
                              "network": "unshare --net; transports denied; no lazy fetch; no inherited Git env"}, sort_keys=True) + "\n").encode())
    check(result.returncode == 0, f"offline git failed: {arguments[0]}: {result.stderr.decode('utf-8', 'replace')}")
    return result.stdout


def blobs(repo, oids, log):
    raw = git(repo, ["cat-file", "--batch"], log, ("\n".join(oids) + "\n").encode())
    cursor, records = 0, []
    for oid in oids:
        end = raw.index(b"\n", cursor)
        fields = raw[cursor:end].split()
        check(len(fields) == 3 and fields[:2] == [oid.encode(), b"blob"], "unexpected batch object/type")
        size = int(fields[2])
        body = raw[end + 1:end + 1 + size]
        check(len(body) == size and raw[end + 1 + size:end + 2 + size] == b"\n", "truncated batch body")
        check(hashlib.sha1(b"blob " + str(size).encode() + b"\0" + body).hexdigest() == oid,
              "blob Git SHA1 mismatch")
        records.append({"oid": oid, "size": size, "sha256": digest(body)})
        cursor = end + 2 + size
    check(cursor == len(raw), "extra batch output")
    return records


def tar_members(files):
    directories = {"repo", "repo/.git", "repo/.git/refs", "repo/.git/objects"}
    for name in files:
        directories.update(str(parent) for parent in PurePosixPath(name).parents if str(parent) != ".")
    return sorted(directories), sorted(files)


def write_archive(path, files):
    with path.open("wb") as destination:
        with gzip.GzipFile(filename="", mode="wb", fileobj=destination, mtime=0, compresslevel=9) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                directories, names = tar_members(files)
                for name in directories + names:
                    info = tarfile.TarInfo(name)
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ""
                    if name in directories:
                        info.type, info.mode = tarfile.DIRTYPE, 0o755
                        archive.addfile(info)
                    else:
                        value = files[name]
                        info.mode = 0o644
                        info.size = value.stat().st_size if isinstance(value, Path) else len(value)
                        if isinstance(value, Path):
                            with value.open("rb") as source:
                                archive.addfile(info, source)
                        else:
                            archive.addfile(info, io.BytesIO(value))


def verify(archive_path, output, expected_sha):
    check(sha(archive_path) == expected_sha, "archive SHA256 mismatch")
    output.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        check(len(names) == len(set(names)), "duplicate archive names")
        check(sum(member.size for member in members) <= 2 * 1024**3, "archive exceeds ceiling")
        for member in members:
            path = PurePosixPath(member.name)
            check(not path.is_absolute() and ".." not in path.parts and (member.isfile() or member.isdir()),
                  "unsafe archive member")
        manifest_bytes = archive.extractfile("corpus-manifest.json").read()
        manifest = json.loads(manifest_bytes)
        check(all(re.fullmatch(r"repo/\.git/(HEAD|config|objects/(pack/pack-[0-9a-f]{40}\.(pack|idx|rev|promisor)|[0-9a-f]{2}/[0-9a-f]{38}))", name)
                  for name in manifest["files"]), "archive manifest permits nonminimal Git files")
        expected_files = {"corpus-manifest.json", *manifest["files"]}
        check({member.name for member in members if member.isfile()} == expected_files, "extra/missing archive file")
        directories, _ = tar_members({name: None for name in expected_files})
        check({member.name for member in members if member.isdir()} == set(directories), "extra/missing directory")
        for member in members:
            path = output / member.name
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                content = archive.extractfile(member).read()
                if member.name != "corpus-manifest.json":
                    record = manifest["files"][member.name]
                    check(digest(content) == record["sha256"] and len(content) == record["size"], "member hash mismatch")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                path.chmod(0o644)
    check(manifest["authorized_snapshot_count"] == 72 and manifest["authorized_blob_count"] == 296,
          "unexpected corpus scope")
    repo, log = output / "repo", output / "commands.jsonl"
    check((repo / ".git/config").read_bytes() == CONFIG, "configuration not sanitized")
    check((repo / ".git/HEAD").read_text() == manifest["boundary_commit"] + "\n", "HEAD not pinned")
    check(git(repo, ["rev-parse", "HEAD"], log).decode().strip() == manifest["boundary_commit"], "HEAD resolution mismatch")
    tree_results = []
    observed_oids = set()
    for record in manifest["authorized_snapshots"]:
        oid = record["commit"]
        check(re.fullmatch(r"[0-9a-f]{40}", oid), "bad authorized commit")
        raw = git(repo, ["ls-tree", "-rz", "--full-tree", oid], log)
        check(digest(raw) == record["raw_ls_tree_sha256"], "tree binding mismatch")
        for entry in raw.split(b"\0"):
            if entry:
                metadata, _ = entry.split(b"\t", 1)
                _, kind, entry_oid = metadata.split()
                check(kind == b"blob", "unexpected nonblob tree entry")
                observed_oids.add(entry_oid.decode())
        tree_results.append({"commit": oid, "raw_ls_tree_sha256": digest(raw)})
    expected_oids = [record["oid"] for record in manifest["authorized_blobs"]]
    check(len(tree_results) == len({r["commit"] for r in tree_results}) == 72
          and observed_oids == set(expected_oids) and len(expected_oids) == 296, "tree/blob allowlist mismatch")
    verified_blobs = blobs(repo, expected_oids, log)
    check(verified_blobs == manifest["authorized_blobs"], "extracted blob size/hash mismatch")
    check(all(sha(output / name) == record["sha256"] for name, record in manifest["files"].items()),
          "verification mutated extracted Git files")
    result = {"status": "verified", "archive_sha256": expected_sha, "snapshot_count": 72, "blob_count": 296,
              "tree_results": tree_results, "blob_results": verified_blobs,
              "network": "every Git process runs under unshare --net; Git transports denied and lazy fetch disabled",
              "commands_sha256": sha(log), "command_count": 74, "project_source_executions": 0,
              "history_completeness": "not asserted; complete only for 72 authorized snapshot trees/blobs",
              "extracted_git_files_unchanged_by_verification": True}
    save(output / "verification.json", result)
    return result


def build(root, source, output):
    output.mkdir(parents=True, exist_ok=False)
    acquisition = root / "reports/research-20261104/packaging-replay-blob-acquisition-v1"
    run = root / "reports/research-20261104/packaging-replay-v2/manifest.json"
    protocol_path = root / "examples/packaging_structural_development_v2/replay_protocol.json"
    check(sha(acquisition / "manifest.json") == ACQUISITION_SHA and sha(run) == RUN_SHA
          and sha(protocol_path) == PROTOCOL_SHA, "requires frozen acquisition/run/protocol")
    acquired, replay, protocol = (json.loads(path.read_text()) for path in (acquisition / "manifest.json", run, protocol_path))
    check(acquired["status"] == replay["status"] == "complete" and acquired["protocol_sha256"] == PROTOCOL_SHA
          and replay["protocol_sha256"] == PROTOCOL_SHA, "incomplete or mismatched sources")
    authorized = protocol["replay_blob_acquisition"]["authorized_snapshot_commits"]
    check(authorized == acquired["authorized_snapshot_commits"] and len(set(authorized)) == 72,
          "authorized snapshot mismatch")
    check(source == (root / protocol["groups"][0]["repo_path"]).resolve(), "unexpected source repository")
    before = inventory(source)
    save(output / "source-before.json", before)
    log = output / "original-read-commands.jsonl"
    sizes_path = acquisition / "blob-sizes.json"
    check(sha(sizes_path) == acquired["artifact_hashes"]["blob-sizes.json"], "acquired sizes changed")
    sizes = json.loads(sizes_path.read_text())
    oids = [row["oid"] for row in sizes]
    check(len(oids) == len(set(oids)) == 296 and oids == acquired["selected_blob_oids"], "blob scope mismatch")
    original_blobs = blobs(source, oids, log)
    check([(r["oid"], r["size"]) for r in sizes] == [(r["oid"], r["size"]) for r in original_blobs],
          "original sizes differ from authorization record")
    tree_bindings = {r["snapshot_commit"]: r for r in acquired["tree_bindings"]}
    snapshots = []
    for oid in authorized:
        record = tree_bindings[oid]
        raw_path = acquisition / record["raw_file"]
        check(sha(raw_path) == record["raw_ls_tree_sha256"] == acquired["artifact_hashes"][record["raw_file"]],
              "authorized tree record changed")
        snapshots.append({"commit": oid, "raw_ls_tree_sha256": record["raw_ls_tree_sha256"]})
    files = {}
    for name in before:
        if name.startswith(".git/objects/"):
            relative = name.removeprefix(".git/objects/")
            check(re.fullmatch(r"pack/pack-[0-9a-f]{40}\.(pack|idx|rev|promisor)|[0-9a-f]{2}/[0-9a-f]{38}", relative),
                  "unexpected object-store auxiliary file")
            files["repo/" + name] = source / name
    check(files, "empty object store")
    files["repo/.git/HEAD"] = (protocol["boundary_commit"] + "\n").encode()
    files["repo/.git/config"] = CONFIG
    file_records = {name: {"size": value.stat().st_size if isinstance(value, Path) else len(value),
                           "sha256": sha(value) if isinstance(value, Path) else digest(value), "mode": "0644"}
                    for name, value in sorted(files.items())}
    manifest = {"schema_version": 1, "scope": "bounded Packaging development offline snapshot corpus",
                "history_completeness": "not complete Git history; historical metadata objects are retained byte-for-byte",
                "authorized_snapshot_count": 72, "authorized_blob_count": 296,
                "authorized_snapshots": snapshots, "authorized_blobs": original_blobs,
                "boundary_commit": protocol["boundary_commit"], "source_repository": str(source.relative_to(root)),
                "source_bindings": {"acquisition_manifest_sha256": ACQUISITION_SHA, "run_manifest_sha256": RUN_SHA,
                                    "replay_protocol_sha256": PROTOCOL_SHA, "replay_seal_sha256": acquired["seal_sha256"],
                                    "run_source_commit": replay["source_before"]["git_head"]},
                "files": file_records, "object_file_count": len(files) - 2,
                "sanitization": "Only existing object files plus synthetic detached HEAD and local no-network config. No original remotes, refs, hooks, logs, index, checkout or credentials.",
                "archive_recipe": "USTAR, sorted dirs/files, uid/gid/mtime0, empty uname/gname, dirs0755/files0644; gzip mtime0/empty filename/level9"}
    save(output / "corpus-manifest.json", manifest)
    files["corpus-manifest.json"] = encoded(manifest)
    archive = output / "packaging-development-v2-offline.tar.gz"
    write_archive(archive, files)
    archive_sha = sha(archive)
    repeated = output / "repeated.tar.gz"
    write_archive(repeated, files)
    check(sha(repeated) == archive_sha, "archive not byte reproducible")
    repeated.unlink()
    verification = verify(archive, output / "extracted", archive_sha)
    after = inventory(source)
    save(output / "source-after.json", after)
    check(before == after, "original repository changed")
    result = {"status": "complete", "archive": archive.name, "archive_sha256": archive_sha,
              "archive_bytes": archive.stat().st_size, "byte_reproducible": True,
              "original_repository_file_identity_unchanged": True, "original_file_count": len(before),
              "original_inventory_sha256": sha(output / "source-before.json"),
              "source_bindings": manifest["source_bindings"], "verified_snapshots": verification["snapshot_count"],
              "verified_blobs": verification["blob_count"], "object_files_copied_byte_for_byte": len(files) - 3,
              "helper_sha256": sha(Path(__file__)), "network": verification["network"],
              "scope": manifest["scope"], "history_completeness": manifest["history_completeness"],
              "artifact_hashes": {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob("*"))
                                  if p.is_file() and "repo" not in p.relative_to(output).parts}}
    save(output / "manifest.json", result)
    print(json.dumps({key: value for key, value in result.items() if key != "artifact_hashes"}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    builder = subparsers.add_parser("build")
    builder.add_argument("--root", type=Path, default=Path.cwd())
    builder.add_argument("--source", type=Path, required=True)
    builder.add_argument("--out", type=Path, required=True)
    verifier = subparsers.add_parser("verify")
    verifier.add_argument("--archive", type=Path, required=True)
    verifier.add_argument("--expected-sha256", required=True)
    verifier.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args.root.resolve(), args.source.resolve(), args.out.resolve())
    else:
        result = verify(args.archive.resolve(), args.out.resolve(), args.expected_sha256)
        print(json.dumps({key: result[key] for key in ("status", "snapshot_count", "blob_count", "archive_sha256")}, indent=2))


if __name__ == "__main__":
    main()
