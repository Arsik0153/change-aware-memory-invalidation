"""Small hand-written synthetic transitions only; never load frozen full graphs."""
import copy
import importlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cami.artifacts import file_hash, read_json, write_json

checker = importlib.import_module("scripts.check_model_translation"
                                  if importlib.util.find_spec("scripts.check_model_translation")
                                  else "check_model_translation")
HERE = Path(__file__).resolve().parent


def state(truth, available, age):
    return {"state_id": f"t{int(truth)}:a{int(available)}@{age}",
            "truth": truth, "available": available, "age": age}


def edge(source, target, *, hint=False, due=False, selected=False, verdict=None):
    return {"from": source["state_id"], "to": target["state_id"], "baseline_trigger": hint,
            "audit_due": due, "selected": selected, "verdict": verdict, "next_truth": target["truth"]}


class TranslationTests(unittest.TestCase):
    def make_case(self, source, target, transition, variant="supported", interval=4):
        return checker.translate_edge(interval, source, target, transition, variant)

    def test_unselected_false_truth_carries_metadata_and_ages(self):
        source, target = state(True, True, 0), state(False, True, 1)
        case = self.make_case(source, target, edge(source, target))
        report = checker.check_case(case)
        self.assertTrue(report["passed"], report["checks"])
        self.assertEqual(report["selection"]["reasons"], [])
        self.assertEqual(report["actual_state"]["basis"], "carried_forward")
        self.assertEqual(report["actual_state"]["last_verdict"], "supported")
        self.assertEqual(report["projected_age"], 1)
        self.assertEqual(report["actual_state"]["last_checked_commit"], case.history[5])
        self.assertEqual(report["actual_state"]["revision"], case.history[6])
        self.assertIsNone(report["validation_input"])

    def test_due_is_at_age_plus_one_and_uses_real_adapter(self):
        source, target = state(False, True, 3), state(False, False, 0)
        case = self.make_case(source, target, edge(source, target, due=True, selected=True, verdict="contradicted"))
        report = checker.check_case(case)
        self.assertTrue(report["passed"], report["checks"])
        self.assertEqual(report["selection"]["reasons"], ["periodic_audit"])
        self.assertEqual(report["actual_state"]["state"], "stale")
        self.assertEqual(report["actual_state"]["last_checked_commit"], case.history[6])
        self.assertEqual(report["actual_state"]["last_supported_commit"], case.history[2])
        self.assertEqual(report["actual_state"]["withheld_reason"], "modeled_contradiction")
        self.assertEqual(report["projected_age"], 0)

    def test_synthetic_known_incomplete_realizes_baseline_hint(self):
        source, target = state(True, True, 0), state(True, True, 0)
        case = self.make_case(source, target, edge(source, target, hint=True, selected=True, verdict="supported"))
        report = checker.check_case(case)
        self.assertTrue(report["passed"], report["checks"])
        self.assertEqual(report["selection"]["reasons"], ["known_incomplete"])
        self.assertTrue(report["actual_state"]["current_provenance"]["known_incomplete"])
        self.assertEqual(report["actual_state"]["basis"], "validated")
        self.assertEqual(report["actual_state"]["last_supported_commit"], case.history[-1])

    def test_both_withheld_metadata_variants_retry_and_recover(self):
        source, target = state(True, False, 0), state(True, True, 0)
        for variant, expected_state in (("contradicted", "stale"), ("insufficient_evidence", "needs_validation")):
            with self.subTest(variant=variant):
                case = self.make_case(source, target, edge(source, target, selected=True, verdict="supported"), variant)
                self.assertEqual(case.context.previous[0].state, expected_state)
                report = checker.check_case(case)
                self.assertTrue(report["passed"], report["checks"])
                self.assertEqual(report["selection"]["reasons"], ["previously_unavailable"])
                self.assertIsNone(report["actual_state"]["withheld_reason"])
                self.assertEqual(report["actual_state"]["state"], "valid")

    def test_reason_union_is_exact_at_k1(self):
        source, target = state(False, False, 0), state(False, False, 0)
        case = self.make_case(source, target, edge(source, target, hint=True, due=True,
                              selected=True, verdict="insufficient_evidence"), "contradicted", interval=1)
        report = checker.check_case(case)
        self.assertTrue(report["passed"], report["checks"])
        self.assertEqual(report["selection"]["reasons"],
                         ["known_incomplete", "periodic_audit", "previously_unavailable"])

    def test_inconclusive_result_withholds_available_memory(self):
        source, target = state(True, True, 0), state(True, False, 0)
        case = self.make_case(source, target, edge(source, target, hint=True, selected=True,
                                                  verdict="insufficient_evidence"))
        report = checker.check_case(case)
        self.assertTrue(report["passed"], report["checks"])
        self.assertFalse(report["actual_state"]["available"])
        self.assertEqual(report["actual_state"]["state"], "needs_validation")
        self.assertEqual(report["actual_state"]["withheld_reason"], "modeled_insufficient")
        self.assertEqual(report["validation_input"]["test_executions"], 0)

    def test_both_negative_controls_detected_on_two_tiny_cases(self):
        source = state(True, True, 1)
        supported, withheld = state(True, True, 0), state(True, False, 0)
        cases = [("deadline", self.make_case(source, supported,
                    edge(source, supported, due=True, selected=True, verdict="supported"), interval=2)),
                 ("inconclusive", self.make_case(source, withheld,
                    edge(source, withheld, due=True, selected=True, verdict="insufficient_evidence"), interval=2))]
        reports = checker.negative_controls(cases)
        self.assertTrue(all(report["detected"] for report in reports.values()))
        self.assertIn("selection_selected", reports["suppress_periodic_deadline"]["failed_checks"])
        self.assertIn("state.available", reports["carry_previous_availability_after_insufficient"]["failed_checks"])

    def test_metadata_corruption_is_detected_even_when_projection_matches(self):
        source, target = state(True, True, 0), state(False, True, 1)
        case = self.make_case(source, target, edge(source, target))

        def corrupt(*args, **kwargs):
            return checker.advance_state(*args, **kwargs).model_copy(update={"last_supported_commit": "wrong"})

        report = checker.check_case(case, transition=corrupt)
        self.assertTrue(report["checks"]["model_availability"])
        self.assertTrue(report["checks"]["model_age"])
        self.assertFalse(report["checks"]["state.last_supported_commit"])
        self.assertFalse(report["passed"])

    def test_inconsistent_model_transition_is_rejected(self):
        source, target = state(True, True, 0), state(True, True, 1)
        transition = edge(source, target)
        transition["selected"] = True
        with self.assertRaisesRegex(ValueError, "selection formula"):
            self.make_case(source, target, transition)


class TinyRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=HERE, prefix="synthetic-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        inputs = self.root / "inputs"
        inputs.mkdir()
        source, supported, withheld = state(True, True, 1), state(True, True, 0), state(True, False, 0)
        self.graph = {"interval": 2, "initial_state": source["state_id"], "state_count": 3,
                      "transition_count": 2, "states": [source, supported, withheld],
                      "transitions": [edge(source, supported, due=True, selected=True, verdict="supported"),
                                      edge(source, withheld, due=True, selected=True, verdict="insufficient_evidence")]}
        self.graph_path = inputs / "sound_positive_only-K2.json"
        write_json(self.graph_path, self.graph)
        self.snapshot = {"source_status": "", "git_head": "synthetic", "sha256": "synthetic"}
        summary_path, manifest_path = inputs / "summary.json", inputs / "manifest.json"
        write_json(summary_path, {"actual_probe_executions": 0, "models": {
            "sound_positive_only-K2": {"interval": 2, "state_count": 3, "transition_count": 2}}})
        write_json(manifest_path, {"status": "complete", "source_before": self.snapshot,
                                  "source_after": self.snapshot, "actual_probe_executions": 0,
                                  "artifact_hashes": {path.name: file_hash(path)
                                                      for path in (self.graph_path, summary_path)}})
        self.plan = {"schema_version": 1, "experiment": "finite-model-to-engine-translation-v1",
                     "input_sha256": {path.relative_to(self.root).as_posix(): file_hash(path)
                                      for path in (manifest_path, summary_path, self.graph_path)},
                     "expected_source_transitions": 2, "expected_canonical_memory_contexts": 4,
                     "expected_translation_cases": 2, "limits": ["Synthetic tiny test only."]}
        self.protocol = self.root / "tiny-protocol.json"
        write_json(self.protocol, self.plan)

    def test_case_expansion_and_canonical_context_count(self):
        # This transition starts withheld, so it expands to two metadata variants.
        source, target = state(True, False, 0), state(True, True, 0)
        graph = {"interval": 2, "initial_state": source["state_id"], "states": [source, target],
                 "transitions": [edge(source, target, selected=True, verdict="supported")]}
        cases, contexts, transitions = checker.prepare_cases([("tiny", graph)])
        self.assertEqual((len(cases), len(contexts), transitions), (2, 3, 1))
        self.assertTrue(all(checker.check_case(case)["passed"] for _, case in cases))

    def test_tiny_runner_records_seals_and_refuses_overwrite(self):
        out = self.root / "out"
        with patch.object(checker, "source_snapshot", return_value=self.snapshot):
            result = checker.run(self.protocol, out, root=self.root)
            with self.assertRaisesRegex(ValueError, "must be new"):
                checker.run(self.protocol, out, root=self.root)
        self.assertEqual(result["matched_cases"], 2)
        self.assertEqual(result["negative_controls_detected"], 2)
        manifest = read_json(out / "manifest.json")
        self.assertEqual(manifest["source_before"], manifest["source_after"])
        self.assertEqual(manifest["actual_probe_executions"], 0)
        translations = read_json(out / "translations.json")
        self.assertEqual([row["edge_index"] for row in translations], [0, 1])
        self.assertTrue(all(row["source_graph_sha256"] == file_hash(self.graph_path) for row in translations))
        for name, expected in manifest["artifact_hashes"].items():
            self.assertEqual(file_hash(out / name), expected)

    def test_hash_tampering_is_rejected_before_output(self):
        self.graph_path.write_text("{}\n")
        out = self.root / "out"
        with patch.object(checker, "source_snapshot", return_value=self.snapshot):
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                checker.run(self.protocol, out, root=self.root)
        self.assertFalse(out.exists())

    def test_count_mismatch_is_rejected_before_output(self):
        self.plan["expected_translation_cases"] = 499
        write_json(self.protocol, self.plan)
        out = self.root / "out"
        with patch.object(checker, "source_snapshot", return_value=self.snapshot):
            with self.assertRaisesRegex(ValueError, "expected counts"):
                checker.run(self.protocol, out, root=self.root)
        self.assertFalse(out.exists())

    def test_dirty_source_is_rejected_before_reading_plan(self):
        dirty = copy.deepcopy(self.snapshot)
        dirty["source_status"] = " M scripts/changed.py"
        with patch.object(checker, "source_snapshot", return_value=dirty):
            with self.assertRaisesRegex(ValueError, "Commit source"):
                checker.run(self.root / "does-not-exist.json", self.root / "out", root=self.root)

    def test_runtime_source_change_fails_manifest(self):
        changed = {**self.snapshot, "sha256": "changed"}
        out = self.root / "out"
        with patch.object(checker, "source_snapshot", side_effect=[self.snapshot, changed, changed]):
            with self.assertRaisesRegex(ValueError, "Runtime source changed"):
                checker.run(self.protocol, out, root=self.root)
        manifest = read_json(out / "manifest.json")
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["source_after"], changed)


if __name__ == "__main__":
    unittest.main()
