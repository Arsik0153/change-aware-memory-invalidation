"""Registered candidate tests on authored histories only; never runs timings."""
# ruff: noqa: E402
from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import sys
import tempfile
import unittest

STAGE = Path(__file__).resolve().parent
ROOT = next(parent for parent in STAGE.parents if (parent / "src/cami").is_dir())
RUNTIME = STAGE if (STAGE / "registered_negative_carry.py").is_file() else ROOT / "scripts"
PLAN_PATH = STAGE / "protocol.json" if (STAGE / "protocol.json").is_file() else ROOT / "examples/registered_negative_carry/protocol.json"
for location in (ROOT, ROOT / "src", ROOT / "scripts", RUNTIME):
    sys.path.insert(0, str(location))

from pydantic import ValidationError
from cami.artifacts import file_hash, read_json, write_json
from cami.index import IndexConfig, build_index, compare_indexes, signature
from cami.models import Equals, PolicyConfig
from registered_negative_carry import RegisteredCarryOwner
from registered_negative_carry_challenge import VARIANTS, prepare_histories, run_history, workload_hash


class RegisteredFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="registered-fixture-", dir=STAGE)
        cls.output = Path(cls.temp.name)
        cls.plan = read_json(PLAN_PATH)
        cls.histories = prepare_histories(cls.plan, cls.output, ROOT)
        cls.by_id = {history.id: history for history in cls.histories}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def owner(self, name="unchanged_module_other_file"):
        history = self.by_id[name]
        owner = RegisteredCarryOwner(ROOT, self.output)
        owner.register(history.initial_claim, history.provenance, history.context)
        owner.initialize_checked_negative(history.parent_result, history.parent, history.parent_index)
        return history, owner

    def step(self, owner, frame, policy="symbol_validate"):
        return owner.step(frame["before"], frame["after"], frame["new_index"], frame["changes"], PolicyConfig(id=policy))

    def test_same_exact_workload_and_original_sources_preserved(self):
        baseline = read_json(ROOT / self.plan["baseline_protocol_path"])
        self.assertEqual(workload_hash(self.plan), workload_hash(baseline))
        self.assertEqual((len(self.histories), sum(len(h.frames) for h in self.histories)), (17, 31))
        self.assertEqual((self.plan["paired_repetitions"], self.plan["histories_per_block"]), (21, 100))
        for path, expected in self.plan["original_implementation_hashes"].items():
            self.assertEqual(file_hash(ROOT / path), expected)

    def test_all_31_states_match_original_blob_candidate_and_fresh_semantics(self):
        rows, counts = [], {}
        for history in self.histories:
            original = run_history(history, "module_blob_witness", capture=True)
            new = run_history(history, "registered_inputs", capture=True)
            self.assertEqual([row["state"] for row in new["rows"]], [row["state"] for row in original["rows"]])
            rows.extend(new["rows"])
            for key, value in new["counts"].items():
                counts[key] = counts.get(key, 0) + value
        self.assertEqual(len(rows), 31)
        self.assertEqual(counts["registrations"], 22)  # 17 reset boundaries + five distinct input edits.
        self.assertEqual(counts["checked_result_imports"], 17)
        self.assertEqual((counts["actual_validation_calls"], counts["suppressed"]), (22, 7))
        for row in rows:
            if row["suppressed"]:
                self.assertEqual((row["fresh"]["verdict"], row["fresh"]["reason"]), ("contradicted", "predicate_mismatch"))
                self.assertEqual(row["state"]["last_checked_commit"], row["previous_state"]["last_checked_commit"])

    def test_same_id_predicate_change_reregisters_and_restores_support(self):
        history, owner = self.owner()
        old = owner.inputs
        changed = history.initial_claim.model_copy(update={"predicate": Equals(type="signature_equals",
            expected_signature=signature(ast.parse("def f(x=2): pass").body[0]))})
        self.assertTrue(owner.register(changed, history.provenance, history.context))
        self.assertNotEqual(owner.inputs.claim.predicate, old.claim.predicate)
        self.assertIsNone(owner.negative)
        result = self.step(owner, history.frames[0])
        self.assertFalse(result["suppressed"])
        self.assertTrue(result["state"].available)
        self.assertIsNotNone(result["validation"])

    def test_equal_new_object_and_provenance_changes_require_registration(self):
        history, owner = self.owner()
        self.assertFalse(owner.register(history.initial_claim, history.provenance, history.context))
        self.assertTrue(owner.register(history.initial_claim.model_copy(), history.provenance, history.context))
        self.assertIsNone(owner.negative)
        result = self.step(owner, history.frames[0])
        self.assertIsNotNone(result["validation"])
        changed = history.provenance.model_copy(update={"scenario_id": "new_registered_scenario"})
        self.assertTrue(owner.register(owner.inputs.claim, changed, history.context))
        self.assertIsNone(owner.negative)

    def test_deep_immutability_and_unvalidated_copy_rejection(self):
        history, owner = self.owner()
        with self.assertRaises(ValidationError):
            owner.inputs.claim.predicate.expected_signature.parameters = ()
        with self.assertRaises(ValidationError):
            owner.state.available = True
        with self.assertRaises(FrozenInstanceError):
            owner.inputs.eligible = False
        with self.assertRaises(FrozenInstanceError):
            owner.inputs.context.build_graph = False
        bad_signature = history.initial_claim.predicate.expected_signature.model_copy(update={"parameters": []})
        bad = history.initial_claim.model_copy(update={"predicate": history.initial_claim.predicate.model_copy(update={"expected_signature": bad_signature})})
        with self.assertRaisesRegex(ValueError, "deeply immutable"):
            owner.register(bad, history.provenance, history.context)
        with self.assertRaisesRegex(ValueError, "deeply immutable"):
            owner.register(history.initial_claim, history.provenance, replace(history.context, source_roots=["."]))

    def test_policy_switch_keeps_last_actual_lineage_and_validates_recovery(self):
        history = self.by_id["policy_switch_lineage"]
        rows = run_history(history, "registered_inputs", capture=True)["rows"]
        self.assertFalse(rows[0]["state"]["available"])
        self.assertFalse(rows[1]["suppressed"])
        self.assertTrue(rows[1]["state"]["available"])
        self.assertEqual(rows[1]["previous_state"]["last_checked_commit"], history.parent.revision)

    def test_foreign_witness_and_imported_state_are_not_actual_results(self):
        history, first = self.owner()
        second = RegisteredCarryOwner(ROOT, self.output)
        second.register(history.initial_claim, history.provenance, history.context)
        for foreign in (first.negative, first.state):
            with self.assertRaisesRegex(ValueError, "actual validation result"):
                second.initialize_checked_negative(foreign, history.parent, history.parent_index)
        with self.assertRaisesRegex(ValueError, "binding mismatch"):
            second.initialize_checked_negative(history.parent_result.model_copy(update={"input_hash": "0" * 64}), history.parent, history.parent_index)
        second.initialize_checked_negative(history.parent_result, history.parent, history.parent_index)
        second._negative = first.negative  # Deliberate private cross-owner fault injection.
        result = self.step(second, history.frames[0])
        self.assertFalse(result["suppressed"])
        self.assertEqual(result["reason"], "owned_last_actual_negative_identity_mismatch")
        self.assertIsNotNone(result["validation"])
        self.assertIs(second.negative.owner, second.inputs.owner)

    def test_new_owner_and_new_run_binding_need_registration_and_verification(self):
        history, owner = self.owner()
        other = RegisteredCarryOwner(ROOT, self.output)
        with self.assertRaisesRegex(ValueError, "registered inputs"):
            other.initialize_checked_negative(history.parent_result, history.parent, history.parent_index)
        with self.assertRaisesRegex(ValueError, "new run binding"):
            owner.register(history.initial_claim, history.provenance, replace(history.context, run_binding="f" * 64))
        with self.assertRaisesRegex(ValueError, "foreign handles"):
            other.register(owner.inputs, history.provenance, history.context)

    def test_unchanged_fresh_supported_never_becomes_a_negative_witness(self):
        history = self.by_id["unchanged_module_other_file"]
        owner = RegisteredCarryOwner(ROOT, self.output)
        claim = history.initial_claim.model_copy(update={"predicate": Equals(type="signature_equals",
            expected_signature=signature(ast.parse("def f(x=2): pass").body[0]))})
        owner.register(claim, history.provenance, history.context)
        owner.initialize_fresh(history.parent, history.parent_index)
        result = self.step(owner, history.frames[0])
        self.assertTrue(result["state"].available)
        self.assertFalse(result["suppressed"])
        self.assertIsNone(owner.negative)
        self.assertIsNone(result["validation"])

    def test_uncertainty_known_incomplete_and_mode_limitation_still_validate(self):
        for name in ("parse_error_recovery", "known_incomplete", "same_blob_symlink", "absence_ancestor_limitation"):
            rows = run_history(self.by_id[name], "registered_inputs", capture=True)["rows"]
            for row in rows:
                if row["fresh"]["verdict"] == "insufficient_evidence" or name == "known_incomplete":
                    self.assertFalse(row["suppressed"])
                    self.assertIsNotNone(row["validation"])

    def test_roots_and_limits_context_edits_register_and_refuse_old_witness(self):
        history, owner = self.owner()
        frame = history.frames[0]
        changed = replace(history.context, source_roots=("missing",))
        owner.register(history.initial_claim, history.provenance, changed)
        index = build_index(frame["after"], IndexConfig(("missing",)))
        changes = compare_indexes(history.parent_index, index, history.parent, frame["after"])
        result = owner.step(history.parent, frame["after"], index, changes, PolicyConfig(id="symbol_validate"))
        self.assertFalse(result["suppressed"])
        self.assertEqual(result["validation"].reason, "outside_source_roots")
        rows = run_history(self.by_id["context_size_limit_change"], "registered_inputs", capture=True)["rows"]
        self.assertTrue(rows[0]["registered_changed"])
        self.assertIsNotNone(rows[0]["validation"])
        self.assertEqual(rows[0]["fresh"]["verdict"], "insufficient_evidence")

    def test_cold_import_cannot_relabel_old_result_for_changed_claim_or_limits(self):
        history = self.by_id["unchanged_module_other_file"]
        changed = history.initial_claim.model_copy(update={"predicate": Equals(type="signature_equals",
            expected_signature=signature(ast.parse("def f(x=2): pass").body[0]))})
        other = RegisteredCarryOwner(ROOT, self.output)
        other.register(changed, history.provenance, history.context)
        with self.assertRaisesRegex(ValueError, "binding mismatch"):
            other.initialize_checked_negative(history.parent_result, history.parent, history.parent_index)
        for context in (replace(history.context, source_roots=("missing",)), replace(history.context, max_file_bytes=5)):
            other = RegisteredCarryOwner(ROOT, self.output)
            other.register(history.initial_claim, history.provenance, context)
            with self.assertRaisesRegex(ValueError, "source witness"):
                other.initialize_checked_negative(history.parent_result, history.parent, history.parent_index)

    def test_declared_new_context_never_reuses_registered_identity(self):
        history, owner = self.owner()
        for context in (replace(history.context, index_version="different"), replace(history.context, validator_version="different"),
                        replace(history.context, python="different"), replace(history.context, implementation_hashes=(("module", "new"),))):
            self.assertTrue(owner.register(history.initial_claim, history.provenance, context))
            self.assertIsNone(owner.negative)
            self.assertIs(owner.inputs.context.__class__, history.context.__class__)

    def test_changed_supported_entry_cannot_escape_through_unsupported_policy(self):
        history = self.by_id["unchanged_module_other_file"]
        owner = RegisteredCarryOwner(ROOT, self.output)
        supported = history.initial_claim.model_copy(update={"predicate": Equals(type="signature_equals",
            expected_signature=signature(ast.parse("def f(x=2): pass").body[0]))})
        owner.register(supported, history.provenance, history.context)
        owner.initialize_fresh(history.parent, history.parent_index)
        owner.register(history.initial_claim, history.provenance, history.context)
        with self.assertRaisesRegex(ValueError, "only symbol_validate and keep_all"):
            self.step(owner, history.frames[0], "file_validate")
        result = self.step(owner, history.frames[0])
        self.assertIsNotNone(result["validation"])
        self.assertFalse(result["state"].available)

    def test_pending_inputs_cannot_publish_old_state_or_use_keep_all(self):
        history, owner = self.owner()
        changed = history.initial_claim.model_copy(update={"text": "New registered input"})
        owner.register(changed, history.provenance, history.context)
        with self.assertRaisesRegex(ValueError, "pending validation"):
            _ = owner.state
        with self.assertRaisesRegex(ValueError, "require validation"):
            self.step(owner, history.frames[0], "keep_all")
        result = self.step(owner, history.frames[0])
        self.assertIsNotNone(result["validation"])
        self.assertIs(owner.state, result["state"])

    def test_four_variant_order_is_position_balanced_over_full_cycles(self):
        from collections import Counter
        from run_registered_negative_carry import variant_order
        ranks = {variant: Counter() for variant in VARIANTS}
        for number in range(8):
            order = variant_order(number)
            self.assertEqual(set(order), set(VARIANTS))
            for position, variant in enumerate(order):
                ranks[variant][position] += 1
        for counts in ranks.values():
            self.assertEqual(dict(counts), {0: 2, 1: 2, 2: 2, 3: 2})

    def test_draft_protocol_refuses_measurement(self):
        import run_registered_negative_carry as driver
        draft = dict(self.plan, status="draft")
        path = self.output / "draft.json"
        write_json(path, draft)
        with self.assertRaisesRegex(ValueError, "newly sealed"):
            driver.preflight(path)
        self.assertEqual(len(VARIANTS), 4)


if __name__ == "__main__":
    unittest.main()
