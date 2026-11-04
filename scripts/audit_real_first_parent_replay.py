#!/usr/bin/env python3
"""Independent, stdlib-only audit of the frozen first-parent Click extension.

Derived from prior independent audit SHA-256
7e43e21f39a45eebcc2bb9409e8b2b3b66b8253a481d2c6cac1eea513f6fbc96;
no CAMI, replay, or reference module is imported.

Never imports the runner, helper, CAMI, or either reference checker. Only exact
protocol-authorized Click commits are passed to Git. No network, execution of
repository source, or held-out inputs. Supports later implementation HEADs by
reading frozen source/input bytes from the recorded historical workspace commit.
"""

import argparse
import ast
import collections
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

PROTOCOL = "examples/real_structural_first_parent_replay/protocol.json"
SEAL = "examples/real_structural_first_parent_replay/seal.json"
PROTOCOL_SHA = "d733b76fc78e9813b39ba0e07398d67b6941fe649c52f5b82e532e9fec686aa9"
SEAL_SHA = "a46d5741a365fdbe8daa1174a782c867c0d654178b7693e999d0e9f838586c81"
IMPLEMENTATION_COMMIT = "02fcd4a8655dbb9932af86d1161411e28301b885"
VARIANTS = ("symbol_anchor", "file_anchor", "known_incomplete", "all_validate")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def pairs(items):
    out = {}
    for key, value in items:
        require(key not in out, "duplicate JSON key: " + key)
        out[key] = value
    return out


def parse(raw):
    def invalid_constant(value):
        raise ValueError("invalid JSON constant: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def rows(path):
    return [parse(line) for line in path.read_bytes().splitlines() if line.strip()]


def git(repo, *args):
    result = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "--no-optional-locks",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(repo),
            *args,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        env={
            **os.environ,
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
        },
    )
    require(result.returncode == 0, "Git read failed: " + repr(args))
    return result.stdout


def safe(base, name):
    path = (base / name).resolve()
    require(path.is_relative_to(base.resolve()), "path escapes root: " + name)
    return path


class Inputs:
    def __init__(self, root):
        self.root = root
        self.history = []
        self.cache = {}

    def read(self, name, expected):
        if name in self.cache:
            raw = self.cache[name]
        else:
            path = safe(self.root, name)
            raw = path.read_bytes() if path.is_file() else b""
            if sha(raw) != expected:
                raw = git(self.root, "show", IMPLEMENTATION_COMMIT + ":" + name)
                self.history.append(name)
            self.cache[name] = raw
        require(sha(raw) == expected, "frozen input/source hash mismatch: " + name)
        return raw


def dump(node):
    return ast.dump(node, include_attributes=False) if node is not None else None


def signature(fn):
    args = fn.args
    positional = args.posonlyargs + args.args
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    parameters = []
    for i, arg in enumerate(positional):
        parameters.append(
            {
                "name": arg.arg,
                "kind": "positional_only" if i < len(args.posonlyargs) else "positional_or_keyword",
                "annotation_ast": dump(arg.annotation),
                "default_ast": dump(defaults[i]),
            }
        )
    if args.vararg:
        parameters.append(
            {
                "name": args.vararg.arg,
                "kind": "var_positional",
                "annotation_ast": dump(args.vararg.annotation),
                "default_ast": None,
            }
        )
    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        parameters.append(
            {
                "name": arg.arg,
                "kind": "keyword_only",
                "annotation_ast": dump(arg.annotation),
                "default_ast": dump(default),
            }
        )
    if args.kwarg:
        parameters.append(
            {
                "name": args.kwarg.arg,
                "kind": "var_keyword",
                "annotation_ast": dump(args.kwarg.annotation),
                "default_ast": None,
            }
        )
    return {
        "parameters": parameters,
        "returns_ast": dump(fn.returns),
        "decorators_ast": list(map(dump, fn.decorator_list)),
        "is_async": isinstance(fn, ast.AsyncFunctionDef),
    }


def binding_hazards(tree, subject_name, direct_definition):
    """Conservative screen of syntactically evaluated module/class code.

    Class stores are rejected even without a global declaration. This can reject
    safe future inputs, but avoids claiming to solve class namespace/global
    interactions. Function/lambda bodies are deferred and are not traversed;
    their defaults, annotations and decorators are traversed. Dynamic namespace
    access is rejected at this evaluated scope rather than interpreted.
    """
    hazards = []

    class Screen(ast.NodeVisitor):
        def flag(self, node, why):
            hazards.append({"line": getattr(node, "lineno", None), "kind": why})

        def visit_Name(self, node):
            if node.id == subject_name and isinstance(node.ctx, (ast.Store, ast.Del)):
                self.flag(node, "name store/delete")

        def visit_FunctionDef(self, node):
            if node.name == subject_name and node is not direct_definition:
                self.flag(node, "other evaluated definition")
            for name, value in ast.iter_fields(node):
                if name == "body":
                    continue
                for child in value if isinstance(value, list) else [value]:
                    if isinstance(child, ast.AST):
                        self.visit(child)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Lambda(self, node):
            self.visit(node.args)

        def visit_ClassDef(self, node):
            if node.name == subject_name:
                self.flag(node, "class definition binds subject")
            self.generic_visit(node)

        def visit_Import(self, node):
            for alias in node.names:
                if (alias.asname or alias.name.split(".")[0]) == subject_name:
                    self.flag(node, "import binds subject")

        def visit_ImportFrom(self, node):
            for alias in node.names:
                if alias.name == "*" or (alias.asname or alias.name) == subject_name:
                    self.flag(node, "import/star import may bind subject")

        def visit_Global(self, node):
            if subject_name in node.names:
                self.flag(node, "evaluated global declaration")

        def visit_Nonlocal(self, node):
            if subject_name in node.names:
                self.flag(node, "evaluated nonlocal declaration")

        def visit_ExceptHandler(self, node):
            if node.name == subject_name:
                self.flag(node, "exception target binds subject")
            self.generic_visit(node)

        def visit_MatchAs(self, node):
            if node.name == subject_name:
                self.flag(node, "match capture binds subject")
            self.generic_visit(node)

        visit_MatchStar = visit_MatchAs

        def visit_MatchMapping(self, node):
            if node.rest == subject_name:
                self.flag(node, "mapping capture binds subject")
            self.generic_visit(node)

        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id in {
                "exec",
                "eval",
                "globals",
                "locals",
                "vars",
            }:
                self.flag(node, "dynamic namespace operation")
            self.generic_visit(node)

    Screen().visit(tree)
    return hazards


