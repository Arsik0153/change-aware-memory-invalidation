"""Independent frozen-input, method and exact-claim AI binding checks."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from packaging_audit_common import canonical, git, parse, require, safe, sha, unique_index
from packaging_audit_syntax import reference

PROTOCOL_SHA = "aec4f1fd0b863bb875deb2e1808285a3359461ecd7e4403eced8cb23e235190e"
SEAL_SHA = "05257c4a0f4d5f950e4ded7fa33734733410001a89dd775b228dafb1bb42d971"
REFERENCE_SHA = "d8e6fc722e08e36b5576d6469ca6c4c6a932f4f9d085fba3600d21fb6bde0e1a"
VARIANTS = ("symbol_anchor", "file_anchor", "known_incomplete", "all_validate")


class Frozen:
    def __init__(self, root, manifest, authored=False):
        self.root, self.commit = root, manifest["source_before"]["git_head"]
        self.python_version = manifest["python"].split()[0]
        self.protocol, self.seal = manifest["protocol"], manifest["seal"]
        self.cache, self.historical, self.authored = {}, [], authored
        raw_protocol = canonical(self.protocol)
        require(
            self.protocol["protocol_id"]
            == "packaging-derived-structural-first-parent-development-v2"
            and self.protocol["status"] == "sealed"
            and self.protocol["evaluation_eligible"] is False
            and self.protocol["origin_kind"] == "new_derived_parent_claim"
            and self.protocol["split"] == "development",
            "final derived development scope",
        )
        protocol_path = Path(manifest["protocol_path"])
        if not protocol_path.is_relative_to(root):
            candidates = (
                git(root, "ls-tree", "-r", "--name-only", self.commit).decode().splitlines()
            )
            candidates = [
                name
                for name in candidates
                if name.endswith("protocol.json")
                and sha(git(root, "cat-file", "blob", self.commit + ":" + name))
                == manifest["protocol_sha256"]
            ]
            require(len(candidates) == 1, "historical protocol path identity")
            protocol_name = candidates[0]
        else:
            protocol_name = str(protocol_path.relative_to(root))
        self.protocol_name = protocol_name
        raw = git(root, "cat-file", "blob", self.commit + ":" + protocol_name)
        require(
            parse(raw) == self.protocol
            and sha(raw) == manifest["protocol_sha256"] == self.seal["protocol_sha256"],
            "historical final protocol binding",
        )
        seal_raw = git(root, "cat-file", "blob", self.commit + ":" + self.protocol["seal_path"])
        require(parse(seal_raw) == self.seal, "historical final seal binding")
        if not authored:
            require(
                sha(raw) == PROTOCOL_SHA and sha(seal_raw) == SEAL_SHA,
                "independent pinned real protocol/seal trust roots",
            )
        else:
            require(
                (root / "AUTHORED_FIXTURE_ONLY").read_text().strip() == "no real project data",
                "explicit authored fixture marker required",
            )
        require(sha(raw_protocol) == sha(canonical(parse(raw))), "canonical protocol equality")
        for name, expected in self.seal["files"].items():
            self.read(name)
            require(
                sha(git(root, "cat-file", "blob", self.commit + ":" + name)) == expected,
                "sealed input not in recorded historical HEAD: " + name,
            )
        source = manifest["source_before"]
        require(
            source == manifest["source_after"]
            and manifest["source_snapshots_match"] is True
            and source["source_status"] == "",
            "recorded source changed/dirty",
        )
        require(
            sha(
                __import__("json")
                .dumps(source["files"], sort_keys=True, ensure_ascii=True)
                .encode()
            )
            == source["sha256"],
            "source inventory digest",
        )
        names = set(
            git(root, "ls-tree", "-r", "-z", "--name-only", self.commit, "--", *source["scope"])
            .decode()
            .split("\0")
        ) - {""}
        require(names == set(source["files"]), "source historical exact file coverage")
        for name, expected in source["files"].items():
            require(
                expected is not None
                and sha(git(root, "cat-file", "blob", self.commit + ":" + name)) == expected,
                "historical source mismatch: " + name,
            )
        production = {
            name: expected
            for name, expected in source["files"].items()
            if name.startswith("src/cami/") and name.endswith(".py")
        }
        require(len(production) == 53, "actual production Python source inventory count differs")
        if not authored:
            for name, expected in production.items():
                require(
                    sha(git(root, "cat-file", "blob", "700ebf2:" + name)) == expected,
                    "production differs from 700ebf2: " + name,
                )
        require(
            self.seal["files"].get(self.protocol["reference_path"])
            == REFERENCE_SHA
            == self.protocol["reference_sha256"],
            "unchanged reference v2 identity",
        )
        self.source_count = len(names)

    def read(self, name):
        require(name in self.seal["files"], "unsealed input: " + name)
        expected = self.seal["files"][name]
        if name not in self.cache:
            path = safe(self.root, name)
            raw = path.read_bytes() if path.is_file() else b""
            if sha(raw) != expected:
                raw = git(self.root, "cat-file", "blob", self.commit + ":" + name)
                self.historical.append(name)
            require(sha(raw) == expected, "sealed input hash: " + name)
            self.cache[name] = raw
        return self.cache[name]

    def json(self, name):
        return parse(self.read(name))

    def rows(self, name):
        return [parse(x) for x in self.read(name).splitlines() if x.strip()]


def method(f):
    p = f.protocol
    require(
        (
            p["primary_horizon"],
            p["prefix_horizon"],
            p["minimum_eligible_per_group"],
            p["candidate_claims"],
            p["candidate_observations_per_variant"],
            p["prefix_observations_per_variant"],
        )
        == (23, 12, 4, 24, 552, 288),
        "registered numeric design",
    )
    plan, amendment = f.json(p["study_plan_path"]), f.json(p["amendment_path"])
    require(
        sha(f.read(p["study_plan_path"])) == p["study_plan_sha256"]
        and sha(f.read(p["amendment_path"])) == p["amendment_sha256"]
        and plan["amendment"] == amendment,
        "study/amendment binding",
    )
    require(
        amendment["kind"] == "metadata_informed_pre_source_amendment"
        and amendment["observed_frame_length"] == 72
        and amendment["original_horizon"] == 24
        and amendment["new_horizon"] == 23
        and amendment["original_plan_succeeded"] is False
        and amendment["parent_positions"] == [0, 24, 48]
        and all(
            amendment[k] == 0
            for k in (
                "parent_sources_read_before_amendment",
                "child_sources_read_before_amendment",
                "AI_or_reference_decisions_before_amendment",
            )
        ),
        "amendment honesty/numeric scope",
    )
    for key in (
        "prior_metadata_protocol",
        "prior_metadata_seal",
        "prior_failure_manifest",
        "infeasibility_report",
        "frame_binding",
    ):
        record = amendment[key]
        require(
            sha(f.read(record["path"])) == record["sha256"],
            "preserved v1/amendment artifact binding",
        )
    require(
        f.json(amendment["prior_failure_manifest"]["path"])["status"] == "failed",
        "v1 remains failed",
    )
    metadata = f.json(p["metadata_manifest_path"])
    ids = [row["commit"] for row in metadata["frame"]]
    require(
        f.read(amendment["frame_binding"]["path"]).decode().splitlines() == ids
        and len(ids) == len(set(ids)) == 72,
        "exact unchanged72 frame",
    )
    topology_protocol = f.json(p["topology_protocol_path"])
    collection = f.json(p["topology_collection_manifest_path"])
    require(
        topology_protocol["protocol_id"] == "packaging-derived-development-collection-v2"
        and topology_protocol["phase"] == "metadata_only"
        and topology_protocol["metadata_informed"] is True
        and topology_protocol["original_plan_succeeded"] is False
        and metadata["protocol_sha256"]
        == collection["protocol_sha256"]
        == sha(f.read(p["topology_protocol_path"]))
        and collection["status"] == "complete"
        and collection["artifact_hashes"]["topology.json"]
        == sha(f.read(p["metadata_manifest_path"])),
        "completed metadata protocol/topology binding",
    )
    for key in ("study_plan", "amendment"):
        require(
            topology_protocol[key + "_path"] == p[key + "_path"]
            and topology_protocol[key + "_sha256"] == p[key + "_sha256"],
            "method protocol cross-binding",
        )
    require(
        ids[0] == p["start_commit"] == metadata["start_commit"]
        and ids[-1] == p["boundary_commit"] == metadata["boundary_commit"]
        and metadata["frame_length"] == 72
        and metadata["child_source_access_authorized"] is False,
        "frozen metadata endpoints",
    )
    require(len(p["groups"]) == len(metadata["groups"]) == 3, "exact3 groups")
    expected = {}
    for group, frozen, position in zip(p["groups"], metadata["groups"], (0, 24, 48), strict=True):
        gid = group["group_id"]
        revisions = [group["parent_commit"], *group["child_commits"]]
        require(
            gid == "packaging-derived-" + revisions[0][:12]
            and revisions == ids[position : position + 24]
            and group["repo_id"] == "packaging"
            and group["source_roots"] == ["src", "packaging"]
            and frozen["parent_position"] == position
            and all(
                frozen[k] == group[k]
                for k in (
                    "group_id",
                    "parent_commit",
                    "child_commits",
                    "repo_id",
                    "repo_path",
                    "source_roots",
                )
            ),
            "exact group/window identity",
        )
        steps = {}
        for i, oid in enumerate(revisions[1:], 1):
            row = metadata["frame"][position + i]
            previous = revisions[i - 1]
            require(
                row["position"] == position + i
                and row["parents"]
                and row["parents"][0] == previous,
                "first-parent edge",
            )
            step = {
                "commit": oid,
                "previous_commit": previous,
                "parent_commits": row["parents"],
                "first_parent_commit": previous,
                "step": i,
                "is_merge": len(row["parents"]) > 1,
                "comparison_basis": "preceding_first_parent_tree",
            }
            steps[oid] = step
        require(
            frozen["steps"]
            == [
                {
                    "step": s["step"],
                    "commit": s["commit"],
                    "previous_commit": s["previous_commit"],
                    "parents": s["parent_commits"],
                    "is_merge": s["is_merge"],
                }
                for s in steps.values()
            ],
            "frozen full-parent steps",
        )
        expected[gid] = steps
    return metadata, expected


def check_ref(record, raw, case, checker):
    expected = reference(raw, case)
    for key in ("verdict", "facts", "evidence", "reason"):
        require(
            record.get(key) == expected[key],
            "independent reference " + key + " mismatch for " + case["id"],
        )
    require(
        record["source_sha256"] == record["declared_source_sha256"] == sha(raw),
        "reference source hash",
    )
    require(
        record["id"] == case["id"] and record["checker"] == checker,
        "phase3 exact reference item/checker identity",
    )


def reviews(f, cohort):
    p = f.protocol
    decisions = {}
    confirmations = {}
    agents = set()
    controls = 0
    declared = unique_index(
        f.rows(p["parent_decisions_path"]), lambda x: x["claim_id"], "declared parent decision"
    )
    require(set(declared) == set(cohort), "parent decision exact cohort coverage")
    require(
        len(p["review_groups"]) == 3
        and {r["group_id"] for r in p["review_groups"]} == {g["group_id"] for g in p["groups"]},
        "exact review group coverage",
    )
    for group in p["review_groups"]:
        gid = group["group_id"]
        packet = group["packet_root"].rstrip("/")
        cases_raw = f.read(group["public_cases_path"])
        cases = unique_index(parse(cases_raw), lambda x: x["id"], "public case")
        private = unique_index(f.json(group["case_map_path"]), lambda x: x["id"], "private case")
        require(len(cases) == 12 and set(cases) == set(private), "exact12 public/private cases")
        sources = {}
        for case in cases.values():
            source = f.read(packet + "/" + case["source_path"])
            require(sha(source) == case["source_sha256"], "public source bytes/hash")
            sources[case["source_path"]] = case["source_sha256"]
        identity = sha(
            canonical(
                {
                    "cases_sha256": sha(cases_raw),
                    "sources": [
                        {"source_path": path, "source_sha256": sources[path]}
                        for path in sorted(sources)
                    ],
                }
            )
        )
        inventory = f.json(group["packet_manifest_path"])
        require(
            sha(f.read(group["packet_manifest_path"])) == group["packet_manifest_sha256"]
            and identity == group["packet_sha256"] == inventory["packet_sha256"],
            "packet identity binding",
        )
        for name, expected in inventory["files"].items():
            require(sha(f.read(name)) == expected, "packet inventory byte hash")
        require(
            set(inventory["files"])
            == {name for name in f.seal["files"] if name.startswith(packet + "/")},
            "complete public packet inventory",
        )
        require(
            not group["case_map_path"].startswith(packet + "/")
            and not group["reference_answers_path"].startswith(packet + "/"),
            "private maps/answers stay outside packet",
        )
        answers = f.json(group["reference_answers_path"])
        require(
            answers["packet_sha256"] == identity and answers["reference_sha256"] == REFERENCE_SHA,
            "reference packet/version",
        )
        refs = unique_index(answers["decisions"], lambda x: x["id"], "parent reference item")
        require(set(refs) == set(cases), "reference case coverage")
        ai = []
        require(len(group["ai_reviews"]) == 2, "exacttwo fresh AI reviews")
        input_budget = f.json(group["token_budget_path"])
        require(
            sha(f.read(group["token_budget_path"])) == group["token_budget_sha256"]
            and input_budget["encoding"] == "o200k_base"
            and input_budget["package_version"] == "0.12.0"
            and type(input_budget["estimated_tokens"]) is int
            and 0 <= input_budget["estimated_tokens"] <= 64000
            and input_budget["input_limit"] == 64000
            and input_budget["primary_response_estimate_limit"] == 8000,
            "named input token estimate scope/cap",
        )
        for entry in group["ai_reviews"]:
            raw = f.read(entry["path"])
            reviewer = parse(raw)
            require(
                sha(raw) == entry["sha256"]
                and reviewer["reviewer_kind"] == "ai_reviewer"
                and reviewer["human"] is False
                and reviewer["packet_sha256"] == identity
                and reviewer["identity_basis"] == "declared_invocation"
                and reviewer["independence_disclosure"]
                == "Model weights and training independence are unverified.",
                "fresh AI identity/packet declaration",
            )
            agent = reviewer["agent_task"]
            require(
                isinstance(agent, str) and agent and agent not in agents,
                "sixdistinct declared agent contexts",
            )
            agents.add(agent)
            require(
                all(
                    isinstance(reviewer[k], str) and reviewer[k].strip()
                    for k in ("provider", "model", "reasoning_effort")
                ),
                "AI provenance strings",
            )
            items = unique_index(reviewer["items"], lambda x: x["id"], "AI response item")
            require(set(items) == set(cases), "AI response full coverage")
            response = f.json(entry["response_budget_path"])
            require(
                sha(f.read(entry["response_budget_path"])) == entry["response_budget_sha256"]
                and response["review_sha256"] == sha(raw)
                and response["encoding"] == "o200k_base"
                and response["package_version"] == "0.12.0"
                and type(response["estimated_tokens"]) is int
                and 0 <= response["estimated_tokens"] <= 8000
                and response["response_limit"] == 8000
                and response["status"] == "within_estimate_limit",
                "complete response estimate binding/cap",
            )
            for cid, item in items.items():
                case = cases[cid]
                source = f.read(packet + "/" + case["source_path"])
                require(
                    item["source_sha256"] == case["source_sha256"]
                    and item["verdict"] in {"supported", "contradicted", "uncertain"}
                    and item["reasoning"].strip()
                    and item["scope_notes"].strip()
                    and item["extracted_facts"],
                    "AI item source/verdict/evidence metadata",
                )
                require(
                    item["verdict"] == "uncertain" or item["evidence"],
                    "positive AI verdict evidence required",
                )
                for ev in item["evidence"]:
                    require(
                        ev["source_path"] == case["source_path"] and type(ev["available"]) is bool,
                        "AI evidence source/availability",
                    )
                    if ev["available"]:
                        require(
                            type(ev["line_start"]) is int
                            and type(ev["line_end"]) is int
                            and 1
                            <= ev["line_start"]
                            <= ev["line_end"]
                            <= len(source.decode().splitlines()),
                            "AI evidence line bounds",
                        )
                    else:
                        require(
                            item["verdict"] == "uncertain" and ev["explanation"].strip(),
                            "unavailable evidence only uncertain",
                        )
            ai.append(items)
        control_kinds = Counter()
        for cid, case in cases.items():
            mapped = private[cid]
            source = f.read(packet + "/" + case["source_path"])
            check_ref(refs[cid], source, case, checker_metadata(f, f.python_version))
            require(
                mapped["group_id"] == gid and mapped["source_sha256"] == case["source_sha256"],
                "private/public source/group",
            )
            base = cohort.get(mapped["derived_claim_id"])
            require(
                base is not None
                and base["group_id"] == gid
                and mapped["derived_claim"] == base["claim"]
                and mapped["derived_claim_sha256"] == base["claim_sha256"],
                "exact derived full claim binding",
            )
            if mapped["origin_class"] == "authored_control":
                kind = mapped["control_kind"]
                control_kinds[kind] += 1
                controls += 1
                expected = "uncertain" if kind == "duplicate_function_uncertain" else "contradicted"
                require(
                    mapped["expected_verdict"] == expected
                    and refs[cid]["verdict"] == expected
                    and all(x[cid]["verdict"] == expected for x in ai),
                    "authored control gate",
                )
            else:
                require(
                    mapped["origin_class"] == "derived_parent_claim"
                    and mapped["control_kind"] is None
                    and mapped["expected_verdict"] is None,
                    "real derived origin",
                )
                claim = base["claim"]
                require(
                    all(
                        case[k] == claim[k]
                        for k in ("kind", "subject", "predicate", "text", "scope")
                    )
                    and case["source_sha256"] == base["parent_source_sha256"],
                    "exact public claim/source binding",
                )
                origin = mapped["source_origin"]
                require(
                    origin["group_id"] == gid
                    and origin["repo_id"] == "packaging"
                    and origin["parent_commit"] == claim["origin_commit"]
                    and origin["repository_path"] == claim["subject"]["path"]
                    and origin["git_blob_object_id"] == base["parent_git_blob_object_id"]
                    and origin["source_sha256"] == base["parent_source_sha256"]
                    and origin["split"] == "development",
                    "exact parent origin binding",
                )
                claim_id = claim["claim_id"]
                require(claim_id not in decisions, "one real case per derived claim")
                reasons = []
                if refs[cid]["verdict"] != "supported":
                    reasons.append("parent_reference_" + refs[cid]["verdict"])
                if any(x[cid]["verdict"] != "supported" for x in ai):
                    reasons.append("fresh_AI_not_both_supported")
                decision = {
                    "group_id": gid,
                    "claim_id": claim_id,
                    "claim_sha256": base["claim_sha256"],
                    "parent_source_sha256": base["parent_source_sha256"],
                    "reference_verdict": refs[cid]["verdict"],
                    "eligible": not reasons,
                    "exclusion_reasons": reasons,
                }
                require(
                    declared[claim_id] == decision,
                    "parent decision differs from bound reference/two AI",
                )
                decisions[claim_id] = decision
                confirmations[claim_id] = {
                    "reviewer_kind": "two_fresh_AI",
                    "eligible": not reasons,
                    "case_id": cid,
                    "reviews": group["ai_reviews"],
                    "reference": refs[cid],
                }
        require(
            control_kinds
            == {
                "signature_mismatch": 2,
                "nonexistent_function": 1,
                "duplicate_function_uncertain": 1,
            },
            "balanced4 controls/group",
        )
        require(
            sum(row["eligible"] for row in decisions.values() if row["group_id"] == gid) >= 4,
            "global parent eligibility threshold",
        )
    require(
        set(decisions) == set(cohort) and len(agents) == 6 and controls == 12,
        "global cohort/reviewer/control coverage",
    )
    return decisions, confirmations


def checker_metadata(f, python_version):
    constants = {}
    for st in ast.parse(f.read(f.protocol["reference_path"])).body:
        if (
            isinstance(st, ast.Assign)
            and len(st.targets) == 1
            and isinstance(st.targets[0], ast.Name)
            and st.targets[0].id in {"IDENTITY", "VERSION", "LIMITATION"}
        ):
            constants[st.targets[0].id] = ast.literal_eval(st.value)
    return {
        "identity": constants["IDENTITY"],
        "version": constants["VERSION"],
        "python": python_version,
        "shared_primitive_limitation": constants["LIMITATION"],
    }
