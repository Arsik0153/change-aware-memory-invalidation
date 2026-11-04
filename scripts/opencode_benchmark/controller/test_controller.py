"""Authored local fixtures only. No Docker, upstream source, credentials, or models."""

from __future__ import annotations

import io
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from study_common import command, digest, inventory, write
from study_controller import run_trial
from study_ledger import complete, summarize, terminals
from study_runtime import quality_valid, verify_memory
from study_schema import ARMS, plan
from study_workspace import capture, create_namespace, evaluation_workspace, extract, reset


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = self.root / "base"
        (self.base / "src/pkg").mkdir(parents=True)
        (self.base / "tests").mkdir()
        (self.base / "src/pkg/a.py").write_text("VALUE = 1\n")
        (self.base / "src/pkg/deleted.py").write_text("OLD = True\n")
        (self.base / "tests/test_a.py").write_text("def test_fixed(): assert False\n")
        self.archive = self.root / "source.tar.gz"
        with tarfile.open(self.archive, "w:gz") as stream:
            for path in sorted(self.base.rglob("*")):
                if path.is_file():
                    stream.add(path, arcname=path.relative_to(self.base), recursive=False)
        self.namespace = self.root / "ns"
        create_namespace(self.namespace, "study")
        self.canonical = reset(self.namespace, self.archive, digest(self.archive), "study")
        self.workspace = self.namespace / "workspace"

    def tearDown(self):
        self.temp.cleanup()

    def test_balanced_schedule_and_dependencies(self):
        rows = plan({"normalized": {"sequence": ["a", "a", "b", "b"]}})
        self.assertEqual(len(rows), 36)
        for stage in range(1, 5):
            orders = [
                [r["arm"] for r in rows if r["stage"] == stage and r["repetition"] == rep]
                for rep in range(1, 4)
            ]
            self.assertEqual({order[0] for order in orders}, set(ARMS))
        self.assertEqual(rows[3]["predecessor"], "r1-static-s1")

    def test_canonical_reset_discards_agent_history_preserves_directory(self):
        inode = self.workspace.stat().st_ino
        (self.workspace / "src/pkg/a.py").write_text("VALUE = 99\n")
        env = dict(
            os.environ,
            GIT_AUTHOR_NAME="agent",
            GIT_AUTHOR_EMAIL="a@invalid",
            GIT_COMMITTER_NAME="agent",
            GIT_COMMITTER_EMAIL="a@invalid",
        )
        command(["git", "-C", self.workspace, "add", "--all"], env=env)
        command(["git", "-C", self.workspace, "commit", "-m", "agent"], env=env)
        command(["git", "-C", self.workspace, "remote", "add", "origin", "/unavailable"])
        old_head = command(["git", "-C", self.workspace, "rev-parse", "HEAD"])["stdout"].strip()
        reset(self.namespace, self.archive, digest(self.archive), "study")
        self.assertEqual(self.workspace.stat().st_ino, inode)
        self.assertEqual((self.workspace / "src/pkg/a.py").read_text(), "VALUE = 1\n")
        self.assertEqual(command(["git", "-C", self.workspace, "remote"])["stdout"], "")
        self.assertNotEqual(
            command(["git", "-C", self.workspace, "cat-file", "-e", old_head])["returncode"], 0
        )

    def test_archive_link_traversal_and_duplicate_rejected(self):
        for name, kind in [
            ("../escape.py", "file"),
            ("src/link.py", "link"),
            ("src/a.py", "duplicate"),
        ]:
            archive = self.root / (kind + ".tar")
            with tarfile.open(archive, "w") as stream:
                member = tarfile.TarInfo(name)
                if kind == "link":
                    member.type = tarfile.SYMTYPE
                    member.linkname = "/etc/passwd"
                    stream.addfile(member)
                else:
                    member.size = 1
                    stream.addfile(member, io.BytesIO(b"x"))
                    if kind == "duplicate":
                        stream.addfile(member, io.BytesIO(b"y"))
            with self.assertRaises(ValueError):
                extract(archive, self.root / ("bad-" + kind))

    def test_canonical_hash_denial_before_reset(self):
        with self.assertRaises(ValueError):
            reset(self.namespace, self.archive, "bad", "study")
        self.assertTrue((self.workspace / "src/pkg/a.py").exists())

    def test_export_captures_committed_additions_and_deletions(self):
        (self.workspace / "src/pkg/a.py").write_text("VALUE = 2\n")
        (self.workspace / "src/pkg/deleted.py").unlink()
        (self.workspace / "src/pkg/new.py").write_text("NEW = 3\n")
        (self.workspace / "tests/test_a.py").write_text("def test_fake(): pass\n")
        command(["git", "-C", self.workspace, "add", "--all"])
        # Commit-independent export also works if Git is removed altogether.
        shutil.rmtree(self.workspace / ".git")
        record = capture(self.workspace, self.canonical["canonical_files"], self.root / "candidate")
        self.assertEqual(record["added"], ["pkg/new.py"])
        self.assertEqual(record["deleted"], ["pkg/deleted.py"])
        self.assertEqual(record["changed"], ["pkg/a.py"])
        self.assertIn("tests/test_a.py", record["outside_source_changes"])

    def test_source_symlink_rejected(self):
        (self.workspace / "src/pkg/leak.py").symlink_to("/etc/passwd")
        with self.assertRaises(ValueError):
            capture(
                self.workspace, self.canonical["canonical_files"], self.root / "symlink-candidate"
            )

    def test_source_fifo_rejected_without_reading(self):
        os.mkfifo(self.workspace / "src/pkg/pipe.py")
        with self.assertRaises(ValueError):
            capture(self.workspace, self.canonical["canonical_files"], self.root / "fifo-candidate")

    def test_source_directory_symlink_rejected(self):
        (self.workspace / "src/subdir").symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(ValueError):
            inventory(self.workspace / "src")

    def test_grader_restores_original_tests(self):
        (self.workspace / "tests/test_a.py").write_text("def test_fake(): pass\n")
        (self.workspace / "src/pkg/deleted.py").unlink()
        candidate = self.root / "candidate"
        capture(self.workspace, self.canonical["canonical_files"], candidate)
        (self.root / "oracles").mkdir()
        (self.root / "oracles/test_acceptance.py").write_text(
            "def test_acceptance(): assert False\n"
        )
        task = {
            "archive": self.archive.name,
            "replace_regression_tests": None,
            "regression": "tests",
            "oracle_root": "oracles",
        }
        target = evaluation_workspace(self.root, task, candidate, self.root / "grading")
        self.assertIn("assert False", (target / "tests/test_a.py").read_text())
        self.assertFalse((target / "src/pkg/deleted.py").exists())
        self.assertTrue((target / "oracles/test_acceptance.py").exists())

    def test_terminal_reused_and_mutation_rejected(self):
        output = self.root / "output"
        trial = {"id": "one"}
        directory = output / "trials/one"
        directory.mkdir(parents=True)
        (directory / "evidence").write_text("original")
        complete(
            directory, {"trial": trial, "status": "failed", "memory_usable": True, "costs": {}}
        )
        self.assertEqual(terminals(output, [trial])["one"]["status"], "failed")
        (directory / "evidence").write_text("tamper")
        with self.assertRaises(ValueError):
            terminals(output, [trial])

    def test_incomplete_recovery_is_terminal_not_retry(self):
        output = self.root / "output"
        trial = {"id": "one"}
        directory = output / "trials/one"
        directory.mkdir(parents=True)
        (directory / "partial").write_text("kept")
        row = terminals(output, [trial], recover=True)["one"]
        self.assertEqual(row["status"], "abandoned")
        self.assertFalse(row["memory_usable"])
        self.assertEqual((directory / "partial").read_text(), "kept")
        self.assertEqual(terminals(output, [trial])["one"], row)

    def test_extra_terminal_file_rejected(self):
        output = self.root / "output"
        trial = {"id": "one"}
        directory = output / "trials/one"
        directory.mkdir(parents=True)
        complete(directory, {"trial": trial, "status": "failed"})
        (directory / "unrecorded").write_text("x")
        with self.assertRaises(ValueError):
            terminals(output, [trial])

    def fake_study(self):
        return {
            "bundle_path": str(self.root),
            "normalized": {
                "tasks": [
                    {
                        "id": "task",
                        "archive": self.archive.name,
                        "archive_sha256": digest(self.archive),
                        "prompt": "authored fixture only",
                    }
                ]
            },
        }

    def trial(self, arm="plain", stage=1):
        return {
            "id": f"r1-{arm}-s{stage}",
            "arm": arm,
            "stage": stage,
            "repetition": 1,
            "task": "task",
            "predecessor": None,
        }

    def test_plain_never_constructs_memory_and_quality_uses_fixed_grader(self):
        output = self.root / "output"
        with (
            patch("study_controller.validate"),
            patch("study_controller.regression_allowance", return_value=({}, "authored-baseline")),
            patch("study_controller.origin_memory") as construct,
            patch("study_controller.session", return_value={"status": "passed"}),
            patch("study_controller.digest", wraps=digest) as hashed,
            patch("study_controller.grade", return_value={"status": "pass"}),
        ):
            # The fake harness still supplies a pinned evidence manifest path.
            def fake_session(study, trial, workspace, memory, prompt, out):
                out.mkdir()
                write(out / "manifest.json", {"status": "passed"})
                return {"status": "passed"}

            with patch("study_controller.session", side_effect=fake_session):
                row = run_trial(self.fake_study(), "study", output, self.trial(), None)
            construct.assert_not_called()
            self.assertEqual(row["status"], "passed")
            self.assertEqual(row["costs"]["construction_host_wall_seconds"], 0)
            self.assertTrue(hashed.called)

    def test_model_failure_preserved_grading_still_runs(self):
        output = self.root / "output"
        with (
            patch("study_controller.validate"),
            patch("study_controller.regression_allowance", return_value=({}, "authored-baseline")),
            patch("study_controller.session", side_effect=RuntimeError("authored timeout")),
            patch("study_controller.grade", return_value={"status": "pass"}) as grader,
        ):
            row = run_trial(self.fake_study(), "study", output, self.trial(), None)
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["quality"], "pass")
            self.assertTrue(row["memory_usable"])
            grader.assert_called_once()
        self.assertIn("authored timeout", str(row["failures"]))

    def test_failed_paid_session_usage_is_retained_and_summarized(self):
        output = self.root / "output"

        def failed_session(study, trial, workspace, memory, prompt, out):
            (out / "evidence").mkdir(parents=True)
            write(out / "evidence/usage.json", {"session_tokens": {"input": 123, "output": 45}})
            raise RuntimeError("paid session failed")

        with (
            patch("study_controller.validate"),
            patch("study_controller.regression_allowance", return_value=({}, "authored-baseline")),
            patch("study_controller.session", side_effect=failed_session),
            patch("study_controller.grade", return_value={"status": "fail"}),
        ):
            row = run_trial(self.fake_study(), "study", output, self.trial(), None)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["usage"]["session_tokens"]["input"], 123)
        self.assertEqual(summarize({"trial": row})["blocks"][0]["session_tokens"][0]["output"], 45)

    def test_unusable_predecessor_blocks_without_session(self):
        output = self.root / "output"
        with (
            patch("study_controller.validate"),
            patch("study_controller.regression_allowance", return_value=({}, "authored-baseline")),
            patch("study_controller.session") as execute,
        ):
            row = run_trial(
                self.fake_study(), "study", output, self.trial(stage=2), {"memory_usable": False}
            )
        execute.assert_not_called()
        self.assertFalse(row["memory_usable"])
        self.assertEqual(row["status"], "failed")

    def test_all_skipped_acceptance_is_not_quality_success(self):
        outcomes = {
            "exit_code": 0,
            "collected": 1,
            "counts": {"executed": 0, "errors": 0, "skipped": 1, "xfailed": 0, "xpassed": 0},
        }
        self.assertFalse(quality_valid("acceptance", outcomes))
        outcomes["counts"].update(executed=1)
        self.assertFalse(quality_valid("acceptance", outcomes))

    def test_regression_only_allows_baseline_skip_nodes(self):
        outcomes = {
            "exit_code": 0,
            "collected": 2,
            "counts": {"executed": 1, "errors": 0},
            "node_ids": {"skipped": ["known"], "xfailed": [], "xpassed": []},
        }
        allowance = {
            "collected": 2,
            "node_ids": {"skipped": ["known"], "xfailed": [], "xpassed": []},
        }
        self.assertTrue(quality_valid("regression", outcomes, allowance))
        outcomes["node_ids"]["skipped"].append("unexpected")
        self.assertFalse(quality_valid("regression", outcomes, allowance))

    def test_adapter_canonical_binding_and_raw_file_hash_are_distinct(self):
        bundle = self.root / "bundle"
        bundle.mkdir()
        memory = self.namespace / "memory"
        (memory / "seed").mkdir()
        (memory / "prepared").mkdir()
        original = {
            "id": "note",
            "kind": "note",
            "subject": {"path": "src/pkg/a.py"},
            "note_key": "key",
            "text": "note \u03bb",
        }
        spec = {"records": [original]}
        write(bundle / "seed.json", spec)
        shutil.copyfile(bundle / "seed.json", memory / "seed/seed-spec.json")
        source = {"path": "src/pkg/a.py", "sha256": "a" * 64, "size": 1}
        catalog = {
            "records": [
                {
                    "id": "note",
                    "source": source,
                    "payload": {
                        "subject": original["subject"],
                        "note_key": "key",
                        "text": original["text"],
                        "sources": [source],
                    },
                }
            ]
        }
        raw = json.dumps(
            catalog, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
        ).encode()
        (memory / "prepared/catalog.json").write_bytes(raw + b"\n")
        binding = {
            "backend": "static",
            "repo": "/workspace",
            "catalog_path": "/memory/prepared/catalog.json",
            "state_home": None,
            "catalog_sha256": hashlib.sha256(raw).hexdigest(),
        }
        write(memory / "prepared/binding.json", binding)
        result = verify_memory(
            {"bundle_path": str(bundle), "normalized": {"seed": "seed.json"}}, memory, "static"
        )
        self.assertEqual(result["prepared/catalog.json"], digest(memory / "prepared/catalog.json"))
        self.assertNotEqual(result["prepared/catalog.json"], binding["catalog_sha256"])
        (memory / "prepared/catalog.json").write_bytes(raw + b"\n\n")
        with self.assertRaises(ValueError):
            verify_memory(
                {"bundle_path": str(bundle), "normalized": {"seed": "seed.json"}},
                memory,
                "static",
                result,
            )

    def test_plain_dummy_memory_mutation_rejected(self):
        memory = self.namespace / "memory"
        verify_memory({}, memory, "plain")
        (memory / "unexpected").write_text("x")
        with self.assertRaises(ValueError):
            verify_memory({}, memory, "plain")

    def test_summary_never_double_counts_nested_costs(self):
        records = {
            "one": {
                "trial": {"id": "one", "repetition": 1, "arm": "plain"},
                "status": "failed",
                "costs": {
                    "complete": True,
                    "construction_host_wall_seconds": 0,
                    "session_host_wall_seconds": 5,
                    "charged_host_wall_seconds": 5,
                    "infrastructure_host_wall_seconds": 7,
                },
            }
        }
        row = summarize(records)["blocks"][0]
        self.assertEqual(row["charged_host_wall_seconds"], 5)
        self.assertFalse(row["four_stage_complete"])


if __name__ == "__main__":
    unittest.main()