def subject(raw, claim):
    # Deliberately scoped to this frozen population: exact direct top-level functions.
    # Fail closed for a new syntax/population; no reuse of the v2 implementation.
    tree = ast.parse(raw.decode("utf-8", errors="strict"))
    name = claim["subject"]["qualname"]
    require(
        "." not in name and claim["subject"]["node_kind"] == "function", "unsupported audit subject"
    )
    defs = [
        x
        for x in tree.body
        if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) and x.name == name
    ]
    nested = [
        x
        for x in ast.walk(tree)
        if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) and x.name == name
    ]
    require(
        len(defs) == len(nested) == 1, "audit requires one unambiguous direct function: " + name
    )
    fn = defs[0]
    require(not getattr(fn, "type_params", []), "unsupported audit type parameters")
    hazards = binding_hazards(tree, name, fn)
    require(not hazards, "unsupported immediate subject binding hazards: " + repr(hazards))
    pred = claim["predicate"]
    if claim["kind"] == "symbol_exists":
        require(pred == {"type": "symbol_exists", "expected": True}, "unexpected exists predicate")
        verdict, reason = "supported", "predicate_matches"
    else:
        require(
            claim["kind"] == "signature_equals" and pred["type"] == "signature_equals",
            "unsupported predicate",
        )
        verdict = "supported" if signature(fn) == pred["expected_signature"] else "contradicted"
        reason = "predicate_matches" if verdict == "supported" else "predicate_mismatch"
    return fn, verdict, reason


def advance(previous, commit, selected, validation):
    state = copy.deepcopy(previous)
    state.update(revision=commit, basis="carried_forward")
    if validation is not None:
        verdict, reason = validation["verdict"], validation["reason"]
        state.update(last_checked_commit=commit, last_verdict=verdict, basis="validated")
        if verdict == "supported":
            state.update(
                state="valid", available=True, last_supported_commit=commit, withheld_reason=None
            )
        elif verdict == "contradicted":
            state.update(
                state="retired" if reason == "subject_absent" else "stale",
                available=False,
                withheld_reason=reason,
            )
        else:
            state.update(state="needs_validation", available=False, withheld_reason=reason)
    elif selected:
        state.update(
            state="needs_validation", available=False, withheld_reason="validation_pending"
        )
    return state


def summarize(records):
    scored = [x for x in records if x["eligible"]]

    def count(predicate, source=scored):
        return sum(bool(predicate(x)) for x in source)

    def ref(record):
        return record["reference"]["verdict"]

    def available(record):
        return record["state"]["available"]

    contradicted = count(lambda x: ref(x) == "contradicted")
    false = count(lambda x: available(x) and ref(x) == "contradicted")
    out = {
        "candidate_observations": len(records),
        "scored_observations": len(scored),
        "excluded_parent_observations": len(records) - len(scored),
        "available": count(available),
        "false_available": false,
        "available_unknown": count(lambda x: available(x) and ref(x) == "uncertain"),
        "withheld_supported": count(lambda x: not available(x) and ref(x) == "supported"),
        "false_available_per_contradicted": false / contradicted if contradicted else None,
        "false_available_per_contradicted_null_reason": None
        if contradicted
        else "zero_reference_contradicted_observations",
        "false_available_per_scored": false / len(scored) if scored else None,
        "false_available_per_scored_null_reason": None if scored else "no_eligible_parent_claims",
        "selected_logical_validations": count(lambda x: x["selection"]["selected"]),
        "actual_validation_calls": count(lambda x: x["validation"] is not None),
        "carried_states": count(lambda x: not x["selection"]["selected"]),
        "available_full_production_contradicted": count(
            lambda x: available(x) and x["full_production_validation"]["verdict"] == "contradicted"
        ),
        "full_production_unknown": count(
            lambda x: x["full_production_validation"]["verdict"] == "insufficient_evidence"
        ),
    }
    for label, verdict in [
        ("supported", "supported"),
        ("contradicted", "contradicted"),
        ("unknown", "uncertain"),
    ]:
        out["reference_" + label] = count(lambda x: ref(x) == verdict)
        out["candidate_reference_" + label] = count(lambda x: ref(x) == verdict, records)
    return out


def unique_index(records, key, label):
    out = {}
    for row in records:
        identity = key(row)
        require(identity not in out, "duplicate " + label + ": " + repr(identity))
        out[identity] = row
    return out


def authentic_case_ids(cohort, case_map, public_cases):
    public = unique_index(public_cases, lambda x: x["id"], "public AI case")
    authentic = {}
    for cid, row in cohort.items():
        matches = [
            x
            for x in case_map
            if x["origin_class"] == "authentic_parent_claim" and x["original_candidate_id"] == cid
        ]
        require(len(matches) == 1, "authentic AI mapping count mismatch")
        mapped = matches[0]
        require(
            mapped["original_claim"] == row["claim"]
            and mapped["original_claim_sha256"]
            == row["claim_sha256"]
            == sha(canonical(row["claim"])),
            "authentic AI original full-claim binding mismatch",
        )
        case = public[mapped["id"]]
        require(
            all(
                case[k] == row["claim"][k]
                for k in ["kind", "subject", "predicate", "text", "scope"]
            ),
            "authentic public AI claim mismatch",
        )
        require(
            case["source_sha256"] == mapped["public_source_sha256"] == row["parent_source_sha256"],
            "authentic public AI source mismatch",
        )
        authentic[cid] = mapped["id"]
    return authentic


