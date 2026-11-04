#!/usr/bin/env python3
"""Explicit parent-filtered blob provisioning after a separate source authorization.

This tool never reads project blob bodies. It acquires explicitly named Git blob
objects, inspects local object headers, and records which may later be read by an
offline parent collector. Unknown transfer sizes require an explicit observed-cap
acknowledgement in the sealed protocol; this is not a hard network/disk quota.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import shutil
import signal
import subprocess
import time
from urllib.parse import urlsplit

PROTOCOL_ID = "packaging-parent-blob-acquisition-v1"
MODE = "parent_filtered_blobs_only"
MAX_STORAGE_BYTES = 2 * 1024**3
MIN_FREE_BYTES = 5 * 1024**3
MAX_BODY_BYTES = 2 * 1024**2
PREFIXES = ("src/packaging/", "packaging/")
EXCLUDED = frozenset({"tests", "test", "_vendor", "vendor", "__pycache__"})
OID = re.compile(r"[0-9a-f]{40}")
OFFLINE_PROTOCOLS = ("file", "http", "https", "ssh", "git", "ext")


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_hash(path):
    return digest(path.read_bytes())


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def pairs(items):
    output = {}
    for key, value in items:
        require(key not in output, "duplicate JSON field: " + key)
        output[key] = value
    return output


def read_json(path):
    return json.loads(path.read_bytes(), object_pairs_hook=pairs)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def local(root, name):
    path = (root / name).resolve()
    require(
        not Path(name).is_absolute() and ".." not in Path(name).parts and path.is_relative_to(root),
        "path must be contained and root-relative",
    )
    return path


def cpu_ns():
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return round((usage.ru_utime + usage.ru_stime) * 1_000_000_000)


class Commands:
    def __init__(self, output, timeout, total_seconds):
        self.output = output
        self.timeout = timeout
        self.deadline = time.monotonic() + total_seconds
        self.records = []

    def run(self, repo, *args, wants=None, allow_codes=(0,), transport=None):
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, "total acquisition time budget exhausted")
        prefix = [
            "git",
            "--no-replace-objects",
            "--no-optional-locks",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            "-c",
            "fetch.negotiationAlgorithm=noop",
            "-c",
            "protocol.allow=never",
        ]
        for name in OFFLINE_PROTOCOLS:
            prefix += [
                "-c",
                "protocol." + name + ".allow=" + ("always" if name == transport else "never"),
            ]
        argv = [*prefix, "-C", str(repo), *args]
        if wants is not None:
            require(
                args[0] == "fetch" and wants and all(OID.fullmatch(oid) for oid in wants),
                "only exact blob OID wants are accepted",
            )
        else:
            require(args[0] != "fetch", "fetch requires explicit OID wants")
        stdin = None if wants is None else ("\n".join(wants) + "\n").encode()
        record = {
            "number": len(self.records),
            "argv": argv,
            "stdin_object_ids": wants,
            "stdin_sha256": digest(stdin) if stdin else None,
            "transport_enabled": transport,
            "started_at": now(),
        }
        started, cpu = time.monotonic_ns(), cpu_ns()
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env={
                **os.environ,
                "GIT_NO_LAZY_FETCH": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(stdin, timeout=min(self.timeout, remaining))
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        record.update(
            returncode=process.returncode,
            timed_out=timed_out,
            wall_ns=time.monotonic_ns() - started,
            observed_child_cpu_ns=cpu_ns() - cpu,
            stdout_bytes=len(stdout),
            stdout_sha256=digest(stdout),
            stderr_bytes=len(stderr),
            stderr_sha256=digest(stderr),
        )
        stderr_path = self.output / f"command-{record['number']:04d}.stderr"
        stderr_path.write_bytes(stderr)
        record["stderr_path"] = stderr_path.name
        self.records.append(record)
        with (self.output / "commands.jsonl").open("a") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
        require(not timed_out, "Git command exceeded acquisition time budget")
        require(process.returncode in allow_codes, "Git command failed; see " + stderr_path.name)
        return stdout


def verify_committed(root, head, paths, commands):
    for name, expected in paths.items():
        actual = local(root, name)
        require(file_hash(actual) == expected, "sealed input changed: " + name)
        committed = commands.run(root, "cat-file", "blob", head + ":" + name)
        require(
            digest(committed) == expected,
            "sealed input does not match frozen committed HEAD: " + name,
        )


def object_inventory(repo, commands):
    raw = commands.run(
        repo,
        "cat-file",
        "--batch-all-objects",
        "--batch-check=%(objectname) %(objecttype) %(objectsize)",
    )
    result = {}
    for line in raw.splitlines():
        oid, kind, size = line.decode("ascii").split()
        require(
            OID.fullmatch(oid) is not None and oid not in result,
            "invalid/duplicate object inventory entry",
        )
        result[oid] = {"type": kind, "size": int(size)}
    return result


def repository_state(repo, commands):
    head = commands.run(repo, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    origin = commands.run(repo, "config", "--get", "remote.origin.url").decode().strip()
    refs = {}
    for line in (
        commands.run(repo, "for-each-ref", "--format=%(refname)%09%(objectname)%09%(symref)")
        .decode()
        .splitlines()
    ):
        name, oid, symbolic = line.split("\t")
        refs[name] = {"oid": oid, "symbolic": symbolic or None}
    return {
        "HEAD": head,
        "origin_url": origin,
        "refs": refs,
        "cached_origin_HEAD": refs.get("refs/remotes/origin/HEAD"),
        "fresh_remote_HEAD_query_performed": False,
    }


def storage_state(gitdir, output):
    def size(directory):
        total = 0
        for path in directory.rglob("*"):
            require(not path.is_symlink(), "symlink in storage-accounting directory")
            if path.is_file():
                total += path.stat().st_size
        return total

    return {
        "git_directory_bytes": size(gitdir),
        "output_directory_bytes": size(output),
        "free_bytes": shutil.disk_usage(gitdir).free,
    }


def check_storage(observed, budget):
    require(
        observed["free_bytes"] > budget["minimum_free_bytes"],
        "available disk is below the sealed minimum free-space threshold",
    )
    require(
        observed["git_directory_bytes"] + observed["output_directory_bytes"]
        <= budget["max_study_storage_bytes"],
        "observed study storage exceeds target; this was a post-acquisition check, not a hard quota",
    )


def tree_entries(raw, parent):
    rows = []
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        info, path_bytes = entry.split(b"\t", 1)
        mode, kind, oid = info.decode("ascii").split()
        require(OID.fullmatch(oid) is not None, "tree contains invalid object ID")
        try:
            path = path_bytes.decode("utf-8")
        except UnicodeDecodeError:
            path = None
        reason = None
        if path is None:
            reason = "unsupported_path_encoding"
        elif PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
            reason = "unsupported_path"
        elif not path.startswith(PREFIXES):
            reason = "outside_fixed_package_prefixes"
        elif any(part in EXCLUDED for part in PurePosixPath(path).parts):
            reason = "excluded_path_component"
        elif not path.endswith(".py"):
            reason = "outside_py_extension"
        elif mode not in {"100644", "100755"} or kind != "blob":
            reason = "nonregular_or_nonblob"
        rows.append(
            {
                "parent_commit": parent,
                "path": path,
                "raw_path_hex": path_bytes.hex() if path is None else None,
                "mode": mode,
                "git_type": kind,
                "oid": oid,
                "selected": reason is None,
                "exclusion_reason": reason,
            }
        )
    return rows


def preflight(root, protocol_path, output):
    protocol = read_json(protocol_path)
    require(
        protocol.get("schema_version") == 1
        and protocol.get("protocol_id") == PROTOCOL_ID
        and protocol.get("status") == "sealed",
        "requires the exact sealed parent-blob protocol",
    )
    require(
        protocol.get("phase") == "parent_blob_acquisition"
        and protocol.get("source_access_authorized") is True
        and protocol.get("child_source_access_authorized") is False,
        "metadata-only or unapproved protocol cannot provision parent source objects",
    )
    require(
        protocol.get("mode") == MODE,
        "only parent_filtered_blobs_only is implemented; no widening default",
    )
    configuration = protocol["source_configuration"]
    require(
        configuration["eligible_module_prefixes"] == list(PREFIXES)
        and set(configuration["excluded_path_components"]) == EXCLUDED
        and configuration["extensions"] == [".py"]
        and set(configuration["regular_modes"]) == {"100644", "100755"}
        and configuration["max_file_bytes"] == MAX_BODY_BYTES,
        "unsupported source configuration; do not widen filters",
    )
    budget = protocol["budget"]
    require(
        budget.get("network_size_policy")
        == "unknown_transfer_sizes_explicitly_acknowledged_postfetch_observed_cap"
        and budget.get("unknown_transfer_and_transient_storage_overshoot_acknowledged") is True,
        "sealed protocol must explicitly acknowledge unknown transfer sizes and observed post-fetch caps; no hard quota is implemented",
    )
    require(
        0 < budget["max_study_storage_bytes"] <= MAX_STORAGE_BYTES
        and budget["minimum_free_bytes"] >= MIN_FREE_BYTES
        and 0 < budget["total_seconds"] <= 1200
        and 0 < budget["command_timeout_seconds"] <= 120
        and 1 <= budget["fetch_batch_objects"] <= 64,
        "invalid sealed storage/time/batch budget",
    )
    seal = read_json(local(root, protocol["seal_path"]))
    require(seal["protocol_sha256"] == file_hash(protocol_path), "protocol seal mismatch")
    own = str(Path(__file__).resolve().relative_to(root))
    require(own in seal["files"], "running provisioning helper must be sealed")
    topology_path = protocol["topology_path"]
    require(
        seal["files"].get(topology_path) == protocol["topology_sha256"],
        "parent topology must be a sealed source-authorization input",
    )
    topology = read_json(local(root, topology_path))
    parents = topology["parent_source_allowlist_after_separate_commit"]
    require(
        len(parents) == len(set(parents)) == 3
        and parents == protocol["authorized_parent_commits"]
        and all(OID.fullmatch(oid) for oid in parents),
        "exact three-parent allowlist required",
    )
    require(
        topology.get("child_source_access_authorized") is False,
        "parent provisioning must not accept child source authorization",
    )
    require(
        [group["parent_commit"] for group in topology["groups"]] == parents,
        "topology group/allowlist mismatch",
    )
    paths = dict(seal["files"])
    paths[str(protocol_path.relative_to(root))] = file_hash(protocol_path)
    paths[protocol["seal_path"]] = file_hash(local(root, protocol["seal_path"]))
    commands = Commands(output, budget["command_timeout_seconds"], budget["total_seconds"])
    head = commands.run(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    verify_committed(root, head, paths, commands)
    return protocol, seal, parents, paths, head, commands


def acquire(root, protocol_path, output):
    root, protocol_path, output = root.resolve(), protocol_path.resolve(), output.resolve()
    require(
        output.is_relative_to(root / "runs") or output.is_relative_to(root / "reports"),
        "output must be a new runs/ or reports/ directory",
    )
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "status": "preflight",
        "started_at": now(),
        "mode": MODE,
        "project_blob_body_reads": 0,
        "project_source_executions": 0,
        "budget_guarantee": "Observed post-fetch storage target and bounded process timeout only; no hard transfer or transient aggregate-storage quota.",
    }
    write_json(output / "manifest.json", manifest)
    commands = None
    repo = gitdir = protocol = None
    try:
        protocol, seal, parents, paths, head, commands = preflight(root, protocol_path, output)
        manifest.update(
            status="enumerating_authorized_parent_trees",
            protocol_sha256=file_hash(protocol_path),
            seal_sha256=file_hash(local(root, protocol["seal_path"])),
            workspace_commit=head,
            source_before=paths,
            source_authorization={
                "phase": protocol["phase"],
                "parents": parents,
                "children": False,
            },
            sealed_remote_HEAD=protocol.get("recorded_remote_HEAD"),
            budget=protocol["budget"],
        )
        repo = local(root, protocol["repo_path"])
        require(
            (repo / ".git").is_dir() and not (repo / ".git").is_symlink(),
            "requires a local no-checkout clone with its own .git directory",
        )
        require(
            not any(path.name != ".git" for path in repo.iterdir()),
            "worktree must remain empty; no checkout/source execution",
        )
        gitdir = Path(
            commands.run(repo, "rev-parse", "--absolute-git-dir").decode().strip()
        ).resolve()
        require(
            gitdir == (repo / ".git").resolve()
            and not (gitdir / "objects/info/alternates").exists(),
            "linked/alternate object stores are outside this provisioning mode",
        )
        require(
            commands.run(repo, "remote").decode().splitlines() == ["origin"],
            "only the sealed origin remote is supported",
        )
        before = repository_state(repo, commands)
        manifest["repository_before"] = before
        require(
            before["origin_url"] == protocol["repository_url"]
            and before["HEAD"] == protocol["boundary_commit"],
            "repository remote/HEAD differs from source-authorized protocol",
        )
        transport = urlsplit(before["origin_url"]).scheme
        require(
            transport in {"https", "file"} and not urlsplit(before["origin_url"]).username,
            "only explicit credential-free HTTPS or authored local-file remotes are supported",
        )
        require(
            commands.run(repo, "config", "--get", "remote.origin.promisor").decode().strip()
            == "true"
            and commands.run(repo, "config", "--get", "remote.origin.partialclonefilter")
            .decode()
            .strip()
            == "blob:none",
            "requires the existing blob:none promisor clone; no full/unfiltered fallback",
        )
        storage = storage_state(gitdir, output)
        manifest["storage_before"] = storage
        check_storage(storage, protocol["budget"])
        objects_before = object_inventory(repo, commands)
        write_json(output / "objects-before.json", objects_before)
        entries = []
        tree_bindings = []
        tree_output = output / "trees"
        tree_output.mkdir()
        for parent in parents:
            require(
                objects_before.get(parent, {}).get("type") == "commit",
                "authorized parent commit is not locally present",
            )
            raw_tree = commands.run(repo, "ls-tree", "-rz", "--full-tree", parent)
            path = tree_output / (parent + ".raw")
            path.write_bytes(raw_tree)
            tree_bindings.append(
                {
                    "parent_commit": parent,
                    "raw_ls_tree_sha256": digest(raw_tree),
                    "raw_file": str(path.relative_to(output)),
                }
            )
            entries.extend(tree_entries(raw_tree, parent))
        selected = sorted({row["oid"] for row in entries if row["selected"]})
        require(
            object_inventory(repo, commands) == objects_before,
            "offline tree enumeration acquired unexpected objects",
        )
        require(selected, "no regular allowed package .py blobs in the authorized parents")
        for oid in selected:
            require(
                oid not in objects_before or objects_before[oid]["type"] == "blob",
                "selected tree OID is not a blob",
            )
        missing = [oid for oid in selected if oid not in objects_before]
        manifest.update(
            tree_bindings=tree_bindings,
            selected_blob_oids=selected,
            explicit_missing_blob_wants=missing,
            excluded_paths_aliasing_selected_oids=[
                row for row in entries if not row["selected"] and row["oid"] in selected
            ],
        )
        write_json(output / "tree-entries.json", entries)
        write_json(output / "selected-oids.json", selected)
        write_json(output / "manifest.json", manifest)
        batch_size = protocol["budget"]["fetch_batch_objects"]
        for offset in range(0, len(missing), batch_size):
            check_storage(storage_state(gitdir, output), protocol["budget"])
            wants = missing[offset : offset + batch_size]
            commands.run(
                repo,
                "fetch",
                "--no-tags",
                "--no-write-fetch-head",
                "--no-recurse-submodules",
                "--no-auto-maintenance",
                "--no-write-commit-graph",
                "--refmap=",
                "--filter=blob:none",
                "--stdin",
                "origin",
                wants=wants,
                transport=transport,
            )
            observed = object_inventory(repo, commands)
            new = set(observed) - set(objects_before)
            write_json(output / f"objects-after-batch-{offset // batch_size:04d}.json", observed)
            manifest["observed_new_object_ids"] = sorted(new)
            require(
                new <= set(missing) and all(observed[oid]["type"] == "blob" for oid in new),
                "fetch acquired unrequested objects; preserve attempt and stop before body inspection",
            )
            require(
                all(oid in observed for oid in wants),
                "explicit fetch did not supply all wanted blobs",
            )
            manifest["last_storage_observation"] = storage_state(gitdir, output)
            check_storage(manifest["last_storage_observation"], protocol["budget"])
        after = object_inventory(repo, commands)
        require(
            all(oid in after and after[oid]["type"] == "blob" for oid in selected),
            "selected blob remains unavailable",
        )
        write_json(output / "objects-after.json", after)
        acquisitions = [
            {
                "oid": oid,
                "size": after[oid]["size"],
                "newly_acquired": oid not in objects_before,
                "eligible_for_later_body_AST_read": after[oid]["size"] <= MAX_BODY_BYTES,
                "body_exclusion_reason": None
                if after[oid]["size"] <= MAX_BODY_BYTES
                else "file_too_large_after_object_acquisition",
                "body_read_by_provisioner": False,
            }
            for oid in selected
        ]
        write_json(output / "blob-sizes.json", acquisitions)
        manifest.update(
            repository_after=repository_state(repo, commands),
            acquired_blob_count=sum(row["newly_acquired"] for row in acquisitions),
            eligible_blob_count=sum(
                row["eligible_for_later_body_AST_read"] for row in acquisitions
            ),
            oversize_blob_count=sum(
                not row["eligible_for_later_body_AST_read"] for row in acquisitions
            ),
            object_sizes=acquisitions,
        )
        require(
            manifest["repository_after"] == before,
            "repository HEAD/remote/refs changed during explicit provisioning",
        )
        verify_committed(root, head, paths, commands)
        require(
            commands.run(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip() == head,
            "workspace HEAD changed during provisioning",
        )
        manifest.update(
            source_after={name: file_hash(local(root, name)) for name in paths},
            storage_after=storage_state(gitdir, output),
            status="complete",
        )
        require(
            manifest["source_after"] == paths,
            "source/protocol/seal inputs changed during acquisition",
        )
        check_storage(manifest["storage_after"], protocol["budget"])
    except Exception as error:
        manifest.update(status="failed", failure=type(error).__name__ + ": " + str(error))
        if gitdir is not None:
            try:
                manifest["storage_at_failure"] = storage_state(gitdir, output)
            except Exception as bookkeeping_error:
                manifest["storage_failure_observation_error"] = str(bookkeeping_error)
        raise
    finally:
        manifest["finished_at"] = now()
        if commands is not None:
            if "source_before" in manifest:
                manifest["source_after"] = {
                    name: file_hash(local(root, name)) if local(root, name).is_file() else None
                    for name in manifest["source_before"]
                }
        command_log = output / "commands.jsonl"
        if command_log.is_file():
            records = [json.loads(line) for line in command_log.read_text().splitlines()]
            manifest["actual_command_count"] = len(records)
            manifest["commands_wall_ns"] = sum(row["wall_ns"] for row in records)
            manifest["observed_commands_child_cpu_ns"] = sum(
                row["observed_child_cpu_ns"] for row in records
            )
        manifest["artifact_hashes"] = {
            str(path.relative_to(output)): file_hash(path)
            for path in output.rglob("*")
            if path.is_file() and path != output / "manifest.json"
        }
        write_json(output / "manifest.json", manifest)
    return manifest


def default_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    acquire(args.root, args.protocol, args.out)


if __name__ == "__main__":
    main()
