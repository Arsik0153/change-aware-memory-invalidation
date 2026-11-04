"""Authored Git fixtures only. No network or real Packaging repository access."""

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
ROOT = next(p for p in STAGE.parents if (p / "src/cami").is_dir())
RUNTIME = STAGE if (STAGE / "run_packaging_replay.py").is_file() else ROOT / "scripts"
for p in (ROOT, ROOT / "src", ROOT / "scripts", RUNTIME, STAGE):
    sys.path.insert(0, str(p))
from cami.artifacts import digest, file_hash, read_json, read_jsonl, write_json, write_jsonl
from cami.index import signature
from scripts.real_structural_replay_support import load_reference
from scripts.validate_ai_review import compute_packet_identity, DISCLOSURE
from scripts.verify_cami import source_snapshot
import run_packaging_replay as driver
import packaging_replay_support as support

SOURCE = "".join(f"def f{i}(x=1):\n    return x\n" for i in range(4))


class PackagingFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="packaging-authored-", dir=STAGE)
        cls.base = Path(cls.temp.name)
        cls.inputs = cls.base / "inputs"
        cls.inputs.mkdir()
        cls.repo = cls.base / "repo"
        cls.repo.mkdir()
        cls.side = set()
        cls.git("init", "-q")
        cls.git("config", "user.name", "Authored fixture")
        cls.git("config", "user.email", "fixture@example.invalid")
        path = cls.repo / "src/packaging/module.py"
        path.parent.mkdir(parents=True)
        cls.frame = []
        previous = None
        for i in range(72):
            source = SOURCE
            if i == 2:
                source = SOURCE.replace("def f0(x=1)", "def f0(x=2)")
            if i == 4:
                source = SOURCE + "class C:\n    global f0\n    f0 = 1\n"
            if i == 6:
                source = "def broken(\n"
            if path.is_symlink():
                path.unlink()
            if i == 8:
                path.unlink()
            elif i == 9:
                path.symlink_to(SOURCE)
            else:
                path.write_text(source)
            cls.git("add", "-A")
            tree = cls.git("write-tree").decode().strip()
            parents = [] if previous is None else [previous]
            if i == 10:
                side = (
                    cls.git("commit-tree", tree, "-p", previous, "-m", "authored side metadata")
                    .decode()
                    .strip()
                )
                cls.side.add(side)
                parents.append(side)
            args = ["commit-tree", tree]
            for parent in parents:
                args += ["-p", parent]
            commit = cls.git(*args, "-m", f"authored position {i}").decode().strip()
            cls.frame.append(
                {"position": i, "commit": commit, "parents": parents, "committer_epoch": 0}
            )
            previous = commit
        cls.git("update-ref", "refs/heads/main", previous)
        cls.git("symbolic-ref", "HEAD", "refs/heads/main")
        cls.git("read-tree", previous)
        cls.make_inputs()
        cls.original_files = {p: p.read_bytes() for p in cls.inputs.rglob("*") if p.is_file()}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def git(cls, *args):
        return subprocess.check_output(
            ["git", "--no-replace-objects", "-C", str(cls.repo), *args], stderr=subprocess.DEVNULL
        )

    @classmethod
    def rel(cls, path):
        return str(path.relative_to(ROOT))

    @classmethod
    def make_inputs(cls):
        import hashlib

        def sha(raw):
            return hashlib.sha256(raw).hexdigest()

        ref = load_reference(ROOT / "scripts/structural_checker_v2.py")
        cls.groups = []
        metadata_groups = []
        cohort = []
        all_provs = {v: [] for v in support.VARIANTS}
        decisions = []
        review_groups = []
        for position in (0, 24, 48):
            parent = cls.frame[position]["commit"]
            gid = "packaging-derived-" + parent[:12]
            group = {
                "group_id": gid,
                "repo_id": "packaging",
                "repo_path": cls.rel(cls.repo),
                "parent_commit": parent,
                "child_commits": [r["commit"] for r in cls.frame[position + 1 : position + 24]],
                "source_roots": support.ROOTS,
                "claims_path": cls.rel(cls.inputs / (gid + "-claims.jsonl")),
            }
            cls.groups.append(group)
            previous = parent
            steps = []
            for number, row in enumerate(cls.frame[position + 1 : position + 24], 1):
                steps.append(
                    {
                        "step": number,
                        "commit": row["commit"],
                        "previous_commit": previous,
                        "parents": row["parents"],
                        "is_merge": len(row["parents"]) > 1,
                    }
                )
                previous = row["commit"]
            metadata_groups.append({**group, "parent_position": position, "steps": steps})
            oid = cls.git("rev-parse", parent + ":src/packaging/module.py").decode().strip()
            source_hash = sha(SOURCE.encode())
            packet = cls.inputs / "packets" / gid
            (packet / "source").mkdir(parents=True)
            cases = []
            private = []
            claims = []
            functions = sorted(
                ast.parse(SOURCE).body,
                key=lambda f: support.digest_rank(parent, "src/packaging/module.py", f.name),
            )
            for rank, fn in enumerate(functions):
                for kind in ("symbol_exists", "signature_equals"):
                    suffix = "exists" if kind == "symbol_exists" else "signature"
                    cid = f"{gid}-f{rank:02d}-{suffix}"
                    predicate = (
                        {"type": kind, "expected": True}
                        if kind == "symbol_exists"
                        else {
                            "type": kind,
                            "expected_signature": signature(fn).model_dump(mode="json"),
                        }
                    )
                    claim = {
                        "schema_version": 1,
                        "claim_id": cid,
                        "repo_id": "packaging",
                        "origin_commit": parent,
                        "kind": kind,
                        "text": "Exact authored derived syntactic claim.",
                        "scope": support.SCOPE_EXISTS
                        if kind == "symbol_exists"
                        else support.SCOPE_SIGNATURE,
                        "subject": {
                            "path": "src/packaging/module.py",
                            "qualname": fn.name,
                            "node_kind": "function",
                        },
                        "predicate": predicate,
                    }
                    claims.append(claim)
                    claim_hash = digest(claim)
                    ast_hash = sha(ast.dump(fn, include_attributes=False).encode())
                    cohort.append(
                        {
                            "schema_version": 1,
                            "origin_kind": "new_derived_parent_claim",
                            "original_candidate_id": None,
                            "group_id": gid,
                            "claim": claim,
                            "claim_sha256": claim_hash,
                            "parent_source_sha256": source_hash,
                            "parent_git_blob_object_id": oid,
                            "symbol_ast_sha256": ast_hash,
                            "rank_sha256": support.digest_rank(
                                parent, claim["subject"]["path"], fn.name
                            ),
                            "function_rank": rank,
                            "split": "development",
                        }
                    )
                    case_id = "case-" + cid
                    case = {
                        "id": case_id,
                        **{k: claim[k] for k in ("kind", "subject", "predicate", "text", "scope")},
                        "source_path": "source/" + source_hash + ".py",
                        "source_sha256": source_hash,
                    }
                    cases.append(case)
                    (packet / case["source_path"]).write_text(SOURCE)
                    private.append(
                        {
                            "id": case_id,
                            "group_id": gid,
                            "origin_class": "derived_parent_claim",
                            "derived_claim_id": cid,
                            "derived_claim_sha256": claim_hash,
                            "derived_claim": claim,
                            "source_sha256": source_hash,
                            "control_kind": None,
                            "expected_verdict": None,
                            "source_origin": {
                                "repo_id": "packaging",
                                "group_id": gid,
                                "parent_commit": parent,
                                "repository_path": claim["subject"]["path"],
                                "git_blob_object_id": oid,
                                "source_sha256": source_hash,
                                "split": "development",
                            },
                        }
                    )
                    decisions.append(
                        {
                            "group_id": gid,
                            "claim_id": cid,
                            "claim_sha256": claim_hash,
                            "parent_source_sha256": source_hash,
                            "reference_verdict": "supported",
                            "eligible": True,
                            "exclusion_reasons": [],
                        }
                    )
                    for variant in support.VARIANTS:
                        file_scope = variant == "file_anchor"
                        anchor = {
                            "scope": "file" if file_scope else "symbol",
                            "path": claim["subject"]["path"],
                            "qualname": None if file_scope else fn.name,
                            "observed_commit": parent,
                            "content_hash": source_hash if file_scope else ast_hash,
                            "origin": "static",
                        }
                        all_provs[variant].append(
                            {
                                "schema_version": 1,
                                "claim_id": cid,
                                "scenario_id": variant,
                                "anchors": [anchor],
                                "dependencies": [],
                                "known_incomplete": variant == "known_incomplete",
                                "unresolved_reasons": ["Research assumption incomplete"]
                                if variant == "known_incomplete"
                                else [],
                            }
                        )
            for number, kind in enumerate(
                (
                    "signature_mismatch",
                    "signature_mismatch",
                    "nonexistent_function",
                    "duplicate_function_uncertain",
                )
            ):
                base = claims[1] if kind == "signature_mismatch" else claims[0]
                case = deepcopy(next(c for c in cases if c["id"] == "case-" + base["claim_id"]))
                case["id"] = gid + "-control-" + str(number)
                raw = SOURCE
                if kind == "signature_mismatch":
                    case["predicate"]["expected_signature"]["parameters"][0]["name"] = (
                        "absent_parameter"
                    )
                elif kind == "nonexistent_function":
                    case["subject"]["qualname"] = "missing_subject"
                else:
                    name = case["subject"]["qualname"]
                    raw += f"def {name}(x=1):\n    return x\n"
                case["source_sha256"] = sha(raw.encode())
                case["source_path"] = "source/" + case["source_sha256"] + ".py"
                (packet / case["source_path"]).write_text(raw)
                cases.append(case)
                private.append(
                    {
                        "id": case["id"],
                        "group_id": gid,
                        "origin_class": "authored_control",
                        "control_kind": kind,
                        "derived_claim_id": base["claim_id"],
                        "derived_claim_sha256": digest(base),
                        "derived_claim": base,
                        "expected_verdict": "uncertain"
                        if kind == "duplicate_function_uncertain"
                        else "contradicted",
                        "source_sha256": case["source_sha256"],
                    }
                )
            write_jsonl(ROOT / group["claims_path"], claims)
            write_json(packet / "cases.json", cases)
            write_json(cls.inputs / (gid + "-map.json"), private)
            references = [ref.check_case(packet, case) for case in cases]
            write_json(
                cls.inputs / (gid + "-reference.json"),
                {
                    "decisions": references,
                    "packet_sha256": compute_packet_identity(packet),
                    "reference_sha256": support.REFERENCE_SHA,
                },
            )
            packet_sha = compute_packet_identity(packet)
            write_json(packet / "rubric.md", {"fixture": "Authored review rubric"})
            write_json(packet / "review.schema.json", {"fixture": "Existing AI review schema"})
            packet_manifest = cls.inputs / (gid + "-packet-manifest.json")
            write_json(
                packet_manifest,
                {
                    "schema_version": 1,
                    "packet_sha256": packet_sha,
                    "files": {cls.rel(p): file_hash(p) for p in packet.rglob("*") if p.is_file()},
                },
            )
            budget = cls.inputs / (gid + "-budget.json")
            write_json(
                budget,
                {
                    "encoding": "o200k_base",
                    "package_version": "0.12.0",
                    "estimated_tokens": 1000,
                    "input_limit": 64000,
                    "primary_response_estimate_limit": 8000,
                    "budget_role": "sealed research envelope estimate only; excludes uncontrolled harness/system/tool metadata; not actual model context or billing",
                },
            )
            ai = []
            for reviewer in range(2):
                path = cls.inputs / f"{gid}-review-{reviewer}.json"
                items = [
                    {
                        "id": case["id"],
                        "source_sha256": case["source_sha256"],
                        "verdict": answer["verdict"],
                        "extracted_facts": {"authored_fixture": True},
                        "evidence": [
                            {
                                "source_path": case["source_path"],
                                "available": True,
                                "line_start": 1,
                                "line_end": 1,
                            }
                        ],
                        "reasoning": "Authored fixture response.",
                        "scope_notes": "Exact syntax authored fixture.",
                    }
                    for case, answer in zip(cases, references, strict=True)
                ]
                write_json(
                    path,
                    {
                        "schema_version": 1,
                        "reviewer_kind": "ai_reviewer",
                        "human": False,
                        "provider": "authored-fixture",
                        "model": "authored-fixture",
                        "reasoning_effort": "fixture",
                        "agent_task": gid + f"-fixture-{reviewer}",
                        "packet_sha256": packet_sha,
                        "independence_disclosure": DISCLOSURE,
                        "identity_basis": "declared_invocation",
                        "items": items,
                    },
                )
                response = cls.inputs / f"{gid}-response-budget-{reviewer}.json"
                write_json(
                    response,
                    {
                        "review_sha256": file_hash(path),
                        "encoding": "o200k_base",
                        "package_version": "0.12.0",
                        "estimated_tokens": 1000,
                        "response_limit": 8000,
                        "status": "within_estimate_limit",
                    },
                )
                ai.append(
                    {
                        "path": cls.rel(path),
                        "sha256": file_hash(path),
                        "response_budget_path": cls.rel(response),
                        "response_budget_sha256": file_hash(response),
                    }
                )
            review_groups.append(
                {
                    "group_id": gid,
                    "packet_root": cls.rel(packet),
                    "public_cases_path": cls.rel(packet / "cases.json"),
                    "case_map_path": cls.rel(cls.inputs / (gid + "-map.json")),
                    "reference_answers_path": cls.rel(cls.inputs / (gid + "-reference.json")),
                    "packet_manifest_path": cls.rel(packet_manifest),
                    "packet_manifest_sha256": file_hash(packet_manifest),
                    "packet_sha256": packet_sha,
                    "token_budget_path": cls.rel(budget),
                    "token_budget_sha256": file_hash(budget),
                    "ai_reviews": ai,
                }
            )
        for variant, rows in all_provs.items():
            write_jsonl(cls.inputs / (variant + ".jsonl"), rows)
        write_json(cls.inputs / "cohort.json", cohort)
        write_jsonl(cls.inputs / "parent-decisions.jsonl", decisions)
        source_config = {
            "proposed_index_source_roots": support.ROOTS,
            "eligible_module_prefixes": ["src/packaging/", "packaging/"],
            "excluded_path_components": ["tests", "test", "_vendor", "vendor", "__pycache__"],
            "extensions": [".py"],
            "regular_modes": ["100644", "100755"],
            "max_file_bytes": 2 * 1024**2,
        }
        collection = {
            "protocol_id": "packaging-derived-development-collection-v2",
            "status": "sealed",
            "phase": "metadata_only",
            "repository_url": support.URL,
            "start_commit": cls.frame[0]["commit"],
            "boundary_commit": cls.frame[-1]["commit"],
            "source_configuration": source_config,
        }
        old = {
            **collection,
            "protocol_id": "packaging-derived-development-collection-v1",
            "selection": {"horizon": 24},
        }
        write_json(cls.inputs / "v1-protocol.json", old)
        write_json(
            cls.inputs / "v1-seal.json",
            {"protocol_sha256": file_hash(cls.inputs / "v1-protocol.json")},
        )
        write_json(
            cls.inputs / "v1-failure.json",
            {"status": "failed", "source_access": "commit metadata only; no trees/blobs/diffs"},
        )
        write_json(cls.inputs / "infeasible.json", {"authored_fixture": True, "frame_length": 72})
        (cls.inputs / "frame.txt").write_text("\n".join(r["commit"] for r in cls.frame) + "\n")
        amendment = {
            "schema_version": 1,
            "kind": "metadata_informed_pre_source_amendment",
            "observed_frame_length": 72,
            "original_horizon": 24,
            "new_horizon": 23,
            "original_plan_succeeded": False,
            "parent_positions": [0, 24, 48],
            "primary_candidate_observations_per_variant": 552,
            "prefix12_candidate_observations_per_variant": 288,
            "parent_sources_read_before_amendment": 0,
            "child_sources_read_before_amendment": 0,
            "AI_or_reference_decisions_before_amendment": 0,
        }
        for key, name in (
            ("prior_metadata_protocol", "v1-protocol.json"),
            ("prior_metadata_seal", "v1-seal.json"),
            ("prior_failure_manifest", "v1-failure.json"),
            ("infeasibility_report", "infeasible.json"),
            ("frame_binding", "frame.txt"),
        ):
            amendment[key] = {
                "path": cls.rel(cls.inputs / name),
                "sha256": file_hash(cls.inputs / name),
            }
        write_json(cls.inputs / "amendment.json", amendment)
        write_json(
            cls.inputs / "study-plan.json",
            {
                "amendment": amendment,
                "resource_budget": {
                    "raw_storage_ceiling_GiB": 2,
                    "local_analysis_cpu_ceiling_seconds": 1200,
                    "replay_wall_ceiling_minutes": 30,
                },
            },
        )
        collection.update(
            metadata_informed=True,
            original_plan_succeeded=False,
            study_plan_path=cls.rel(cls.inputs / "study-plan.json"),
            study_plan_sha256=file_hash(cls.inputs / "study-plan.json"),
            amendment_path=cls.rel(cls.inputs / "amendment.json"),
            amendment_sha256=file_hash(cls.inputs / "amendment.json"),
            frame_binding_path=cls.rel(cls.inputs / "frame.txt"),
            frame_binding_sha256=file_hash(cls.inputs / "frame.txt"),
        )
        write_json(cls.inputs / "collection-protocol.json", collection)
        metadata = {
            "schema_version": 1,
            "protocol_sha256": file_hash(cls.inputs / "collection-protocol.json"),
            "start_commit": cls.frame[0]["commit"],
            "boundary_commit": cls.frame[-1]["commit"],
            "frame_length": 72,
            "frame": cls.frame,
            "groups": metadata_groups,
            "child_source_access_authorized": False,
            "source_configuration": source_config,
        }
        write_json(cls.inputs / "topology.json", metadata)
        write_json(
            cls.inputs / "collection-manifest.json",
            {
                "status": "complete",
                "protocol_sha256": file_hash(cls.inputs / "collection-protocol.json"),
                "artifact_hashes": {"topology.json": file_hash(cls.inputs / "topology.json")},
            },
        )
        write_json(
            cls.inputs / "parent-generation.json",
            {
                "status": "prepared_awaiting_packet_seal_and_independent_review",
                "parent_only": True,
                "child_source_access": False,
                "reference_calls": 0,
                "AI_reviews": 0,
                "candidate_claims": 24,
                "selected_function_occurrences": 12,
                "public_cases": 36,
                "authored_controls": 12,
                "artifact_hashes": {"cohort.json": file_hash(cls.inputs / "cohort.json")},
            },
        )
        cls.protocol = {
            "schema_version": 1,
            "status": "sealed",
            "protocol_id": support.PROTOCOL_ID,
            "repo_id": "packaging",
            "repository_url": support.URL,
            "split": "development",
            "evaluation_eligible": False,
            "origin_kind": "new_derived_parent_claim",
            "production_protocol_version": "1.1",
            "primary_horizon": 23,
            "prefix_horizon": 12,
            "minimum_eligible_per_group": 4,
            "candidate_claims": 24,
            "disk_budget_bytes": 2 * 1024**3,
            "resource_budget": {
                "raw_storage_ceiling_GiB": 2,
                "local_analysis_cpu_ceiling_seconds": 1200,
                "replay_wall_ceiling_minutes": 30,
            },
            "candidate_observations_per_variant": 552,
            "prefix_observations_per_variant": 288,
            "root": str(ROOT),
            "seal_path": cls.rel(cls.inputs / "seal.json"),
            "start_commit": cls.frame[0]["commit"],
            "boundary_commit": cls.frame[-1]["commit"],
            "groups": cls.groups,
            "study_plan_path": cls.rel(cls.inputs / "study-plan.json"),
            "study_plan_sha256": file_hash(cls.inputs / "study-plan.json"),
            "amendment_path": cls.rel(cls.inputs / "amendment.json"),
            "amendment_sha256": file_hash(cls.inputs / "amendment.json"),
            "cohort_path": cls.rel(cls.inputs / "cohort.json"),
            "parent_generation_manifest_path": cls.rel(cls.inputs / "parent-generation.json"),
            "parent_decisions_path": cls.rel(cls.inputs / "parent-decisions.jsonl"),
            "metadata_manifest_path": cls.rel(cls.inputs / "topology.json"),
            "topology_protocol_path": cls.rel(cls.inputs / "collection-protocol.json"),
            "topology_collection_manifest_path": cls.rel(cls.inputs / "collection-manifest.json"),
            "review_groups": review_groups,
            "provenance": {v: cls.rel(cls.inputs / (v + ".jsonl")) for v in support.VARIANTS},
            "reference_path": "scripts/structural_checker_v2.py",
            "reference_sha256": support.REFERENCE_SHA,
            "test_path": cls.rel(STAGE / "test_packaging_replay.py"),
            "implementation_paths": [
                cls.rel(RUNTIME / n)
                for n in ("run_packaging_replay.py", "packaging_replay_support.py")
            ]
            + [cls.rel(Path(__file__).resolve())],
        }
        cls.protocol_path = cls.inputs / "protocol.json"
        write_json(cls.protocol_path, cls.protocol)

    def setUp(self):
        for p, raw in self.original_files.items():
            p.write_bytes(raw)
        self.p = deepcopy(self.protocol)
        self.seal()

    def seal(self):
        write_json(self.protocol_path, self.p)
        paths = list(self.inputs.rglob("*")) + list((ROOT / "src/cami").rglob("*.py"))
        paths += [ROOT / p for p in self.p["implementation_paths"]]
        paths += [
            ROOT / p
            for p in (
                "scripts/real_structural_replay_support.py",
                "scripts/validate_ai_review.py",
                "scripts/verify_cami.py",
                "scripts/structural_checker_v2.py",
                "pyproject.toml",
                ".python-version",
                "uv.lock",
            )
        ]
        write_json(
            ROOT / self.p["seal_path"],
            {
                "protocol_sha256": file_hash(self.protocol_path),
                "files": {
                    self.rel(p): file_hash(p)
                    for p in paths
                    if p.is_file() and p not in (self.protocol_path, ROOT / self.p["seal_path"])
                },
            },
        )

    def rebind_response(self, ref):
        path = ROOT / ref["response_budget_path"]
        value = read_json(path)
        value["review_sha256"] = ref["sha256"]
        write_json(path, value)
        ref["response_budget_sha256"] = file_hash(path)

    def execute(self, name):
        with patch.object(
            driver, "source_snapshot", side_effect=lambda _: source_snapshot(self.repo)
        ):
            return driver.execute(self.protocol_path, self.base / name)

    def deny(self, pattern="."):
        self.seal()
        with (
            patch.object(
                driver, "read_snapshot", side_effect=AssertionError("source touched")
            ) as production,
            patch.object(
                driver, "reference_claim", side_effect=AssertionError("reference touched")
            ) as reference,
        ):
            with self.assertRaisesRegex((ValueError, KeyError, OSError), pattern):
                self.execute(self._testMethodName)
        production.assert_not_called()
        reference.assert_not_called()
        self.assertEqual(
            read_json(self.base / self._testMethodName / "manifest.json")["status"], "failed"
        )

    def test_complete_replay_prefix_strata_costs_recovery_cache_and_no_side_reads(self):
        actual = driver.read_snapshot
        actual_reference = driver.reference_claim
        actual_advance = driver.advance_state
        advances = {}
        children = {c for g in self.groups for c in g["child_commits"]}
        allowed = {r["commit"] for r in self.frame}
        seen = []

        def snapshot(repo, commit):
            self.assertIn(commit, allowed)
            self.assertNotIn(commit, self.side)
            seen.append(commit)
            return actual(repo, commit)

        def advance(previous, selection, *args):
            advances[selection.commit] = advances.get(selection.commit, 0) + 1
            return actual_advance(previous, selection, *args)

        def reference(repo, commit, *args):
            self.assertNotIn(commit, self.side)
            if commit in children:
                self.assertEqual(advances.get(commit), 32)
            return actual_reference(repo, commit, *args)

        with (
            patch.object(driver, "read_snapshot", side_effect=snapshot),
            patch.object(driver, "reference_claim", side_effect=reference),
            patch.object(driver, "advance_state", side_effect=advance),
        ):
            self.execute("complete")
        out = self.base / "complete"
        rows = read_jsonl(out / "observations.jsonl")
        report = read_json(out / "report.json")
        self.assertEqual((len(rows), len(seen)), (2208, 72))
        self.assertEqual(seen[:3], [g["parent_commit"] for g in self.groups])
        for variant in support.VARIANTS:
            self.assertEqual(report["full23"]["variants"][variant]["candidate_observations"], 552)
            self.assertEqual(report["prefix12"]["variants"][variant]["candidate_observations"], 288)
        subject = next(
            r["claim"]["claim_id"]
            for r in read_json(self.inputs / "cohort.json")
            if r["group_id"] == self.groups[0]["group_id"]
            and r["claim"]["subject"]["qualname"] == "f0"
            and r["claim"]["kind"] == "signature_equals"
        )
        points = [r for r in rows if r["claim_id"] == subject and r["variant"] == "symbol_anchor"]
        self.assertEqual(points[1]["state"]["state"], "stale")
        self.assertTrue(points[2]["state"]["available"])
        self.assertEqual(points[3]["reference"]["verdict"], "uncertain")
        self.assertEqual(points[5]["validation"]["reason"], "parse_error")
        self.assertEqual(points[7]["validation"]["reason"], "subject_absent")
        self.assertEqual(points[8]["validation"]["reason"], "symlink_unsupported")
        self.assertTrue(points[9]["state"]["available"])
        costs = read_jsonl(out / "costs.jsonl")
        self.assertEqual(
            sum(
                c.get("actual_calls", 0)
                for c in costs
                if c["phase"] == "child_production_validation"
            ),
            sum(r["validation"] is not None for r in rows),
        )
        before = file_hash(out / "manifest.json")
        with self.assertRaises(Exception):
            self.execute("complete")
        self.assertEqual(before, file_hash(out / "manifest.json"))

    def test_wrong_scope_rejected(self):
        self.p["repo_id"] = "click"
        self.deny("scope")

    def test_v1_child_protocol_is_rejected(self):
        self.p["protocol_id"] = "packaging-derived-structural-first-parent-development-v1"
        self.deny("new-derived")

    def test_v1_metadata_protocol_is_rejected(self):
        path = self.inputs / "collection-protocol.json"
        value = read_json(path)
        value["protocol_id"] = "packaging-derived-development-collection-v1"
        write_json(path, value)
        metadata = read_json(self.inputs / "topology.json")
        metadata["protocol_sha256"] = file_hash(path)
        write_json(self.inputs / "topology.json", metadata)
        manifest = read_json(self.inputs / "collection-manifest.json")
        manifest["protocol_sha256"] = file_hash(path)
        manifest["artifact_hashes"]["topology.json"] = file_hash(self.inputs / "topology.json")
        write_json(self.inputs / "collection-manifest.json", manifest)
        self.deny("collection protocol")

    def test_generator_cannot_claim_independent_truth(self):
        path = self.inputs / "parent-generation.json"
        value = read_json(path)
        value["reference_calls"] = 1
        write_json(path, value)
        self.deny("reference-free")

    def rebind_method(self, amendment):
        path = self.inputs / "amendment.json"
        write_json(path, amendment)
        plan = read_json(self.inputs / "study-plan.json")
        plan["amendment"] = amendment
        write_json(self.inputs / "study-plan.json", plan)
        collection = read_json(self.inputs / "collection-protocol.json")
        collection["amendment_sha256"] = file_hash(path)
        collection["study_plan_sha256"] = file_hash(self.inputs / "study-plan.json")
        write_json(self.inputs / "collection-protocol.json", collection)
        metadata = read_json(self.inputs / "topology.json")
        metadata["protocol_sha256"] = file_hash(self.inputs / "collection-protocol.json")
        write_json(self.inputs / "topology.json", metadata)
        manifest = read_json(self.inputs / "collection-manifest.json")
        manifest["protocol_sha256"] = metadata["protocol_sha256"]
        manifest["artifact_hashes"]["topology.json"] = file_hash(self.inputs / "topology.json")
        write_json(self.inputs / "collection-manifest.json", manifest)
        self.p["amendment_sha256"] = collection["amendment_sha256"]
        self.p["study_plan_sha256"] = collection["study_plan_sha256"]

    def test_amendment_cannot_claim_source_blindness_after_exposure(self):
        amendment = read_json(self.inputs / "amendment.json")
        amendment["parent_sources_read_before_amendment"] = 1
        self.rebind_method(amendment)
        self.deny("pre-source amendment")

    def test_original_failure_cannot_be_relabelled_success(self):
        path = self.inputs / "v1-failure.json"
        value = read_json(path)
        value["status"] = "complete"
        write_json(path, value)
        amendment = read_json(self.inputs / "amendment.json")
        amendment["prior_failure_manifest"]["sha256"] = file_hash(path)
        self.rebind_method(amendment)
        self.deny("stay failed")

    def test_wrong_horizon_rejected(self):
        self.p["primary_horizon"] = 24
        self.deny("horizon")

    def test_original_630_origin_rejected(self):
        rows = read_json(self.inputs / "cohort.json")
        rows[0]["origin_kind"] = "authentic_parent_claim"
        write_json(self.inputs / "cohort.json", rows)
        self.deny("schema")

    def test_missing_review_input_rejected(self):
        self.p["review_groups"][0]["ai_reviews"].pop()
        self.deny("two fresh")

    def test_bad_ai_packet_binding_rejected(self):
        ref = self.p["review_groups"][0]["ai_reviews"][0]
        path = ROOT / ref["path"]
        raw = read_json(path)
        raw["packet_sha256"] = "0" * 64
        write_json(path, raw)
        ref["sha256"] = file_hash(path)
        self.rebind_response(ref)
        self.deny("packet identity")

    def test_bad_derived_case_join_rejected(self):
        path = ROOT / self.p["review_groups"][0]["case_map_path"]
        rows = read_json(path)
        rows[0]["derived_claim_id"] = rows[1]["derived_claim_id"]
        write_json(path, rows)
        self.deny("new-derived")

    def test_failed_control_rejected(self):
        ref = self.p["review_groups"][0]["ai_reviews"][0]
        path = ROOT / ref["path"]
        raw = read_json(path)
        raw["items"][-1]["verdict"] = "supported"
        write_json(path, raw)
        ref["sha256"] = file_hash(path)
        self.rebind_response(ref)
        self.deny("control gate")

    def test_sealed_decision_disagreement_rejected(self):
        rows = read_jsonl(self.inputs / "parent-decisions.jsonl")
        rows[0]["eligible"] = False
        write_jsonl(self.inputs / "parent-decisions.jsonl", rows)
        self.deny("decision disagrees")

    def test_global_late_parent_topology_denied_before_all_sources(self):
        path = self.inputs / "topology.json"
        raw = read_json(path)
        raw["frame"][-1]["parents"] = [self.frame[0]["commit"]]
        write_json(path, raw)
        manifest = read_json(self.inputs / "collection-manifest.json")
        manifest["artifact_hashes"]["topology.json"] = file_hash(path)
        write_json(self.inputs / "collection-manifest.json", manifest)
        self.deny("full.*parent")

    def exclude(self, group_number, count):
        entry = self.p["review_groups"][group_number]
        ids = [r["claim_id"] for r in read_jsonl(ROOT / self.groups[group_number]["claims_path"])][
            :count
        ]
        for ref in entry["ai_reviews"]:
            path = ROOT / ref["path"]
            raw = read_json(path)
            for item in raw["items"]:
                if item["id"] in {"case-" + cid for cid in ids}:
                    item["verdict"] = "uncertain"
            write_json(path, raw)
            ref["sha256"] = file_hash(path)
            self.rebind_response(ref)
        rows = read_jsonl(self.inputs / "parent-decisions.jsonl")
        for row in rows:
            if row["claim_id"] in ids:
                row["eligible"] = False
                row["exclusion_reasons"] = ["fresh_AI_not_both_supported"]
        write_jsonl(self.inputs / "parent-decisions.jsonl", rows)

    def test_final_group_below_minimum_excludes_before_any_source(self):
        self.exclude(2, 5)
        self.deny("fewerthan4")

    def test_four_exclusions_are_retained_without_replacement(self):
        self.exclude(2, 4)
        self.seal()
        self.execute("excluded-valid")
        report = read_json(self.base / "excluded-valid/report.json")
        parents = read_jsonl(self.base / "excluded-valid/parents.jsonl")
        self.assertEqual(sum(not p["eligible"] for p in parents), 4)
        for variant in support.VARIANTS:
            self.assertEqual(report["full23"]["variants"][variant]["candidate_observations"], 552)
            self.assertEqual(
                report["full23"]["variants"][variant]["excluded_parent_observations"], 92
            )
            self.assertEqual(
                report["prefix12"]["variants"][variant]["excluded_parent_observations"], 48
            )

    def test_71_position_frame_stops_without_source_or_replacement(self):
        path = self.inputs / "topology.json"
        raw = read_json(path)
        raw["frame"] = raw["frame"][:71]
        raw["frame_length"] = 71
        write_json(path, raw)
        manifest = read_json(self.inputs / "collection-manifest.json")
        manifest["artifact_hashes"]["topology.json"] = file_hash(path)
        write_json(self.inputs / "collection-manifest.json", manifest)
        self.deny("frame")

    def test_response_estimate_limit_rejects_before_any_source(self):
        ref = self.p["review_groups"][0]["ai_reviews"][0]
        path = ROOT / ref["response_budget_path"]
        raw = read_json(path)
        raw["estimated_tokens"] = 8001
        write_json(path, raw)
        ref["response_budget_sha256"] = file_hash(path)
        self.deny("response estimate")

    def test_packet_source_missing_denies_before_any_source(self):
        entry = self.p["review_groups"][0]
        cases = read_json(ROOT / entry["public_cases_path"])
        (ROOT / entry["packet_root"] / cases[0]["source_path"]).unlink()
        self.deny("packet|source|sealed")

    def test_prefix_is_nested_and_empty_strata_have_nulls(self):
        report = support.summarize_records([])
        self.assertIsNone(report["false_available_per_scored"])
        self.assertEqual(
            report["false_available_per_scored_null_reason"], "no_observations_in_stratum"
        )

    def test_dirty_workspace_rejected(self):
        with (
            patch.object(driver, "source_snapshot", return_value={"source_status": " M src/f.py"}),
            patch.object(driver, "read_snapshot", side_effect=AssertionError("source touched")),
        ):
            with self.assertRaisesRegex(ValueError, "clean"):
                driver.execute(self.protocol_path, self.base / self._testMethodName)

    def test_zero_merge_stratum_has_explicit_empty_nulls_for_every_group(self):
        report = support.report_stratum([], [(group, ()) for group in self.groups])
        for variant in support.VARIANTS:
            metric = report["variants"][variant]
            self.assertEqual(metric["candidate_observations"], 0)
            self.assertIsNone(metric["false_available_per_contradicted"])
            self.assertIsNone(metric["false_available_per_scored"])
            self.assertEqual(
                metric["false_available_per_scored_null_reason"], "no_observations_in_stratum"
            )
            for group in self.groups:
                self.assertEqual(
                    report["groups"][group["group_id"]][variant]["candidate_observations"], 0
                )

    def test_wall_ceiling_after_last_parent_preserves_partial_and_reads_no_child(self):
        clock = {"wall": 0.0}
        seen = []
        actual = driver.read_snapshot
        parents = [g["parent_commit"] for g in self.groups]

        def snapshot(repo, commit):
            self.assertIn(commit, parents)
            seen.append(commit)
            value = actual(repo, commit)
            if commit == parents[-1]:
                clock["wall"] = 1801.0
            return value

        with (
            patch.object(driver.time, "monotonic", side_effect=lambda: clock["wall"]),
            patch.object(driver, "total_cpu", return_value=0.0),
            patch.object(driver, "read_snapshot", side_effect=snapshot),
        ):
            with self.assertRaisesRegex(ValueError, "wall_seconds"):
                self.execute(self._testMethodName)
        out = self.base / self._testMethodName
        manifest = read_json(out / "manifest.json")
        self.assertEqual(seen, parents)
        self.assertEqual(manifest["status"], "failed")
        self.assertGreater(manifest["resource_usage"]["wall_seconds"], 1800)
        self.assertEqual(len(read_jsonl(out / "parents.jsonl")), 24)
        self.assertEqual(read_jsonl(out / "observations.jsonl"), [])

    def test_cpu_ceiling_preserves_parent_partial_and_reads_no_child(self):
        clock = {"cpu": 0.0}
        seen = []
        actual = driver.read_snapshot
        parent = self.groups[0]["parent_commit"]

        def snapshot(repo, commit):
            self.assertEqual(commit, parent)
            seen.append(commit)
            value = actual(repo, commit)
            clock["cpu"] = 1201.0
            return value

        with (
            patch.object(driver, "total_cpu", side_effect=lambda: clock["cpu"]),
            patch.object(driver, "read_snapshot", side_effect=snapshot),
        ):
            with self.assertRaisesRegex(ValueError, "cpu_seconds"):
                self.execute(self._testMethodName)
        out = self.base / self._testMethodName
        manifest = read_json(out / "manifest.json")
        self.assertEqual(seen, [parent])
        self.assertEqual(manifest["status"], "failed")
        self.assertGreater(manifest["resource_usage"]["cpu_seconds"], 1200)
        self.assertEqual(len(read_jsonl(out / "parents.jsonl")), 8)
        self.assertEqual(read_jsonl(out / "observations.jsonl"), [])

    def test_final_wall_guard_includes_artifact_hashing_and_retains_full_partial(self):
        clock = {"wall": 0.0}
        actual_hash = driver.file_hash
        out = (self.base / self._testMethodName).resolve()

        def file_hash_with_elapsed_time(path):
            value = actual_hash(path)
            if path.is_relative_to(out):
                clock["wall"] = 1801.0
            return value

        with (
            patch.object(driver.time, "monotonic", side_effect=lambda: clock["wall"]),
            patch.object(driver, "total_cpu", return_value=0.0),
            patch.object(driver, "file_hash", side_effect=file_hash_with_elapsed_time),
        ):
            with self.assertRaisesRegex(ValueError, "final.*wall_seconds"):
                self.execute(self._testMethodName)
        manifest = read_json(out / "manifest.json")
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(len(read_jsonl(out / "observations.jsonl")), 2208)
        self.assertGreater(manifest["resource_usage"]["wall_seconds"], 1800)
        self.assertTrue(any(p["phase"] == "final" for p in manifest["resource_checkpoints"]))

    def test_total_cpu_includes_completed_child_user_and_system(self):
        from types import SimpleNamespace

        with (
            patch.object(driver.time, "process_time", return_value=2.0),
            patch.object(
                driver.resource,
                "getrusage",
                return_value=SimpleNamespace(ru_utime=3.0, ru_stime=4.0),
            ),
        ):
            self.assertEqual(driver.total_cpu(), 9.0)

    def test_episode_and_ternary_metrics(self):
        base = {"eligible": True, "claim_id": "a", "commit": "x"}
        rows = [
            {**base, "trajectory": {"step": i}, "reference": {"verdict": v}}
            for i, v in enumerate(
                ["supported", "contradicted", "contradicted", "uncertain", "contradicted"], 1
            )
        ]
        result = support.episode_summary(rows)
        self.assertEqual(
            (
                result["unique_contradicted_claims"],
                result["repeated_contradicted_observations"],
                result["observed_contradiction_runs"],
            ),
            (1, 2, 2),
        )


if __name__ == "__main__":
    unittest.main()
