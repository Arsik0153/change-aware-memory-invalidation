"""Strict new-derived Packaging cohort, review, topology and reporting boundaries."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import sys

from cami.artifacts import canonical, digest, file_hash, read_json, read_jsonl, within
from cami.models import Claim, Provenance
from cami.repository import git, resolve
from scripts.real_structural_replay_support import VARIANTS, summarize
from scripts.validate_ai_review import audit_review, compute_packet_identity

PROTOCOL_ID = "packaging-derived-structural-first-parent-development-v2"
URL = "https://github.com/pypa/packaging.git"
ROOTS = ["src", "packaging"]
REFERENCE_SHA = "d8e6fc722e08e36b5576d6469ca6c4c6a932f4f9d085fba3600d21fb6bde0e1a"
COHORT_FIELDS = {
    "schema_version",
    "origin_kind",
    "original_candidate_id",
    "group_id",
    "claim",
    "claim_sha256",
    "parent_source_sha256",
    "parent_git_blob_object_id",
    "symbol_ast_sha256",
    "rank_sha256",
    "function_rank",
    "split",
}
SCOPE_EXISTS = "Exact syntactic definition identity only."
SCOPE_SIGNATURE = (
    "Exact normalized syntax, including defaults, annotations, decorators, and async status."
)
CONTROL_COUNTS = {
    "signature_mismatch": 2,
    "nonexistent_function": 1,
    "duplicate_function_uncertain": 1,
}


def check(condition, message):
    if not condition:
        raise ValueError(message)


def unique(rows, key, label):
    result = {}
    for row in rows:
        identity = key(row)
        check(identity not in result, "duplicate " + label)
        result[identity] = row
    return result


def oid(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def allowed_path(path):
    return (
        path.endswith(".py")
        and path.startswith(("src/packaging/", "packaging/"))
        and not set(Path(path).parts) & {"tests", "test", "_vendor", "vendor", "__pycache__"}
    )


def load_inputs(protocol_path):
    check(
        sys.implementation.name == "cpython" and sys.version_info[:2] == (3, 12),
        "requires CPython3.12 syntax context",
    )
    p = read_json(protocol_path)
    check(
        p.get("schema_version") == 1
        and p.get("status") == "sealed"
        and p.get("protocol_id") == PROTOCOL_ID,
        "requires sealed new-derived Packaging protocol",
    )
    check(
        p.get("repo_id") == "packaging"
        and p.get("repository_url") == URL
        and p.get("split") == "development"
        and p.get("evaluation_eligible") is False
        and p.get("origin_kind") == "new_derived_parent_claim"
        and p.get("production_protocol_version") == "1.1",
        "invalid derived development scope",
    )
    check(
        (p.get("primary_horizon"), p.get("prefix_horizon"), p.get("minimum_eligible_per_group"))
        == (23, 12, 4),
        "fixed horizons and parent feasibility threshold required",
    )
    check(p.get("disk_budget_bytes") == 2 * 1024**3, "fixed2GiB disk cap required")
    check(
        p["resource_budget"]["raw_storage_ceiling_GiB"] == 2
        and p["resource_budget"]["local_analysis_cpu_ceiling_seconds"] == 1200
        and p["resource_budget"]["replay_wall_ceiling_minutes"] == 30,
        "fixed observed CPU/wall/storage ceilings required",
    )
    check(
        p.get("candidate_claims") == 24
        and p.get("candidate_observations_per_variant") == 552
        and p.get("prefix_observations_per_variant") == 288,
        "fixed derived denominators required",
    )
    root = (protocol_path.parent / p["root"]).resolve(strict=True)
    seal = read_json(within(root, p["seal_path"]))
    check(seal["protocol_sha256"] == file_hash(protocol_path), "protocol seal mismatch")
    for name, expected in seal["files"].items():
        check(file_hash(within(root, name)) == expected, "sealed file mismatch: " + name)

    def required(name):
        path = within(root, name)
        check(str(path.relative_to(root)) in seal["files"], "unsealed input: " + name)
        return path

    required(str(Path(__file__).resolve().relative_to(root)))
    for path in (root / "src/cami").rglob("*.py"):
        required(str(path.relative_to(root)))
    for name in p["implementation_paths"]:
        required(name)
    for name in (
        "scripts/real_structural_replay_support.py",
        "scripts/validate_ai_review.py",
        "scripts/verify_cami.py",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
    ):
        required(name)
    check(
        Path(p["test_path"]).name == "test_packaging_replay.py"
        and p["test_path"] in p["implementation_paths"],
        "focused authored tests must be explicitly sealed",
    )
    required(p["test_path"])
    reference = required(p["reference_path"])
    check(
        file_hash(reference) == REFERENCE_SHA == p["reference_sha256"],
        "reference v2 must remain unchanged",
    )
    cohort_rows = read_json(required(p["cohort_path"]))
    cohort = unique(cohort_rows, lambda r: r["claim"]["claim_id"], "derived cohort claim")
    check(len(cohort) == 24, "exactly24 derived claims required")
    for row in cohort_rows:
        check(
            set(row) == COHORT_FIELDS
            and row["schema_version"] == 1
            and row["origin_kind"] == "new_derived_parent_claim"
            and row["original_candidate_id"] is None
            and row["split"] == "development",
            "invalid new-derived cohort schema",
        )
        check(
            digest(row["claim"]) == row["claim_sha256"]
            and type(row["function_rank"]) is int
            and row["function_rank"] in range(4),
            "derived claim/rank binding",
        )
    groups = []
    for group in p["groups"]:
        check(
            group["repo_id"] == "packaging" and group["source_roots"] == ROOTS,
            "frozen Packaging roots/repo required",
        )
        parent = group["parent_commit"]
        check(
            oid(parent) and group["group_id"] == "packaging-derived-" + parent[:12],
            "derived group identity",
        )
        revisions = [parent, *group["child_commits"]]
        check(
            len(revisions) == len(set(revisions)) == 24 and all(map(oid, revisions)),
            "exact23 distinct successor IDs required",
        )
        claims = tuple(
            Claim.model_validate_json(canonical(r))
            for r in read_jsonl(required(group["claims_path"]))
        )
        check(
            len(claims) == 8 and len({c.claim_id for c in claims}) == 8,
            "exactly8 derived claims per group",
        )
        ranks = {}
        for claim in claims:
            check(claim.claim_id in cohort, "unknown group claim")
            row = cohort[claim.claim_id]
            suffix = "exists" if claim.kind == "symbol_exists" else "signature"
            check(
                row["group_id"] == group["group_id"]
                and row["claim"] == claim.model_dump(mode="json")
                and claim.repo_id == "packaging"
                and claim.origin_commit == parent
                and claim.kind in {"symbol_exists", "signature_equals"}
                and claim.claim_id == f"{group['group_id']}-f{row['function_rank']:02d}-{suffix}"
                and claim.subject.node_kind == "function"
                and claim.subject.qualname.isidentifier()
                and allowed_path(claim.subject.path)
                and claim.scope
                == (SCOPE_EXISTS if claim.kind == "symbol_exists" else SCOPE_SIGNATURE),
                "derived claim identity/scope mismatch",
            )
            key = claim.subject.path, claim.subject.qualname
            ranks.setdefault(row["function_rank"], []).append((claim.kind, key, row["rank_sha256"]))
        check(
            set(ranks) == set(range(4))
            and all(
                len(v) == 2
                and {x[0] for x in v} == {"symbol_exists", "signature_equals"}
                and v[0][1:] == v[1][1:]
                for v in ranks.values()
            )
            and len({v[0][1] for v in ranks.values()}) == 4,
            "four paired distinct ranked subjects required",
        )
        for rank, pairs in ranks.items():
            path, name = pairs[0][1]
            expected = digest_rank(parent, path, name)
            check(pairs[0][2] == expected, "function rank digest mismatch")
        check(
            [ranks[r][0][2] for r in range(4)] == sorted(ranks[r][0][2] for r in range(4)),
            "rank order mismatch",
        )
        groups.append((group, claims))
    check(
        len(groups) == 3
        and len({g["group_id"] for g, _ in groups}) == 3
        and {c.claim_id for _, cs in groups for c in cs} == set(cohort),
        "exact3 group cohort coverage",
    )
    provenance = {}
    check(set(p["provenance"]) == set(VARIANTS), "exact four provenance variants required")
    for variant, name in p["provenance"].items():
        rows = read_jsonl(required(name))
        check(len(rows) == 24, "provenance coverage")
        provs = unique(
            [Provenance.model_validate_json(canonical(r)) for r in rows],
            lambda r: r.claim_id,
            "provenance",
        )
        check(set(provs) == set(cohort), "provenance claim coverage")
        for cid, prov in provs.items():
            row = cohort[cid]
            claim = row["claim"]
            scope = "file" if variant == "file_anchor" else "symbol"
            check(
                not prov.dependencies
                and len(prov.anchors) == 1
                and prov.known_incomplete == (variant == "known_incomplete")
                and bool(prov.unresolved_reasons) == (variant == "known_incomplete"),
                "provenance completeness assumptions",
            )
            a = prov.anchors[0]
            check(
                a.scope == scope
                and a.path == claim["subject"]["path"]
                and a.observed_commit == claim["origin_commit"]
                and a.qualname == (None if scope == "file" else claim["subject"]["qualname"])
                and a.content_hash
                == row["parent_source_sha256" if scope == "file" else "symbol_ast_sha256"],
                "provenance anchor identity",
            )
        provenance[variant] = provs
    generation_path = required(p["parent_generation_manifest_path"])
    generation = read_json(generation_path)
    check(
        generation["status"] == "prepared_awaiting_packet_seal_and_independent_review"
        and generation["parent_only"] is True
        and generation["child_source_access"] is False
        and generation["reference_calls"] == generation["AI_reviews"] == 0
        and generation["candidate_claims"] == 24
        and generation["selected_function_occurrences"] == 12
        and generation["public_cases"] == 36
        and generation["authored_controls"] == 12,
        "reference-free parent generation boundary",
    )
    for name, expected in generation["artifact_hashes"].items():
        generated = within(generation_path.parent, name)
        check(
            file_hash(required(str(generated.relative_to(root)))) == expected,
            "parent generation artifact changed after collection",
        )
    reviews, decisions = review_inputs(p, required, cohort, groups)
    metadata = read_json(required(p["metadata_manifest_path"]))
    collection_protocol = required(p["topology_protocol_path"])
    collection = read_json(collection_protocol)
    collection_manifest = read_json(required(p["topology_collection_manifest_path"]))
    check(
        collection_manifest["status"] == "complete"
        and metadata["protocol_sha256"] == file_hash(collection_protocol)
        and collection_manifest["protocol_sha256"] == file_hash(collection_protocol)
        and collection_manifest["artifact_hashes"]["topology.json"]
        == file_hash(required(p["metadata_manifest_path"])),
        "completed metadata-only collection binding",
    )
    check(
        collection["protocol_id"] == "packaging-derived-development-collection-v2"
        and collection["status"] == "sealed"
        and collection["phase"] == "metadata_only"
        and collection["repository_url"] == URL
        and collection["start_commit"] == p["start_commit"]
        and collection["boundary_commit"] == p["boundary_commit"]
        and collection["source_configuration"]["proposed_index_source_roots"] == ROOTS,
        "frozen collection protocol identity",
    )
    method_inputs(p, required, collection, metadata)
    return p, root, seal, groups, cohort, reviews, provenance, reference, metadata, decisions


def method_inputs(p, required, collection, metadata):
    plan_path = required(p["study_plan_path"])
    amendment_path = required(p["amendment_path"])
    plan, amendment = read_json(plan_path), read_json(amendment_path)
    check(
        all(
            p["resource_budget"][k] == plan["resource_budget"][k]
            for k in (
                "raw_storage_ceiling_GiB",
                "local_analysis_cpu_ceiling_seconds",
                "replay_wall_ceiling_minutes",
            )
        ),
        "replay resource ceilings must match sealed study plan",
    )
    check(
        file_hash(plan_path) == p["study_plan_sha256"] == collection["study_plan_sha256"]
        and p["study_plan_path"] == collection["study_plan_path"]
        and file_hash(amendment_path) == p["amendment_sha256"] == collection["amendment_sha256"]
        and p["amendment_path"] == collection["amendment_path"]
        and plan["amendment"] == amendment,
        "v2 method/amendment binding",
    )
    check(
        amendment["schema_version"] == 1
        and amendment["kind"] == "metadata_informed_pre_source_amendment"
        and amendment["observed_frame_length"] == 72
        and amendment["original_horizon"] == 24
        and amendment["new_horizon"] == 23
        and amendment["original_plan_succeeded"] is False
        and amendment["parent_positions"] == [0, 24, 48]
        and amendment["primary_candidate_observations_per_variant"] == 552
        and amendment["prefix12_candidate_observations_per_variant"] == 288
        and all(
            amendment[k] == 0
            for k in (
                "parent_sources_read_before_amendment",
                "child_sources_read_before_amendment",
                "AI_or_reference_decisions_before_amendment",
            )
        )
        and collection["metadata_informed"] is True
        and collection["original_plan_succeeded"] is False,
        "explicit metadata-informed pre-source amendment required",
    )
    bound = {}
    for key in (
        "prior_metadata_protocol",
        "prior_metadata_seal",
        "prior_failure_manifest",
        "infeasibility_report",
        "frame_binding",
    ):
        record = amendment[key]
        path = required(record["path"])
        check(file_hash(path) == record["sha256"], "preserved v1/amendment input changed")
        bound[key] = path
    prior = read_json(bound["prior_metadata_protocol"])
    check(
        prior["protocol_id"] == "packaging-derived-development-collection-v1"
        and prior["selection"]["horizon"] == 24
        and prior["repository_url"] == p["repository_url"]
        and prior["start_commit"] == p["start_commit"]
        and prior["boundary_commit"] == p["boundary_commit"]
        and prior["source_configuration"] == collection["source_configuration"]
        and read_json(bound["prior_metadata_seal"])["protocol_sha256"]
        == file_hash(bound["prior_metadata_protocol"]),
        "original failed24 protocol must remain bound and unchanged in scope",
    )
    failure = read_json(bound["prior_failure_manifest"])
    check(
        failure["status"] == "failed" and "no trees/blobs/diffs" in failure["source_access"],
        "v1 metadata failure must stay failed",
    )
    frame = bound["frame_binding"].read_text().splitlines()
    check(
        len(frame) == 72
        and frame == [r["commit"] for r in metadata["frame"]]
        and collection["frame_binding_path"] == amendment["frame_binding"]["path"]
        and collection["frame_binding_sha256"] == amendment["frame_binding"]["sha256"],
        "unchanged72-position frame binding",
    )


def digest_rank(parent, path, name):
    import hashlib

    return hashlib.sha256(
        (
            "20261104-packaging-derived-development-v1\n" + parent + "\n" + path + "\n" + name
        ).encode()
    ).hexdigest()


def review_inputs(p, required, cohort, groups):
    review_groups = unique(p["review_groups"], lambda r: r["group_id"], "review group")
    check(
        set(review_groups) == {g["group_id"] for g, _ in groups}, "all fresh review groups required"
    )
    decisions_rows = read_jsonl(required(p["parent_decisions_path"]))
    decisions = unique(decisions_rows, lambda r: r["claim_id"], "parent decision")
    check(
        len(decisions_rows) == 24 and set(decisions) == set(cohort),
        "sealed parent decision coverage",
    )
    confirmations = {}
    all_agents = set()
    for group, claims in groups:
        gid = group["group_id"]
        entry = review_groups[gid]
        public_path = required(entry["public_cases_path"])
        check(
            public_path.name == "cases.json"
            and entry["public_cases_path"] == entry["packet_root"].rstrip("/") + "/cases.json",
            "packet root/cases identity",
        )
        packet_root = public_path.parent
        manifest_path = required(entry["packet_manifest_path"])
        packet_manifest = read_json(manifest_path)
        check(
            file_hash(manifest_path) == entry["packet_manifest_sha256"]
            and packet_manifest["packet_sha256"]
            == entry["packet_sha256"]
            == compute_packet_identity(packet_root),
            "bound public packet identity",
        )
        for name, expected in packet_manifest["files"].items():
            check(file_hash(required(name)) == expected, "public packet inventory mismatch")
        check(
            entry["public_cases_path"] in packet_manifest["files"],
            "packet must inventory its cases",
        )
        public_inventory = {
            entry["packet_root"].rstrip("/") + "/" + str(path.relative_to(packet_root))
            for path in packet_root.rglob("*")
            if path.is_file()
        }
        check(
            set(packet_manifest["files"]) == public_inventory
            and entry["packet_root"].rstrip("/") + "/rubric.md" in public_inventory
            and entry["packet_root"].rstrip("/") + "/review.schema.json" in public_inventory,
            "complete sealed public packet inventory required",
        )
        check(
            not required(entry["case_map_path"]).is_relative_to(packet_root)
            and not required(entry["reference_answers_path"]).is_relative_to(packet_root),
            "private answer artifacts must stay outside public packet",
        )
        budget_path = required(entry["token_budget_path"])
        check(
            file_hash(budget_path) == entry["token_budget_sha256"],
            "input token estimate artifact binding",
        )
        budget = read_json(budget_path)
        check(
            budget["encoding"] == "o200k_base"
            and budget["package_version"] == "0.12.0"
            and type(budget["estimated_tokens"]) is int
            and 0 <= budget["estimated_tokens"] <= 64000
            and budget["input_limit"] == 64000
            and budget["primary_response_estimate_limit"] == 8000
            and budget["budget_role"]
            == "sealed research envelope estimate only; excludes uncontrolled harness/system/tool metadata; not actual model context or billing",
            "research envelope estimate cap/scope",
        )
        public = unique(read_json(public_path), lambda r: r["id"], "public case")
        private = unique(
            read_json(required(entry["case_map_path"])), lambda r: r["id"], "private case"
        )
        check(
            set(public) == set(private) and len(public) == 12,
            "exact8 real plus4 control cases required",
        )
        reference_answers = read_json(required(entry["reference_answers_path"]))
        check(
            reference_answers["packet_sha256"] == entry["packet_sha256"]
            and reference_answers["reference_sha256"] == REFERENCE_SHA,
            "reference packet/version binding",
        )
        references = unique(reference_answers["decisions"], lambda r: r["id"], "reference answer")
        check(set(references) == set(public), "reference case coverage")
        controls = [r for r in private.values() if r["origin_class"] == "authored_control"]
        check(
            Counter(r["control_kind"] for r in controls) == CONTROL_COUNTS,
            "frozen authored control balance",
        )
        check(len(entry["ai_reviews"]) == 2, "exactlytwo fresh AI reviews per group")
        ai = []
        for ref in entry["ai_reviews"]:
            path = required(ref["path"])
            check(file_hash(path) == ref["sha256"], "fresh AI artifact hash mismatch")
            check(
                not path.is_relative_to(packet_root), "AI answers must stay outside public packet"
            )
            response_path = required(ref["response_budget_path"])
            response = read_json(response_path)
            check(
                file_hash(response_path) == ref["response_budget_sha256"]
                and response["review_sha256"] == file_hash(path)
                and response["encoding"] == "o200k_base"
                and response["package_version"] == "0.12.0"
                and type(response["estimated_tokens"]) is int
                and 0 <= response["estimated_tokens"] <= 8000
                and response["response_limit"] == 8000
                and response["status"] == "within_estimate_limit",
                "complete primary AI response estimate cap/binding",
            )
            audit_review(packet_root, path)
            raw = read_json(path)
            check(
                raw.get("human") is False
                and raw.get("reviewer_kind") == "ai_reviewer"
                and raw.get("packet_sha256") == entry["packet_sha256"]
                and isinstance(raw.get("agent_task"), str)
                and raw["agent_task"]
                and raw["agent_task"] not in all_agents,
                "fresh independent AI context/packet identity",
            )
            all_agents.add(raw["agent_task"])
            answers = unique(raw["items"], lambda r: r["id"], "AI item")
            check(set(answers) == set(public), "fresh AI item coverage")
            ai.append((ref, answers))
        for cid, case in public.items():
            mapped = private[cid]
            source = (packet_root / case["source_path"]).resolve(strict=True)
            check(
                source.is_relative_to(packet_root) and source.is_file(), "packet source containment"
            )
            source_key = entry["packet_root"].rstrip("/") + "/" + case["source_path"]
            check(
                source_key in packet_manifest["files"]
                and file_hash(required(source_key)) == case["source_sha256"],
                "packet source inventory binding",
            )
            check(
                mapped["origin_class"] in {"derived_parent_claim", "authored_control"},
                "unknown derived/control origin",
            )
            check(
                mapped["group_id"] == gid and case["source_sha256"] == mapped["source_sha256"],
                "public/private group/source binding",
            )
            check(
                references[cid]["source_sha256"] == case["source_sha256"],
                "reference source binding",
            )
            for _, answers in ai:
                check(
                    answers[cid]["source_sha256"] == case["source_sha256"]
                    and answers[cid]["verdict"] in {"supported", "contradicted", "uncertain"},
                    "AI item source/verdict",
                )
            if mapped["origin_class"] == "authored_control":
                base = cohort.get(mapped["derived_claim_id"])
                check(
                    base is not None
                    and base["group_id"] == gid
                    and mapped["derived_claim"] == base["claim"]
                    and mapped["derived_claim_sha256"] == base["claim_sha256"],
                    "control must bind a new-derived base claim",
                )
                expected = (
                    "uncertain"
                    if mapped["control_kind"] == "duplicate_function_uncertain"
                    else "contradicted"
                )
                check(
                    mapped["expected_verdict"] == expected
                    and references[cid]["verdict"] == expected
                    and all(answers[cid]["verdict"] == expected for _, answers in ai),
                    "authored control gate failed",
                )
        group_eligible = 0
        for claim in claims:
            cid = claim.claim_id
            row = cohort[cid]
            matches = [
                r
                for r in private.values()
                if r["origin_class"] == "derived_parent_claim" and r["derived_claim_id"] == cid
            ]
            check(len(matches) == 1, "one exact new-derived AI case required")
            mapped = matches[0]
            case_id = mapped["id"]
            case = public[case_id]
            check(
                mapped["control_kind"] is None and mapped["expected_verdict"] is None,
                "derived case must not contain a coordinator truth answer",
            )
            origin = mapped["source_origin"]
            check(
                mapped["derived_claim"] == row["claim"]
                and mapped["derived_claim_sha256"] == row["claim_sha256"]
                and all(
                    case[k] == row["claim"][k]
                    for k in ("kind", "subject", "predicate", "text", "scope")
                )
                and case["source_sha256"] == row["parent_source_sha256"]
                and origin["group_id"] == gid
                and origin["repo_id"] == "packaging"
                and origin["parent_commit"] == group["parent_commit"]
                and origin["repository_path"] == claim.subject.path
                and origin["git_blob_object_id"] == row["parent_git_blob_object_id"]
                and origin["source_sha256"] == row["parent_source_sha256"]
                and origin["split"] == "development",
                "exact derived claim/AI source binding",
            )
            reason = []
            ref = references[case_id]
            if ref["verdict"] != "supported":
                reason.append("parent_reference_" + ref["verdict"])
            if any(answers[case_id]["verdict"] != "supported" for _, answers in ai):
                reason.append("fresh_AI_not_both_supported")
            expected = {
                "group_id": gid,
                "claim_id": cid,
                "claim_sha256": row["claim_sha256"],
                "parent_source_sha256": row["parent_source_sha256"],
                "reference_verdict": ref["verdict"],
                "eligible": not reason,
                "exclusion_reasons": reason,
            }
            check(decisions[cid] == expected, "sealed parent decision disagrees with bound reviews")
            confirmations[cid] = {
                "reviewer_kind": "two_fresh_AI",
                "eligible": not reason,
                "case_id": case_id,
                "reviews": [r for r, _ in ai],
                "reference": ref,
            }
            group_eligible += not reason
        check(group_eligible >= 4, "fewerthan4 eligible parents in group; no replacement")
    return confirmations, decisions


def preflight_topology(p, metadata, groups, root):
    check(
        metadata["schema_version"] == 1
        and metadata["source_configuration"]["proposed_index_source_roots"] == ROOTS
        and metadata["start_commit"] == p["start_commit"]
        and metadata["boundary_commit"] == p["boundary_commit"]
        and metadata["child_source_access_authorized"] is False,
        "metadata project/ref/scope binding",
    )
    config = metadata["source_configuration"]
    check(
        config == read_json(within(root, p["topology_protocol_path"]))["source_configuration"]
        and config["eligible_module_prefixes"] == ["src/packaging/", "packaging/"]
        and config["excluded_path_components"]
        == ["tests", "test", "_vendor", "vendor", "__pycache__"]
        and config["extensions"] == [".py"]
        and config["regular_modes"] == ["100644", "100755"]
        and config["max_file_bytes"] == 2 * 1024**2,
        "fixed parent enumeration and snapshot source configuration",
    )
    frame = metadata["frame"]
    check(
        len(frame) >= 72
        and len({r["commit"] for r in frame}) == len(frame)
        and all(oid(r["commit"]) for r in frame),
        "frozen commit frame identity",
    )
    check(
        metadata["frame_length"] == len(frame)
        and all(r["position"] == i for i, r in enumerate(frame)),
        "frozen frame positions",
    )
    indices = [0, (len(frame) - 24) // 2, len(frame) - 24]
    check(all(b - a >= 24 for a, b in zip(indices, indices[1:])), "parent windows must be disjoint")
    selected = unique(metadata["groups"], lambda r: r["group_id"], "metadata group")
    topology = {}
    source_ids = set()
    repo_paths = set()
    verified_repos = set()
    for (group, _), position in zip(groups, indices, strict=True):
        gid = group["group_id"]
        repo = within(root, group["repo_path"])
        repo_paths.add(str(repo))
        check(
            resolve(repo, p["start_commit"]) == p["start_commit"]
            and resolve(repo, p["boundary_commit"]) == p["boundary_commit"]
            and resolve(repo, "HEAD") == p["boundary_commit"],
            "exact pinned ref/HEAD identity",
        )
        path = (
            git(repo, "rev-list", "--first-parent", "--reverse", p["boundary_commit"])
            .decode()
            .splitlines()
        )
        check(
            p["start_commit"] in path
            and path[path.index(p["start_commit"]) :] == [r["commit"] for r in frame],
            "frozen first-parent frame mismatch",
        )
        if str(repo) not in verified_repos:
            for number, frozen in enumerate(frame):
                actual = (
                    git(repo, "rev-list", "--parents", "-n", "1", frozen["commit"]).decode().split()
                )
                check(
                    actual == [frozen["commit"], *frozen["parents"]]
                    and len(set(frozen["parents"])) == len(frozen["parents"])
                    and all(map(oid, frozen["parents"]))
                    and (
                        not number
                        or frozen["parents"]
                        and frozen["parents"][0] == frame[number - 1]["commit"]
                    ),
                    "full frame parent metadata mismatch",
                )
            verified_repos.add(str(repo))
        check(
            selected[gid]["parent_position"] == position
            and group["parent_commit"] == frame[position]["commit"]
            and group["child_commits"] == [r["commit"] for r in frame[position + 1 : position + 24]]
            and selected[gid]["parent_commit"] == group["parent_commit"]
            and selected[gid]["child_commits"] == group["child_commits"],
            "metadata-only parent/window selection mismatch",
        )
        by_commit = {}
        previous = group["parent_commit"]
        for number, commit in enumerate([previous, *group["child_commits"]]):
            frozen = frame[position + number]
            actual = git(repo, "rev-list", "--parents", "-n", "1", commit).decode().split()
            check(actual == [commit, *frozen["parents"]], "full parent list mismatch")
            if number:
                check(
                    frozen["parents"] and frozen["parents"][0] == previous,
                    "preceding snapshot must be first parent",
                )
                by_commit[commit] = {
                    "commit": commit,
                    "previous_commit": previous,
                    "parent_commits": frozen["parents"],
                    "first_parent_commit": previous,
                    "step": number,
                    "is_merge": len(frozen["parents"]) > 1,
                    "comparison_basis": "preceding_first_parent_tree",
                }
            check(commit not in source_ids, "source windows overlap")
            source_ids.add(commit)
            previous = commit
        expected_steps = [
            {
                "step": r["step"],
                "commit": r["commit"],
                "previous_commit": r["previous_commit"],
                "parents": r["parent_commits"],
                "is_merge": r["is_merge"],
            }
            for r in by_commit.values()
        ]
        check(
            selected[gid]["steps"] == expected_steps
            and selected[gid]["repo_id"] == "packaging"
            and selected[gid]["repo_path"] == group["repo_path"]
            and selected[gid]["source_roots"] == ROOTS,
            "selected trajectory metadata mismatch",
        )
        topology[gid] = by_commit
    check(
        len(repo_paths) == 1 and len(source_ids) == 72 and set(selected) == set(topology),
        "exact one-project72snapshot allowlist",
    )
    return topology


def episode_summary(rows):
    scored = [r for r in rows if r["eligible"]]
    by_claim = {}
    for row in scored:
        by_claim.setdefault(row["claim_id"], []).append(row)
    first = []
    runs = []
    for cid, records in sorted(by_claim.items()):
        records.sort(key=lambda r: r["trajectory"]["step"])
        negatives = [r for r in records if r["reference"]["verdict"] == "contradicted"]
        if negatives:
            first.append(
                {
                    "claim_id": cid,
                    "commit": negatives[0]["commit"],
                    "step": negatives[0]["trajectory"]["step"],
                }
            )
        current = None
        for row in records:
            if row["reference"]["verdict"] == "contradicted":
                if current is None or row["trajectory"]["step"] != current["last_step"] + 1:
                    current = {
                        "claim_id": cid,
                        "first_step": row["trajectory"]["step"],
                        "last_step": row["trajectory"]["step"],
                        "observations": 0,
                    }
                    runs.append(current)
                current["last_step"] = row["trajectory"]["step"]
                current["observations"] += 1
            else:
                current = None
    total = sum(r["reference"]["verdict"] == "contradicted" for r in scored)
    return {
        "unique_contradicted_claims": len(first),
        "first_contradiction_observations": len(first),
        "repeated_contradicted_observations": total - len(first),
        "observed_contradiction_runs": len(runs),
        "first_contradictions": first,
        "runs": runs,
        "episode_definition": "Maximal observed consecutive contradicted ranks; unknown breaks an observed run but is not proof of recovery.",
    }


def summarize_records(rows):
    result = summarize(rows)
    if not rows:
        result["false_available_per_scored_null_reason"] = "no_observations_in_stratum"
    result["incidence"] = episode_summary(rows)
    return result


def report_stratum(rows, groups):
    return {
        "variants": {
            v: summarize_records([r for r in rows if r["variant"] == v]) for v in VARIANTS
        },
        "groups": {
            g["group_id"]: {
                v: summarize_records(
                    [r for r in rows if r["group_id"] == g["group_id"] and r["variant"] == v]
                )
                for v in VARIANTS
            }
            for g, _ in groups
        },
        "claim_kinds": {
            kind: {
                v: summarize_records(
                    [r for r in rows if r["claim_kind"] == kind and r["variant"] == v]
                )
                for v in VARIANTS
            }
            for kind in ("symbol_exists", "signature_equals")
        },
    }


def storage_bytes(path):
    return sum(p.lstat().st_size for p in path.rglob("*") if p.is_file() or p.is_symlink())


def enforce_disk_cap(output, groups, root, limit):
    repositories = {within(root, group["repo_path"]) for group, _ in groups}
    check(
        not any(output.is_relative_to(repo) for repo in repositories),
        "output must be outside repository",
    )
    total = storage_bytes(output) + sum(storage_bytes(repo) for repo in repositories)
    check(total <= limit, "research2GiB disk resource cap exceeded")
    return total
