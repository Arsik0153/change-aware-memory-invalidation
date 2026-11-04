#!/usr/bin/env python3
"""Authored local Git controls for final replay provisioning; NEW outputs only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "src/cami").is_dir())
HELPER = HERE / "acquire_packaging_replay_blobs.py"
DRIVER = ROOT / "scripts"
if not (DRIVER / "packaging_replay_support.py").is_file():
    DRIVER = ROOT / "runs/packaging-replay-driver-v2-development-20261104"
BASE = None
FIXTURE = None


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def write(path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def run(argv, *, input_bytes=None, check=True, cwd=None):
    result = subprocess.run(
        argv,
        input=input_bytes,
        capture_output=True,
        cwd=cwd,
        timeout=180,
        env={
            **os.environ,
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    return result


def git(repo, *args, check=True):
    return run(
        ["git", "--no-replace-objects", "--no-optional-locks", "-C", str(repo), *args], check=check
    )


def init(repo):
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Authored fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")


def commit(repo, text):
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", text)


def inventory(repo):
    return {
        line.split()[0].decode(): {"type": line.split()[1].decode(), "size": int(line.split()[2])}
        for line in git(
            repo,
            "cat-file",
            "--batch-all-objects",
            "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        ).stdout.splitlines()
    }


def authored_history():
    author = BASE / "authored-source"
    init(author)
    path = author / "src/packaging/module.py"
    path.parent.mkdir(parents=True)
    path.write_text("".join(f"def f{i}(x=1):\n    return x\n" for i in range(4)))
    (author / "outside-symlink.py").symlink_to("src/packaging/module.py")
    (author / "outside-text.txt").write_text("Full snapshots include this regular text file.\n")
    (author / "outside-large.bin").write_bytes(random.Random(321).randbytes(2 * 1024**2 + 1))
    previous, side, side_blob = None, None, None
    frame = []
    for i in range(72):
        (author / "trajectory.txt").write_text(f"Authored first-parent position {i}\n")
        git(author, "add", "-A")
        if i == 10:
            (author / "side-parent-only.txt").write_text(
                "Distinct side-parent-only body never acquired.\n"
            )
            git(author, "add", "-A")
            tree = git(author, "write-tree").stdout.decode().strip()
            side = (
                git(author, "commit-tree", tree, "-p", previous, "-m", "authored side only")
                .stdout.decode()
                .strip()
            )
            side_blob = (
                git(author, "rev-parse", side + ":side-parent-only.txt").stdout.decode().strip()
            )
            (author / "side-parent-only.txt").unlink()
            git(author, "add", "-A")
        if side:
            git(
                author,
                "update-index",
                "--add",
                "--cacheinfo",
                "160000," + side + ",authored-submodule",
            )
        tree = git(author, "write-tree").stdout.decode().strip()
        parents = [] if previous is None else [previous]
        if i == 10:
            parents.append(side)
        args = ["commit-tree", tree]
        for parent in parents:
            args += ["-p", parent]
        oid = git(author, *args, "-m", f"authored snapshot {i}").stdout.decode().strip()
        frame.append({"position": i, "commit": oid, "parents": parents, "committer_epoch": 0})
        previous = oid
    git(author, "update-ref", "refs/heads/main", previous)
    remote = BASE / "authored-remote.git"
    git(BASE, "clone", "--bare", "--no-local", str(author), str(remote))
    git(remote, "config", "uploadpack.allowFilter", "true")
    git(remote, "config", "uploadpack.allowAnySHA1InWant", "true")
    data = {
        "frame": frame,
        "side_parent": side,
        "side_parent_only_blob": side_blob,
        "remote": remote.as_uri(),
        "boundary": previous,
    }
    write(BASE / "fixture.json", data)
    return data


def make_workspace(name):
    root = BASE / name
    init(root)
    (root / ".gitignore").write_text("/data/\n/runs/\n*.stdout\n*.stderr\n")
    shutil.copytree(
        ROOT / "src/cami", root / "src/cami", ignore=shutil.ignore_patterns("__pycache__")
    )
    (root / "scripts").mkdir()
    for filename in (
        "verify_cami.py",
        "real_structural_replay_support.py",
        "validate_ai_review.py",
        "structural_checker_v2.py",
        "acquire_packaging_parent_blobs.py",
    ):
        shutil.copyfile(ROOT / "scripts" / filename, root / "scripts" / filename)
    for filename in ("run_packaging_replay.py", "packaging_replay_support.py"):
        shutil.copyfile(DRIVER / filename, root / "scripts" / filename)
    fixture_test = DRIVER / "test_packaging_replay.py"
    if not fixture_test.is_file():
        fixture_test = ROOT / "tests/test_packaging_replay.py"
    shutil.copyfile(fixture_test, root / "scripts/test_packaging_replay.py")
    helper = root / "scripts/acquire_packaging_replay_blobs.py"
    shutil.copyfile(HELPER, helper)
    for filename in ("pyproject.toml", ".python-version", "uv.lock"):
        shutil.copyfile(ROOT / filename, root / filename)
    repo = root / "data/authored-partial"
    repo.parent.mkdir()
    git(
        root,
        "-c",
        "protocol.file.allow=always",
        "clone",
        "--filter=blob:none",
        "--no-checkout",
        "--single-branch",
        "--branch",
        "main",
        FIXTURE["remote"],
        str(repo),
    )
    inputs = root / "inputs"
    inputs.mkdir()
    write(root / "authored-frame.json", FIXTURE["frame"])
    bootstrap = """