def confirmation_eligible(cid, confirmation, cohort, authentic, frozen):
    agents = set()
    verdicts = []
    require(confirmation["claim_sha256"] == cohort[cid]["claim_sha256"], "AI claim hash binding")
    for review in confirmation["reviews"]:
        require(
            review["item_id"] == authentic[cid],
            "AI review item is not the exact authentic original claim",
        )
        raw_review = frozen(review["review_path"])
        require(sha(raw_review) == review["review_sha256"], "AI review hash binding")
        reviewer = parse(raw_review)
        require(
            reviewer["human"] is False and reviewer["reviewer_kind"] == "ai_reviewer",
            "raw AI reviewer identity",
        )
        require(reviewer["agent_task"] not in agents, "duplicate AI reviewer")
        agents.add(reviewer["agent_task"])
        matches = [x for x in reviewer["items"] if x["id"] == review["item_id"]]
        require(
            len(matches) == 1
            and matches[0]["source_sha256"] == cohort[cid]["parent_source_sha256"],
            "AI source binding",
        )
        verdicts.append(matches[0]["verdict"] == "supported")
    return len(agents) >= 2 and all(verdicts)


def commit_parents(repo, commit):
    require(
        len(commit) == 40 and all(c in "0123456789abcdef" for c in commit), "invalid frozen commit"
    )
    raw = git(repo, "cat-file", "commit", commit)
    return [
        line[7:].decode()
        for line in raw.split(b"\n\n", 1)[0].splitlines()
        if line.startswith(b"parent ")
    ]


def topology_check(protocol, frozen, root, result):
    require(
        protocol["protocol_id"] == "real-click-structural-first-parent-extension-development-v1"
        and protocol["trajectory_mode"] == "ordered_first_parent_snapshots_v1",
        "wrong extension protocol",
    )
    metadata = parse(frozen(protocol["metadata_manifest_path"]))
    old_binding = protocol["old_protocol"]
    old = parse(frozen(old_binding["path"]))
    old_seal = parse(frozen(old_binding["seal_path"]))
    require(
        sha(frozen(old_binding["path"])) == old_binding["sha256"]
        and sha(frozen(old_binding["seal_path"])) == old_binding["seal_sha256"]
        and old_seal["protocol_sha256"] == old_binding["sha256"],
        "old frozen protocol binding",
    )
    for field in (
        "cohort_path",
        "ai_case_map_path",
        "ai_public_cases_path",
        "confirmations_path",
        "reference_path",
        "provenance",
    ):
        require(protocol[field] == old[field], "original input path changed: " + field)
    for name, expected in old_seal["files"].items():
        if (
            name.startswith("src/cami/")
            and name.endswith(".py")
            or name
            in (
                "scripts/run_real_structural_replay.py",
                "scripts/real_structural_replay_support.py",
            )
        ):
            require(sha(frozen(name)) == expected, "old implementation identity: " + name)
    for field in (
        "cohort_path",
        "ai_case_map_path",
        "ai_public_cases_path",
        "confirmations_path",
        "reference_path",
    ):
        name = protocol[field]
        require(sha(frozen(name)) == old_seal["files"][name], "old input identity: " + name)
    for name in protocol["provenance"].values():
        require(sha(frozen(name)) == old_seal["files"][name], "old provenance identity")
    for name, expected in metadata["input_sha256"].items():
        require(sha(frozen(name)) == expected, "metadata input binding")
    for name, expected in metadata.get(
        "old_seal_bindings_without_opening_review_answers", {}
    ).items():
        require(sha(frozen(name)) == expected, "metadata original review/reference binding")
    old_groups = unique_index(old["groups"], lambda x: x["group_id"], "old group")
    trajectories = unique_index(metadata["trajectories"], lambda x: x["group_id"], "trajectory")
    require(
        set(old_groups) == set(trajectories) == {g["group_id"] for g in protocol["groups"]},
        "topology group inventory",
    )
    boundary = protocol["boundary_commit"]
    require(
        metadata["boundary_commit"] == metadata["local_HEAD"] == boundary,
        "frozen boundary metadata",
    )
    topology = {}
    paths = {}
    for group in protocol["groups"]:
        gid = group["group_id"]
        repo = safe(root, group["repo_path"])
        trajectory = trajectories[gid]
        prior = group["parent_commit"]
        oldg = old_groups[gid]
        require(
            all(
                group[k] == oldg[k]
                for k in ("repo_id", "repo_path", "parent_commit", "source_roots", "claims_path")
            ),
            "original group input changed",
        )
        require(
            sha(frozen(group["claims_path"])) == old_seal["files"][group["claims_path"]],
            "old claim bytes changed",
        )
        if str(repo) not in paths:
            require(
                git(repo, "rev-parse", "--verify", "HEAD^{commit}").decode().strip() == boundary,
                "corpus HEAD boundary",
            )
            paths[str(repo)] = (
                git(repo, "rev-list", "--first-parent", "--reverse", boundary).decode().splitlines()
            )
        path = paths[str(repo)]
        require(
            prior in path
            and path[path.index(prior) + 1 : path.index(prior) + 13] == group["child_commits"],
            "boundary first-parent sequence",
        )
        require(
            len(group["child_commits"]) == len(set(group["child_commits"])) == 12,
            "twelve exact children",
        )
        require(
            group["child_commits"][: len(oldg["child_commits"])] == oldg["child_commits"],
            "old prefix changed",
        )
        require(
            trajectory["parent"]["commit"] == prior
            and commit_parents(repo, prior) == trajectory["parent"]["parents"],
            "original parent full list",
        )
        require(
            trajectory["source_roots"] == group["source_roots"]
            and trajectory["repo_id"] == group["repo_id"]
            and trajectory["split"] == "development",
            "trajectory inputs",
        )
        require(trajectory["child_count"] == len(trajectory["steps"]) == 12, "trajectory count")
        by_commit = {}
        for number, (commit, step) in enumerate(
            zip(group["child_commits"], trajectory["steps"], strict=True), 1
        ):
            parents = commit_parents(repo, commit)
            require(
                parents and parents[0] == prior and len(set(parents)) == len(parents),
                "ordered first-parent edge",
            )
            expected_step = {
                "step": number,
                "commit": commit,
                "parents": parents,
                "previous_commit": prior,
                "is_merge": len(parents) > 1,
                "comparison_basis": "preceding_first_parent_tree",
                "already_in_old_protocol": commit in oldg["child_commits"],
            }
            require(
                all(step[k] == v for k, v in expected_step.items()),
                "frozen full-parent topology mismatch",
            )
            by_commit[commit] = {
                "previous_commit": prior,
                "parent_commits": parents,
                "first_parent_commit": parents[0],
                "is_merge": len(parents) > 1,
                "comparison_basis": "preceding_first_parent_tree",
                "step": number,
                "coverage_stratum": "old_overlap"
                if commit in oldg["child_commits"]
                else "new_added",
                "commit": commit,
            }
            prior = commit
        require(
            trajectory["merge_count"] == sum(t["is_merge"] for t in by_commit.values())
            and trajectory["new_child_count"]
            == sum(t["coverage_stratum"] == "new_added" for t in by_commit.values())
            and trajectory["previously_frozen_child_count"] == len(oldg["child_commits"]),
            "trajectory stratum counts",
        )
        topology[gid] = by_commit
    steps = [s for g in topology.values() for s in g.values()]
    require(
        len(steps) == metadata["total_steps"] == 36
        and sum(s["is_merge"] for s in steps) == metadata["merge_steps"] == 10
        and sum(s["coverage_stratum"] == "new_added" for s in steps)
        == metadata["newly_authorizable_steps"]
        == 22
        and metadata["old_overlap_steps"] == 14
        and metadata["candidate_observations_per_variant"] == 288
        and metadata["new_candidate_observations_per_variant"] == 176,
        "global topology/partition counts",
    )
    require(
        parse((result / "topology.json").read_bytes()) == topology, "topology artifact mismatch"
    )
    return topology, old


