"""Full authored first-parent/merge fixture; no real corpus source/tree access."""
# ruff: noqa: E402
from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

STAGE = Path(__file__).resolve().parent
ROOT = next(parent for parent in STAGE.parents if (parent / "src/cami").is_dir())
RUNTIME = STAGE if (STAGE / "real_structural_first_parent_support.py").is_file() else ROOT / "scripts"
for location in (ROOT, ROOT / "src", ROOT / "scripts", RUNTIME):
    sys.path.insert(0, str(location))

from cami.artifacts import digest, file_hash, read_json, read_jsonl, write_json, write_jsonl
from cami.index import signature
from cami.repository import chain
from scripts import run_real_structural_replay as old_driver
from scripts.verify_cami import source_snapshot
import run_real_structural_first_parent_replay as driver
from real_structural_first_parent_support import BASIS, MODE, PROTOCOL_ID, compare_overlap, extension_inputs, preflight_first_parent, stratum_report

SOURCE = "def f(x=1):\n    return x\n"


class FirstParentFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="first-parent-fixture-", dir=STAGE)
        cls.base = Path(cls.temp.name)
        cls.repo = cls.base / "repo"
        cls.repo.mkdir()
        cls.git("init", "-q")
        cls.git("config", "user.name", "Authored first parent fixture")
        cls.git("config", "user.email", "fixture@example.invalid")
        cls.side_ids, cls.groups, cls.trajectories = set(), [], []
        previous = cls.commit_tree(cls.tree(SOURCE), [])
        group_numbers = [("group-a", 7), ("group-b", 0), ("group-c", 3)]
        for group_id, merge_count in group_numbers:
            parent = previous
            children, steps = [], []
            for number in range(1, 13):
                source = SOURCE
                if group_id == "group-a":
                    source = {2: "def f(x=2):\n    return x\n", 5: None,
                        6: SOURCE + SOURCE, 8: "def broken(\n"}.get(number, SOURCE)
                merge = 2 <= number <= merge_count + 1
                main_tree = cls.tree(source)
                parents = [previous]
                if merge:
                    feature_tree = cls.tree("def f(x=9): return x\n") if number == 4 else main_tree
                    side = cls.commit_tree(feature_tree, [previous])
                    cls.side_ids.add(side)
                    parents.append(side)
                    if group_id == "group-a" and number == 3:
                        extra = cls.commit_tree(main_tree, [previous])
                        cls.side_ids.add(extra)
                        parents.append(extra)
                commit = cls.commit_tree(main_tree, parents)
                children.append(commit)
                steps.append({"step": number, "commit": commit, "parents": parents, "previous_commit": previous,
                    "is_merge": merge, "comparison_basis": BASIS,
                    "already_in_old_protocol": group_id == "group-b" or number == 1})
                previous = commit
            group = {"group_id": group_id, "repo_id": "authored", "repo_path": cls.rel(cls.repo),
                     "parent_commit": parent, "child_commits": children, "source_roots": ["."],
                     "claims_path": cls.rel(cls.base / f"{group_id}-claims.jsonl")}
            cls.groups.append(group)
            cls.trajectories.append({"group_id": group_id, "repo_id": "authored", "split": "development",
                "source_roots": ["."], "child_count": 12, "merge_count": merge_count,
                "new_child_count": 0 if group_id == "group-b" else 11,
                "previously_frozen_child_count": 12 if group_id == "group-b" else 1,
                "parent": {"commit": parent, "parents": cls.parents(parent)}, "steps": steps})
        cls.boundary = previous
        cls.git("update-ref", "refs/heads/main", previous)
        cls.git("symbolic-ref", "HEAD", "refs/heads/main")
        cls.git("read-tree", previous)
        cls.make_inputs()
        # Old actual runner supplies legitimate original observations on single-parent prefixes.
        with patch.object(old_driver, "source_snapshot", side_effect=lambda _: source_snapshot(cls.repo)):
            old_driver.execute(cls.old_path, cls.base / "old-output")
        cls.make_extension()
        cls.inputs, cls.metadata, cls.old_protocol, cls.old_rows, cls.old_parents = extension_inputs(cls.new_path)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def git(cls, *arguments):
        return subprocess.check_output(["git", "--no-replace-objects", "-C", str(cls.repo), *arguments], stderr=subprocess.DEVNULL)

    @classmethod
    def rel(cls, path):
        return str(path.relative_to(ROOT))

    @classmethod
    def tree(cls, source):
        path = cls.repo / "module.py"
        if source is None:
            if path.exists():
                path.unlink()
        else:
            path.write_text(source)
        cls.git("add", "-A")
        return cls.git("write-tree").decode().strip()

    @classmethod
    def commit_tree(cls, tree, parents):
        arguments = ["commit-tree", tree]
        for parent in parents:
            arguments += ["-p", parent]
        arguments += ["-m", f"authored-{len(cls.side_ids)}-{tree}-{parents}"]
        return cls.git(*arguments).decode().strip()

    @classmethod
    def parents(cls, commit):
        return cls.git("rev-list", "--parents", "-n", "1", commit).decode().split()[1:]

    @classmethod
    def seal(cls, protocol_path, protocol, extras=()):
        write_json(protocol_path, protocol)
        paths = list((ROOT / "src/cami").rglob("*.py"))
        paths += [ROOT / "scripts/verify_cami.py", ROOT / "scripts/structural_checker_v2.py",
                  ROOT / "scripts/real_structural_replay_support.py", ROOT / "scripts/run_real_structural_replay.py"]
        paths += [RUNTIME / "real_structural_first_parent_support.py", RUNTIME / "run_real_structural_first_parent_replay.py", Path(__file__)]
        paths += [path for path in cls.base.glob("*.json*") if path != protocol_path and path.name not in {"old-seal.json", "new-seal.json"}]
        paths += list(extras)
        old_seal = cls.base / "old-seal.json"
        if old_seal.is_file() and cls.rel(old_seal) != protocol["seal_path"]:
            paths.append(old_seal)
        paths = [path for path in paths if path.is_file() and path != ROOT / protocol["seal_path"]]
        write_json(ROOT / protocol["seal_path"], {"protocol_sha256": file_hash(protocol_path),
            "files": {cls.rel(path): file_hash(path) for path in paths}})

    @classmethod
    def make_inputs(cls):
        import hashlib
        source_hash = hashlib.sha256(SOURCE.encode()).hexdigest()
        ast_hash = hashlib.sha256(ast.dump(ast.parse(SOURCE).body[0], include_attributes=False).encode()).hexdigest()
        expected_signature = signature(ast.parse(SOURCE).body[0]).model_dump(mode="json")
        cohort, mappings, public, confirmations = [], [], [], []
        provenance = {variant: [] for variant in ("symbol_anchor", "file_anchor", "known_incomplete")}
        for group in cls.groups:
            claims = []
            for number in range(8):
                claim = {"schema_version": 1, "claim_id": group["group_id"] + f"-{number}", "repo_id": "authored",
                    "origin_commit": group["parent_commit"], "kind": "signature_equals", "text": "Exact authored signature.",
                    "scope": "Exact normalized syntax, including defaults, annotations, decorators, and async status.",
                    "subject": {"path": "module.py", "qualname": "f", "node_kind": "function"},
                    "predicate": {"type": "signature_equals", "expected_signature": expected_signature}}
                claims.append(claim)
                claim_id = claim["claim_id"]
                cohort.append({"claim": claim, "claim_sha256": digest(claim), "group_id": group["group_id"],
                    "parent_source_sha256": source_hash, "symbol_ast_sha256": ast_hash, "split": "development",
                    "parent_git_blob_object_id": cls.git("rev-parse", group["parent_commit"] + ":module.py").decode().strip()})
                case_id = "case-" + claim_id
                mappings.append({"id": case_id, "origin_class": "authentic_parent_claim", "original_candidate_id": claim_id,
                    "original_claim_sha256": digest(claim), "original_claim": claim})
                public.append({"id": case_id, "source_sha256": source_hash,
                    **{field: claim[field] for field in ("kind", "subject", "predicate", "text", "scope")}})
                for variant in provenance:
                    anchor = {"scope": "file" if variant == "file_anchor" else "symbol", "path": "module.py",
                        "observed_commit": group["parent_commit"], "content_hash": source_hash if variant == "file_anchor" else ast_hash,
                        "origin": "static"}
                    if variant != "file_anchor":
                        anchor["qualname"] = "f"
                    provenance[variant].append({"schema_version": 1, "claim_id": claim_id, "scenario_id": variant,
                        "anchors": [anchor], "dependencies": [], "known_incomplete": variant == "known_incomplete",
                        "unresolved_reasons": ["authored incomplete"] if variant == "known_incomplete" else []})
            write_jsonl(ROOT / group["claims_path"], claims)
        write_json(cls.base / "cohort.json", cohort)
        write_json(cls.base / "map.json", mappings)
        write_json(cls.base / "public.json", public)
        for variant, rows in provenance.items():
            write_jsonl(cls.base / (variant + ".jsonl"), rows)
        review_refs = []
        for number in range(2):
            path = cls.base / f"review-{number}.json"
            write_json(path, {"human": False, "reviewer_kind": "ai_reviewer", "agent_task": f"authored-{number}",
                "items": [{"id": item["id"], "source_sha256": source_hash, "verdict": "supported"} for item in public]})
            review_refs.append({"review_path": cls.rel(path), "review_sha256": file_hash(path)})
        for row in cohort:
            confirmations.append({"claim_id": row["claim"]["claim_id"], "claim_sha256": row["claim_sha256"],
                "reviewer_kind": "ai_reviewer", "reviews": [{**review, "item_id": "case-" + row["claim"]["claim_id"]} for review in review_refs]})
        write_jsonl(cls.base / "confirmations.jsonl", confirmations)
        old_groups = deepcopy(cls.groups)
        for group in old_groups:
            if group["group_id"] != "group-b":
                group["child_commits"] = group["child_commits"][:1]
        cls.old = {"schema_version": 1, "status": "sealed", "production_protocol_version": "1.1", "split": "development",
            "root": str(ROOT), "seal_path": cls.rel(cls.base / "old-seal.json"), "groups": old_groups,
            "cohort_path": cls.rel(cls.base / "cohort.json"), "ai_case_map_path": cls.rel(cls.base / "map.json"),
            "ai_public_cases_path": cls.rel(cls.base / "public.json"), "confirmations_path": cls.rel(cls.base / "confirmations.jsonl"),
            "reference_path": "scripts/structural_checker_v2.py", "candidate_claims": 24,
            "candidate_claim_child_observations_per_variant": 112,
            "provenance": {variant: cls.rel(cls.base / (("symbol_anchor" if variant == "all_validate" else variant) + ".jsonl"))
                for variant in ("symbol_anchor", "file_anchor", "known_incomplete", "all_validate")},
            "implementation_paths": ["scripts/run_real_structural_replay.py", "scripts/real_structural_replay_support.py"]}
        cls.old_path = cls.base / "old-protocol.json"
        cls.seal(cls.old_path, cls.old)

    @classmethod
    def make_extension(cls):
        cls.meta = {"boundary_commit": cls.boundary, "local_HEAD": cls.boundary, "trajectories": cls.trajectories,
            "input_sha256": {cls.rel(cls.old_path): file_hash(cls.old_path), cls.old["seal_path"]: file_hash(ROOT / cls.old["seal_path"])},
            "total_steps": 36, "merge_steps": 10, "newly_authorizable_steps": 22, "old_overlap_steps": 14,
            "candidate_observations_per_variant": 288, "new_candidate_observations_per_variant": 176}
        write_json(cls.base / "metadata.json", cls.meta)
        cls.protocol = {**cls.old, "protocol_id": PROTOCOL_ID, "trajectory_mode": MODE,
            "seal_path": cls.rel(cls.base / "new-seal.json"), "groups": cls.groups, "boundary_commit": cls.boundary,
            "metadata_manifest_path": cls.rel(cls.base / "metadata.json"), "candidate_claim_child_observations_per_variant": 288,
            "new_candidate_claim_child_observations_per_variant": 176, "reference_sha256": file_hash(ROOT / cls.old["reference_path"]),
            "old_protocol": {"path": cls.rel(cls.old_path), "sha256": file_hash(cls.old_path),
                "seal_path": cls.old["seal_path"], "seal_sha256": file_hash(ROOT / cls.old["seal_path"])},
            "old_result": {field + "_path": cls.rel(cls.base / "old-output" / filename) for field, filename in
                (("manifest", "manifest.json"), ("observations", "observations.jsonl"), ("parents", "parents.jsonl"))},
            "implementation_paths": [*cls.old["implementation_paths"], cls.rel(RUNTIME / "real_structural_first_parent_support.py"),
                cls.rel(RUNTIME / "run_real_structural_first_parent_replay.py"), cls.rel(Path(__file__))]}
        for field in ("manifest", "observations", "parents"):
            cls.protocol["old_result"][field + "_sha256"] = file_hash(ROOT / cls.protocol["old_result"][field + "_path"])
        cls.new_path = cls.base / "new-protocol.json"
        cls.seal(cls.new_path, cls.protocol, extras=[ROOT / value for key, value in cls.protocol["old_result"].items() if key.endswith("_path")])

    def altered_protocol(self, name, *, metadata=None, edit=None, extras=()):
        protocol = deepcopy(self.protocol)
        protocol["seal_path"] = self.rel(self.base / f"{name}-seal.json")
        if metadata is not None:
            path = self.base / f"{name}-metadata.json"
            write_json(path, metadata)
            protocol["metadata_manifest_path"] = self.rel(path)
        if edit:
            edit(protocol)
        path = self.base / f"{name}-protocol.json"
        artifacts = [ROOT / value for key, value in protocol["old_result"].items() if key.endswith("_path")]
        self.seal(path, protocol, extras=[*artifacts, *extras])
        return path

    def execute(self, path, output):
        with patch.object(driver, "source_snapshot", side_effect=lambda _: source_snapshot(self.repo)):
            return driver.execute(path, output)

    def test_full_replay_has_exact_strata_and_semantic_overlap_without_side_reads(self):
        observed = []
        actual_snapshot, actual_reference = driver.read_snapshot, driver.reference_claim
        allowed = {group["parent_commit"] for group in self.groups} | {commit for group in self.groups for commit in group["child_commits"]}
        def snapshot(repo, commit):
            self.assertIn(commit, allowed)
            self.assertNotIn(commit, self.side_ids)
            observed.append(commit)
            return actual_snapshot(repo, commit)
        def reference(repo, commit, *arguments):
            self.assertIn(commit, allowed)
            self.assertNotIn(commit, self.side_ids)
            return actual_reference(repo, commit, *arguments)
        output = self.base / "complete"
        with patch.object(driver, "read_snapshot", side_effect=snapshot), patch.object(driver, "reference_claim", side_effect=reference):
            self.execute(self.new_path, output)
        report = read_json(output / "report.json")
        self.assertEqual(report["overlap_check"], {"status": "matched", "observation_count": 448, "parent_count": 24})
        for variant in self.protocol["provenance"]:
            self.assertEqual(report["variants"][variant]["candidate_observations"], 288)
            self.assertEqual(report["primary_new_coverage"]["variants"][variant]["candidate_observations"], 176)
            self.assertEqual(report["old_overlap"]["variants"][variant]["candidate_observations"], 112)
            self.assertEqual(report["topology_strata"]["merge"]["variants"][variant]["candidate_observations"], 80)
            self.assertEqual(report["topology_strata"]["nonmerge"]["variants"][variant]["candidate_observations"], 208)
        rows = [row for row in read_jsonl(output / "observations.jsonl") if row["group_id"] == "group-a" and row["variant"] == "symbol_anchor"]
        by_step = {number: [row for row in rows if row["trajectory"]["step"] == number] for number in range(1, 13)}
        self.assertTrue(all(row["state"]["state"] == "stale" and row["selection"]["selected"] for row in by_step[2]))
        self.assertTrue(all(row["state"]["available"] for row in by_step[3]))
        self.assertTrue(all(not row["selection"]["selected"] for row in by_step[4]))
        self.assertTrue(all(row["state"]["state"] == "retired" for row in by_step[5]))
        self.assertTrue(all(row["reference"]["verdict"] == "uncertain" for row in by_step[6]))
        self.assertTrue(all(row["state"]["available"] for row in by_step[7]))
        self.assertEqual(len(observed), 39)
        before = file_hash(output / "manifest.json")
        with self.assertRaises(Exception):
            self.execute(self.new_path, output)
        self.assertEqual(file_hash(output / "manifest.json"), before)

    def test_topology_accepts_octopus_and_preserves_parent_order(self):
        result = preflight_first_parent(self.protocol, self.meta, self.old, self.inputs[3], ROOT)
        child = self.groups[0]["child_commits"][2]
        self.assertEqual(len(result["group-a"][child]["parent_commits"]), 3)
        self.assertEqual(result["group-a"][child]["parent_commits"], self.trajectories[0]["steps"][2]["parents"])

    def test_topology_rejects_second_parent_changed_parent_list_gap_reorder_duplicate_boundary(self):
        for mutation in ("second", "parents", "gap", "reorder", "duplicate", "boundary"):
            protocol, metadata, groups = deepcopy(self.protocol), deepcopy(self.meta), deepcopy(self.inputs[3])
            if mutation == "second":
                metadata["trajectories"][0]["steps"][1]["previous_commit"] = metadata["trajectories"][0]["steps"][1]["parents"][1]
            elif mutation == "parents":
                metadata["trajectories"][0]["steps"][1]["parents"].reverse()
            elif mutation in {"gap", "reorder", "duplicate"}:
                children = groups[0][0]["child_commits"]
                if mutation == "gap":
                    children.pop(1)
                elif mutation == "reorder":
                    children[1], children[2] = children[2], children[1]
                else:
                    children[1] = children[0]
            else:
                protocol["boundary_commit"] = self.groups[0]["parent_commit"]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                preflight_first_parent(protocol, metadata, self.old, groups, ROOT)

    def test_global_final_group_rejection_precedes_all_source_readers(self):
        metadata = deepcopy(self.meta)
        metadata["trajectories"][-1]["steps"][-1]["parents"] = [self.groups[-1]["parent_commit"]]
        path = self.altered_protocol("late-invalid", metadata=metadata)
        output = self.base / "late-invalid"
        with patch.object(driver, "read_snapshot", side_effect=AssertionError("production source touched")) as production:
            with patch.object(driver, "reference_claim", side_effect=AssertionError("reference source touched")) as reference:
                with self.assertRaisesRegex(ValueError, "full parent list"):
                    self.execute(path, output)
        production.assert_not_called()
        reference.assert_not_called()
        self.assertEqual(read_json(output / "manifest.json")["status"], "failed")

    def test_wrong_mode_and_seal_mismatch_preserve_failure_without_source_access(self):
        path = self.altered_protocol("wrong-mode", edit=lambda p: p.update(trajectory_mode="old_single_parent"))
        for name, source in (("wrong-mode", path), ("seal-mismatch", self.altered_protocol("seal-mismatch"))):
            if name == "seal-mismatch":
                source.write_text(source.read_text() + "\n")
            with patch.object(driver, "read_snapshot", side_effect=AssertionError("source touched")):
                with self.assertRaises(ValueError):
                    self.execute(source, self.base / name)
            self.assertEqual(read_json(self.base / name / "manifest.json")["status"], "failed")

    def test_implementation_change_after_preflight_is_denied_and_outputs_preserved(self):
        marker = self.base / "frozen_marker.py"
        marker.write_text("# sealed implementation fixture\n")
        path = self.altered_protocol("implementation-change", edit=lambda p: p["implementation_paths"].append(self.rel(marker)), extras=[marker])
        actual = driver.read_snapshot
        first = True
        def change_once(repo, commit):
            nonlocal first
            if first:
                first = False
                marker.write_text("# changed after preflight\n")
            return actual(repo, commit)
        output = self.base / "implementation-change"
        with patch.object(driver, "read_snapshot", side_effect=change_once):
            with self.assertRaisesRegex(ValueError, "sealed input changed during replay"):
                self.execute(path, output)
        self.assertEqual(read_json(output / "manifest.json")["status"], "failed")
        self.assertEqual(len(read_jsonl(output / "observations.jsonl")), 1152)

    def test_overlap_ignores_only_validation_timings_and_input_case_paths(self):
        old = deepcopy(self.old_rows)
        records = deepcopy(old)
        for row in records:
            row["trajectory"] = {"coverage_stratum": "old_overlap"}
            row["reference"]["case_path"] = "/new/output/case.json"
            for field in ("validation", "full_production_validation"):
                if row.get(field):
                    row[field]["cpu_seconds"] = 999.0
                    row[field]["duration_seconds"] = 888.0
        result = compare_overlap(records, self.old_parents, old, self.old_parents, self.base / "normalization")
        self.assertEqual(result["status"], "matched")
        records[0]["state"]["last_checked_commit"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "semantic mismatch"):
            compare_overlap(records, self.old_parents, old, self.old_parents, self.base / "semantic-mismatch")
        self.assertEqual(read_json(self.base / "semantic-mismatch/overlap-check.json")["status"], "mismatch")

    def test_unknown_availability_is_separate_and_empty_added_group_is_explicit(self):
        row = deepcopy(self.old_rows[0])
        row["reference"]["verdict"] = "uncertain"
        row["state"]["available"] = True
        report = stratum_report([row], self.inputs[3])
        result = report["variants"][row["variant"]]
        self.assertEqual((result["available_unknown"], result["false_available"]), (1, 0))
        self.assertIsNone(result["false_available_per_contradicted"])
        empty = report["groups"]["group-b"][row["variant"]]
        self.assertEqual(empty["candidate_observations"], 0)
        self.assertEqual(empty["false_available_per_scored_null_reason"], "no_observations_in_stratum")

    def test_old_entrypoint_still_rejects_merge_before_snapshot(self):
        protocol = deepcopy(self.old)
        protocol["groups"][0]["child_commits"] = self.groups[0]["child_commits"][:2]
        protocol["candidate_claim_child_observations_per_variant"] = 120
        protocol["seal_path"] = self.rel(self.base / "old-merge-test-seal.json")
        path = self.base / "old-merge-test-protocol.json"
        self.seal(path, protocol)
        with patch.object(old_driver, "source_snapshot", side_effect=lambda _: source_snapshot(self.repo)):
            with patch.object(old_driver, "read_snapshot", side_effect=AssertionError("old snapshot touched")):
                with self.assertRaisesRegex(Exception, "must have exactly one parent"):
                    old_driver.execute(path, self.base / "old-merge-test")

    def test_old_implementation_binding_cannot_be_reinterpreted_by_new_seal(self):
        # Simulate a different sealed original implementation without touching tracked source.
        for number, name in enumerate(("src/cami/repository.py", "scripts/run_real_structural_replay.py", "scripts/real_structural_replay_support.py", "src/cami/missing_historical_fixture_module.py")):
            old_seal = read_json(ROOT / self.old["seal_path"])
            old_seal["files"][name] = "0" * 64
            path = self.base / f"changed-old-binding-{number}.json"
            write_json(path, old_seal)
            def edit(protocol):
                protocol["old_protocol"]["seal_path"] = self.rel(path)
                protocol["old_protocol"]["seal_sha256"] = file_hash(path)
            changed = self.altered_protocol(f"changed-old-binding-{number}", edit=edit)
            with patch.object(driver, "read_snapshot", side_effect=AssertionError("source touched")):
                with self.assertRaisesRegex(ValueError, "changed extension binding"):
                    self.execute(changed, self.base / f"old-binding-denied-{number}")

    def test_original_single_parent_chain_and_old_runner_still_reject_merge(self):
        group = self.groups[0]
        with self.assertRaisesRegex(Exception, "must have exactly one parent"):
            chain(self.repo, group["parent_commit"], tuple(group["child_commits"][:2]))
        self.assertIs(old_driver.chain, chain)


if __name__ == "__main__":
    unittest.main()
