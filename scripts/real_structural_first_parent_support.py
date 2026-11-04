"""Research-only first-parent topology gate and strict repeated-prefix comparison."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from cami.artifacts import digest, file_hash, read_json, read_jsonl, within, write_json
from cami.repository import git, resolve
from scripts.real_structural_replay_support import VARIANTS, sealed_inputs, summarize

PROTOCOL_ID = "real-click-structural-first-parent-extension-development-v1"
MODE = "ordered_first_parent_snapshots_v1"
BASIS = "preceding_first_parent_tree"


def extension_inputs(protocol_path):
    declared = read_json(protocol_path)
    if declared.get("protocol_id") != PROTOCOL_ID or declared.get("trajectory_mode") != MODE:
        raise ValueError("requires the separate exact first-parent extension protocol and mode")
    result = sealed_inputs(protocol_path)
    protocol, root, seal, groups, cohort, confirmations, provenance, reference_path = result
    inventory = seal["files"]

    def require(name, expected=None):
        path = within(root, name)
        if name not in inventory or (expected is not None and inventory[name] != expected):
            raise ValueError(f"unsealed or changed extension binding: {name}")
        return path

    own_path = str(Path(__file__).resolve().relative_to(root))
    if own_path not in protocol["implementation_paths"]:
        raise ValueError("new first-parent support implementation must be explicitly frozen")
    require(own_path)
    metadata = read_json(require(protocol["metadata_manifest_path"]))
    old_binding = protocol["old_protocol"]
    old_protocol = read_json(require(old_binding["path"], old_binding["sha256"]))
    old_seal = read_json(require(old_binding["seal_path"], old_binding["seal_sha256"]))
    if old_seal["protocol_sha256"] != old_binding["sha256"]:
        raise ValueError("old protocol seal no longer binds original protocol")
    fixed_fields = ("cohort_path", "ai_case_map_path", "ai_public_cases_path", "confirmations_path", "reference_path", "provenance")
    if any(protocol[field] != old_protocol[field] for field in fixed_fields):
        raise ValueError("extension changed original claim/provenance/reference/AI inputs")
    old_groups = {group["group_id"]: group for group in old_protocol["groups"]}
    if len(old_groups) != 3 or set(old_groups) != {group["group_id"] for group, _ in groups}:
        raise ValueError("extension must retain the exact original three groups")
    required_originals = [protocol[field] for field in fixed_fields if field != "provenance"]
    required_originals += list(protocol["provenance"].values())
    required_originals += [group["claims_path"] for group, _ in groups]
    required_originals += ["scripts/run_real_structural_replay.py", "scripts/real_structural_replay_support.py"]
    required_originals += [str(path.relative_to(root)) for path in (root / "src/cami").rglob("*.py")]
    required_originals += [name for name in old_seal["files"] if name.startswith("src/cami/") and name.endswith(".py")]
    for name in required_originals:
        require(name, old_seal["files"][name])
    for name, expected in metadata["input_sha256"].items():
        require(name, expected)
    for name, expected in metadata.get("old_seal_bindings_without_opening_review_answers", {}).items():
        require(name, expected)
    if (protocol["candidate_claims"] != 24 or protocol["candidate_claim_child_observations_per_variant"] != 288
            or protocol["new_candidate_claim_child_observations_per_variant"] != 176
            or old_protocol["candidate_claims"] != 24
            or old_protocol["candidate_claim_child_observations_per_variant"] != 112):
        raise ValueError("extension population/coverage denominators must remain fixed")
    for group, claims in groups:
        old = old_groups[group["group_id"]]
        if (len(claims) != 8 or len(group["child_commits"]) != 12
                or any(group[field] != old[field] for field in ("repo_id", "repo_path", "parent_commit", "source_roots", "claims_path"))
                or group["child_commits"][:len(old["child_commits"])] != old["child_commits"]):
            raise ValueError("extension altered original parent inputs or old prefix")
    if sorted(len(group["child_commits"]) for group in old_groups.values()) != [1, 1, 12]:
        raise ValueError("unexpected original trajectory lengths")
    if file_hash(reference_path) != protocol["reference_sha256"]:
        raise ValueError("independent reference version changed")
    for name in protocol.get("reference_contract_paths", []):
        require(name, old_seal["files"][name])
    observed = protocol["old_result"]
    old_manifest = read_json(require(observed["manifest_path"], observed["manifest_sha256"]))
    old_rows = read_jsonl(require(observed["observations_path"], observed["observations_sha256"]))
    old_parents = read_jsonl(require(observed["parents_path"], observed["parents_sha256"]))
    if old_manifest["status"] != "complete" or old_manifest["protocol_sha256"] != old_binding["sha256"]:
        raise ValueError("old observed run is not the completed original protocol")
    for field, basename in (("observations_sha256", "observations.jsonl"), ("parents_sha256", "parents.jsonl")):
        if old_manifest["artifact_hashes"].get(basename) != observed[field]:
            raise ValueError("old observed artifact does not match its original manifest")
    expected_keys = {(group["group_id"], commit, claim.claim_id, variant)
                     for group, claims in groups for commit in old_groups[group["group_id"]]["child_commits"]
                     for claim in claims for variant in VARIANTS}
    keys = [observation_key(row) for row in old_rows]
    if len(keys) != 448 or len(keys) != len(set(keys)) or set(keys) != expected_keys:
        raise ValueError("old overlap must contain all original 448 observations exactly once")
    parent_keys = [(row["group_id"], row["claim"]["claim_id"]) for row in old_parents]
    if len(parent_keys) != 24 or len(set(parent_keys)) != 24 or {key[1] for key in parent_keys} != set(cohort):
        raise ValueError("old parent inventory is not the fixed original cohort")
    return result, metadata, old_protocol, old_rows, old_parents


def preflight_first_parent(protocol, metadata, old_protocol, groups, root):
    """Metadata only. Complete ALL groups before any snapshot/reference source access."""
    boundary = protocol["boundary_commit"]
    if (re.fullmatch(r"[0-9a-f]{40}", boundary) is None or metadata["boundary_commit"] != boundary
            or metadata.get("local_HEAD", boundary) != boundary):
        raise ValueError("pinned boundary mismatch")
    trajectories = {trajectory["group_id"]: trajectory for trajectory in metadata["trajectories"]}
    old_groups = {group["group_id"]: group for group in old_protocol["groups"]}
    if len(trajectories) != len(metadata["trajectories"]) or set(trajectories) != {group["group_id"] for group, _ in groups}:
        raise ValueError("topology must cover each group exactly once")
    topology, paths = {}, {}
    for group, claims in groups:
        repo = within(root, group["repo_path"])
        if str(repo) not in paths:
            if resolve(repo, boundary) != boundary or resolve(repo, "HEAD") != boundary:
                raise ValueError("repository boundary/HEAD differs from frozen boundary")
            paths[str(repo)] = git(repo, "rev-list", "--first-parent", "--reverse", boundary).decode().splitlines()
        path = paths[str(repo)]
        trajectory = trajectories[group["group_id"]]
        parent = group["parent_commit"]
        if parent not in path or path[path.index(parent)+1:path.index(parent)+13] != group["child_commits"]:
            raise ValueError("children are not exactly the next twelve boundary first-parent successors")
        if (trajectory["parent"]["commit"] != parent or trajectory["source_roots"] != group["source_roots"]
                or trajectory["repo_id"] != group["repo_id"] or trajectory["split"] != "development"
                or trajectory["child_count"] != 12 or len(trajectory["steps"]) != 12):
            raise ValueError("frozen trajectory identity/length mismatch")
        actual_parent = git(repo, "rev-list", "--parents", "-n", "1", parent).decode().split()
        if actual_parent != [parent, *trajectory["parent"]["parents"]] or resolve(repo, parent) != parent:
            raise ValueError("original parent full topology mismatch")
        previous = parent
        old_children = old_groups[group["group_id"]]["child_commits"]
        if group["child_commits"][:len(old_children)] != old_children:
            raise ValueError("old sequence must remain the unchanged prefix")
        group_steps = []
        for number, (commit, frozen) in enumerate(zip(group["child_commits"], trajectory["steps"], strict=True), 1):
            if resolve(repo, commit) != commit:
                raise ValueError("child exact identity mismatch")
            actual = git(repo, "rev-list", "--parents", "-n", "1", commit).decode().split()
            parents = frozen["parents"]
            if (actual != [commit, *parents] or not parents or parents[0] != previous
                    or any(re.fullmatch(r"[0-9a-f]{40}", oid) is None for oid in parents)
                    or len(parents) != len(set(parents)) or frozen["commit"] != commit
                    or frozen["previous_commit"] != previous or frozen["step"] != number
                    or frozen["is_merge"] != (len(parents) > 1) or frozen["comparison_basis"] != BASIS
                    or frozen["already_in_old_protocol"] != (commit in old_children)):
                raise ValueError("ordered full parent list or first-parent edge mismatch")
            group_steps.append({"previous_commit": previous, "parent_commits": parents,
                "first_parent_commit": parents[0], "is_merge": len(parents) > 1, "comparison_basis": BASIS,
                "step": number, "coverage_stratum": "old_overlap" if commit in old_children else "new_added",
                "commit": commit})
            previous = commit
        if (sum(step["is_merge"] for step in group_steps) != trajectory["merge_count"]
                or sum(step["coverage_stratum"] == "new_added" for step in group_steps) != trajectory["new_child_count"]
                or trajectory["previously_frozen_child_count"] != len(old_children)):
            raise ValueError("trajectory stratum accounting mismatch")
        topology[group["group_id"]] = {step["commit"]: step for step in group_steps}
    steps = [step for group in topology.values() for step in group.values()]
    if (len(steps) != 36 or sum(step["is_merge"] for step in steps) != 10
            or sum(step["coverage_stratum"] == "new_added" for step in steps) != 22
            or metadata["total_steps"] != 36 or metadata["merge_steps"] != 10
            or metadata["newly_authorizable_steps"] != 22 or metadata["old_overlap_steps"] != 14
            or metadata["candidate_observations_per_variant"] != 288
            or metadata["new_candidate_observations_per_variant"] != 176):
        raise ValueError("global topology/coverage denominators mismatch")
    return topology


def observation_key(row):
    return row["group_id"], row["commit"], row["claim_id"], row["variant"]


def normalized_observation(row):
    result = deepcopy(row)
    result.pop("trajectory", None)  # Added metadata has no field in the old schema.
    for field in ("validation", "full_production_validation"):
        if result.get(field) is not None:
            result[field].pop("duration_seconds", None)
            result[field].pop("cpu_seconds", None)
    # Current checker emits no case-packet paths; retain a narrow explicit allowance.
    for field in ("input_case_path", "packet_path", "case_path"):
        result["reference"].pop(field, None)
    return result


def normalized_parent(row):
    result = deepcopy(row)
    for value in result["variants"].values():
        value["validation"].pop("duration_seconds", None)
        value["validation"].pop("cpu_seconds", None)
    for field in ("input_case_path", "packet_path", "case_path"):
        result["reference"].pop(field, None)
    return result


def compare_overlap(records, parents, old_rows, old_parents, output):
    new = {observation_key(row): row for row in records}
    repeated = [row for row in records if row["trajectory"]["coverage_stratum"] == "old_overlap"]
    if len(repeated) != len(old_rows) or {observation_key(row) for row in repeated} != {observation_key(row) for row in old_rows}:
        raise ValueError("new run did not retain the exact original overlap inventory")
    checks = []
    for old in old_rows:
        key = observation_key(old)
        before, after = normalized_observation(old), normalized_observation(new[key])
        checks.append({"key": list(key), "matched": before == after,
                       "old_semantic_sha256": digest(before), "new_semantic_sha256": digest(after),
                       "old": before if before != after else None, "new": after if before != after else None})
    parent_checks = []
    current = {(row["group_id"], row["claim"]["claim_id"]): row for row in parents}
    for old in old_parents:
        key = old["group_id"], old["claim"]["claim_id"]
        before, after = normalized_parent(old), normalized_parent(current[key])
        parent_checks.append({"key": list(key), "matched": before == after,
                              "old_semantic_sha256": digest(before), "new_semantic_sha256": digest(after),
                              "old": before if before != after else None, "new": after if before != after else None})
    result = {"status": "matched" if all(row["matched"] for row in [*checks, *parent_checks]) else "mismatch",
              "observation_count": len(checks), "parent_count": len(parent_checks),
              "normalization": "Ignore only validation CPU/duration seconds and explicit reference input-case packet paths; compare every old observation/parent field. New trajectory annotations are separate.",
              "observations": checks, "parents": parent_checks}
    write_json(output / "overlap-check.json", result)
    if result["status"] != "matched":
        raise ValueError("old overlap semantic mismatch; preserve this run without resealing")
    return result


def stratum_report(rows, groups):
    def summary(selected):
        result = summarize(selected)
        if not selected:
            result["false_available_per_scored_null_reason"] = "no_observations_in_stratum"
        return result
    return {"variants": {variant: summary([row for row in rows if row["variant"] == variant]) for variant in VARIANTS},
            "groups": {group["group_id"]: {variant: summary([row for row in rows
                if row["group_id"] == group["group_id"] and row["variant"] == variant]) for variant in VARIANTS} for group, _ in groups}}
