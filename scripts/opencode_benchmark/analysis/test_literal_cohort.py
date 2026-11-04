"""Pre-outcome admission controls using only authored synthetic records."""

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import pytest

import aggregate_study as evaluator
import test_aggregate as legacy


@pytest.mark.parametrize('study_id', sorted(evaluator.LITERAL_COMPACT_DEVELOPMENT_IDS))
def test_explicit_literal_versions_keep_same_rules_and_cohort_gate(study_id):
    supported = json.loads((Path(__file__).parent / 'supported_rules.json').read_text())
    protocol = {**supported, 'study_id': study_id}
    assert evaluator.admit_protocol(protocol, supported) == study_id
    with pytest.raises(ValueError, match='schema2 study cohort'):
        evaluator.admit_study_cohort(study_id, {'bundle_kind': 'development'})
    changed = copy.deepcopy(protocol)
    changed['success_rule']['paired_win'] = 'one favorable run is enough'
    with pytest.raises(ValueError, match='success rules differ'):
        evaluator.admit_protocol(changed, supported)


class LiteralCohortTests(unittest.TestCase):
    def setUp(self):
        self.fixture = legacy.AggregateTests(methodName="runTest")
        self.fixture.setUp()
        self.supported = json.loads((Path(__file__).parent / "supported_rules.json").read_text())

    def tearDown(self):
        self.fixture.tearDown()

    def freeze(self):
        f = self.fixture
        for path in (f.root / "study.json", f.run / "frozen-study.json"):
            path.write_text(json.dumps(f.study))
        (f.run / "run.json").write_text(
            json.dumps(
                {
                    "study_path": str(f.root / "study.json"),
                    "study_sha256": evaluator.sha(f.root / "study.json"),
                    "mode": "model",
                }
            )
        )

    def v4(self):
        f = self.fixture
        protocol = copy.deepcopy(self.supported)
        protocol["study_id"] = evaluator.LITERAL_COMPACT_DEVELOPMENT_ID
        f.protocol.write_text(json.dumps(protocol))
        f.study.update(bundle_kind="development", memory_response_format="compact")
        source = {
            "schema_version": 2,
            "seed": "origin/literals.json",
            "generator": "seed_source_literals_v2.py",
            "helpers": ["literal_source.py"],
            "payload_kind": "source_excerpt_equals",
            "extractor_format": "python.definition-prefix/1",
        }
        f.study["normalized"].update(
            seed=source["seed"],
            memory_source=source,
            asset_hashes={
                name: "a" * 64
                for name in [
                    "memory-source.json",
                    source["seed"],
                    source["generator"],
                    *source["helpers"],
                ]
            },
        )
        self.freeze()
        return protocol

    def reject_before_trial_read(self):
        with patch.object(
            evaluator, "trial_row", side_effect=AssertionError("trial read before cohort admission")
        ):
            with self.assertRaises(ValueError):
                evaluator.aggregate(self.fixture.run, self.fixture.protocol)

    def test_legacy_complete_semantics_identical(self):
        self.fixture.test_complete_same_metric_all_six_wins()

    def test_valid_v4_keeps_same_success_rule_and_six_pair_metric_logic(self):
        self.v4()
        self.fixture.fill()
        result = evaluator.aggregate(self.fixture.run, self.fixture.protocol)
        self.assertEqual(
            set(result["summary"]["winning_metrics_satisfying_all_six_pairs"]),
            {"charged_wall", "token_work"},
        )
        self.assertEqual(len(result["summary"]["paired_comparisons"]), 6)
        self.assertEqual(result["integrity"]["terminal_artifact_hashes_verified"], 108)
        self.assertIn("Development", result["claim_scope"])

    def test_new_id_does_not_relabel_old_notes_study(self):
        protocol = dict(self.supported, study_id=evaluator.LITERAL_COMPACT_DEVELOPMENT_ID)
        self.fixture.protocol.write_text(json.dumps(protocol))
        self.reject_before_trial_read()

    def test_actual_cohort_mismatch_rejected_before_outcomes(self):
        self.v4()
        baseline = copy.deepcopy(self.fixture.study)
        mutations = [
            lambda s: s.update(bundle_kind="heldout"),
            lambda s: s.pop("memory_response_format"),
            lambda s: s.update(memory_response_format="full"),
            lambda s: s["normalized"].pop("memory_source"),
            lambda s: s["normalized"]["memory_source"].update(schema_version=1),
            lambda s: s["normalized"]["memory_source"].update(schema_version=2.0),
            lambda s: s["normalized"]["memory_source"].update(payload_kind="note"),
            lambda s: s["normalized"]["memory_source"].update(
                extractor_format="python.definition-prefix/2"
            ),
            lambda s: s["normalized"]["memory_source"].update(seed="old-notes.json"),
            lambda s: s["normalized"]["memory_source"].update(generator="seed_source_notes.py"),
            lambda s: s["normalized"]["memory_source"].update(helpers=[]),
            lambda s: s["normalized"]["asset_hashes"].pop("literal_source.py"),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutations.index(mutation)):
                self.fixture.study = copy.deepcopy(baseline)
                mutation(self.fixture.study)
                self.freeze()
                self.reject_before_trial_read()

    def test_altered_shared_rules_and_unknown_ids_rejected(self):
        self.v4()
        for name in list(self.supported):
            with self.subTest(field=name):
                protocol = copy.deepcopy(self.supported)
                protocol["study_id"] = evaluator.LITERAL_COMPACT_DEVELOPMENT_ID
                if name == "success_rule":
                    protocol[name]["paired_win"] = "weaker criterion"
                elif name == "study_id":
                    protocol[name] = "arbitrary-new-cohort"
                else:
                    protocol[name] = "altered"
                self.fixture.protocol.write_text(json.dumps(protocol))
                self.reject_before_trial_read()

    def test_v4_order_cannot_change_the_independent_cyclic_schedule(self):
        self.v4()
        path = self.fixture.run / "plan.json"
        value = evaluator.read(path)
        value["trials"] = list(reversed(value["trials"]))
        path.write_text(json.dumps(value))
        self.reject_before_trial_read()

    def test_unknown_study_or_cross_version_binding_rejected(self):
        self.v4()
        original = evaluator.read(self.fixture.run / "run.json")["study_sha256"]
        self.fixture.study["memory_response_format"] = "full"
        self.freeze()
        with self.assertRaisesRegex(ValueError, "unexpected study version"):
            evaluator.aggregate(
                self.fixture.run, self.fixture.protocol, expected_study_sha=original
            )

    def test_legacy_path_does_not_gain_new_cohort_requirements(self):
        self.fixture.fill()
        baseline = evaluator.aggregate(self.fixture.run, self.fixture.protocol)["summary"]
        self.fixture.study.update(memory_response_format="full")
        self.freeze()
        self.assertEqual(
            evaluator.aggregate(self.fixture.run, self.fixture.protocol)["summary"], baseline
        )


if __name__ == "__main__":
    unittest.main()