import importlib.util, json, sys
from pathlib import Path
root=Path(sys.argv[1])
spec=importlib.util.spec_from_file_location('authored_driver_fixture', root/'scripts/test_packaging_replay.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
c=m.PackagingFixture
c.inputs=root/'inputs'; c.repo=root/'data/authored-partial'; c.base=root
c.frame=json.loads((root/'authored-frame.json').read_bytes())
c.make_inputs()
"""
    run([sys.executable, "-c", bootstrap, str(root)])
    p = read(inputs / "protocol.json")
    p["implementation_paths"].append("scripts/acquire_packaging_replay_blobs.py")
    p["replay_blob_acquisition"] = {
        "enabled": True,
        "phase": "final_replay_full_snapshots",
        "source_access_authorized": True,
        "child_source_access_authorized": True,
        "mode": "full_snapshots_exact_frozen_72_only",
        "authorized_snapshot_commits": [row["commit"] for row in FIXTURE["frame"]],
        "mechanics_path": "scripts/acquire_packaging_parent_blobs.py",
        "mechanics_sha256": sha(root / "scripts/acquire_packaging_parent_blobs.py"),
        "replay_support_path": "scripts/packaging_replay_support.py",
        "replay_support_sha256": sha(root / "scripts/packaging_replay_support.py"),
        "repository_transport_url": FIXTURE["remote"],
        "recorded_remote_HEAD": FIXTURE["boundary"],
        "budget": {
            "network_size_policy": "unknown_transfer_sizes_explicitly_acknowledged_postfetch_observed_cap",
            "unknown_transfer_and_transient_storage_overshoot_acknowledged": True,
            "max_study_storage_bytes": 2147483648,
            "minimum_free_bytes": 5368709120,
            "total_seconds": 1200,
            "command_timeout_seconds": 120,
            "fetch_batch_objects": 32,
        },
    }
    write(inputs / "protocol.json", p)
    reseal(root)
    return root, repo, helper


def reseal(root):
    protocol = root / "inputs/protocol.json"
    files = {
        str(path.relative_to(root)): sha(path)
        for folder in ("src", "scripts", "inputs")
        for path in (root / folder).rglob("*")
        if path.is_file()
        and path.name not in {"protocol.json", "seal.json"}
        and "__pycache__" not in path.parts
    }
    for name in ("pyproject.toml", ".python-version", "uv.lock"):
        files[name] = sha(root / name)
    write(root / "inputs/seal.json", {"protocol_sha256": sha(protocol), "files": files})
    commit(root, "authored sealed final replay inputs")


def invoke(root, helper, name="attempt"):
    out = root / "runs" / name
    result = run(
        [
            sys.executable,
            str(helper),
            "--root",
            str(root),
            "--protocol",
            str(root / "inputs/protocol.json"),
            "--out",
            str(out),
        ],
        check=False,
    )
    (root / (name + ".stdout")).write_bytes(result.stdout)
    (root / (name + ".stderr")).write_bytes(result.stderr)
    return result, out, read(out / "manifest.json")


class ReplayBlobTests(unittest.TestCase):
    def deny(self, name, change, *, seal=True):
        root, repo, helper = make_workspace(name)
        change(root)
        if seal:
            reseal(root)
        before = inventory(repo)
        result, out, report = invoke(root, helper)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(inventory(repo), before)
        if (out / "commands.jsonl").exists():
            self.assertNotIn(str(repo), (out / "commands.jsonl").read_text())
        return report

    def test_exact72_all_blob_kinds_and_side_parent_exclusion(self):
        root, repo, helper = make_workspace("exact")
        before = inventory(repo)
        self.assertFalse(any(row["type"] == "blob" for row in before.values()))
        result, out, report = invoke(root, helper)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        after = inventory(repo)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["snapshot_count"], 72)
        self.assertEqual(set(after) - set(before), set(report["selected_blob_oids"]))
        self.assertNotIn(FIXTURE["side_parent_only_blob"], after)
        self.assertEqual(len(report["authorized_child_commits"]), 69)
        self.assertEqual(len(report["authorized_parent_commits"]), 3)
        self.assertEqual(report["global_authorization_gate"]["candidate_claims"], 24)
        self.assertEqual(
            set(report["global_authorization_gate"]["eligible_counts_by_group"].values()), {8}
        )
        self.assertEqual(report["repository_before"], report["repository_after"])
        self.assertEqual(report["source_before"], report["source_after"])
        self.assertEqual(report["oversize_blob_count"], 1)
        entries = read(out / "snapshot-entry-sizes.json")
        self.assertTrue(
            any(
                row["mode"] == "120000"
                and row["oid"] in after
                and not row["production_reader_would_read_body_by_mode_and_size"]
                for row in entries
            )
        )
        self.assertTrue(
            any(
                row["git_type"] == "commit"
                and not row["selected_for_acquisition"]
                and row["size"] is None
                for row in entries
            )
        )
        self.assertTrue(
            any(
                row["path"] == "outside-text.txt"
                and row["production_reader_would_read_body_by_mode_and_size"]
                for row in entries
            )
        )
        commands = [json.loads(line) for line in (out / "commands.jsonl").read_text().splitlines()]
        trees = [row for row in commands if "ls-tree" in row["argv"]]
        self.assertEqual([row["argv"][-1] for row in trees], report["authorized_snapshot_commits"])
        self.assertNotIn(FIXTURE["side_parent"], [row["argv"][-1] for row in trees])
        self.assertTrue(all("-l" not in row["argv"] for row in trees))
        fetches = [row for row in commands if "fetch" in row["argv"]]
        self.assertEqual(
            [oid for row in fetches for oid in row["stdin_object_ids"]],
            report["explicit_missing_blob_wants"],
        )
        project_commands = [row for row in commands if str(repo) in row["argv"]]
        self.assertFalse(
            any("blob" in row["argv"] or "--batch" in row["argv"] for row in project_commands)
        )
        for name, expected in report["artifact_hashes"].items():
            self.assertEqual(sha(out / name), expected)
        repeat, _, repeated = invoke(root, helper, "repeat")
        self.assertEqual(repeat.returncode, 0, repeat.stderr.decode())
        self.assertEqual(repeated["acquired_blob_count"], 0)
        self.assertEqual(repeated["explicit_missing_blob_wants"], [])
        frozen = sha(out / "manifest.json")
        existing, _, _ = invoke(root, helper)
        self.assertNotEqual(existing.returncode, 0)
        self.assertEqual(sha(out / "manifest.json"), frozen)

    def test_unsealed_final_protocol_denied(self):
        def change(root):
            path = root / "inputs/protocol.json"
            p = read(path)
            p["status"] = "draft"
            write(path, p)

        self.deny("unsealed", change)

    def test_uncommitted_rehashed_final_protocol_denied(self):
        def change(root):
            path = root / "inputs/protocol.json"
            p = read(path)
            p["note"] = "authored uncommitted bytes"
            write(path, p)
            seal = read(root / "inputs/seal.json")
            seal["protocol_sha256"] = sha(path)
            write(root / "inputs/seal.json", seal)

        report = self.deny("uncommitted", change, seal=False)
        self.assertIn("committed", report["failure"])

    def test_disabled_acquisition_denied(self):
        def change(root):
            path = root / "inputs/protocol.json"
            p = read(path)
            p["replay_blob_acquisition"]["enabled"] = False
            write(path, p)

        self.deny("disabled", change)

    def test_side_parent_allowlist_injection_denied(self):
        def change(root):
            path = root / "inputs/protocol.json"
            p = read(path)
            p["replay_blob_acquisition"]["authorized_snapshot_commits"][10] = FIXTURE["side_parent"]
            write(path, p)

        self.deny("side-injection", change)

    def test_global_parent_ineligibility_denied(self):
        def change(root):
            p = read(root / "inputs/protocol.json")
            group = p["review_groups"][-1]
            review_ref = group["ai_reviews"][0]
            review_path = root / review_ref["path"]
            review = read(review_path)
            real_ids = {
                row["id"]
                for row in read(root / group["case_map_path"])
                if row["origin_class"] == "derived_parent_claim"
            }
            for row in review["items"]:
                if row["id"] in real_ids:
                    row["verdict"] = "contradicted"
            write(review_path, review)
            review_ref["sha256"] = sha(review_path)
            response_path = root / review_ref["response_budget_path"]
            response = read(response_path)
            response["review_sha256"] = sha(review_path)
            write(response_path, response)
            review_ref["response_budget_sha256"] = sha(response_path)
            decisions_path = root / p["parent_decisions_path"]
            decisions = [json.loads(line) for line in decisions_path.read_text().splitlines()]
            for row in decisions:
                if row["group_id"] == group["group_id"]:
                    row["eligible"] = False
                    row["exclusion_reasons"] = ["fresh_AI_not_both_supported"]
            decisions_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in decisions)
            )
            write(root / "inputs/protocol.json", p)

        report = self.deny("ineligible-last-group", change)
        self.assertIn("fewerthan4", report["failure"])

    def test_forged_eligible_summary_denied(self):
        def change(root):
            p = read(root / "inputs/protocol.json")
            path = root / p["parent_decisions_path"]
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            rows[0]["eligible"] = False
            rows[0]["exclusion_reasons"] = ["fresh_AI_not_both_supported"]
            path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))

        report = self.deny("forged-decision", change)
        self.assertIn("disagrees", report["failure"])

    def test_parent_mechanics_pin_denied(self):
        def change(root):
            path = root / "scripts/acquire_packaging_parent_blobs.py"
            path.write_text(path.read_text() + "\n# Authored mutation\n")

        report = self.deny("mechanics-mutated", change)
        self.assertIn("pinned immutable", report["failure"])

    def test_gate_not_sealed_denied(self):
        root, repo, helper = make_workspace("gate-unsealed")
        seal = read(root / "inputs/seal.json")
        del seal["files"]["scripts/packaging_replay_support.py"]
        write(root / "inputs/seal.json", seal)
        commit(root, "authored unsealed review gate")
        before = inventory(repo)
        result, out, report = invoke(root, helper)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("offline review gate", report["failure"])
        self.assertEqual(before, inventory(repo))
        self.assertFalse((out / "commands.jsonl").exists())

    def test_observed_overshoot_preserves_exact_attempt(self):
        root, repo, helper = make_workspace("observed-overshoot")
        path = root / "inputs/protocol.json"
        p = read(path)
        p["replay_blob_acquisition"]["budget"]["max_study_storage_bytes"] = 1024**2
        write(path, p)
        reseal(root)
        before = inventory(repo)
        result, out, report = invoke(root, helper)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["status"], "failed")
        self.assertIn("post-acquisition", report["failure"])
        self.assertTrue(list(out.glob("objects-after-batch-*.json")))
        self.assertEqual(set(inventory(repo)) - set(before), set(report["observed_new_object_ids"]))
        self.assertTrue(
            set(report["observed_new_object_ids"]) <= set(report["explicit_missing_blob_wants"])
        )
        self.assertNotIn(FIXTURE["side_parent_only_blob"], inventory(repo))
        self.assertEqual(report["source_before"], report["source_after"])


def main():
    global ROOT, HELPER, DRIVER, BASE, FIXTURE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--helper", type=Path, default=HELPER)
    parser.add_argument("--driver-dir", type=Path, default=DRIVER)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    ROOT, HELPER, DRIVER, BASE = (
        args.root.resolve(),
        args.helper.resolve(),
        args.driver_dir.resolve(),
        args.out.resolve(),
    )
    BASE.mkdir(parents=True, exist_ok=False)
    FIXTURE = authored_history()
    with (BASE / "tests.log").open("w") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(ReplayBlobTests)
        )
    report = {
        "status": "pass" if result.wasSuccessful() else "fail",
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "helper_sha256": sha(HELPER),
        "review_gate_sha256": sha(DRIVER / "packaging_replay_support.py"),
        "fixture_builder_sha256": sha(DRIVER / "test_packaging_replay.py")
        if (DRIVER / "test_packaging_replay.py").is_file()
        else sha(ROOT / "tests/test_packaging_replay.py"),
        "parent_mechanics_sha256": sha(ROOT / "scripts/acquire_packaging_parent_blobs.py"),
        "actual_packaging_commands": 0,
        "external_network_commands": 0,
        "fixture_scope": "72 authored first-parent snapshots plus a distinct side-parent-only blob; unchanged real replay load_inputs and authored review fixture builder",
        "raw_test_log": "tests.log",
    }
    write(BASE / "report.json", report)
    print(json.dumps(report, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
