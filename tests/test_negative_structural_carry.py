"""Authored temporary Git histories; no original repository corpus access."""
# ruff: noqa: E402
from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

STAGE = Path(__file__).resolve().parent
ROOT = next(parent for parent in STAGE.parents if (parent / "src/cami").is_dir())
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
RUNTIME = STAGE if (STAGE / "negative_carry.py").is_file() else ROOT / "scripts"
PLAN_PATH = STAGE / "challenge-protocol.json" if (STAGE / "challenge-protocol.json").is_file() else ROOT / "examples/negative_structural_carry/protocol.json"
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(STAGE))

from cami.artifacts import digest, read_json
from cami.index import IndexConfig, build_index, compare_indexes, signature
from cami.models import Anchor, Claim, Equals, MemoryState, PolicyConfig, Provenance, RepoLocation, Subject
from cami.policies import SelectionContext, advance_state, select_claims
from cami.repository import read_snapshot
from cami.validation import ValidationContext, validate_claim
from negative_carry import select_negative_carry
from negative_carry_witness import SCOPE, bind_context, mint_witness
from blob_negative_carry import select_blob_negative_carry

POLICY = PolicyConfig(id="symbol_validate")


class NegativeCarryFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fixture-", dir=STAGE)
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Authored fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / "pkg").mkdir()
        self.path = self.repo / "pkg/f.py"
        self.path.write_text("def f(x=2):\n    return x\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "authored mismatch")
        self.location = RepoLocation(repo_id="authored", path=str(self.repo))
        self.before = read_snapshot(self.location, self.head())
        self.old_index = build_index(self.before, IndexConfig())
        self.claim = Claim(claim_id="f", repo_id="authored", origin_commit=self.before.revision,
            kind="signature_equals", subject=Subject(path="pkg/f.py", qualname="f", node_kind="function"),
            text="Exact syntax f", scope=SCOPE,
            predicate=Equals(type="signature_equals", expected_signature=signature(ast.parse("def f(x=1): pass").body[0])))
        self.prov = Provenance(claim_id="f", scenario_id="authored", anchors=(Anchor(scope="symbol", path="pkg/f.py",
            qualname="f", observed_commit=self.before.revision, content_hash=self.before.blobs[0].content_hash, origin="static"),))
        result = validate_claim(self.claim, ValidationContext(self.before, self.old_index, self.prov, ROOT, self.repo))
        self.assertEqual((result.verdict, result.reason), ("contradicted", "predicate_mismatch"))
        self.context = bind_context(self.location, IndexConfig(), run_binding=digest({"fixture_parent": self.before.revision}))
        self.witness = mint_witness(self.claim, self.prov, result, self.before, self.old_index, self.context)
        self.assertIsNotNone(self.witness)
        self.previous = MemoryState(claim_id="f", revision=self.before.revision, state="stale", available=False,
            basis="validated", last_checked_commit=self.before.revision, last_supported_commit=None,
            last_verdict="contradicted", current_provenance=self.prov, withheld_reason="predicate_mismatch")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.DEVNULL)

    def head(self):
        return self.git("rev-parse", "HEAD").decode().strip()

    def step(self, source=None, *, mutate=None, previous=None, provenance=None):
        if source is not None:
            self.path.write_text(source)
        if mutate:
            mutate()
        self.git("add", "-A")
        self.git("commit", "--allow-empty", "-qm", "authored transition")
        after = read_snapshot(self.location, self.head())
        new_index = build_index(after, IndexConfig())
        changes = compare_indexes(self.old_index, new_index, self.before, after)
        previous = previous or self.previous
        provenance = provenance or self.prov
        original, = select_claims(SelectionContext(after.revision, (self.claim,), (provenance,), (previous,), changes,
                                 protocol_version="1.1"), POLICY)
        decision = select_negative_carry(self.claim, provenance, previous, original, self.before, after, self.old_index, new_index, witness=self.witness, context=self.context)
        fresh = validate_claim(self.claim, ValidationContext(after, new_index, provenance, ROOT, self.repo))
        state = advance_state(previous, decision.effective, POLICY, None if decision.suppressed else fresh, True)
        return decision, fresh, state, after, new_index

    def test_unchanged_mismatch_carries_without_relabeling_check(self):
        decision, fresh, state, after, new_index = self.step(mutate=lambda: (self.repo / "unrelated.txt").write_text("one"))
        self.assertTrue(decision.suppressed)
        self.assertEqual(fresh.verdict, "contradicted")
        self.assertFalse(state.available)
        self.assertEqual(state.last_checked_commit, self.before.revision)
        self.assertEqual(state.basis, "carried_forward")
        self.before, self.old_index, self.previous = after, new_index, state
        decision, fresh, state, _, _ = self.step()
        self.assertTrue(decision.suppressed)
        self.assertEqual(fresh.verdict, state.last_verdict)

    def test_recovery_is_validated(self):
        decision, fresh, state, _, _ = self.step("def f(x=1):\n    return x\n")
        self.assertFalse(decision.suppressed)
        self.assertEqual(fresh.verdict, "supported")
        self.assertTrue(state.available)

    def test_known_incomplete_and_uncertain_always_retry(self):
        incomplete = self.prov.model_copy(update={"known_incomplete": True})
        decision, _, _, _, _ = self.step(provenance=incomplete)
        self.assertFalse(decision.suppressed)
        unknown = self.previous.model_copy(update={"last_verdict": "insufficient_evidence", "state": "needs_validation", "withheld_reason": "parse_error"})
        decision, _, _, _, _ = self.step(previous=unknown)
        self.assertFalse(decision.suppressed)

    def test_parse_failure_and_shadowing_retain_validation(self):
        for source in ("def f(\n", "def f(x=2): return x\nf = 7\n",
                       "def f(x=2): return x\ndef f(x=2): return x\n",
                       "if True:\n    def f(x=2): return x\n",
                       "def f(x=2): return x\nclass C:\n    global f\n    f = 7\n"):
            decision, fresh, state, _, _ = self.step(source)
            self.assertFalse(decision.suppressed)
            self.assertEqual(fresh.verdict, "insufficient_evidence")
            self.assertFalse(state.available)

    def test_symlink_with_same_blob_and_absence_retain_validation(self):
        source = self.path.read_text()
        def symlink():
            self.path.unlink()
            self.path.symlink_to(source)
        decision, fresh, state, _, _ = self.step(mutate=symlink)
        self.assertFalse(decision.suppressed)
        self.assertEqual(fresh.verdict, "insufficient_evidence")
        self.path.unlink()
        decision, fresh, state, _, _ = self.step()
        self.assertFalse(decision.suppressed)
        self.assertEqual(fresh.reason, "subject_absent")

    def test_naive_absence_filter_has_real_ancestor_limitation_counterexample(self):
        self.path.unlink()
        _, absent, absent_state, after, new_index = self.step()
        self.assertEqual(absent.reason, "subject_absent")
        self.before, self.old_index, self.previous = after, new_index, absent_state
        def ancestor_symlink():
            (self.repo / "pkg").rmdir()
            (self.repo / "pkg").symlink_to("elsewhere")
        decision, fresh, state, _, _ = self.step(mutate=ancestor_symlink)
        self.assertEqual(decision.original.reasons, ("previously_unavailable",))
        self.assertEqual(fresh.verdict, "insufficient_evidence")
        self.assertEqual(fresh.reason, "symlink_unsupported")
        self.assertFalse(decision.suppressed)
        naive_selection = decision.original.model_copy(update={"selected": False, "reasons": ()})
        naive = advance_state(absent_state, naive_selection, POLICY, None, True)
        self.assertEqual(naive.last_verdict, "contradicted")
        self.assertNotEqual(naive.last_verdict, fresh.verdict)
        self.assertFalse(naive.available)  # Availability alone misses stale negative evidence.

    def test_absent_subject_recovery_is_always_validated(self):
        self.path.unlink()
        _, _, state, after, new_index = self.step()
        self.before, self.old_index, self.previous = after, new_index, state
        decision, fresh, state, _, _ = self.step("def f(x=1): return x\n")
        self.assertFalse(decision.suppressed)
        self.assertEqual(fresh.verdict, "supported")
        self.assertTrue(state.available)

    def test_blob_candidate_carries_only_last_validated_module_identity(self):
        decision, fresh, _, after, new_index = self.step()
        blob = select_blob_negative_carry(self.claim, self.prov, self.previous, decision.original,
            self.before, after, witness=self.witness, context=self.context)
        self.assertTrue(blob.suppressed)
        self.assertEqual(fresh.verdict, "contradicted")
        decision, fresh, _, after, new_index = self.step("# changed comment\ndef f(x=2):\n    return x\n")
        self.assertTrue(decision.suppressed)
        blob = select_blob_negative_carry(self.claim, self.prov, self.previous, decision.original,
            self.before, after, witness=self.witness, context=self.context)
        self.assertFalse(blob.suppressed)

    def test_same_id_predicate_or_context_change_refuses_blob_carry(self):
        decision, _, _, after, _ = self.step()
        changed_claim = self.claim.model_copy(update={"predicate": Equals(type="signature_equals",
            expected_signature=signature(ast.parse("def f(x=2): pass").body[0]))})
        changed_contexts = [replace(self.context, source_roots=("different",)),
            replace(self.context, max_file_bytes=100), replace(self.context, python="another parser"),
            replace(self.context, validator_version="different"), replace(self.context, index_version="different"),
            replace(self.context, scope_contract="runtime_signature"), replace(self.context, run_binding="f" * 64)]
        for context in changed_contexts:
            blob = select_blob_negative_carry(self.claim, self.prov, self.previous, decision.original,
                self.before, after, witness=self.witness, context=context)
            self.assertFalse(blob.suppressed)
        blob = select_blob_negative_carry(changed_claim, self.prov, self.previous, decision.original,
            self.before, after, witness=self.witness, context=self.context)
        self.assertFalse(blob.suppressed)
        self.assertEqual(blob.reason, "bound_claim_provenance_or_context_changed")

    def test_policy_switch_recovery_cannot_reuse_old_negative_witness(self):
        _, fresh, _, recovery, recovery_index = self.step("def f(x=1):\n    return x\n")
        self.assertEqual(fresh.verdict, "supported")
        changes = compare_indexes(self.old_index, recovery_index, self.before, recovery)
        keep, = select_claims(SelectionContext(recovery.revision, (self.claim,), (self.prov,),
            (self.previous,), changes, protocol_version="1.1"), PolicyConfig(id="keep_all"))
        carried = advance_state(self.previous, keep, PolicyConfig(id="keep_all"), None, True)
        self.before, self.old_index, self.previous = recovery, recovery_index, carried
        decision, fresh, state, after, _ = self.step()
        self.assertEqual(decision.original.reasons, ("previously_unavailable",))
        self.assertFalse(decision.suppressed)
        blob = select_blob_negative_carry(self.claim, self.prov, carried, decision.original,
            recovery, after, witness=self.witness, context=self.context)
        self.assertFalse(blob.suppressed)
        self.assertEqual(fresh.verdict, "supported")
        self.assertTrue(state.available)

    def test_invalid_actual_validation_input_cannot_mint_witness(self):
        result = validate_claim(self.claim, ValidationContext(self.before, self.old_index, self.prov, ROOT, self.repo))
        result = result.model_copy(update={"input_hash": "0" * 64})
        self.assertIsNone(mint_witness(self.claim, self.prov, result, self.before, self.old_index, self.context))

    def test_fixed_challenge_correctness_without_timing(self):
        from negative_carry_challenge import VARIANTS, prepare_histories, run_history
        plan = read_json(PLAN_PATH)
        histories = prepare_histories(plan, self.repo / "authored-challenge", ROOT)
        self.assertEqual(len(histories), 17)
        for history in histories:
            for variant in VARIANTS:
                result = run_history(history, variant, capture=True)
                self.assertEqual(len(result["rows"]), len(history.frames))
                for row in result["rows"]:
                    if row["suppressed"]:
                        self.assertEqual(row["fresh"]["verdict"], "contradicted")
                        self.assertEqual(row["state"]["last_checked_commit"], row["previous_state"]["last_checked_commit"])

    def test_draft_protocol_cannot_start_measurement(self):
        import run_negative_carry_challenge as driver
        draft = read_json(PLAN_PATH)
        draft["status"] = "draft"
        from cami.artifacts import write_json
        draft_path = self.repo / "draft-protocol.json"
        write_json(draft_path, draft)
        with self.assertRaisesRegex(ValueError, "newly sealed"):
            driver.preflight(draft_path)

    def test_extra_reason_or_wrong_provenance_cannot_be_suppressed(self):
        decision, _, _, after, new_index = self.step()
        extra = decision.original.model_copy(update={"reasons": ("previously_unavailable", "subject_changed")})
        blocked = select_negative_carry(self.claim, self.prov, self.previous, extra, self.before, after, self.old_index, new_index, witness=self.witness, context=self.context)
        self.assertFalse(blocked.suppressed)
        changed = self.prov.model_copy(update={"scenario_id": "another"})
        blocked = select_negative_carry(self.claim, changed, self.previous, decision.original, self.before, after, self.old_index, new_index, witness=self.witness, context=self.context)
        self.assertFalse(blocked.suppressed)


if __name__ == "__main__":
    unittest.main()
