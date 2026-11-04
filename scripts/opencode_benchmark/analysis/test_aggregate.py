"""Authored synthetic trial records only; no task sources, models, or heldout results."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aggregate_study import ARMS, HERE, aggregate, artifact_files, export_csv, schedule, sha, write


class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run = self.root / "run"
        (self.run / "trials").mkdir(parents=True)
        rules = json.loads((HERE / "supported_rules.json").read_bytes())
        self.protocol = self.root / "protocol.json"
        write(self.protocol, rules)
        self.study = {
            "arms": list(ARMS),
            "model": rules["model"],
            "repetitions": 3,
            "bundle_kind": "authored_development_fixture",
            "image": "authored-image",
            "normalized": {"sequence": ["task-a", "task-a", "task-b", "task-b"]},
        }
        source = self.root / "study.json"
        write(source, self.study)
        write(self.run / "frozen-study.json", self.study)
        write(
            self.run / "run.json",
            {"study_path": str(source), "study_sha256": sha(source), "mode": "model"},
        )
        self.plan = schedule(self.study)
        write(self.run / "plan.json", {"trials": self.plan})

    def tearDown(self):
        self.temp.cleanup()

    def terminal(self, item, *, wall=None, token_input=None, failed=False):
        directory = self.run / "trials" / item["id"]
        (directory / "session/evidence").mkdir(parents=True)
        (directory / "evaluation").mkdir()
        wall = wall if wall is not None else {"plain": 100, "static": 120, "cami": 80}[item["arm"]]
        construction = (
            (3 if item["arm"] == "cami" else 5)
            if item["stage"] == 1 and item["arm"] != "plain"
            else 0
        )
        usage = {
            "session_tokens": {
                "input": token_input
                if token_input is not None
                else {"plain": 100, "static": 150, "cami": 80}[item["arm"]],
                "output": 20,
                "reasoning": 5,
                "cache": {"read": 500, "write": 10},
            }
        }
        if failed:
            usage["status"] = "failed_attempt_latest_reported"
        write(directory / "session/evidence/usage.json", usage)
        write(
            directory / "session/manifest.json",
            {"status": "failed" if failed else "passed", "model_requested": True},
        )
        outcomes = {
            key: {
                "exit_code": 0,
                "counts": {
                    "executed": 1,
                    "passed": 1,
                    "failed": 0,
                    "errors": 0,
                    "skipped": 0,
                    "xfailed": 0,
                    "xpassed": 0,
                },
            }
            for key in ["acceptance", "regression"]
        }
        write(directory / "evaluation/report.json", {"status": "pass", "outcomes": outcomes})
        record = {
            "trial": item,
            "status": "failed" if failed else "passed",
            "operational_status": "failed" if failed else "passed",
            "session_status": "failed" if failed else "passed",
            "quality": "pass",
            "failures": ["authored failure"] if failed else [],
            "usage": usage,
            "costs": {
                "complete": True,
                "charged_host_wall_seconds": wall,
                "controller_total_host_wall_seconds": wall + 10,
                "infrastructure_host_wall_seconds": 10,
                "construction_host_wall_seconds": construction,
                "session_host_wall_seconds": wall - construction - 2,
                "construction_cgroup": {"cpu_seconds": 999},
                "session_cgroup": {"cpu_seconds": 888},
            },
            "artifact_hashes": artifact_files(directory),
        }
        write(directory / "terminal.json", record)
        return directory, record

    def fill(self):
        for item in self.plan:
            self.terminal(item)

    def rewrite(self, directory, record):
        record["artifact_hashes"] = artifact_files(directory)
        (directory / "terminal.json").write_text(json.dumps(record))

    def test_complete_same_metric_all_six_wins(self):
        self.fill()
        report = aggregate(self.run, self.protocol)
        summary = report["summary"]
        self.assertTrue(summary["primary_efficiency_eligible"])
        self.assertEqual(
            set(summary["winning_metrics_satisfying_all_six_pairs"]), {"charged_wall", "token_work"}
        )
        self.assertEqual(len(summary["paired_comparisons"]), 6)
        cami = next(b for b in summary["blocks"] if b["arm"] == "cami")
        self.assertEqual(cami["charged_wall"]["total"], 320)
        self.assertEqual(cami["token_work"]["total"], 4 * (80 + 10 + 20 + 5))
        self.assertEqual(cami["tokens"]["cache_read"]["total"], 2000)
        self.assertEqual(report["integrity"]["terminal_artifact_hashes_verified"], 108)

    def test_partial_active_trial_never_read(self):
        self.terminal(self.plan[0])
        active = self.run / "trials" / self.plan[1]["id"] / "private-state"
        active.mkdir(parents=True)
        (active / "secret").write_text("never read")
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            if path.is_relative_to(active):
                raise AssertionError("active private payload opened")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded_open):
            report = aggregate(self.run, self.protocol)
        self.assertEqual(report["summary"]["terminal_trials"], 1)
        self.assertEqual(report["summary"]["primary_superiority"], "not_established")
        self.assertFalse(report["integrity"]["active_trial_payloads_read"])
        self.assertIsNone(report["trials"][1]["tokens"]["input"])

    def test_failure_is_not_cheap_success_paid_tokens_retained(self):
        for index, item in enumerate(self.plan):
            self.terminal(item, failed=index == 0)
        report = aggregate(self.run, self.protocol)
        self.assertFalse(report["summary"]["primary_efficiency_eligible"])
        self.assertEqual(report["trials"][0]["tokens"]["input"], 100)
        self.assertFalse(report["trials"][0]["tokens_complete"])
        self.assertEqual(report["summary"]["winning_metrics_satisfying_all_six_pairs"], [])

    def test_missing_usage_is_unknown_never_zero(self):
        self.fill()
        directory = self.run / "trials" / self.plan[0]["id"]
        record = json.loads((directory / "terminal.json").read_bytes())
        (directory / "session/evidence/usage.json").unlink()
        record["usage"] = {"session_tokens": None, "status": "unavailable"}
        self.rewrite(directory, record)
        report = aggregate(self.run, self.protocol)
        self.assertIsNone(report["trials"][0]["token_work"])
        self.assertIsNone(report["trials"][0]["tokens"]["cache_read"])
        self.assertFalse(report["summary"]["primary_efficiency_eligible"])

    def test_one_missing_counter_blocks_primary_even_if_wall_wins(self):
        self.fill()
        directory = self.run / "trials" / self.plan[0]["id"]
        record = json.loads((directory / "terminal.json").read_bytes())
        record["usage"]["session_tokens"]["cache"].pop("read")
        (directory / "session/evidence/usage.json").write_text(json.dumps(record["usage"]))
        self.rewrite(directory, record)
        row = aggregate(self.run, self.protocol)["trials"][0]
        self.assertIsNone(row["tokens"]["cache_read"])
        self.assertEqual(row["token_work"], 135)
        self.assertFalse(row["tokens_complete"])

    def test_explicit_partial_telemetry_never_qualifies(self):
        self.fill()
        directory = self.run / "trials" / self.plan[0]["id"]
        record = json.loads((directory / "terminal.json").read_bytes())
        record["usage"]["telemetry_complete"] = False
        (directory / "session/evidence/usage.json").write_text(json.dumps(record["usage"]))
        self.rewrite(directory, record)
        report = aggregate(self.run, self.protocol)
        self.assertFalse(report["trials"][0]["tokens_complete"])
        self.assertEqual(report["summary"]["primary_superiority"], "not_established")

    def test_mixed_metric_pairwise_wins_do_not_satisfy_same_metric_rule(self):
        for item in self.plan:
            self.terminal(
                item,
                wall={"plain": 100, "static": 80, "cami": 90}[item["arm"]],
                token_input={"plain": 90, "static": 110, "cami": 100}[item["arm"]],
            )
        report = aggregate(self.run, self.protocol)
        self.assertTrue(report["summary"]["primary_efficiency_eligible"])
        self.assertEqual(report["summary"]["primary_superiority"], "not_established")

    def test_one_tie_is_not_strict_superiority(self):
        for item in self.plan:
            self.terminal(
                item,
                wall=80 if item["arm"] == "plain" else None,
                token_input=80 if item["arm"] == "plain" else None,
            )
        self.assertEqual(
            aggregate(self.run, self.protocol)["summary"][
                "winning_metrics_satisfying_all_six_pairs"
            ],
            [],
        )

    def caveat(self, *, ids=None, evidence_hash=None, hash_only=False):
        evidence = self.root / "phase-timing.json"
        write(evidence, {"authored_overlap": True})
        item = {
            "trial_ids": ids or ["r1-plain-s1"],
            "reason": "Authored concurrent infrastructure phase",
            "evidence_sha256": evidence_hash or sha(evidence),
        }
        if not hash_only:
            item["evidence_path"] = evidence.name
        path = self.root / "timing-caveats.json"
        write(path, {"schema_version": 1, "caveats": [item]})
        return path

    def test_timing_caveat_blocks_wall_but_keeps_valid_token_win(self):
        self.fill()
        original = aggregate(self.run, self.protocol)
        caveat = self.caveat()
        report = aggregate(self.run, self.protocol, timing_caveats_path=caveat)
        self.assertEqual(
            report["summary"]["winning_metrics_satisfying_all_six_pairs"], ["token_work"]
        )
        self.assertFalse(report["summary"]["primary_metric_eligibility"]["charged_wall"])
        self.assertTrue(report["summary"]["primary_metric_eligibility"]["token_work"])
        self.assertEqual(report["summary"]["excluded_trial_ids"], [])
        self.assertEqual(len(report["trials"]), 36)
        self.assertEqual(report["timing_caveats"]["source_sha256"], sha(caveat))
        for left, right in zip(
            original["summary"]["paired_comparisons"],
            report["summary"]["paired_comparisons"],
            strict=True,
        ):
            self.assertEqual(
                left["charged_wall"]["delta_cami_minus_comparator"],
                right["charged_wall"]["delta_cami_minus_comparator"],
            )
        self.assertTrue(report["trials"][0]["timing_caveat"])

    def test_known_timing_caveat_prevents_false_wall_only_win(self):
        for item in self.plan:
            self.terminal(item, token_input=200 if item["arm"] == "cami" else None)
        self.assertEqual(
            aggregate(self.run, self.protocol)["summary"][
                "winning_metrics_satisfying_all_six_pairs"
            ],
            ["charged_wall"],
        )
        report = aggregate(self.run, self.protocol, timing_caveats_path=self.caveat())
        self.assertEqual(report["summary"]["primary_superiority"], "not_established")
        self.assertTrue(report["summary"]["primary_metric_eligibility"]["token_work"])

    def test_unknown_caveat_trial_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown/invalid trial"):
            aggregate(self.run, self.protocol, timing_caveats_path=self.caveat(ids=["r4-cami-s1"]))

    def test_timing_evidence_hash_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "evidence SHA256 mismatch"):
            aggregate(
                self.run, self.protocol, timing_caveats_path=self.caveat(evidence_hash="a" * 64)
            )

    def test_hash_only_caveat_labels_unverified_file(self):
        report = aggregate(self.run, self.protocol, timing_caveats_path=self.caveat(hash_only=True))
        self.assertEqual(
            report["timing_caveats"]["entries"][0]["evidence_verification"],
            "declared_hash_only_no_file_read",
        )
        self.assertTrue(report["summary"]["charged_wall_disqualified_by_timing_caveats"])

    def test_artifact_tamper_rejected(self):
        self.fill()
        path = self.run / "trials" / self.plan[0]["id"] / "session/evidence/usage.json"
        path.write_text("{}")
        with self.assertRaisesRegex(ValueError, "artifact hashes"):
            aggregate(self.run, self.protocol)

    def test_rehashed_usage_summary_mismatch_rejected(self):
        self.fill()
        directory = self.run / "trials" / self.plan[0]["id"]
        record = json.loads((directory / "terminal.json").read_bytes())
        record["usage"] = copy.deepcopy(record["usage"])
        record["usage"]["session_tokens"]["input"] = 0
        self.rewrite(directory, record)
        with self.assertRaisesRegex(ValueError, "usage differs"):
            aggregate(self.run, self.protocol)

    def test_forged_charged_cost_rejected(self):
        self.fill()
        directory = self.run / "trials" / self.plan[0]["id"]
        record = json.loads((directory / "terminal.json").read_bytes())
        record["costs"]["charged_host_wall_seconds"] = 0
        self.rewrite(directory, record)
        with self.assertRaisesRegex(ValueError, "charged wall"):
            aggregate(self.run, self.protocol)

    def test_extra_row_version_pooling_rejected(self):
        self.fill()
        (self.run / "trials/another-version").mkdir()
        with self.assertRaisesRegex(ValueError, "unregistered trial"):
            aggregate(self.run, self.protocol)

    def test_missing_metric_preserves_unknown(self):
        self.fill()
        directory = self.run / "trials" / self.plan[0]["id"]
        record = json.loads((directory / "terminal.json").read_bytes())
        for key in ["charged_host_wall_seconds", "controller_total_host_wall_seconds"]:
            record["costs"].pop(key)
        self.rewrite(directory, record)
        report = aggregate(self.run, self.protocol)
        self.assertIsNone(report["trials"][0]["charged_wall_seconds"])
        self.assertFalse(report["summary"]["primary_efficiency_eligible"])

    def test_csv_unknown_is_blank_and_resource_components_not_summed(self):
        report = aggregate(self.run, self.protocol)
        output = self.root / "analysis"
        output.mkdir()
        export_csv(output, report)
        self.assertIn("missing_or_in_progress", (output / "trials.csv").read_text())
        self.assertEqual(len((output / "blocks.csv").read_text().splitlines()), 10)
        self.assertIsNone(report["summary"]["blocks"][0]["charged_wall"]["observed_subtotal"])


if __name__ == "__main__":
    unittest.main()