def normalize_overlap(record, parent=False):
    value = copy.deepcopy(record)
    if parent:
        validations = [x["validation"] for x in value["variants"].values()]
    else:
        value.pop("trajectory", None)
        validations = [value.get(k) for k in ("validation", "full_production_validation")]
    for validation in validations:
        if validation is not None:
            for field in ("duration_seconds", "cpu_seconds"):
                validation.pop(field, None)
    for field in ("input_case_path", "packet_path", "case_path"):
        value["reference"].pop(field, None)
    return value


def overlap_check(protocol, frozen, parents, observations, result):
    binding = protocol["old_result"]
    old_manifest = parse(frozen(binding["manifest_path"]))
    require(
        old_manifest["status"] == "complete"
        and old_manifest["protocol_sha256"] == protocol["old_protocol"]["sha256"],
        "completed old run binding",
    )
    for field, basename in (("observations", "observations.jsonl"), ("parents", "parents.jsonl")):
        require(
            sha(frozen(binding[field + "_path"]))
            == binding[field + "_sha256"]
            == old_manifest["artifact_hashes"][basename],
            "old artifact anchor",
        )
    old_rows = [parse(x) for x in frozen(binding["observations_path"]).splitlines() if x.strip()]
    old_parents = [parse(x) for x in frozen(binding["parents_path"]).splitlines() if x.strip()]
    def observation_key(x):
        return x["group_id"], x["commit"], x["claim_id"], x["variant"]
    repeated = [r for r in observations if r["trajectory"]["coverage_stratum"] == "old_overlap"]
    before = unique_index(old_rows, observation_key, "old observation")
    after = unique_index(repeated, observation_key, "overlap observation")
    require(len(before) == len(after) == 448 and set(before) == set(after), "old overlap coverage")
    checks = []
    for row in old_rows:
        identity = observation_key(row)
        a = normalize_overlap(row)
        b = normalize_overlap(after[identity])
        require(a == b, "old overlap semantic mismatch")
        checks.append(
            {
                "key": list(identity),
                "matched": True,
                "old_semantic_sha256": sha(canonical(a)),
                "new_semantic_sha256": sha(canonical(b)),
                "old": None,
                "new": None,
            }
        )
    def parent_key(x):
        return x["group_id"], x["claim"]["claim_id"]

    before = unique_index(old_parents, parent_key, "old parent")
    after = unique_index(parents, parent_key, "new parent")
    require(len(before) == len(after) == 24 and set(before) == set(after), "old parent inventory")
    parent_checks = []
    for row in old_parents:
        identity = parent_key(row)
        a = normalize_overlap(row, True)
        b = normalize_overlap(after[identity], True)
        require(a == b, "old parent semantic mismatch")
        parent_checks.append(
            {
                "key": list(identity),
                "matched": True,
                "old_semantic_sha256": sha(canonical(a)),
                "new_semantic_sha256": sha(canonical(b)),
                "old": None,
                "new": None,
            }
        )
    expected = {
        "status": "matched",
        "observation_count": 448,
        "parent_count": 24,
        "normalization": "Ignore only validation CPU/duration seconds and explicit reference input-case packet paths; compare every old observation/parent field. New trajectory annotations are separate.",
        "observations": checks,
        "parents": parent_checks,
    }
    require(
        parse((result / "overlap-check.json").read_bytes()) == expected,
        "overlap-check artifact mismatch",
    )
    return {k: expected[k] for k in ("status", "observation_count", "parent_count")}


def strata(records, groups):
    def summary(selected):
        value = summarize(selected)
        if not selected:
            value["false_available_per_scored_null_reason"] = "no_observations_in_stratum"
        return value

    return {
        "variants": {v: summary([r for r in records if r["variant"] == v]) for v in VARIANTS},
        "groups": {
            g["group_id"]: {
                v: summary(
                    [r for r in records if r["group_id"] == g["group_id"] and r["variant"] == v]
                )
                for v in VARIANTS
            }
            for g in groups
        },
    }


