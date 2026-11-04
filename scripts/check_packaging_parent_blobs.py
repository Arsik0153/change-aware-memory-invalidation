#!/usr/bin/env python3
"""Run authored local Git controls in one NEW output directory; no project access."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
HELPER = HERE / "acquire_packaging_parent_blobs.py"
BASE = None
FIXTURE = None


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def read_json(path):
    return json.loads(path.read_bytes())


def git(repo, *args, check=True):
    result = subprocess.run(
        ["git", "--no-replace-objects", "--no-optional-locks", "-C", str(repo), *args],
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"},
        capture_output=True,
        timeout=30,
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    return result


def inventory(repo):
    return {
        line.split()[0].decode(): (line.split()[1].decode(), int(line.split()[2]))
        for line in git(
            repo,
            "cat-file",
            "--batch-all-objects",
            "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        ).stdout.splitlines()
    }


def init(repo):
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Authored fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")


def commit(repo, message):
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD").stdout.decode().strip()


def make_fixture():
    author = BASE / "authored-source"
    init(author)
    files = {
        "packaging/allowed.py": b"def allowed(): return 0\n",
        "src/packaging/second.py": b"def second(): return 2\n",
        "outside.py": b"OUTSIDE_DISTINCT_NEVER_FETCH\n",
        "packaging/tests/rejected.py": b"TEST_DISTINCT_NEVER_FETCH\n",
        "packaging/vendor/rejected.py": b"VENDOR_DISTINCT_NEVER_FETCH\n",
        "packaging/note.txt": b"TEXT_DISTINCT_NEVER_FETCH\n",
        "aliased_outside.py": b"def second(): return 2\n",
        "packaging/large.py": random.Random(123).randbytes(2 * 1024**2 + 1),
    }
    for name, raw in files.items():
        path = author / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    (author / "packaging/link.py").symlink_to("../outside.py")
    os.chmod(author / "src/packaging/second.py", 0o755)
    parents = [commit(author, "authored parent zero")]
    for number in (1, 2):
        (author / "packaging/allowed.py").write_text(f"def allowed(): return {number}\n")
        parents.append(commit(author, f"authored parent {number}"))
    (author / "packaging/allowed.py").write_text("CHILD_DISTINCT_NEVER_FETCH\n")
    (author / "packaging/child_only.py").write_text("CHILD_ONLY_DISTINCT_NEVER_FETCH\n")
    boundary = commit(author, "authored child boundary")
    unwanted = {
        name: git(author, "rev-parse", parents[0] + ":" + name).stdout.decode().strip()
        for name in (
            "outside.py",
            "packaging/tests/rejected.py",
            "packaging/vendor/rejected.py",
            "packaging/note.txt",
            "packaging/link.py",
        )
    }
    unwanted["child_modified"] = (
        git(author, "rev-parse", "HEAD:packaging/allowed.py").stdout.decode().strip()
    )
    unwanted["child_only"] = (
        git(author, "rev-parse", "HEAD:packaging/child_only.py").stdout.decode().strip()
    )
    remote = BASE / "authored-remote.git"
    git(BASE, "clone", "--bare", "--no-local", str(author), str(remote))
    git(remote, "config", "uploadpack.allowFilter", "true")
    git(remote, "config", "uploadpack.allowAnySHA1InWant", "true")
    write_json(
        BASE / "fixture.json",
        {"parents": parents, "boundary": boundary, "unwanted": unwanted, "remote": remote.as_uri()},
    )
    return {"parents": parents, "boundary": boundary, "unwanted": unwanted, "remote": remote}


def workspace(name, change=None):
    root = BASE / name
    init(root)
    (root / "scripts").mkdir()
    helper = root / "scripts/acquire_packaging_parent_blobs.py"
    shutil.copyfile(HELPER, helper)
    (root / "pyproject.toml").write_text("# Authored infrastructure fixture\n")
    (root / ".gitignore").write_text("/data/\n/runs/\n")
    repo = root / "data/partial"
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
        FIXTURE["remote"].as_uri(),
        str(repo),
    )
    topology = {
        "parent_source_allowlist_after_separate_commit": FIXTURE["parents"],
        "child_source_access_authorized": False,
        "groups": [{"parent_commit": oid} for oid in FIXTURE["parents"]],
    }
    write_json(root / "topology.json", topology)
    protocol = {
        "schema_version": 1,
        "protocol_id": "packaging-parent-blob-acquisition-v1",
        "status": "sealed",
        "phase": "parent_blob_acquisition",
        "source_access_authorized": True,
        "child_source_access_authorized": False,
        "mode": "parent_filtered_blobs_only",
        "source_configuration": {
            "eligible_module_prefixes": ["src/packaging/", "packaging/"],
            "excluded_path_components": ["tests", "test", "_vendor", "vendor", "__pycache__"],
            "extensions": [".py"],
            "regular_modes": ["100644", "100755"],
            "max_file_bytes": 2097152,
        },
        "budget": {
            "network_size_policy": "unknown_transfer_sizes_explicitly_acknowledged_postfetch_observed_cap",
            "unknown_transfer_and_transient_storage_overshoot_acknowledged": True,
            "max_study_storage_bytes": 2147483648,
            "minimum_free_bytes": 5368709120,
            "total_seconds": 120,
            "command_timeout_seconds": 30,
            "fetch_batch_objects": 64,
        },
        "repo_path": "data/partial",
        "repository_url": FIXTURE["remote"].as_uri(),
        "boundary_commit": FIXTURE["boundary"],
        "authorized_parent_commits": FIXTURE["parents"],
        "topology_path": "topology.json",
        "topology_sha256": sha(root / "topology.json"),
        "seal_path": "seal.json",
        "recorded_remote_HEAD": FIXTURE["boundary"],
    }
    if change:
        change(protocol, topology, root)
        write_json(root / "topology.json", topology)
        protocol["topology_sha256"] = sha(root / "topology.json")
    write_json(root / "protocol.json", protocol)
    write_json(
        root / "seal.json",
        {
            "protocol_sha256": sha(root / "protocol.json"),
            "files": {
                "topology.json": sha(root / "topology.json"),
                "scripts/acquire_packaging_parent_blobs.py": sha(helper),
            },
        },
    )
    commit(root, "authored sealed source authorization")
    return root, repo, helper


def invoke(root, helper, name="attempt"):
    output = root / "runs" / name
    result = subprocess.run(
        [
            sys.executable,
            str(helper),
            "--root",
            str(root),
            "--protocol",
            str(root / "protocol.json"),
            "--out",
            str(output),
        ],
        capture_output=True,
        timeout=150,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    (root / f"{name}.stdout").write_bytes(result.stdout)
    (root / f"{name}.stderr").write_bytes(result.stderr)
    return result, output, read_json(output / "manifest.json")


class AcquisitionTests(unittest.TestCase):
    def test_exact_oid_acquisition_and_repeat(self):
        root, repo, helper = workspace("exact")
        before = inventory(repo)
        self.assertFalse(any(kind == "blob" for kind, _ in before.values()))
        result, out, report = invoke(root, helper)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        after = inventory(repo)
        self.assertEqual(set(after) - set(before), set(report["explicit_missing_blob_wants"]))
        self.assertEqual(
            set(report["explicit_missing_blob_wants"]), set(report["selected_blob_oids"])
        )
        self.assertTrue(set(FIXTURE["unwanted"].values()).isdisjoint(after))
        self.assertEqual(report["oversize_blob_count"], 1)
        self.assertEqual(report["project_blob_body_reads"], 0)
        self.assertEqual(report["repository_before"], report["repository_after"])
        self.assertEqual(report["source_before"], report["source_after"])
        self.assertEqual({p.name for p in repo.iterdir()}, {".git"})
        self.assertEqual(len(report["excluded_paths_aliasing_selected_oids"]), 3)
        commands = [json.loads(line) for line in (out / "commands.jsonl").read_text().splitlines()]
        project = [row for row in commands if str(repo) in row["argv"]]
        self.assertEqual(len([row for row in project if "ls-tree" in row["argv"]]), 3)
        self.assertTrue(all("-l" not in row["argv"] for row in project))
        self.assertFalse(any("blob" in row["argv"] for row in project))
        fetches = [row for row in project if "fetch" in row["argv"]]
        self.assertEqual(len(fetches), 1)
        self.assertEqual(fetches[0]["stdin_object_ids"], report["explicit_missing_blob_wants"])
        self.assertTrue(
            all(row["transport_enabled"] is None for row in commands if "fetch" not in row["argv"])
        )
        for name, expected in report["artifact_hashes"].items():
            self.assertEqual(sha(out / name), expected)
        second, _, rerun = invoke(root, helper, "repeat")
        self.assertEqual(second.returncode, 0, second.stderr.decode())
        self.assertEqual(rerun["explicit_missing_blob_wants"], [])
        self.assertEqual(rerun["acquired_blob_count"], 0)
        frozen = sha(out / "manifest.json")
        existing, _, _ = invoke(root, helper)
        self.assertNotEqual(existing.returncode, 0)
        self.assertEqual(sha(out / "manifest.json"), frozen)

    def rejected_before_project(self, name, change):
        root, repo, helper = workspace(name, change)
        before = inventory(repo)
        result, out, report = invoke(root, helper)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(inventory(repo), before)
        if (out / "commands.jsonl").exists():
            self.assertNotIn(str(repo), (out / "commands.jsonl").read_text())
        return report

    def test_metadata_phase_denied(self):
        self.rejected_before_project(
            "metadata-denied",
            lambda p, t, r: p.update(phase="metadata_only", source_access_authorized=False),
        )

    def test_multiple_exact_oid_batches(self):
        def change(p, t, r):
            p["budget"]["fetch_batch_objects"] = 2

        root, repo, helper = workspace("multiple-batches", change)
        result, out, report = invoke(root, helper)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        commands = [json.loads(line) for line in (out / "commands.jsonl").read_text().splitlines()]
        wants = [row["stdin_object_ids"] for row in commands if "fetch" in row["argv"]]
        self.assertEqual([len(batch) for batch in wants], [2, 2, 1])
        self.assertEqual([oid for batch in wants for oid in batch], report["selected_blob_oids"])
        self.assertEqual(len(list(out.glob("objects-after-batch-*.json"))), 3)
        self.assertTrue(set(FIXTURE["unwanted"].values()).isdisjoint(inventory(repo)))

    def test_child_authorization_denied(self):
        self.rejected_before_project(
            "child-denied", lambda p, t, r: p.update(child_source_access_authorized=True)
        )

    def test_acknowledgement_required(self):
        def change(p, t, r):
            p["budget"]["unknown_transfer_and_transient_storage_overshoot_acknowledged"] = False

        self.rejected_before_project("ack-denied", change)

    def test_filter_widening_denied(self):
        def change(p, t, r):
            p["source_configuration"]["eligible_module_prefixes"].append("")

        self.rejected_before_project("widen-denied", change)

    def test_parent_allowlist_mismatch_denied(self):
        def change(p, t, r):
            p["authorized_parent_commits"] = list(reversed(p["authorized_parent_commits"]))

        self.rejected_before_project("parent-denied", change)

    def test_ignored_sealed_input_denied(self):
        root, repo, helper = workspace("ignored-denied")
        (root / ".gitignore").write_text("/data/\n/runs/\n/ignored.json\n")
        (root / "ignored.json").write_text("{}\n")
        seal = read_json(root / "seal.json")
        seal["files"]["ignored.json"] = sha(root / "ignored.json")
        write_json(root / "seal.json", seal)
        commit(root, "authored ignored sealed input")
        before = inventory(repo)
        result, out, report = invoke(root, helper)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(inventory(repo), before)
        self.assertNotIn(str(repo), (out / "commands.jsonl").read_text())

    def test_modified_assume_unchanged_input_denied(self):
        root, repo, helper = workspace("assume-unchanged-denied")
        git(root, "update-index", "--assume-unchanged", "topology.json")
        (root / "topology.json").write_text((root / "topology.json").read_text() + "\n")
        seal = read_json(root / "seal.json")
        seal["files"]["topology.json"] = sha(root / "topology.json")
        protocol = read_json(root / "protocol.json")
        protocol["topology_sha256"] = sha(root / "topology.json")
        write_json(root / "protocol.json", protocol)
        seal["protocol_sha256"] = sha(root / "protocol.json")
        write_json(root / "seal.json", seal)
        commit(root, "authored protocol rehash without committed topology")
        self.assertEqual(git(root, "status", "--porcelain").stdout, b"")
        result, out, report = invoke(root, helper)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["status"], "failed")
        self.assertNotIn(str(repo), (out / "commands.jsonl").read_text())

    def test_observed_overshoot_preserves_attempt(self):
        def change(p, t, r):
            p["budget"]["max_study_storage_bytes"] = 1024**2

        root, repo, helper = workspace("storage-overshoot", change)
        before = inventory(repo)
        result, out, report = invoke(root, helper)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["status"], "failed")
        self.assertIn("post-acquisition", report["failure"])
        self.assertTrue((out / "objects-after-batch-0000.json").is_file())
        self.assertEqual(
            set(inventory(repo)) - set(before), set(report["explicit_missing_blob_wants"])
        )
        self.assertEqual(
            set(report["observed_new_object_ids"]), set(report["explicit_missing_blob_wants"])
        )
        self.assertTrue(set(FIXTURE["unwanted"].values()).isdisjoint(inventory(repo)))
        self.assertEqual(report["source_before"], report["source_after"])

    def test_misconfigured_clone_denied_before_tree(self):
        root, repo, helper = workspace("filter-clone-denied")
        git(repo, "config", "remote.origin.partialclonefilter", "blob:limit=1m")
        before = inventory(repo)
        result, out, report = invoke(root, helper)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("blob:none", report["failure"])
        self.assertNotIn("ls-tree", (out / "commands.jsonl").read_text())
        self.assertEqual(inventory(repo), before)

    def test_disabled_lazy_fetch(self):
        root, repo, _ = workspace("lazy-disabled")
        before = inventory(repo)
        oid = FIXTURE["unwanted"]["outside.py"]
        result = git(repo, "cat-file", "-e", oid, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(inventory(repo), before)
        write_json(
            root / "lazy-result.json",
            {
                "returncode": result.returncode,
                "stderr": result.stderr.decode(),
                "inventory_unchanged": True,
            },
        )

    def test_tree_filter_edge_cases(self):
        spec = importlib.util.spec_from_file_location("authored_helper_filter", HELPER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        oid = "a" * 40
        paths = [
            ("100644", "blob", b"packaging/direct.py", True),
            ("100755", "blob", b"src/packaging/direct.py", True),
            ("100644", "blob", b"packaging/tests/test.py", False),
            ("100644", "blob", b"packaging/test/test.py", False),
            ("100644", "blob", b"packaging/_vendor/test.py", False),
            ("100644", "blob", b"packaging/vendor/test.py", False),
            ("100644", "blob", b"packaging/__pycache__/test.py", False),
            ("120000", "blob", b"packaging/symlink.py", False),
            ("160000", "commit", b"packaging/submodule.py", False),
            ("100644", "blob", b"packaging/../outside.py", False),
            ("100644", "blob", b"packaging/not-python.pyi", False),
            ("100644", "blob", b"outside.py", False),
            ("100644", "blob", b"packaging/invalid-\xff.py", False),
        ]
        raw = b"".join(
            f"{mode} {kind} {oid}\t".encode() + path + b"\0" for mode, kind, path, _ in paths
        )
        rows = module.tree_entries(raw, "b" * 40)
        self.assertEqual([row["selected"] for row in rows], [row[3] for row in paths])
        write_json(BASE / "filter-edge-cases.json", rows)

    def test_timeout_record_preserved(self):
        spec = importlib.util.spec_from_file_location("authored_helper_timeout", HELPER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        output = BASE / "timeout-record"
        output.mkdir()
        commands = module.Commands(output, 0.05, 2)
        with self.assertRaisesRegex(ValueError, "exceeded"):
            commands.run(BASE, "-c", "alias.authoredwait=!sleep 2", "authoredwait")
        self.assertTrue(commands.records[0]["timed_out"])
        self.assertTrue((output / "commands.jsonl").is_file())


def main():
    global BASE, HELPER, FIXTURE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helper", type=Path, default=HELPER)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    HELPER = args.helper.resolve()
    BASE = args.out.resolve()
    BASE.mkdir(parents=True, exist_ok=False)
    FIXTURE = make_fixture()
    stream = io.StringIO()
    with redirect_stdout(stream), redirect_stderr(stream):
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(AcquisitionTests)
        )
    (BASE / "tests.log").write_text(stream.getvalue())
    report = {
        "status": "pass" if result.wasSuccessful() else "fail",
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "helper_sha256": sha(HELPER),
        "external_network_commands": 0,
        "actual_packaging_commands": 0,
        "fixture_source": "authored local Git only",
        "raw_test_log": "tests.log",
    }
    write_json(BASE / "report.json", report)
    print(json.dumps(report, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
