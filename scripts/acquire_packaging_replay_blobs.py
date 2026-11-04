#!/usr/bin/env python3
"""Explicit complete-snapshot blobs for a separately sealed final replay only.

This is a distinct mode and executable. The parent-only provisioner is never
patched or widened. No project body is read; locally available headers determine
which entries production read_snapshot will later limit or read.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import sys
from urllib.parse import urlsplit

PARENT_MECHANICS_SHA256 = "6e5d4833b2a0a7ab6d07597285523bb80eb30216f35f515e78200679623acfa4"
PROTOCOL_ID = "packaging-derived-structural-first-parent-development-v2"
MODE = "full_snapshots_exact_frozen_72_only"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mechanics(root):
    path = root / "scripts/acquire_packaging_parent_blobs.py"
    require(
        sha(path) == PARENT_MECHANICS_SHA256,
        "parent mechanics differs from pinned immutable implementation",
    )
    return load_module(path, "_frozen_parent_blob_mechanics")


def preflight(root, protocol_path, output, common):
    p = common.read_json(protocol_path)
    require(
        p.get("schema_version") == 1
        and p.get("status") == "sealed"
        and p.get("protocol_id") == PROTOCOL_ID,
        "requires the exact sealed final replay protocol",
    )
    cfg = p["replay_blob_acquisition"]
    require(
        cfg.get("enabled") is True
        and cfg.get("phase") == "final_replay_full_snapshots"
        and cfg.get("source_access_authorized") is True
        and cfg.get("child_source_access_authorized") is True
        and cfg.get("mode") == MODE,
        "explicit final full-snapshot source authorization required; no widening default",
    )
    budget = cfg["budget"]
    require(
        budget.get("network_size_policy")
        == "unknown_transfer_sizes_explicitly_acknowledged_postfetch_observed_cap"
        and budget.get("unknown_transfer_and_transient_storage_overshoot_acknowledged") is True,
        "unknown transfer and transient overshoot must be explicitly acknowledged",
    )
    require(
        0 < budget["max_study_storage_bytes"] <= common.MAX_STORAGE_BYTES
        and budget["minimum_free_bytes"] >= common.MIN_FREE_BYTES
        and 0 < budget["total_seconds"] <= 1200
        and 0 < budget["command_timeout_seconds"] <= 120
        and 1 <= budget["fetch_batch_objects"] <= 64,
        "invalid observed storage/time/batch budget",
    )
    seal = common.read_json(common.local(root, p["seal_path"]))
    require(seal["protocol_sha256"] == sha(protocol_path), "final protocol seal mismatch")
    own = str(Path(__file__).resolve().relative_to(root))
    require(
        own in seal["files"] and own in p["implementation_paths"],
        "final provisioner must be sealed and declared",
    )
    require(
        cfg["mechanics_path"] == "scripts/acquire_packaging_parent_blobs.py"
        and cfg["mechanics_sha256"] == PARENT_MECHANICS_SHA256
        and seal["files"].get(cfg["mechanics_path"]) == PARENT_MECHANICS_SHA256,
        "immutable parent mechanics must be pinned by final seal",
    )
    support_path = cfg["replay_support_path"]
    require(
        Path(support_path).name == "packaging_replay_support.py"
        and support_path in p["implementation_paths"]
        and seal["files"].get(support_path) == cfg["replay_support_sha256"],
        "exact final offline review gate must be sealed",
    )
    paths = dict(seal["files"])
    paths[str(protocol_path.relative_to(root))] = sha(protocol_path)
    paths[p["seal_path"]] = sha(common.local(root, p["seal_path"]))
    commands = common.Commands(output, budget["command_timeout_seconds"], budget["total_seconds"])
    head = commands.run(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    common.verify_committed(root, head, paths, commands)
    for path in (root, root / "src", root / "scripts", common.local(root, support_path).parent):
        sys.path.insert(0, str(path))
    support = load_module(common.local(root, support_path), "_sealed_final_replay_review_gate")
    loaded = support.load_inputs(protocol_path)
    checked_p, checked_root, checked_seal, groups, cohort, reviews, _, _, metadata, decisions = (
        loaded
    )
    require(
        checked_p == p and checked_root == root and checked_seal == seal,
        "final review gate returned a different protocol/root/seal",
    )
    snapshots, repo_name = frozen_snapshots(p, metadata, groups, common)
    require(
        cfg["authorized_snapshot_commits"] == snapshots,
        "full-snapshot allowlist differs from exact frozen72 IDs/order",
    )
    require(
        set(decisions) == set(cohort) == set(reviews) and len(decisions) == 24,
        "global final parent decision/review coverage mismatch",
    )
    eligible = {}
    for group, claims in groups:
        count = sum(decisions[claim.claim_id]["eligible"] for claim in claims)
        require(count >= 4, "global parent feasibility failed before project access")
        eligible[group["group_id"]] = count
    evidence = {
        "status": "passed_exact_sealed_load_inputs",
        "review_gate_path": support_path,
        "review_gate_sha256": cfg["replay_support_sha256"],
        "candidate_claims": len(cohort),
        "eligible_counts_by_group": eligible,
        "decisions_sha256": sha(common.local(root, p["parent_decisions_path"])),
        "generation_manifest_sha256": sha(common.local(root, p["parent_generation_manifest_path"])),
        "bound_review_groups": p["review_groups"],
        "source_bodies_read_by_review_gate": "Previously authorized sealed parent packet artifacts only; no project Git source.",
    }
    return p, cfg, seal, paths, head, commands, snapshots, metadata, repo_name, evidence


def frozen_snapshots(p, metadata, groups, common):
    frame = metadata["frame"]
    ids = [row["commit"] for row in frame]
    require(
        len(ids) == len(set(ids)) == 72
        and all(common.OID.fullmatch(oid) for oid in ids)
        and metadata["frame_length"] == 72
        and metadata["start_commit"] == p["start_commit"] == ids[0]
        and metadata["boundary_commit"] == p["boundary_commit"] == ids[-1]
        and metadata["child_source_access_authorized"] is False,
        "exact frozen72 frame and preserved metadata authorization required",
    )
    require(len(groups) == len(metadata["groups"]) == 3, "exact three frozen groups required")
    for i, row in enumerate(frame):
        parents = row["parents"]
        require(
            row["position"] == i
            and len(parents) == len(set(parents))
            and all(common.OID.fullmatch(oid) for oid in parents)
            and (not i or parents and parents[0] == ids[i - 1]),
            "frozen first-parent frame discontinuity",
        )
    snapshots, repo_names = [], set()
    for (group, _), frozen, position in zip(groups, metadata["groups"], (0, 24, 48), strict=True):
        revisions = [group["parent_commit"], *group["child_commits"]]
        require(
            revisions == ids[position : position + 24]
            and frozen["parent_position"] == position
            and all(
                frozen[key] == group[key]
                for key in (
                    "group_id",
                    "parent_commit",
                    "child_commits",
                    "repo_id",
                    "repo_path",
                    "source_roots",
                )
            ),
            "final group/window differs from frozen topology",
        )
        expected_steps = [
            {
                "step": n,
                "commit": ids[position + n],
                "previous_commit": ids[position + n - 1],
                "parents": frame[position + n]["parents"],
                "is_merge": len(frame[position + n]["parents"]) > 1,
            }
            for n in range(1, 24)
        ]
        require(frozen["steps"] == expected_steps, "frozen full-parent step bindings differ")
        snapshots.extend(revisions)
        repo_names.add(group["repo_path"])
    require(
        snapshots == ids and len(repo_names) == 1,
        "one repository and exact72 ordered snapshots required",
    )
    return snapshots, repo_names.pop()


def snapshot_entries(raw, revision, common):
    rows = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        info, raw_path = item.split(b"\t", 1)
        mode, kind, oid = info.decode("ascii").split()
        require(common.OID.fullmatch(oid) is not None, "invalid tree object ID")
        path = raw_path.decode("utf-8", "strict")
        require(
            path
            and path == PurePosixPath(path).as_posix()
            and not PurePosixPath(path).is_absolute()
            and ".." not in PurePosixPath(path).parts
            and "\\" not in path
            and "\x00" not in path,
            "unsupported production snapshot path",
        )
        require(
            (kind == "blob" and mode in {"100644", "100755", "120000"})
            or (kind == "commit" and mode == "160000"),
            "unsupported production snapshot tree entry",
        )
        rows.append(
            {
                "snapshot_commit": revision,
                "path": path,
                "oid": oid,
                "mode": mode,
                "git_type": kind,
                "selected_for_acquisition": kind == "blob",
                "entry_limitation": "submodule_unsupported"
                if kind == "commit"
                else "symlink_unsupported"
                if mode == "120000"
                else None,
            }
        )
    return rows


def verify_actual_topology(repo, p, metadata, snapshots, commands):
    actual = (
        commands.run(repo, "rev-list", "--first-parent", "--reverse", p["boundary_commit"])
        .decode()
        .splitlines()
    )
    require(
        p["start_commit"] in actual and actual[actual.index(p["start_commit"]) :] == snapshots,
        "actual commit-only first-parent frame differs from frozen72",
    )
    for row in metadata["frame"]:
        parents = (
            commands.run(repo, "rev-list", "--parents", "-n", "1", row["commit"]).decode().split()
        )
        require(
            parents == [row["commit"], *row["parents"]],
            "actual full parent list differs from sealed metadata",
        )


def acquire(root, protocol_path, output):
    root, protocol_path, output = root.resolve(), protocol_path.resolve(), output.resolve()
    require(
        output.is_relative_to(root / "runs") or output.is_relative_to(root / "reports"),
        "output must be a new runs/ or reports/ directory",
    )
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "status": "preflight",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "mode": MODE,
        "project_blob_body_reads": 0,
        "project_source_executions": 0,
        "parent_only_helper_unchanged_sha256": PARENT_MECHANICS_SHA256,
        "budget_guarantee": "Observed post-fetch target and bounded Git process timeouts; no hard network or transient aggregate-storage quota.",
    }
    write_json(output / "manifest.json", manifest)
    common = commands = gitdir = None
    try:
        common = mechanics(root)
        p, cfg, seal, paths, head, commands, snapshots, metadata, repo_name, gate = preflight(
            root, protocol_path, output, common
        )
        manifest.update(
            protocol_sha256=sha(protocol_path),
            seal_sha256=sha(common.local(root, p["seal_path"])),
            workspace_commit=head,
            source_before=paths,
            global_authorization_gate=gate,
            authorized_snapshot_commits=snapshots,
            authorized_parent_commits=snapshots[::24],
            authorized_child_commits=[oid for i, oid in enumerate(snapshots) if i % 24],
            budget=cfg["budget"],
            sealed_remote_HEAD=cfg.get("recorded_remote_HEAD"),
        )
        common.write_json(output / "manifest.json", manifest)
        repo = common.local(root, repo_name)
        require(
            (repo / ".git").is_dir()
            and not (repo / ".git").is_symlink()
            and not any(path.name != ".git" for path in repo.iterdir()),
            "requires an empty no-checkout clone",
        )
        gitdir = Path(
            commands.run(repo, "rev-parse", "--absolute-git-dir").decode().strip()
        ).resolve()
        require(
            gitdir == (repo / ".git").resolve()
            and not (gitdir / "objects/info/alternates").exists(),
            "linked/alternate object stores are outside this mode",
        )
        require(
            commands.run(repo, "remote").decode().splitlines() == ["origin"],
            "only sealed origin supported",
        )
        before = common.repository_state(repo, commands)
        manifest["repository_before"] = before
        transport_url = cfg["repository_transport_url"]
        parsed = urlsplit(transport_url)
        require(
            before["HEAD"] == p["boundary_commit"] and before["origin_url"] == transport_url,
            "origin/HEAD differs from final sealed source authorization",
        )
        require(
            parsed.scheme in {"https", "file"}
            and not parsed.username
            and (parsed.scheme == "file" or transport_url == p["repository_url"]),
            "only sealed HTTPS project URL or explicitly named local-file transport supported",
        )
        require(
            commands.run(repo, "config", "--get", "remote.origin.promisor").decode().strip()
            == "true"
            and commands.run(repo, "config", "--get", "remote.origin.partialclonefilter")
            .decode()
            .strip()
            == "blob:none",
            "requires existing blob:none promisor clone; no unfiltered fallback",
        )
        manifest["storage_before"] = common.storage_state(gitdir, output)
        common.check_storage(manifest["storage_before"], cfg["budget"])
        before_objects = common.object_inventory(repo, commands)
        common.write_json(output / "objects-before.json", before_objects)
        require(
            all(before_objects.get(oid, {}).get("type") == "commit" for oid in snapshots),
            "authorized snapshot commit missing locally",
        )
        verify_actual_topology(repo, p, metadata, snapshots, commands)
        manifest["status"] = "enumerating_exact_authorized_snapshot_trees"
        entries, bindings = [], []
        (output / "trees").mkdir()
        for revision in snapshots:
            raw = commands.run(repo, "ls-tree", "-rz", "--full-tree", revision)
            path = output / "trees" / (revision + ".raw")
            path.write_bytes(raw)
            entries.extend(snapshot_entries(raw, revision, common))
            bindings.append(
                {
                    "snapshot_commit": revision,
                    "raw_file": str(path.relative_to(output)),
                    "raw_ls_tree_sha256": common.digest(raw),
                }
            )
        require(
            common.object_inventory(repo, commands) == before_objects,
            "offline metadata/tree phase acquired objects",
        )
        selected = sorted({row["oid"] for row in entries if row["selected_for_acquisition"]})
        require(
            selected
            and all(
                oid not in before_objects or before_objects[oid]["type"] == "blob"
                for oid in selected
            ),
            "snapshot blob inventory invalid",
        )
        missing = [oid for oid in selected if oid not in before_objects]
        manifest.update(
            tree_bindings=bindings,
            selected_blob_oids=selected,
            explicit_missing_blob_wants=missing,
            submodule_entries=[row for row in entries if row["git_type"] == "commit"],
            symlink_entry_observations=sum(row["mode"] == "120000" for row in entries),
        )
        common.write_json(output / "tree-entries.json", entries)
        common.write_json(output / "selected-oids.json", selected)
        common.write_json(output / "manifest.json", manifest)
        batch_size = cfg["budget"]["fetch_batch_objects"]
        for offset in range(0, len(missing), batch_size):
            common.check_storage(common.storage_state(gitdir, output), cfg["budget"])
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
                transport=parsed.scheme,
            )
            observed = common.object_inventory(repo, commands)
            common.write_json(
                output / f"objects-after-batch-{offset // batch_size:04d}.json", observed
            )
            new = set(observed) - set(before_objects)
            manifest["observed_new_object_ids"] = sorted(new)
            require(
                new <= set(missing) and all(observed[oid]["type"] == "blob" for oid in new),
                "fetch acquired unrequested objects",
            )
            require(all(oid in observed for oid in wants), "explicit wanted blob still missing")
            manifest["last_storage_observation"] = common.storage_state(gitdir, output)
            common.check_storage(manifest["last_storage_observation"], cfg["budget"])
        after = common.object_inventory(repo, commands)
        common.write_json(output / "objects-after.json", after)
        require(
            all(after.get(oid, {}).get("type") == "blob" for oid in selected),
            "snapshot blob remains missing",
        )
        sizes = [
            {
                "oid": oid,
                "size": after[oid]["size"],
                "newly_acquired": oid not in before_objects,
                "over_production_size_limit": after[oid]["size"] > common.MAX_BODY_BYTES,
                "body_read_by_provisioner": False,
            }
            for oid in selected
        ]
        for row in entries:
            row["size"] = after[row["oid"]]["size"] if row["git_type"] == "blob" else None
            if row["entry_limitation"] is None and row["size"] > common.MAX_BODY_BYTES:
                row["entry_limitation"] = "file_too_large"
            row["production_reader_would_read_body_by_mode_and_size"] = (
                row["entry_limitation"] is None
            )
        common.write_json(output / "snapshot-entry-sizes.json", entries)
        common.write_json(output / "blob-sizes.json", sizes)
        manifest.update(
            repository_after=common.repository_state(repo, commands),
            acquired_blob_count=sum(row["newly_acquired"] for row in sizes),
            selected_blob_count=len(selected),
            snapshot_count=len(snapshots),
            oversize_blob_count=sum(row["over_production_size_limit"] for row in sizes),
            storage_after=common.storage_state(gitdir, output),
        )
        require(manifest["repository_after"] == before, "repository refs/HEAD/origin changed")
        common.verify_committed(root, head, paths, commands)
        require(
            commands.run(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip() == head,
            "workspace HEAD changed",
        )
        common.check_storage(manifest["storage_after"], cfg["budget"])
        require(
            all(sha(common.local(root, name)) == expected for name, expected in paths.items()),
            "sealed source/protocol inputs changed after final committed-byte check",
        )
        manifest["status"] = "complete"
    except Exception as error:
        manifest.update(status="failed", failure=type(error).__name__ + ": " + str(error))
        if gitdir is not None:
            try:
                manifest["storage_at_failure"] = common.storage_state(gitdir, output)
            except Exception as bookkeeping_error:
                manifest["storage_failure_observation_error"] = str(bookkeeping_error)
        raise
    finally:
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        if "source_before" in manifest:
            manifest["source_after"] = {
                name: sha(common.local(root, name)) if common.local(root, name).is_file() else None
                for name in manifest["source_before"]
            }
        log = output / "commands.jsonl"
        if log.is_file():
            records = [json.loads(line) for line in log.read_text().splitlines()]
            manifest.update(
                actual_command_count=len(records),
                commands_wall_ns=sum(r["wall_ns"] for r in records),
                observed_commands_child_cpu_ns=sum(r["observed_child_cpu_ns"] for r in records),
            )
        manifest["artifact_hashes"] = {
            str(path.relative_to(output)): sha(path)
            for path in output.rglob("*")
            if path.is_file() and path.name != "manifest.json"
        }
        write_json(output / "manifest.json", manifest)
    return manifest


def default_root():
    return next(
        (p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file()),
        Path.cwd(),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    acquire(args.root, args.protocol, args.out)


if __name__ == "__main__":
    main()
