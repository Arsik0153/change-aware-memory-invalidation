"""Authored temporary Git fixtures only: never opens the development corpus."""
# ruff: noqa: E402
from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

STAGE = Path(__file__).resolve().parent
ROOT = next(parent for parent in STAGE.parents if (parent / "src/cami").is_dir())
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(STAGE))
import run_real_structural_replay as replay
import real_structural_replay_support as support
from cami.artifacts import digest, file_hash, read_json, read_jsonl, write_json, write_jsonl
from cami.index import signature
from real_structural_replay_support import VARIANTS, load_reference, reference_claim, summarize
from scripts.verify_cami import source_snapshot as replay_source_snapshot


class ReplayFixture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="fixture-", dir=STAGE)
        self.base = Path(self.directory.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.parent = self.commit("def f(x=1):\n    return x\n")
        self.children = [self.commit("def f(x=2):\n    return x\n"), self.commit(None),
                         self.commit("def f(x=1):\n    return x\ndef f(x=1):\n    return x\n"),
                         self.commit("def f(x=1):\n    return x\n")]
        self.claim = {"schema_version": 1, "claim_id": "fixture-claim", "repo_id": "fixture",
                      "origin_commit": self.parent, "kind": "signature_equals", "text": "f signature",
                      "scope": "exact syntax", "subject": {"path": "module.py", "qualname": "f", "node_kind": "function"},
                      "predicate": {"type": "signature_equals", "expected_signature": signature(ast.parse("def f(x=1): pass").body[0]).model_dump(mode="json")}}
        self.snapshot_patch = patch.object(replay, "source_snapshot", side_effect=lambda _: replay_source_snapshot(self.repo))
        self.snapshot_patch.start()
        self.addCleanup(self.snapshot_patch.stop)
        self.claims = self.base / "claims.jsonl"
        write_jsonl(self.claims, [self.claim])
        source = b"def f(x=1):\n    return x\n"
        import hashlib
        source_hash = hashlib.sha256(source).hexdigest()
        self.cohort = [{"claim": self.claim, "claim_sha256": digest(self.claim), "group_id": "fixture",
                        "parent_source_sha256": source_hash, "split": "development",
                        "symbol_ast_sha256": hashlib.sha256(ast.dump(ast.parse(source).body[0], include_attributes=False).encode()).hexdigest(),
                        "parent_git_blob_object_id": self.git("rev-parse", self.parent + ":module.py").decode().strip()}]
        write_json(self.base / "cohort.json", self.cohort)
        write_json(self.base / "ai_case_map.json", [{"id": "case-fixture", "origin_class": "authentic_parent_claim",
            "original_candidate_id": self.claim["claim_id"], "original_claim_sha256": digest(self.claim), "original_claim": self.claim}])
        write_json(self.base / "ai_public_cases.json", [{"id": "case-fixture", "source_sha256": source_hash,
            **{field: self.claim[field] for field in ("kind", "subject", "predicate", "text", "scope")}}])
        reviews = []
        for number in range(2):
            path = self.base / f"review-{number}.json"
            write_json(path, {"human": False, "reviewer_kind": "ai_reviewer", "agent_task": f"fixture-{number}",
                              "items": [{"id": "case-fixture", "source_sha256": source_hash, "verdict": "supported"}]})
            reviews.append({"review_path": self.rel(path), "review_sha256": file_hash(path), "item_id": "case-fixture"})
        write_jsonl(self.base / "confirmations.jsonl", [{"claim_id": self.claim["claim_id"],
            "claim_sha256": digest(self.claim), "reviewer_kind": "ai_reviewer", "reviews": reviews}])
        provenance = {}
        for variant in VARIANTS:
            path = self.base / f"{variant}.jsonl"
            anchor = {"scope": "file" if variant == "file_anchor" else "symbol", "path": "module.py",
                      "observed_commit": self.parent, "content_hash": source_hash, "origin": "static"}
            if anchor["scope"] == "symbol":
                anchor["qualname"] = "f"
                anchor["content_hash"] = self.cohort[0]["symbol_ast_sha256"]
            write_jsonl(path, [{"schema_version": 1, "claim_id": self.claim["claim_id"], "scenario_id": variant,
                "anchors": [anchor], "dependencies": [], "known_incomplete": variant == "known_incomplete",
                "unresolved_reasons": ["fixture known incomplete"] if variant == "known_incomplete" else []}])
            provenance[variant] = self.rel(path)
        self.protocol = {"schema_version": 1, "status": "sealed", "production_protocol_version": "1.1",
            "split": "development", "root": str(ROOT), "seal_path": self.rel(self.base / "seal.json"),
            "reference_path": "scripts/structural_checker_v2.py", "cohort_path": self.rel(self.base / "cohort.json"),
            "confirmations_path": self.rel(self.base / "confirmations.jsonl"), "provenance": provenance,
            "ai_case_map_path": self.rel(self.base / "ai_case_map.json"),
            "ai_public_cases_path": self.rel(self.base / "ai_public_cases.json"),
            "implementation_paths": [self.rel(Path(replay.__file__)), self.rel(Path(support.__file__)), self.rel(Path(__file__))],
            "candidate_claims": 1, "candidate_claim_child_observations_per_variant": 4,
            "groups": [{"group_id": "fixture", "repo_id": "fixture", "repo_path": self.rel(self.repo),
                        "source_roots": ["."], "parent_commit": self.parent, "child_commits": self.children,
                        "claims_path": self.rel(self.claims)}]}
        self.protocol_path = self.base / "protocol.json"
        self.seal()

    def tearDown(self):
        self.directory.cleanup()

    def rel(self, path):
        return str(path.relative_to(ROOT))

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.DEVNULL)

    def commit(self, source):
        path = self.repo / "module.py"
        if source is None:
            path.unlink()
        else:
            path.write_text(source)
        self.git("add", "-A")
        self.git("commit", "-qm", "authored fixture")
        return self.git("rev-parse", "HEAD").decode().strip()

    def seal(self):
        write_json(self.protocol_path, self.protocol)
        paths = list((ROOT / "src/cami").rglob("*.py")) + [ROOT / "scripts/verify_cami.py", ROOT / "scripts/structural_checker_v2.py"]
        paths += [ROOT / name for name in self.protocol["implementation_paths"]]
        paths += [path for path in self.base.glob("*.json*") if path.name not in {"seal.json", "protocol.json"}]
        write_json(self.base / "seal.json", {"protocol_sha256": file_hash(self.protocol_path),
                   "files": {self.rel(path): file_hash(path) for path in paths}})

    def test_production_transitions_reference_and_recovery(self):
        output = self.base / "output"
        manifest = replay.execute(self.protocol_path, output)
        self.assertEqual(manifest["status"], "complete")
        rows = [row for row in read_jsonl(output / "observations.jsonl") if row["variant"] == "all_validate"]
        self.assertEqual([row["state"]["state"] for row in rows], ["stale", "retired", "needs_validation", "valid"])
        self.assertEqual([row["reference"]["verdict"] for row in rows], ["contradicted", "contradicted", "uncertain", "supported"])
        self.assertEqual(read_json(output / "report.json")["variants"]["all_validate"]["actual_validation_calls"], 4)
        self.assertIsNotNone(rows[1]["reference"]["evidence"])
        validations = [row["validation"]["input_hash"] for row in read_jsonl(output / "observations.jsonl") if row["commit"] == self.children[0]]
        self.assertEqual(len(set(validations)), 4)
        with self.assertRaises(Exception):
            replay.execute(self.protocol_path, output)

    def test_relative_cli_paths_produce_supported_parent_reference(self):
        output = self.base / "relative-output"
        manifest = replay.execute(Path(self.rel(self.protocol_path)), Path(self.rel(output)))
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(read_jsonl(output / "parents.jsonl")[0]["reference"]["verdict"], "supported")

    def test_no_supported_parent_retains_all_denominators(self):
        write_jsonl(self.base / "confirmations.jsonl", [])
        self.seal()
        output = self.base / "excluded"
        replay.execute(self.protocol_path, output)
        report = read_json(output / "report.json")["variants"]["symbol_anchor"]
        self.assertEqual(report["candidate_observations"], 4)
        self.assertEqual(report["scored_observations"], 0)
        self.assertIsNone(report["false_available_per_contradicted"])
        self.assertEqual(report["actual_validation_calls"], 0)
        self.assertEqual(len(read_jsonl(output / "parents.jsonl")), 1)

    def test_parent_production_uncertain_stays_withheld(self):
        self.protocol["groups"][0]["source_roots"] = ["unrelated"]
        self.seal()
        output = self.base / "withheld"
        replay.execute(self.protocol_path, output)
        row = read_jsonl(output / "parents.jsonl")[0]
        self.assertTrue(row["eligible"])
        self.assertFalse(row["variants"]["symbol_anchor"]["state"]["available"])
        self.assertEqual(row["variants"]["symbol_anchor"]["validation"]["reason"], "outside_source_roots")

    def test_seal_failure_prevents_child_access_and_preserves_failure(self):
        self.claims.write_text(self.claims.read_text() + "\n")
        with patch.object(replay, "read_snapshot", side_effect=AssertionError("snapshot touched")):
            with self.assertRaisesRegex(ValueError, "sealed file mismatch"):
                replay.execute(self.protocol_path, self.base / "failed")
        self.assertEqual(read_json(self.base / "failed/manifest.json")["status"], "failed")

    def test_reference_unknown_stays_outside_false_availability_denominator(self):
        child = self.commit("def f(x=1):\n    return x\nfrom another_module import *\n")
        # Replay from the original parent through all existing successors, then the authored ambiguity.
        self.protocol["groups"][0]["parent_commit"] = self.parent
        self.protocol["groups"][0]["child_commits"].append(child)
        self.protocol["candidate_claim_child_observations_per_variant"] = 5
        self.seal()
        output = self.base / "unknown"
        replay.execute(self.protocol_path, output)
        report = read_json(output / "report.json")["variants"]["symbol_anchor"]
        self.assertEqual(report["reference_unknown"], 2)
        self.assertEqual(report["reference_contradicted"], 2)
        self.assertEqual(report["false_available"], 0)

    def test_nonregular_and_invalid_source_are_reference_unknown(self):
        from cami.models import Claim
        from cami.artifacts import canonical
        claim = Claim.model_validate_json(canonical(self.claim))
        reference = load_reference(ROOT / "scripts/structural_checker_v2.py")
        (self.repo / "module.py").unlink()
        (self.repo / "module.py").symlink_to("elsewhere")
        self.git("add", "-A")
        self.git("commit", "-qm", "authored symlink fixture")
        revision = self.git("rev-parse", "HEAD").decode().strip()
        result = reference_claim(self.repo, revision, claim, self.base / "symlink-packet", reference)
        self.assertEqual(result["verdict"], "uncertain")
        self.assertEqual(result["git_mode"], "120000")
        self.assertEqual((self.base / "symlink-packet/subject.raw").read_bytes(), b"elsewhere")
        (self.repo / "module.py").unlink()
        for index, raw in enumerate((b"def broken(\n", b"\xff\xfe")):
            (self.repo / "module.py").write_bytes(raw)
            self.git("add", "-A")
            self.git("commit", "-qm", "authored unsupported source")
            revision = self.git("rev-parse", "HEAD").decode().strip()
            result = reference_claim(self.repo, revision, claim, self.base / f"invalid-{index}", reference)
            self.assertEqual(result["verdict"], "uncertain")

    def test_same_module_ai_case_swap_is_rejected_before_source_access(self):
        confirmations = read_jsonl(self.base / "confirmations.jsonl")
        for review in confirmations[0]["reviews"]:
            review["item_id"] = "other-claim-same-source"
            path = ROOT / review["review_path"]
            raw = read_json(path)
            raw["items"].append({**raw["items"][0], "id": "other-claim-same-source"})
            write_json(path, raw)
            review["review_sha256"] = file_hash(path)
        write_jsonl(self.base / "confirmations.jsonl", confirmations)
        self.seal()
        with patch.object(replay, "read_snapshot", side_effect=AssertionError("snapshot touched")):
            with self.assertRaisesRegex(ValueError, "does not match authentic original claim"):
                replay.execute(self.protocol_path, self.base / "swapped")

    def test_all_chains_are_checked_before_any_snapshot(self):
        from copy import deepcopy
        second_claim = {**self.claim, "claim_id": "fixture-second"}
        second_cohort = {**self.cohort[0], "claim": second_claim, "claim_sha256": digest(second_claim), "group_id": "second"}
        write_json(self.base / "cohort.json", [self.cohort[0], second_cohort])
        second_path = self.base / "second-claims.jsonl"
        write_jsonl(second_path, [second_claim])
        mappings = read_json(self.base / "ai_case_map.json")
        mappings.append({**mappings[0], "id": "case-second", "original_candidate_id": "fixture-second",
                         "original_claim_sha256": digest(second_claim), "original_claim": second_claim})
        write_json(self.base / "ai_case_map.json", mappings)
        public = read_json(self.base / "ai_public_cases.json")
        write_json(self.base / "ai_public_cases.json", [public[0], {**public[0], "id": "case-second"}])
        for path in self.protocol["provenance"].values():
            rows = read_jsonl(ROOT / path)
            write_jsonl(ROOT / path, [rows[0], {**rows[0], "claim_id": "fixture-second"}])
        group = deepcopy(self.protocol["groups"][0])
        group.update(group_id="second", child_commits=[self.children[2]], claims_path=self.rel(second_path))
        self.protocol["groups"].append(group)
        self.protocol["candidate_claims"] = 2
        self.protocol["candidate_claim_child_observations_per_variant"] = 5
        self.seal()
        with patch.object(replay, "read_snapshot", side_effect=AssertionError("snapshot touched")):
            with self.assertRaisesRegex(Exception, "must have exactly one parent"):
                replay.execute(self.protocol_path, self.base / "bad-chain")

    def test_dirty_implementation_refused_before_source_access(self):
        with patch.object(replay, "source_snapshot", return_value={"source_status": " M scripts/example.py"}):
            with patch.object(replay, "read_snapshot", side_effect=AssertionError("snapshot touched")):
                with self.assertRaisesRegex(ValueError, "must be clean"):
                    replay.execute(self.protocol_path, self.base / "dirty")

    def test_unknown_counts_do_not_count_as_false_availability(self):
        row = {"eligible": True, "reference": {"verdict": "uncertain"}, "state": {"available": True},
               "selection": {"selected": False}, "validation": None}
        result = summarize([row])
        self.assertEqual(result["available_unknown"], 1)
        self.assertEqual(result["reference_unknown"], 1)
        self.assertEqual(result["false_available"], 0)
        self.assertIsNone(result["false_available_per_contradicted"])


if __name__ == "__main__":
    unittest.main()