def audit(root, result):
    inputs = Inputs(root)
    protocol = parse(inputs.read(PROTOCOL, PROTOCOL_SHA))
    seal = parse(inputs.read(SEAL, SEAL_SHA))
    require(seal["protocol_sha256"] == PROTOCOL_SHA, "protocol seal anchor")
    for name, expected in seal["files"].items():
        inputs.read(name, expected)

    def frozen(name):
        return inputs.read(name, seal["files"][name])

    manifest = parse((result / "manifest.json").read_bytes())
    require(
        manifest["status"] == "complete" and not manifest["evaluation_eligible"],
        "manifest completion/scope",
    )
    require(
        manifest["protocol"] == protocol
        and manifest["seal"] == seal
        and manifest["protocol_sha256"] == PROTOCOL_SHA,
        "embedded frozen inputs",
    )
    require(
        manifest["source_before"] == manifest["source_after"]
        and manifest["source_snapshots_match"],
        "source snapshot mismatch",
    )
    source = manifest["source_before"]
    require(
        source["git_head"] == IMPLEMENTATION_COMMIT and source["source_status"] == "",
        "recorded implementation identity",
    )
    require(
        sha(json.dumps(source["files"], sort_keys=True, ensure_ascii=True).encode())
        == source["sha256"],
        "source inventory hash",
    )
    historical_names = set(
        git(
            root,
            "ls-tree",
            "-r",
            "-z",
            "--name-only",
            IMPLEMENTATION_COMMIT,
            "--",
            *source["scope"],
        )
        .decode()
        .split("\0")
    ) - {""}
    require(
        historical_names == set(source["files"]), "historical source inventory coverage mismatch"
    )
    for name, expected in source["files"].items():
        require(expected is not None, "missing source inventory entry")
        inputs.read(name, expected)
        require(
            sha(git(root, "show", IMPLEMENTATION_COMMIT + ":" + name)) == expected,
            "historical implementation source hash mismatch: " + name,
        )
    actual_files = {
        str(x.relative_to(result))
        for x in result.rglob("*")
        if x.is_file() and x.relative_to(result) != Path("manifest.json")
    }
    require(actual_files == set(manifest["artifact_hashes"]), "artifact file coverage mismatch")
    for name, expected in manifest["artifact_hashes"].items():
        require(sha(safe(result, name).read_bytes()) == expected, "artifact hash mismatch: " + name)
    parents = rows(result / "parents.jsonl")
    observations = rows(result / "observations.jsonl")
    costs = rows(result / "costs.jsonl")
    pindex = unique_index(parents, lambda x: (x["group_id"], x["claim"]["claim_id"]), "parent")
    oindex = unique_index(
        observations,
        lambda x: (x["group_id"], x["commit"], x["claim_id"], x["variant"]),
        "observation",
    )
    claims_by_group = {
        g["group_id"]: [parse(x) for x in frozen(g["claims_path"]).splitlines() if x.strip()]
        for g in protocol["groups"]
    }
    expected_parents = {
        (g["group_id"], c["claim_id"])
        for g in protocol["groups"]
        for c in claims_by_group[g["group_id"]]
    }
    expected_observations = {
        (g["group_id"], commit, c["claim_id"], v)
        for g in protocol["groups"]
        for commit in g["child_commits"]
        for c in claims_by_group[g["group_id"]]
        for v in VARIANTS
    }
    require(
        set(pindex) == expected_parents and len(parents) == protocol["candidate_claims"],
        "parent coverage mismatch",
    )
    require(
        set(oindex) == expected_observations
        and len(observations) == 4 * protocol["candidate_claim_child_observations_per_variant"],
        "observation coverage mismatch",
    )
    cohort = {x["claim"]["claim_id"]: x for x in parse(frozen(protocol["cohort_path"]))}
    confirmations = {
        x["claim_id"]: x
        for x in [
            parse(s) for s in frozen(protocol["confirmations_path"]).splitlines() if s.strip()
        ]
    }
    authentic = authentic_case_ids(
        cohort,
        parse(frozen(protocol["ai_case_map_path"])),
        parse(frozen(protocol["ai_public_cases_path"])),
    )
    for cid, confirmation in confirmations.items():
        confirmation["eligible"] = confirmation_eligible(
            cid, confirmation, cohort, authentic, frozen
        )
    provenance = {
        v: {
            x["claim_id"]: x
            for x in [parse(s) for s in frozen(protocol["provenance"][v]).splitlines() if s.strip()]
        }
        for v in VARIANTS
    }
    for variant in provenance.values():
        for prov in variant.values():
            for anchor in prov["anchors"]:
                anchor.setdefault("qualname", None)
    topology, old_protocol = topology_check(protocol, frozen, root, result)
    packets = {}
    evidence = {}
    expected_packet_dirs = set()
    expected_costs = []
    expected_changes = set()
    contradictions = collections.defaultdict(list)
    git_reads = []
    for group in protocol["groups"]:
        gid = group["group_id"]
        allowed = {group["parent_commit"], *group["child_commits"]}
        repo = safe(root, group["repo_path"])

        def authorized(commit, *args):
            require(commit in allowed, "unauthorized Click commit")
            git_reads.append({"group_id": gid, "commit": commit, "operation": args[0]})
            return git(repo, *args)

        previous_commit = group["parent_commit"]
        for commit in [group["parent_commit"], *group["child_commits"]]:
            if commit != group["parent_commit"]:
                commit_record = authorized(commit, "cat-file", "commit", commit)
                parent_ids = [
                    s[7:].decode()
                    for s in commit_record.split(b"\n\n", 1)[0].splitlines()
                    if s.startswith(b"parent ")
                ]
                require(
                    parent_ids == topology[gid][commit]["parent_commits"]
                    and parent_ids[0] == previous_commit,
                    "first-parent/full-parent mismatch",
                )
                changed = set(
                    authorized(
                        commit,
                        "diff",
                        "--no-ext-diff",
                        "--no-textconv",
                        "--no-renames",
                        "--name-only",
                        "-z",
                        previous_commit,
                        commit,
                        "--",
                    )
                    .decode()
                    .split("\0")
                ) - {""}
                change_path = "changes/" + gid + "/" + commit + ".json"
                expected_changes.add(change_path)
                changes = parse((result / change_path).read_bytes())
                require(
                    changes["before"] == previous_commit and changes["after"] == commit,
                    "change chain mismatch",
                )
                require(
                    all(changes.get(k) == v for k, v in topology[gid][commit].items()),
                    "change topology mismatch",
                )
                require(set(changes["files"]) == changed, "changed files mismatch")
                require(not changes["limited_paths"], "audit scope requires no parse-limited paths")
                expected_costs.append(("child_snapshot_index_compare", gid, commit, None, None))
            else:
                expected_costs.append(("parent_snapshot_index", gid, commit, None, None))
            for claim in claims_by_group[gid]:
                cid = claim["claim_id"]
                path = claim["subject"]["path"]
                packet = result / "packets" / gid / commit / cid
                expected_packet_dirs.add(str(packet.relative_to(result)))
                tree = authorized(
                    commit, "ls-tree", "-z", "--full-tree", commit, "--", ":(literal)" + path
                )
                require((packet / "git-ls-tree.raw").read_bytes() == tree, "raw Git tree mismatch")
                entries = [x for x in tree.split(b"\0") if x]
                require(len(entries) == 1, "audit frozen population requires exact present blob")
                info, found = entries[0].split(b"\t")
                mode, kind, oid = info.decode().split()
                require(
                    found.decode() == path and mode in ["100644", "100755"] and kind == "blob",
                    "unsupported frozen source mode/path",
                )
                raw = authorized(
                    commit, "show", "--no-ext-diff", "--no-textconv", commit + ":" + path
                )
                require((packet / "subject.raw").read_bytes() == raw, "raw Git source mismatch")
                require(
                    hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
                    == oid,
                    "Git blob OID mismatch",
                )
                fn, verdict, reason = subject(raw, claim)
                case = parse((packet / "case.json").read_bytes())
                decision = parse((packet / "decision.json").read_bytes())
                expected_case = {
                    "id": cid,
                    **{k: claim[k] for k in ["kind", "predicate", "scope", "subject", "text"]},
                    "source_path": "subject.raw",
                    "source_sha256": sha(raw),
                }
                require(case == expected_case, "packet case mismatch")
                for field, value in {
                    "id": cid,
                    "commit": commit,
                    "path": path,
                    "git_mode": mode,
                    "git_type": kind,
                    "git_oid": oid,
                    "source_sha256": sha(raw),
                    "declared_source_sha256": sha(raw),
                    "git_ls_tree_sha256": sha(tree),
                    "verdict": verdict,
                }.items():
                    require(
                        decision.get(field) == value, "reference " + field + " mismatch for " + cid
                    )
                expected_facts = {
                    "definition_count": 1,
                    "unconditional_definition_count": 1,
                    "exists": True,
                    "signature": signature(fn),
                }
                require(decision["facts"] == expected_facts, "reference extracted facts mismatch")
                require(
                    decision["evidence"]
                    == [
                        {
                            "start_line": fn.lineno,
                            "end_line": fn.end_lineno,
                            "role": "unconditional definition",
                        }
                    ],
                    "reference evidence range mismatch",
                )
                reference_reason = (
                    "unique unconditional top-level syntactic function definition"
                    if claim["kind"] == "symbol_exists"
                    else "all complete signature fields match"
                    if verdict == "supported"
                    else "signature mismatch in: "
                    + ", ".join(
                        sorted(
                            k
                            for k, v in signature(fn).items()
                            if v != claim["predicate"]["expected_signature"][k]
                        )
                    )
                )
                constants = {}
                for statement in ast.parse(frozen(protocol["reference_path"])).body:
                    if (
                        isinstance(statement, ast.Assign)
                        and len(statement.targets) == 1
                        and isinstance(statement.targets[0], ast.Name)
                        and statement.targets[0].id in {"IDENTITY", "VERSION", "LIMITATION"}
                    ):
                        constants[statement.targets[0].id] = ast.literal_eval(statement.value)
                checker = {
                    "identity": constants["IDENTITY"],
                    "version": constants["VERSION"],
                    "python": manifest["python"].split()[0],
                    "shared_primitive_limitation": constants["LIMITATION"],
                }
                expected_decision = {
                    "id": cid,
                    "commit": commit,
                    "path": path,
                    "verdict": verdict,
                    "reason": reference_reason,
                    "git_mode": mode,
                    "git_oid": oid,
                    "git_type": kind,
                    "source_sha256": sha(raw),
                    "declared_source_sha256": sha(raw),
                    "git_ls_tree_sha256": sha(tree),
                    "facts": expected_facts,
                    "evidence": [
                        {
                            "start_line": fn.lineno,
                            "end_line": fn.end_lineno,
                            "role": "unconditional definition",
                        }
                    ],
                    "checker": checker,
                }
                require(decision == expected_decision, "complete reference decision mismatch")
                packets[(gid, commit, cid)] = decision
                evidence[(gid, commit, cid)] = (raw, sha(dump(fn).encode()), verdict, reason, fn)
                if commit == group["parent_commit"]:
                    parent = pindex[(gid, cid)]
                    c = cohort[cid]
                    require(
                        parent["claim"] == claim
                        and parent["claim_sha256"] == sha(canonical(claim)) == c["claim_sha256"],
                        "original claim binding",
                    )
                    require(
                        parent["ai_confirmation"] == confirmations[cid]
                        and confirmations[cid]["reviewer_kind"] == "ai_reviewer",
                        "AI confirmation identity",
                    )
                    require(parent["reference"] == decision, "parent reference packet mismatch")
                    eligible = verdict == "supported" and confirmations[cid]["eligible"]
                    require(
                        eligible and parent["eligible"] and parent["exclusion_reasons"] == [],
                        "frozen eligible population mismatch",
                    )
                    require(
                        c["parent_source_sha256"] == sha(raw)
                        and c["parent_git_blob_object_id"] == oid
                        and c["symbol_ast_sha256"] == sha(dump(fn).encode()),
                        "cohort parent binding",
                    )
                    expected_costs.append(("parent_reference", gid, None, cid, None))
                else:
                    expected_costs.append(("child_reference", gid, commit, cid, None))
                    if verdict == "contradicted":
                        contradictions[cid].append(commit)
            previous_commit = commit
    require(
        {str(x.parent.relative_to(result)) for x in (result / "packets").rglob("decision.json")}
        == expected_packet_dirs,
        "packet coverage mismatch",
    )
    require(
        {str(x.relative_to(result)) for x in (result / "changes").rglob("*.json")}
        == expected_changes,
        "change coverage mismatch",
    )
    expected_artifacts = expected_changes | {
        "parents.jsonl",
        "observations.jsonl",
        "costs.jsonl",
        "report.json",
        "topology.json",
        "overlap-check.json",
    }
    expected_artifacts.update(
        directory + "/" + name
        for directory in expected_packet_dirs
        for name in ["case.json", "decision.json", "git-ls-tree.raw", "subject.raw"]
    )
    require(actual_files == expected_artifacts, "exact authorized artifact layout mismatch")
    for group in protocol["groups"]:
        gid = group["group_id"]
        parent_commit = group["parent_commit"]
        for claim in claims_by_group[gid]:
            cid = claim["claim_id"]
            parent = pindex[(gid, cid)]
            for variant in VARIANTS:
                prov = provenance[variant][cid]
                raw, ast_hash, _, _, fn = evidence[(gid, parent_commit, cid)]
                require(
                    prov["dependencies"] == [] and len(prov["anchors"]) == 1,
                    "unexpected frozen provenance domain",
                )
                a = prov["anchors"][0]
                require(
                    a["observed_commit"] == parent_commit
                    and a["path"] == claim["subject"]["path"]
                    and a["origin"] == "static",
                    "anchor identity",
                )
                if variant == "file_anchor":
                    require(
                        a["scope"] == "file"
                        and a["qualname"] is None
                        and a["content_hash"] == sha(raw)
                        and a["start_line"] == 1
                        and a["end_line"] == len(raw.decode().splitlines()),
                        "full file provenance derivation",
                    )
                else:
                    require(
                        a["scope"] == "symbol"
                        and a["qualname"] == claim["subject"]["qualname"]
                        and a["content_hash"] == ast_hash
                        and a["start_line"] == fn.lineno
                        and a["end_line"] == fn.end_lineno,
                        "symbol provenance derivation",
                    )
                require(
                    prov["known_incomplete"] == (variant == "known_incomplete"),
                    "known incomplete provenance flag",
                )
                pr = parent["variants"][variant]
                require(pr["provenance"] == prov, "parent provenance mismatch")
                previous = {
                    "schema_version": 1,
                    "claim_id": cid,
                    "revision": parent_commit,
                    "state": "needs_validation",
                    "last_checked_commit": None,
                    "last_supported_commit": None,
                    "last_verdict": None,
                    "basis": "validated",
                    "current_provenance": prov,
                    "available": False,
                    "withheld_reason": "parent_not_validated",
                }

                def validate_record(validation, commit):
                    require(validation is not None, "missing selected validation")
                    _, _, verdict, reason, _ = evidence[(gid, commit, cid)]
                    expected_evidence = [
                        commit + ":" + claim["subject"]["path"] + ":" + claim["subject"]["qualname"]
                    ]
                    require(
                        validation["verdict"] == verdict and validation["reason"] == reason,
                        "production validation verdict mismatch",
                    )
                    require(
                        validation["claim_id"] == cid
                        and validation["commit"] == commit
                        and validation["validator"] == "structural"
                        and validation["evidence"] == expected_evidence,
                        "validation identity",
                    )
                    expected_hash = sha(
                        canonical(
                            {
                                "claim": claim,
                                "commit": commit,
                                "evidence": expected_evidence,
                                "validator_version": "5",
                                "provenance": prov,
                            }
                        )
                    )
                    require(
                        validation["input_hash"] == expected_hash
                        and not validation["cache_hit"]
                        and validation["test_executions"] == 0,
                        "validation input/provenance identity",
                    )

                validate_record(pr["validation"], parent_commit)
                previous = advance(previous, parent_commit, True, pr["validation"])
                require(pr["state"] == previous, "parent state transition mismatch")
                expected_costs.append(("parent_production_validation", gid, None, cid, variant))
                prior_commit = parent_commit
                for commit in group["child_commits"]:
                    row = oindex[(gid, commit, cid, variant)]
                    require(
                        row["trajectory"] == topology[gid][commit], "observation topology mismatch"
                    )
                    require(
                        row["eligible"] and row["reference"] == packets[(gid, commit, cid)],
                        "reference record mismatch",
                    )
                    require(
                        row["provenance"] == prov and row["previous_state"] == previous,
                        "prior state/provenance mismatch",
                    )
                    changes = parse((result / "changes" / gid / (commit + ".json")).read_bytes())
                    changed = (
                        evidence[(gid, prior_commit, cid)][1] != evidence[(gid, commit, cid)][1]
                    )
                    symbol_nodes = {(x["path"], x["qualname"]) for x in changes["symbols"]}
                    require(
                        ((claim["subject"]["path"], claim["subject"]["qualname"]) in symbol_nodes)
                        == changed,
                        "subject change record mismatch",
                    )
                    reasons = []
                    if variant == "all_validate":
                        reasons.append("all_claims")
                    else:
                        if (
                            prov["known_incomplete"]
                            or prov["unresolved_reasons"]
                            or not prov["anchors"]
                        ):
                            reasons.append("known_incomplete")
                        if variant == "file_anchor" and a["path"] in changes["files"]:
                            reasons.extend(["subject_file_changed", "anchor_file_changed"])
                        elif variant != "file_anchor" and changed:
                            reasons.extend(["subject_changed", "symbol_or_dependency_changed"])
                    if not previous["available"]:
                        reasons.append("previously_unavailable")
                    selection = {
                        "schema_version": 1,
                        "claim_id": cid,
                        "commit": commit,
                        "selected": bool(reasons),
                        "reasons": sorted(set(reasons)),
                    }
                    require(row["selection"] == selection, "selection recomputation mismatch")
                    if reasons:
                        validate_record(row["validation"], commit)
                        expected_costs.append(
                            ("child_production_validation", gid, commit, cid, variant)
                        )
                    else:
                        require(row["validation"] is None, "unselected validation consumed")
                    previous = advance(previous, commit, bool(reasons), row["validation"])
                    require(row["state"] == previous, "state transition mismatch")
                    full = oindex[(gid, commit, cid, "all_validate")]["validation"]
                    require(
                        row["full_production_validation"] == full,
                        "full production comparison mismatch",
                    )
                    prior_commit = commit
    require(
        set(manifest["eligible_claims"]) == {cid for _, cid in expected_parents}
        and not manifest["parent_exclusions"],
        "manifest eligibility",
    )
    actual_costs = []
    for row in costs:
        actual_costs.append(
            (
                row["phase"],
                row["group_id"],
                row.get("commit"),
                row.get("claim_id"),
                row.get("variant"),
            )
        )
        require(row["seconds"] >= 0, "negative cost")
        if "production_validation" in row["phase"]:
            require(
                row["actual_calls"] == 1 and row.get("logical_calls", 1) == 1,
                "forged validation cost",
            )
        elif "reference" in row["phase"]:
            require(row["reference_calls"] == 1, "forged reference cost")
        else:
            require(row["index_builds"] == 1, "forged index cost")
    require(
        collections.Counter(actual_costs) == collections.Counter(expected_costs),
        "exact cost coverage mismatch",
    )
    report = {
        "variants": {
            v: summarize([x for x in observations if x["variant"] == v]) for v in VARIANTS
        },
        "groups": {},
        "parent_initialization": {},
    }
    for group in protocol["groups"]:
        gid = group["group_id"]
        report["groups"][gid] = {
            "candidate_claims": len(claims_by_group[gid]),
            "child_count": len(group["child_commits"]),
            "variants": {
                v: summarize(
                    [x for x in observations if x["group_id"] == gid and x["variant"] == v]
                )
                for v in VARIANTS
            },
        }
    for variant in VARIANTS:
        report["parent_initialization"][variant] = {
            "eligible_parent_claims": len(parents),
            "supported": sum(x["variants"][variant]["state"]["available"] for x in parents),
            "initially_withheld": sum(
                not x["variants"][variant]["state"]["available"] for x in parents
            ),
            "actual_validation_calls": len(parents),
        }
    report["separate_work"] = {
        "parent_reference_calls": len(parents),
        "child_reference_calls": len(observations) // 4,
        "shared_index_builds": len(protocol["groups"])
        + sum(len(g["child_commits"]) for g in protocol["groups"]),
    }
    report["primary_new_coverage"] = strata(
        [r for r in observations if r["trajectory"]["coverage_stratum"] == "new_added"],
        protocol["groups"],
    )
    report["old_overlap"] = strata(
        [r for r in observations if r["trajectory"]["coverage_stratum"] == "old_overlap"],
        protocol["groups"],
    )
    report["topology_strata"] = {
        name: strata(
            [r for r in observations if r["trajectory"]["is_merge"] == merge], protocol["groups"]
        )
        for name, merge in (("merge", True), ("nonmerge", False))
    }
    report["coverage_note"] = (
        "Added transitions are outcome-informed development coverage; old overlap is repeated evidence. Merge strata are descriptive, not causal."
    )
    report["overlap_check"] = overlap_check(protocol, frozen, parents, observations, result)
    require(
        report == parse((result / "report.json").read_bytes()),
        "report metric recomputation mismatch",
    )
    return {
        "status": "pass",
        "manifest_sha256": sha((result / "manifest.json").read_bytes()),
        "protocol_sha256": PROTOCOL_SHA,
        "seal_sha256": SEAL_SHA,
        "implementation_commit": IMPLEMENTATION_COMMIT,
        "artifact_files_checked": len(actual_files),
        "frozen_sealed_files_checked": len(seal["files"]),
        "source_inventory_files_checked": len(source["files"]),
        "historical_source_inventory_files_checked": len(historical_names),
        "historical_fallback_paths": inputs.history,
        "parent_records": len(parents),
        "exact_authentic_ai_claim_bindings_checked": len(authentic),
        "cost_rows_checked": len(costs),
        "observation_records": len(observations),
        "coverage_per_variant": {
            "full": 288,
            "new_added": 176,
            "old_overlap": 112,
            "merge": 80,
            "nonmerge": 208,
        },
        "old_overlap_semantic_equality": report["overlap_check"],
        "independent_audit_source_reuse_sha256": "7e43e21f39a45eebcc2bb9409e8b2b3b66b8253a481d2c6cac1eea513f6fbc96",
        "source_access_log": git_reads,
        "reference_packets_checked": len(packets),
        "independent_binding_screen": {
            "packets_screened": len(packets),
            "hazards_found": 0,
            "scope": "Conservative module/class evaluated syntax; deferred function/lambda bodies excluded; rejects dynamic namespace calls and possible subject writes/imports/captures; not a runtime binding oracle.",
        },
        "authorized_click_git_read_count": len(git_reads),
        "authorized_click_commits": sorted({x["commit"] for x in git_reads}),
        "unique_contradicted_claims": len(contradictions),
        "unique_false_available_claims_by_variant": {
            v: len(
                {
                    x["claim_id"]
                    for x in observations
                    if x["variant"] == v
                    and x["state"]["available"]
                    and x["reference"]["verdict"] == "contradicted"
                }
            )
            for v in VARIANTS
        },
        "contradicted_claim_child_observations_per_variant": sum(map(len, contradictions.values())),
        "contradiction_commits_by_claim": dict(contradictions),
        "recomputed_report": report,
        "limits": [
            "The pinned protocol/seal and local Git object database are the trust roots; artifact hashes are integrity checks, not signatures.",
            "The bounded independent semantic check supports this exact population of present, unique direct functions passing a conservative immediate binding screen; unsupported future populations stop the audit.",
            "CPython ast is shared with production/reference. Syntactic predicates do not establish dynamic binding or runtime behavior.",
            "Source inspection finds references computed after policy transitions and never passed into selection/state; this is not a dynamic information-flow proof.",
            "Recorded actual calls are reconciled exactly against raw validation/cost rows; this does not independently observe past physical executions or wall time.",
            "Coverage and topology partitions describe overlapping dependent observations from the same claims/modules/history. New added coverage is development evidence, not a new independent sample or causal merge effect.",
        ],
    }


def default_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / PROTOCOL).is_file() and (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument(
        "--result", type=Path, default=Path("reports/research-20261104/real-first-parent-replay-v1")
    )
    parser.add_argument(
        "--out", type=Path, help="Write a new report file; existing files are never replaced."
    )
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        result = audit(root, (root / args.result).resolve())
    except Exception as error:
        result = {"status": "fail", "error": type(error).__name__ + ": " + str(error)}
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        with args.out.open("x") as stream:
            stream.write(encoded)
    else:
        print(encoded, end="")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
