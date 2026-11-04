"""Synthetic format/identity tests; no candidate packet or CAMI import."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts import validate_ai_review as validator


HERE = Path(__file__).resolve().parent


class ReviewAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="synthetic-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.packet = self.root / "packet"
        self.packet.mkdir()
        source = b"def sample(x):\n    return x\n"
        (self.packet / "source.py").write_bytes(source)
        self.source_hash = validator.sha256(source)
        self.cases = [{"id": case_id, "kind": "symbol_exists", "subject": {"qualname": "sample"},
                       "predicate": {"type": "symbol_exists"}, "text": "Exact synthetic syntax.",
                       "scope": "Syntax only.", "source_path": "source.py", "source_sha256": self.source_hash}
                      for case_id in ("tiny-a", "tiny-b")]
        self.write_cases()
        self.review = {"schema_version": 1, "reviewer_kind": "ai_reviewer", "human": False,
                       "provider": "codex", "model": "codex:gpt-6.1-sol", "reasoning_effort": "high",
                       "agent_task": "/synthetic/test-review", "identity_basis": "declared_invocation",
                       "independence_disclosure": validator.DISCLOSURE,
                       "packet_sha256": validator.compute_packet_identity(self.packet),
                       "items": [{"id": case["id"], "source_sha256": self.source_hash,
                                  "verdict": "supported", "extracted_facts": {"name": "sample"},
                                  "reasoning": "The source defines sample at module scope.",
                                  "scope_notes": "No runtime claim.",
                                  "evidence": [{"source_path": "source.py", "available": True,
                                                "line_start": 1, "line_end": 2}]}
                                 for case in self.cases]}
        self.review_path = self.root / "review.json"

    def write_cases(self):
        (self.packet / "cases.json").write_text(json.dumps(self.cases), encoding="utf-8")

    def write_review(self):
        self.review_path.write_text(json.dumps(self.review), encoding="utf-8")

    def audit(self):
        self.write_review()
        return validator.audit_review(self.packet, self.review_path)

    def rejected(self, message):
        with self.assertRaisesRegex(validator.ReviewError, message):
            self.audit()

    def test_two_case_packet_is_valid_and_produces_audit_only(self):
        audit = self.audit()
        self.assertEqual(audit["counts"]["packet_cases"], 2)
        self.assertEqual(audit["artifact_kind"], "ai_review_format_audit")
        self.assertEqual(audit["input_hashes"]["review_sha256"], validator.sha256(self.review_path.read_bytes()))
        self.assertNotIn("items", audit)
        self.assertNotIn("labels", audit)

    def test_packet_identity_is_bound_to_exact_manifest_bytes(self):
        with (self.packet / "cases.json").open("a") as stream:
            stream.write("\n")
        self.rejected("packet identity mismatch")

    def test_source_tampering_is_rejected(self):
        (self.packet / "source.py").write_text("changed\n")
        self.rejected("source hash mismatch")

    def test_review_source_hash_is_bound(self):
        self.review["items"][0]["source_sha256"] = "0" * 64
        self.rejected("review source hash mismatch")

    def test_missing_case_is_rejected(self):
        self.review["items"].pop()
        self.rejected("coverage mismatch")

    def test_duplicate_case_is_rejected(self):
        self.review["items"].append(copy.deepcopy(self.review["items"][0]))
        self.rejected("duplicate review case")

    def test_unknown_case_is_rejected(self):
        self.review["items"][0]["id"] = "foreign"
        self.rejected("unknown or duplicate")

    def test_duplicate_packet_id_is_rejected(self):
        self.cases[1]["id"] = self.cases[0]["id"]
        self.write_cases()
        self.rejected("duplicate packet case")

    def test_human_disguise_is_rejected(self):
        for key, value in (("human", True), ("human", 0), ("reviewer_kind", "human"),
                           ("reviewer_kind", "independent_oracle")):
            with self.subTest(key=key, value=value):
                previous = self.review[key]
                self.review[key] = value
                self.rejected("AI provenance")
                self.review[key] = previous

    def test_disclosure_and_identity_basis_are_required(self):
        self.review["independence_disclosure"] = "These reviewers are independent."
        self.rejected("disclosure")
        self.review["independence_disclosure"] = validator.DISCLOSURE
        self.review["identity_basis"] = "model_weight_fingerprint"
        self.rejected("declared invocation")

    def test_out_of_range_and_boolean_line_numbers_are_rejected(self):
        for value in (0, 3, True, 1.5):
            with self.subTest(value=value):
                self.review["items"][0]["evidence"][0]["line_end"] = value
                self.rejected("line")

    def test_wrong_evidence_source_is_rejected(self):
        self.review["items"][0]["evidence"][0]["source_path"] = "other.py"
        self.rejected("sealed source")

    def test_positive_verdict_requires_evidence_and_reasoning(self):
        self.review["items"][0]["evidence"] = []
        self.rejected("requires source evidence")
        self.review["items"][0]["verdict"] = "uncertain"
        self.review["items"][0]["reasoning"] = " "
        self.rejected("reasoning")

    def test_uncertain_may_document_unavailable_evidence(self):
        item = self.review["items"][0]
        item["verdict"] = "uncertain"
        item["reasoning"] = "The syntax is visible, but requested runtime evidence is unavailable."
        item["evidence"] = [{"source_path": "source.py", "available": False,
                            "explanation": "Runtime evidence is outside this sealed source packet."}]
        self.assertEqual(self.audit()["counts"]["unavailable_evidence_entries"], 1)
        item["verdict"] = "contradicted"
        self.rejected("only allowed for uncertain")

    def test_uncertain_without_citation_still_needs_explanation(self):
        item = self.review["items"][0]
        item["verdict"] = "uncertain"
        item["evidence"] = []
        item["reasoning"] = "Source cannot establish this claim within the stated scope."
        self.assertEqual(self.audit()["counts"]["declared_verdicts"]["uncertain"], 1)

    def test_blank_unavailable_evidence_is_rejected(self):
        item = self.review["items"][0]
        item["verdict"] = "uncertain"
        item["evidence"] = [{"source_path": "source.py", "available": False, "explanation": ""}]
        self.rejected("explanation")

    def test_path_traversal_and_symlink_escape_are_rejected(self):
        self.cases[0]["source_path"] = "../source.py"
        self.write_cases()
        self.rejected("relative path")
        outside = self.root / "outside.py"
        outside.write_text("outside\n")
        (self.packet / "escape.py").symlink_to(outside)
        self.cases[0]["source_path"] = "escape.py"
        self.write_cases()
        self.rejected("escapes packet")

    def test_duplicate_json_key_is_rejected(self):
        self.write_review()
        text = self.review_path.read_text()
        self.review_path.write_text(text.replace('"human": false', '"human": false, "human": true'))
        with self.assertRaisesRegex(validator.ReviewError, "duplicate JSON key"):
            validator.audit_review(self.packet, self.review_path)

    def test_empty_source_cannot_supply_positive_line_evidence(self):
        (self.packet / "source.py").write_bytes(b"")
        empty_hash = validator.sha256(b"")
        for case, item in zip(self.cases, self.review["items"]):
            case["source_sha256"] = item["source_sha256"] = empty_hash
        self.write_cases()
        self.review["packet_sha256"] = validator.compute_packet_identity(self.packet)
        self.rejected("outside source")

    def test_schema_is_valid_json_with_explicit_ai_provenance(self):
        schema = json.loads((HERE.parent / "examples/ai_review_pilot/packet/review.schema.json").read_text())
        self.assertEqual(schema["properties"]["reviewer_kind"]["const"], "ai_reviewer")
        self.assertIs(schema["properties"]["human"]["const"], False)
        self.assertEqual(set(schema["required"]), validator.HEADER_KEYS)
        self.assertEqual(set(schema["$defs"]["item"]["required"]), validator.ITEM_KEYS)

    def test_cli_writes_new_audit_and_refuses_overwrite(self):
        self.write_review()
        output = self.root / "audit.json"
        command = [sys.executable, str(HERE.parent / "scripts/validate_ai_review.py"), "--packet", str(self.packet),
                   "--review", str(self.review_path), "--out", str(output)]
        run = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        original = output.read_bytes()
        repeated = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(repeated.returncode, 2)
        self.assertEqual(output.read_bytes(), original)

    def test_cli_failure_does_not_create_audit(self):
        self.review["items"].pop()
        self.write_review()
        output = self.root / "audit.json"
        run = subprocess.run([sys.executable, str(HERE.parent / "scripts/validate_ai_review.py"), "--packet", str(self.packet),
                              "--review", str(self.review_path), "--out", str(output)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
