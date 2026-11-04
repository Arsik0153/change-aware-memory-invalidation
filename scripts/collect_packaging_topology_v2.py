"""Separate metadata-adaptive23-step protocol; preserves the failed24-step v1."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_ID = "packaging-derived-development-collection-v2"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def local(root, name):
    path = (root / name).resolve()
    if Path(name).is_absolute() or ".." in Path(name).parts or not path.is_relative_to(root):
        raise ValueError("input must be a contained root-relative path")
    return path


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True, timeout=30).strip()


def committed_inputs(root, head, names):
    for name in names:
        path = local(root, name)
        result = subprocess.run(
            ["git", "-C", str(root), "cat-file", "blob", head + ":" + name],
            capture_output=True,
            timeout=30,
        )
        if result.returncode or hashlib.sha256(result.stdout).hexdigest() != sha(path):
            raise ValueError("sealed input must match committed HEAD bytes: " + name)


def select_windows(frame):
    if len(frame) < 72 or len(set(frame)) != len(frame):
        raise ValueError("requires at least72 distinct first-parent positions")
    if any(re.fullmatch(r"[0-9a-f]{40}", oid) is None for oid in frame):
        raise ValueError("requires exact40hex commit identities")
    positions = [0, (len(frame) - 24) // 2, len(frame) - 24]
    if any(b - a < 24 for a, b in zip(positions, positions[1:])):
        raise ValueError("selected parent windows must be separated by24positions")
    return [
        {
            "group_id": "packaging-derived-" + frame[position][:12],
            "parent_position": position,
            "parent_commit": frame[position],
            "child_commits": frame[position + 1 : position + 24],
        }
        for position in positions
    ]


def collect(protocol_path, output):
    protocol_path, output = protocol_path.resolve(), output.resolve()
    if output.is_relative_to(ROOT / "data") or not output.is_relative_to(ROOT):
        raise ValueError("output must be a new workspace directory outside data")
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "status": "preflight",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source_access": "commit IDs, ordered parents and timestamps only; no trees/blobs/diffs",
        "evaluation_eligible": False,
    }
    write(output / "manifest.json", manifest)
    try:
        protocol = json.loads(protocol_path.read_text())
        if (
            protocol["protocol_id"] != PROTOCOL_ID
            or protocol["status"] != "sealed"
            or protocol["phase"] != "metadata_only"
            or protocol["schema_version"] != 1
        ):
            raise ValueError("requires the exact sealed metadata-only collection protocol")
        seal = json.loads(local(ROOT, protocol["seal_path"]).read_text())
        if seal["protocol_sha256"] != sha(protocol_path):
            raise ValueError("protocol hash mismatch")
        for name, expected in seal["files"].items():
            if sha(local(ROOT, name)) != expected:
                raise ValueError("sealed input changed: " + name)
        if (
            protocol.get("metadata_informed") is not True
            or protocol.get("original_plan_succeeded") is not False
        ):
            raise ValueError("v2 must disclose the failed v1 and metadata-informed amendment")
        for field in ("amendment", "frame_binding", "study_plan"):
            if seal["files"].get(protocol[field + "_path"]) != protocol[field + "_sha256"]:
                raise ValueError("unsealed v2 method binding: " + field)
        own_name = str(Path(__file__).resolve().relative_to(ROOT))
        if own_name not in seal["files"]:
            raise ValueError("running collector must be sealed")
        expected_selection = {
            "parents": 3,
            "horizon": 23,
            "prefix": 12,
            "minimum_frame": 72,
            "minimum_parent_gap": 24,
            "positions": "0, (L-24)//2, L-24",
        }
        if protocol["selection"] != expected_selection:
            raise ValueError("unsupported selection rule; do not widen a failed frame")
        before = git(ROOT, "rev-parse", "HEAD")
        sealed_names = [*seal["files"], str(protocol_path.relative_to(ROOT)), protocol["seal_path"]]
        if git(ROOT, "status", "--porcelain", "--untracked-files=all", "--", *sealed_names):
            raise ValueError("collection inputs must be committed before metadata access")
        committed_inputs(ROOT, before, sealed_names)
        repo = local(ROOT, protocol["repo_path"])
        if git(repo, "config", "--get", "remote.origin.url") != protocol["repository_url"]:
            raise ValueError("unexpected repository identity")
        start, end = protocol["start_commit"], protocol["boundary_commit"]
        if any(re.fullmatch(r"[0-9a-f]{40}", oid) is None for oid in [start, end]):
            raise ValueError("exact start and boundary commit IDs required")
        if git(repo, "rev-parse", "HEAD") != end:
            raise ValueError("repository HEAD must equal pinned25.0 boundary")
        for oid in [start, end]:
            if git(repo, "rev-parse", "--verify", oid + "^{commit}") != oid:
                raise ValueError("endpoint commit identity mismatch")
        full_path = git(repo, "rev-list", "--first-parent", "--reverse", end).splitlines()
        if start not in full_path:
            raise ValueError("23.2 start is not on25.0 first-parent ancestry")
        frame = full_path[full_path.index(start) :]
        if frame != local(ROOT, protocol["frame_binding_path"]).read_text().splitlines():
            raise ValueError("v2 frame differs from the preserved72-position feasibility evidence")
        groups = select_windows(frame)
        topology = {}
        for position, oid in enumerate(frame):
            row = git(repo, "rev-list", "--parents", "-n", "1", oid).split()
            if row[0] != oid or (position and row[1] != frame[position - 1]):
                raise ValueError("frame first-parent discontinuity")
            topology[oid] = {
                "commit": oid,
                "parents": row[1:],
                "position": position,
                "committer_epoch": int(git(repo, "log", "-1", "--format=%ct", oid)),
            }
        for group in groups:
            previous = group["parent_commit"]
            group.update(
                repo_id="packaging",
                repo_path=protocol["repo_path"],
                source_roots=protocol["source_configuration"]["proposed_index_source_roots"],
            )
            steps = []
            for number, oid in enumerate(group["child_commits"], 1):
                parents = topology[oid]["parents"]
                if not parents or parents[0] != previous:
                    raise ValueError("selected first-parent edge mismatch")
                steps.append(
                    {
                        "step": number,
                        "commit": oid,
                        "previous_commit": previous,
                        "parents": parents,
                        "is_merge": len(parents) > 1,
                    }
                )
                previous = oid
            group["steps"] = steps
        result = {
            "schema_version": 1,
            "protocol_sha256": sha(protocol_path),
            "start_commit": start,
            "boundary_commit": end,
            "frame_length": len(frame),
            "frame": list(topology.values()),
            "groups": groups,
            "parent_source_allowlist_after_separate_commit": [g["parent_commit"] for g in groups],
            "child_source_access_authorized": False,
            "source_configuration": protocol["source_configuration"],
            "merge_steps": sum(s["is_merge"] for g in groups for s in g["steps"]),
        }
        write(output / "topology.json", result)
        for name, expected in seal["files"].items():
            if sha(local(ROOT, name)) != expected:
                raise ValueError("sealed input changed during metadata collection")
        if (
            git(ROOT, "rev-parse", "HEAD") != before
            or sha(protocol_path) != seal["protocol_sha256"]
        ):
            raise ValueError("workspace/protocol changed during collection")
        committed_inputs(ROOT, before, sealed_names)
        manifest.update(
            status="complete",
            implementation_commit=before,
            protocol_sha256=sha(protocol_path),
            seal=seal,
            frame_length=len(frame),
            parent_positions=[g["parent_position"] for g in groups],
            artifact_hashes={"topology.json": sha(output / "topology.json")},
        )
    except Exception as error:
        manifest.update(status="failed", failure=f"{type(error).__name__}: {error}")
        raise
    finally:
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        write(output / "manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    collect(args.protocol, args.out)
