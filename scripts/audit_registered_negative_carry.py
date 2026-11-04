#!/usr/bin/env python3
"""Independent stdlib-only audit of the sealed registered-input negative-carry experiment.

Reads frozen bytes and historical source; never imports CAMI, the runner, or
reference checkers, and never reruns the measured maintenance workload.
"""

import argparse
import ast
import collections
import copy
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import pstats
import statistics
import subprocess
import sys

PROTOCOL = "examples/registered_negative_carry/protocol.json"
SEAL = "examples/registered_negative_carry/seal.json"
PROTOCOL_SHA = "4c624f86fe06b02d99455a7a52af86b36aa39876bbb74831e5619d8cf0c905d1"
SEAL_SHA = "f7a0ab0efd520cbb2d2cd5c2c2e2a912834da1483eb788ac7ef7d65813036c2c"
IMPLEMENTATION_COMMIT = "8e4241cb2cc42d16faed3b16a28e13d07b01b32b"
VARIANTS = ("production", "signature_witness", "module_blob_witness", "registered_inputs")
SCOPE = "Exact normalized syntax, including defaults, annotations, decorators, and async status."
DEFAULT_RESULT = "reports/research-20261104/registered-negative-carry-v1"
COUNTERS = (
    "actual_validation_calls",
    "effective_selected",
    "eligibility_attempts",
    "original_selected",
    "suppressed",
    "witness_mint_attempts",
)


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


def unique_index(records, key, label):
    out = {}
    for row in records:
        identity = key(row)
        require(identity not in out, "duplicate " + label + ": " + repr(identity))
        out[identity] = row
    return out


def tree_snapshot(repo, commit, expected_parent):
    require(
        (repo / ".git").is_dir() and not (repo / ".git").is_symlink(),
        "fixture Git directory must be local",
    )
    require(
        not (repo / ".git/objects/info/alternates").exists(),
        "fixture object alternates are outside scope",
    )
    raw_commit = git(repo, "cat-file", "commit", commit)
    require(
        hashlib.sha1(b"commit " + str(len(raw_commit)).encode() + b"\0" + raw_commit).hexdigest()
        == commit,
        "fixture commit object identity",
    )
    parents = [line[7:].decode() for line in raw_commit.splitlines() if line.startswith(b"parent ")]
    require(
        parents == ([] if expected_parent is None else [expected_parent]),
        "authored fixture chain mismatch",
    )
    output = {}
    for entry in git(repo, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0"):
        if not entry:
            continue
        info, name = entry.split(b"\t")
        mode, kind, oid = info.decode().split()
        require(kind == "blob", "authored fixture must contain only blobs")
        raw = git(repo, "cat-file", "blob", oid)
        require(
            hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == oid,
            "fixture blob object identity",
        )
        output[name.decode()] = {"mode": mode, "oid": oid, "raw": raw}
    return output


def expected_tree_step(tree, operation, step):
    tree = copy.deepcopy(tree)
    kind = operation["operation"]
    if kind == "source":
        old_mode = tree.get("pkg/f.py", {}).get("mode", "100644")
        tree["pkg/f.py"] = {
            "mode": "100644" if old_mode == "120000" else old_mode,
            "raw": operation["source"].encode(),
        }
    elif kind == "other_file":
        tree["other.txt"] = {"mode": "100644", "raw": str(step).encode()}
    elif kind == "symlink_same_blob":
        tree["pkg/f.py"]["mode"] = "120000"
    elif kind == "delete":
        del tree["pkg/f.py"]
    elif kind == "ancestor_symlink":
        tree["pkg"] = {"mode": "120000", "raw": b"elsewhere"}
    elif kind == "executable":
        tree["pkg/f.py"]["mode"] = "100755"
    else:
        require(kind == "noop", "unknown frozen operation")
    return tree


def simple_tree(tree):
    return {name: {key: value[key] for key in ["mode", "raw"]} for name, value in tree.items()}


def inspect_source(tree, limit):
    blob = tree.get("pkg/f.py")
    if blob is None:
        ancestor = tree.get("pkg")
        return {
            "definition": None,
            "limitation": None,
            "ancestor_limitation": "symlink_unsupported"
            if ancestor and ancestor["mode"] == "120000"
            else None,
            "blob": None,
        }
    limitation = (
        "symlink_unsupported"
        if blob["mode"] == "120000"
        else ("file_too_large" if len(blob["raw"]) > limit else None)
    )
    result = {
        "definition": None,
        "limitation": limitation,
        "ancestor_limitation": None,
        "blob": blob,
    }
    if limitation:
        return result
    try:
        module = ast.parse(blob["raw"], filename="f.py")
    except SyntaxError:
        result["limitation"] = "parse_error"
        return result
    functions = [
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "f"
    ]
    require(len(functions) == 1, "bounded authored syntax requires one direct f definition")
    fn = functions[0]
    # This population has no imports, loops or reflective namespace mutations.
    # Class-global writes are the only authored ambiguity; fail on other syntax.
    ambiguous = False
    for node in ast.walk(module):
        if isinstance(node, ast.Global) and "f" in node.names:
            ambiguous = True
        if isinstance(
            node,
            (ast.Import, ast.ImportFrom, ast.NamedExpr, ast.With, ast.For, ast.Match, ast.Delete),
        ):
            raise ValueError("unsupported syntax outside the frozen authored population")
    result["definition"] = {
        "ast_hash": sha(dump(fn).encode()),
        "signature": signature(fn),
        "ambiguous": ambiguous,
        "start_line": fn.lineno,
        "end_line": fn.end_lineno,
    }
    return result


def production_verdict(info, claim):
    reason = info["ancestor_limitation"] or info["limitation"]
    if reason:
        return "insufficient_evidence", reason
    definition = info["definition"]
    if definition is None:
        return "contradicted", "subject_absent"
    if definition["ambiguous"]:
        return "insufficient_evidence", "ambiguous_subject"
    matches = definition["signature"] == claim["predicate"]["expected_signature"]
    return ("supported", "predicate_matches") if matches else ("contradicted", "predicate_mismatch")


def reference_verdict(tree, claim):
    blob = tree.get("pkg/f.py")
    if blob is None:
        return "uncertain" if "pkg" in tree else "contradicted"
    if blob["mode"] not in {"100644", "100755"}:
        return "uncertain"
    info = inspect_source(tree, 2**63)
    verdict, _ = production_verdict(info, claim)
    return "uncertain" if verdict == "insufficient_evidence" else verdict


def claim_for(history, commit):
    return {
        "schema_version": 1,
        "claim_id": history,
        "repo_id": history,
        "origin_commit": commit,
        "kind": "signature_equals",
        "text": "Exact authored normalized function signature.",
        "scope": SCOPE,
        "subject": {"path": "pkg/f.py", "qualname": "f", "node_kind": "function"},
        "predicate": {
            "type": "signature_equals",
            "expected_signature": signature(ast.parse("def f(x=1): pass").body[0]),
        },
    }


def input_identity(claim, provenance, commit):
    return sha(
        canonical(
            {
                "claim": claim,
                "commit": commit,
                "evidence": [commit + ":pkg/f.py:f"],
                "validator_version": "5",
                "provenance": provenance,
            }
        )
    )


def check_validation(validation, claim, provenance, commit, info):
    verdict, reason = production_verdict(info, claim)
    require(validation is not None, "selected validation missing")
    expected = {
        "claim_id": claim["claim_id"],
        "commit": commit,
        "validator": "structural",
        "verdict": verdict,
        "reason": reason,
        "input_hash": input_identity(claim, provenance, commit),
        "evidence": [commit + ":pkg/f.py:f"],
        "cache_hit": False,
        "test_executions": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "logs": [],
        "original_measurement": None,
        "schema_version": 1,
    }
    require(
        all(validation[key] == value for key, value in expected.items()),
        "validation identity/verdict mismatch",
    )
    require(
        validation["duration_seconds"] >= 0 and validation["cpu_seconds"] >= 0,
        "negative validation measurement",
    )


def exact_scope(claim, provenance, context):
    return (
        context["protocol_version"] == "1.1"
        and context["scope_contract"] == "exact_normalized_python_function_signature_v1"
        and claim["scope"] in {SCOPE, "Exact syntactic definition, no runtime semantics."}
        and not provenance["known_incomplete"]
        and not provenance["unresolved_reasons"]
        and not provenance["dependencies"]
        and bool(provenance["anchors"])
    )


def mint(claim, provenance, context, commit, info):
    verdict, reason = production_verdict(info, claim)
    if not exact_scope(claim, provenance, context) or (verdict, reason) != (
        "contradicted",
        "predicate_mismatch",
    ):
        return None
    blob = info["blob"]
    definition = info["definition"]
    return {
        "claim_sha256": sha(canonical(claim)),
        "provenance_sha256": sha(canonical(provenance)),
        "context_sha256": sha(canonical(context)),
        "checked_commit": commit,
        "validation_input_hash": input_identity(claim, provenance, commit),
        "module_oid": blob["oid"],
        "module_sha256": sha(blob["raw"]),
        "subject_ast_hash": definition["ast_hash"],
        "signature": definition["signature"],
    }


def registered_witness(claim, provenance, context, commit, info):
    witness = mint(claim, provenance, context, commit, info)
    if witness is None:
        return None
    return {
        "checked_commit": commit,
        "input_hash": witness["validation_input_hash"],
        "module_oid": witness["module_oid"],
        "claim_hash": sha(canonical(claim)),
        "provenance_hash": sha(canonical(provenance)),
        "context_hash": sha(canonical(context)),
    }


def registered_decision(original, previous, before, after, witness, changed, eligible):
    if not original["selected"] or original["reasons"] != ["previously_unavailable"]:
        return False, "original_selection_requires_normal_behavior"
    if changed or not eligible or witness is None:
        return False, "registration_scope_or_actual_negative_not_eligible"
    if (
        previous["last_checked_commit"] != witness["checked_commit"]
        or previous["available"]
        or previous["state"] != "stale"
        or previous["last_verdict"] != "contradicted"
        or previous["withheld_reason"] != "predicate_mismatch"
    ):
        return False, "owned_last_actual_negative_identity_mismatch"
    for info in [before, after]:
        blob = info["blob"]
        if (
            blob is None
            or blob["mode"] not in {"100644", "100755"}
            or info["limitation"]
            or info["ancestor_limitation"]
        ):
            return False, "subject_not_readable_regular_file"
        if blob["oid"] != witness["module_oid"]:
            return False, "module_changed_since_last_actual_negative"
    return True, None


def carry_decision(
    variant,
    claim,
    provenance,
    context,
    previous,
    original,
    before_commit,
    after_commit,
    before,
    after,
    witness,
):
    if witness is None:
        return False, "missing_actual_negative_witness"
    if not exact_scope(claim, provenance, context):
        return False, "outside_exact_scope_or_incomplete_provenance"
    if any(
        witness[key] != sha(canonical(value))
        for key, value in [
            ("claim_sha256", claim),
            ("provenance_sha256", provenance),
            ("context_sha256", context),
        ]
    ):
        return False, "bound_claim_provenance_or_context_changed"
    if (
        previous["revision"] != before_commit
        or previous["last_checked_commit"] != witness["checked_commit"]
        or witness["validation_input_hash"]
        != input_identity(claim, provenance, witness["checked_commit"])
    ):
        return False, "negative_validation_identity_or_lineage_mismatch"
    if (
        not original["selected"]
        or original["reasons"] != ["previously_unavailable"]
        or previous["available"]
        or previous["state"] != "stale"
        or previous["last_verdict"] != "contradicted"
        or previous["withheld_reason"] != "predicate_mismatch"
        or previous["current_provenance"] != provenance
    ):
        return False, "production_reason_or_previous_state_requires_validation"
    for info in [before, after]:
        blob = info["blob"]
        if (
            blob is None
            or blob["mode"] not in {"100644", "100755"}
            or info["limitation"]
            or info["ancestor_limitation"]
        ):
            return (
                False,
                "subject_not_readable_regular_file"
                if variant == "module_blob_witness"
                else "missing_or_nonregular_subject_module",
            )
        if variant == "module_blob_witness" and blob["oid"] != witness["module_oid"]:
            return False, "module_changed_since_actual_negative_validation"
    if variant == "signature_witness":
        left, right = before["definition"], after["definition"]
        if left is None or right is None or left["ambiguous"] or right["ambiguous"]:
            return False, "subject_not_unique_unambiguous_function"
        if (
            left["ast_hash"] != right["ast_hash"]
            or left["signature"] != right["signature"]
            or right["ast_hash"] != witness["subject_ast_hash"]
            or right["signature"] != witness["signature"]
        ):
            return False, "subject_witness_changed"
        return True, "unchanged_existing_signature_mismatch_carried"
    return True, "same_regular_module_as_actual_signature_mismatch"


def selection(claim, provenance, previous, before, after, commit, policy):
    reasons = []
    if policy == "symbol_validate":
        if provenance["known_incomplete"]:
            reasons.append("known_incomplete")
        if before["limitation"] or after["limitation"]:
            reasons.append("analysis_limitation")
        left, right = before["definition"], after["definition"]
        changed = (left is None) != (right is None) or (
            left is not None
            and right is not None
            and (left["ast_hash"] != right["ast_hash"] or left["ambiguous"] or right["ambiguous"])
        )
        if changed:
            reasons.extend(["subject_changed", "symbol_or_dependency_changed"])
        if not previous["available"]:
            reasons.append("previously_unavailable")
    else:
        require(policy == "keep_all", "unfrozen policy")
    return {
        "schema_version": 1,
        "claim_id": claim["claim_id"],
        "commit": commit,
        "selected": bool(reasons),
        "reasons": sorted(set(reasons)),
    }


def check_reference(packet, row, tree, repo, commit):
    raw_tree = git(repo, "ls-tree", "-z", "--full-tree", commit, "--", ":(literal)pkg/f.py")
    require((packet / "git-ls-tree.raw").read_bytes() == raw_tree, "reference raw tree mismatch")
    decision = parse((packet / "decision.json").read_bytes())
    require(row["reference"] == decision, "reference row/packet mismatch")
    claim = row["claim"]
    blob = tree.get("pkg/f.py")
    identity = {
        "id": claim["claim_id"],
        "commit": commit,
        "path": "pkg/f.py",
        "verdict": reference_verdict(tree, claim),
        "git_ls_tree_sha256": sha(raw_tree),
    }
    if blob:
        require(
            (packet / "subject.raw").read_bytes() == blob["raw"], "reference raw source mismatch"
        )
        identity.update(
            git_mode=blob["mode"],
            git_type="blob",
            git_oid=blob["oid"],
            source_sha256=sha(blob["raw"]),
        )
        if blob["mode"] in {"100644", "100755"}:
            case = parse((packet / "case.json").read_bytes())
            expected_case = {
                "id": claim["claim_id"],
                **{key: claim[key] for key in ["kind", "predicate", "subject", "scope", "text"]},
                "source_path": "subject.raw",
                "source_sha256": sha(blob["raw"]),
            }
            require(case == expected_case, "reference case claim binding mismatch")
            identity["declared_source_sha256"] = sha(blob["raw"])
    else:
        identity.update(git_mode=None, git_oid=None, source_sha256=None)
        ancestor_path = packet / ("ancestor-" + sha(b"pkg") + ".raw")
        ancestor = git(repo, "ls-tree", "-z", "--full-tree", commit, "--", ":(literal)pkg")
        require(ancestor_path.read_bytes() == ancestor, "reference ancestor tree mismatch")
    require(
        all(decision.get(key) == value for key, value in identity.items()),
        "independent reference verdict/identity mismatch",
    )


def frozen_source_review(frozen):
    runner = ast.parse(frozen("scripts/run_registered_negative_carry.py"))
    helper = ast.parse(frozen("scripts/negative_carry_challenge.py"))
    execute = next(
        node for node in runner.body if isinstance(node, ast.FunctionDef) and node.name == "execute"
    )
    block = next(
        node
        for node in runner.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_block"
    )
    history = next(
        node
        for node in helper.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_history"
    )

    def calls(node):
        return [child for child in ast.walk(node) if isinstance(child, ast.Call)]

    def name(call):
        return (
            call.func.id
            if isinstance(call.func, ast.Name)
            else (call.func.attr if isinstance(call.func, ast.Attribute) else "")
        )

    timed_loop = next(
        node
        for node in ast.walk(execute)
        if isinstance(node, ast.For)
        and isinstance(node.target, ast.Name)
        and node.target.id == "repetition"
    )
    timed_calls = calls(timed_loop)
    require(
        any(name(call) == "run_block" for call in timed_calls),
        "complete block missing from measured loop",
    )
    require(
        not any(name(call) in {"Profile", "runcall", "enable", "disable"} for call in timed_calls),
        "profiling inside timing samples",
    )
    start = next(
        node
        for node in ast.walk(timed_loop)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Tuple)
            and any(isinstance(item, ast.Name) and item.id == "wall_start" for item in target.elts)
            for target in node.targets
        )
    )
    stop = next(
        node
        for node in ast.walk(timed_loop)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Tuple)
            and any(isinstance(item, ast.Name) and item.id == "cpu_ns" for item in target.elts)
            for target in node.targets
        )
    )
    block_call = next(call for call in timed_calls if name(call) == "run_block")
    require(start.lineno < block_call.lineno < stop.lineno, "maintenance outside clock interval")
    profile_calls = [call for call in calls(execute) if name(call) in {"Profile", "runcall"}]
    require(
        profile_calls and all(call.lineno > timed_loop.end_lineno for call in profile_calls),
        "profiling must follow all timing samples",
    )
    require(
        any(name(call) == "run_history" for call in calls(block)),
        "history work not consumed by timed block",
    )
    history_calls = {name(call) for call in calls(history)}
    require(
        {
            "select_claims",
            "select_negative_carry",
            "select_blob_negative_carry",
            "mint_witness",
            "validate_claim",
            "advance_state",
        }
        <= history_calls,
        "timed maintenance work incomplete",
    )
    witness = ast.parse(frozen("scripts/negative_carry_witness.py"))
    witness_calls = {name(call) for call in calls(witness)}
    require(
        {"digest", "asdict", "context_hash", "input_hash"} <= witness_calls,
        "context/hash work absent",
    )
    helper_calls = {name(call) for call in calls(history)}
    require(
        not {"prepare_histories", "reference_claim", "build_index", "read_snapshot"} & helper_calls,
        "setup/reference leaked into maintenance",
    )
    registered_tree = ast.parse(frozen("scripts/registered_negative_carry_challenge.py"))
    owned_tree = ast.parse(frozen("scripts/registered_negative_carry.py"))
    registered_history = next(
        node
        for node in registered_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_history"
    )
    history_loop = next(node for node in registered_history.body if isinstance(node, ast.For))
    reset_calls = [call for call in calls(registered_history) if call.lineno < history_loop.lineno]
    require(
        {"RegisteredCarryOwner", "register", "initialize_checked_negative"}
        <= {name(call) for call in reset_calls},
        "registration/ingress costs omitted from history reset",
    )
    require(
        any(name(call) == "register" for call in calls(history_loop)),
        "mutation registration outside timed history",
    )

    class TraceScreen(ast.NodeVisitor):
        def __init__(self):
            self.capture_depth = 0

        def visit_If(self, node):
            capturing = isinstance(node.test, ast.Name) and node.test.id == "capture"
            self.capture_depth += capturing
            for child in node.body:
                self.visit(child)
            self.capture_depth -= capturing
            for child in node.orelse:
                self.visit(child)

        def visit_Call(self, node):
            if name(node) in {"digest", "asdict", "negative_record"}:
                require(
                    self.capture_depth > 0, "trace hashing leaks into genuine registered algorithm"
                )
            self.generic_visit(node)

    TraceScreen().visit(registered_history)
    register = next(
        node
        for node in ast.walk(owned_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    ingress = next(
        node
        for node in ast.walk(owned_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "initialize_checked_negative"
    )
    gate = next(
        node
        for node in ast.walk(owned_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_carry_reason"
    )
    require(
        {"immutable", "canonical", "model_validate_json"}
        <= {name(call) for call in calls(register)},
        "deep immutable registration/schema work missing",
    )
    require(
        {"canonical", "model_validate_json", "input_hash", "_initialize_actual"}
        <= {name(call) for call in calls(ingress)},
        "checked-result ingress binding work missing",
    )
    require(
        not {"digest", "asdict", "canonical", "context_hash", "input_hash"}
        & {name(call) for call in calls(gate)},
        "registered gate unexpectedly rehashes trace bindings",
    )
    return {
        "status": "pass",
        "timed_clock_lines": [start.lineno, stop.lineno],
        "profile_call_lines": sorted(call.lineno for call in profile_calls),
        "registered_lifecycle_review": {
            "reset_owner_and_registration_and_checked_import_inside_history": True,
            "step_registration_inside_history": True,
            "trace_hashes_capture_only": True,
            "deep_registration_and_checked_ingress_remain_timed": True,
        },
        "work_included": [
            "owner creation, deep registration and once-checked parent-result ingress",
            "selection",
            "eligibility/witness gate",
            "claim/provenance/context hashing",
            "initial and refresh witness minting",
            "actual structural validation",
            "state advance",
        ],
        "excluded_setup": [
            "authored Git creation",
            "snapshot/index/compare",
            "independent reference",
            "output serialization",
        ],
        "limitation": "Static frozen-source inspection establishes the intended measured call path; it cannot independently observe historical clock placement or untimed warmup executions.",
    }


def semantic_projection(records):
    output = {}
    grouped = collections.defaultdict(list)
    for row in records:
        grouped[(row["history"], row["variant"])].append(row)
    for (history, variant), values in grouped.items():
        values.sort(key=lambda row: row["step"])
        labels = {values[0]["claim"]["origin_commit"]: "parent"}
        labels.update(
            {row["original_selection"]["commit"]: "step" + str(row["step"]) for row in values}
        )

        def normalize(value):
            if isinstance(value, str):
                return labels.get(value, value)
            if isinstance(value, list):
                return [normalize(item) for item in value]
            if isinstance(value, dict):
                return {key: normalize(item) for key, item in value.items()}
            return value

        for row in values:
            context = {key: value for key, value in row["context"].items() if key != "run_binding"}
            witnesses = {
                key: None
                if row[key] is None
                else {
                    field: row[key][field]
                    for field in [
                        "checked_commit",
                        "module_oid",
                        "module_sha256",
                        "subject_ast_hash",
                        "signature",
                    ]
                }
                for key in ["prior_witness", "current_witness"]
            }
            projected = {
                key: row[key]
                for key in [
                    "policy",
                    "claim",
                    "provenance",
                    "original_selection",
                    "effective_selection",
                    "suppressed",
                    "audit_reason",
                    "previous_state",
                    "state",
                ]
            }
            projected.update(context=context, **witnesses)
            for key in ["fresh", "validation"]:
                projected[key] = (
                    None
                    if row[key] is None
                    else {field: row[key][field] for field in ["verdict", "reason", "validator"]}
                )
            projected["reference"] = {
                key: row["reference"].get(key)
                for key in ["verdict", "facts", "git_mode", "git_oid", "source_sha256"]
            }
            output[(history, row["step"], variant)] = normalize(projected)
    return output


def audit(root, result, fixture_root=None, comparison_result=None):
    inputs = Inputs(root)
    plan = parse(inputs.read(PROTOCOL, PROTOCOL_SHA))
    seal = parse(inputs.read(SEAL, SEAL_SHA))
    require(
        seal["protocol_sha256"] == PROTOCOL_SHA and len(seal["files"]) == 88,
        "frozen seal inventory",
    )
    for name, expected in seal["files"].items():
        inputs.read(name, expected)

    def frozen(name):
        return inputs.read(name, seal["files"][name])

    baseline_raw = frozen(plan["baseline_protocol_path"])
    require(
        sha(baseline_raw)
        == plan["baseline_protocol_sha256"]
        == "ac7b044b8874caccf44a0a45973f04f3b239e66c5bc974628e72d6c31c6164e3",
        "baseline protocol pin mismatch",
    )
    baseline_plan = parse(baseline_raw)
    workload_fields = [
        "histories",
        "paired_repetitions",
        "histories_per_block",
        "warmup_blocks",
        "minimum_block_ns",
        "profile_history_pack_repetitions",
        "profile_top_functions",
    ]
    require(
        all(plan[key] == baseline_plan[key] for key in workload_fields),
        "original authored workload changed",
    )
    require(
        all(
            sha(frozen(name)) == expected
            for name, expected in plan["original_implementation_hashes"].items()
        ),
        "original comparison implementation changed",
    )
    manifest = parse((result / "manifest.json").read_bytes())
    require(
        manifest["status"] == "complete"
        and manifest["error_count"] == 0
        and not any(
            manifest[key]
            for key in ["corpus_access", "evaluation_eligible", "source_execution", "network"]
        ),
        "manifest completion/scope",
    )
    require(
        manifest["protocol"] == plan
        and manifest["seal"] == seal
        and manifest["protocol_sha256"] == PROTOCOL_SHA,
        "manifest frozen input identity",
    )
    require(manifest["source_before"] == manifest["source_after"], "source before/after mismatch")
    source = manifest["source_before"]
    require(
        source["git_head"] == IMPLEMENTATION_COMMIT and source["source_status"] == "",
        "historical source identity",
    )
    require(
        sha(json.dumps(source["files"], sort_keys=True, ensure_ascii=True).encode())
        == source["sha256"],
        "source inventory digest",
    )
    historical = set(
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
    require(historical == set(source["files"]), "historical source coverage")
    for name, expected in source["files"].items():
        inputs.read(name, expected)
        require(
            sha(git(root, "show", IMPLEMENTATION_COMMIT + ":" + name)) == expected,
            "historical source hash mismatch: " + name,
        )
    actual = {
        str(path.relative_to(result))
        for path in result.rglob("*")
        if path.is_file()
        and path != result / "manifest.json"
        and ".git" not in path.relative_to(result).parts
    }
    require(
        len(actual) == 153 and actual == set(manifest["artifact_hashes"]),
        "artifact coverage mismatch",
    )
    for name, expected in manifest["artifact_hashes"].items():
        require(sha(safe(result, name).read_bytes()) == expected, "artifact hash mismatch: " + name)
    correctness = rows(result / "correctness.jsonl")
    timings = rows(result / "timings.jsonl")
    cases = {case["id"]: case for case in plan["histories"]}
    require(
        len(cases) == 17 and sum(len(case["steps"]) for case in cases.values()) == 31,
        "history population changed",
    )
    record_index = unique_index(
        correctness, lambda row: (row["history"], row["step"], row["variant"]), "correctness row"
    )
    expected_keys = {
        (name, step, variant)
        for name, case in cases.items()
        for step in range(len(case["steps"]))
        for variant in VARIANTS
    }
    require(
        len(correctness) == 124 and set(record_index) == expected_keys,
        "correctness coverage mismatch",
    )
    fixture_root = (fixture_root or result / "git-fixtures").resolve()
    expected_artifacts = {
        "correctness.jsonl",
        "expected-work.json",
        "profiling-work.json",
        "setup.json",
        "summary.json",
        "timings.jsonl",
    }
    expected_artifacts.update(
        "profiles/" + variant + suffix for variant in VARIANTS for suffix in [".prof", ".json"]
    )
    snapshots = {}
    frames = {}
    authorized_ids = {}
    expected_packet_dirs = set()
    run_binding = sha(canonical(plan))
    for hid, case in cases.items():
        first = record_index[(hid, 0, "production")]
        parent = first["claim"]["origin_commit"]
        repo = safe(fixture_root, hid)
        expected_tree = {"pkg/f.py": {"mode": "100644", "raw": case["initial_source"].encode()}}
        parent_tree = tree_snapshot(repo, parent, None)
        require(simple_tree(parent_tree) == expected_tree, "authored initial source tree mismatch")
        snapshots[(hid, parent)] = parent_tree
        claim = claim_for(hid, parent)
        context = {
            "repo_id": hid,
            "source_roots": ["."],
            "build_graph": True,
            "max_file_bytes": case.get("max_file_bytes", 2097152),
            "implementation_hashes": [
                [module, seal["files"]["src/" + module.replace(".", "/") + ".py"]]
                for module in [
                    "cami.index",
                    "cami.models",
                    "cami.policies",
                    "cami.repository",
                    "cami.validation",
                ]
            ],
            "run_binding": run_binding,
            "python": manifest["python"],
            "index_version": "4",
            "validator_version": "5",
            "protocol_version": "1.1",
            "scope_contract": "exact_normalized_python_function_signature_v1",
        }
        initial_context = copy.deepcopy(context)
        provenance = {
            "schema_version": 1,
            "claim_id": hid,
            "scenario_id": "authored_challenge",
            "known_incomplete": case.get("known_incomplete", False),
            "unresolved_reasons": [],
            "dependencies": [],
            "anchors": [
                {
                    "scope": "symbol",
                    "path": "pkg/f.py",
                    "qualname": "f",
                    "observed_commit": parent,
                    "content_hash": sha(case["initial_source"].encode()),
                    "origin": "static",
                    "start_line": None,
                    "end_line": None,
                }
            ],
        }
        previous_commit = parent
        old_info = inspect_source(parent_tree, context["max_file_bytes"])
        authorized_ids[hid] = [parent]
        frames[hid] = {
            "parent": parent,
            "initial_claim": copy.deepcopy(claim),
            "initial_context": initial_context,
            "provenance": provenance,
            "initial_info": old_info,
            "steps": [],
        }
        for step, operation in enumerate(case["steps"]):
            row = record_index[(hid, step, "production")]
            commit = row["original_selection"]["commit"]
            tree = tree_snapshot(repo, commit, previous_commit)
            expected_tree = expected_tree_step(expected_tree, operation, step)
            require(simple_tree(tree) == expected_tree, "authored step tree mismatch")
            snapshots[(hid, commit)] = tree
            if "expected_source" in operation:
                claim["predicate"]["expected_signature"] = signature(
                    ast.parse(operation["expected_source"]).body[0]
                )
            if "scope" in operation:
                claim["scope"] = operation["scope"]
            context.update(operation.get("context", {}))
            info = inspect_source(tree, context["max_file_bytes"])
            require(
                production_verdict(info, claim)[0] == operation["expected_production"]
                and reference_verdict(tree, claim) == operation["expected_reference"],
                "independent frozen semantic expectation mismatch",
            )
            frame = {
                "before_commit": previous_commit,
                "commit": commit,
                "before": old_info,
                "after": info,
                "claim": copy.deepcopy(claim),
                "context": copy.deepcopy(context),
                "operation": operation,
            }
            frames[hid]["steps"].append(frame)
            for variant in VARIANTS:
                other = record_index[(hid, step, variant)]
                require(
                    other["claim"] == claim
                    and other["claim_hash"] == sha(canonical(claim))
                    and other["context"] == context
                    and other["provenance"] == provenance,
                    "claim/provenance/context binding mismatch",
                )
            packet = result / "reference-packets" / hid / str(step)
            expected_packet_dirs.add(str(packet.relative_to(result)))
            check_reference(packet, row, tree, repo, commit)
            packet_names = ["decision.json", "git-ls-tree.raw"]
            if "pkg/f.py" in tree:
                packet_names.append("subject.raw")
                if tree["pkg/f.py"]["mode"] in {"100644", "100755"}:
                    packet_names.append("case.json")
            else:
                packet_names.append("ancestor-" + sha(b"pkg") + ".raw")
            expected_artifacts.update(
                str(packet.relative_to(result)) + "/" + name for name in packet_names
            )
            for variant in VARIANTS:
                require(
                    record_index[(hid, step, variant)]["reference"] == row["reference"],
                    "variant reference mismatch",
                )
            authorized_ids[hid].append(commit)
            previous_commit, old_info = commit, info
        for path, value in tree.items():
            if value["mode"] in {"100644", "100755"}:
                name = "git-fixtures/" + hid + "/" + path
                expected_artifacts.add(name)
                require(
                    (result / name).read_bytes() == value["raw"],
                    "final fixture working-file/source mismatch",
                )
    require(actual == expected_artifacts, "exact authored artifact layout mismatch")
    require(
        {
            str(path.parent.relative_to(result))
            for path in (result / "reference-packets").rglob("decision.json")
        }
        == expected_packet_dirs,
        "reference packet coverage",
    )
    counts = {}
    endpoints = {}
    correctness_groups = {}
    reasons = {}
    for variant in VARIANTS:
        work = dict.fromkeys(COUNTERS, 0)
        if variant == "registered_inputs":
            work.update(registrations=0, checked_result_imports=0)
        endpoint = {}
        reason_counts = collections.Counter()
        group_rows = {"ordinary": [], "controlled_keep_all": []}
        for hid, history in frames.items():
            parent = history["parent"]
            provenance = history["provenance"]
            previous = {
                "schema_version": 1,
                "claim_id": hid,
                "revision": parent,
                "state": "stale",
                "available": False,
                "basis": "validated",
                "last_checked_commit": parent,
                "last_supported_commit": None,
                "last_verdict": "contradicted",
                "current_provenance": provenance,
                "withheld_reason": "predicate_mismatch",
            }
            witness = None
            if variant == "registered_inputs":
                work["registrations"] += 1
                work["checked_result_imports"] += 1
            if variant != "production":
                work["witness_mint_attempts"] += 1
                mint_function = registered_witness if variant == "registered_inputs" else mint
                witness = mint_function(
                    history["initial_claim"],
                    provenance,
                    history["initial_context"],
                    parent,
                    history["initial_info"],
                )
            for step, frame in enumerate(history["steps"]):
                row = record_index[(hid, step, variant)]
                claim, context, commit = frame["claim"], frame["context"], frame["commit"]
                policy = frame["operation"].get("policy", "symbol_validate")
                changed = variant == "registered_inputs" and bool(
                    {"expected_source", "scope", "context"} & frame["operation"].keys()
                )
                if variant == "registered_inputs":
                    if changed:
                        witness = None
                        work["registrations"] += 1
                    require(
                        row["registered_changed"] == changed
                        and row["context_hash"] == sha(canonical(context))
                        and row["provenance_hash"] == sha(canonical(provenance)),
                        "registered input/trace binding mismatch",
                    )
                require(
                    row["policy"] == policy
                    and row["previous_state"] == previous
                    and row["prior_witness"] == witness,
                    "state/witness lineage mismatch",
                )
                original = selection(
                    claim, provenance, previous, frame["before"], frame["after"], commit, policy
                )
                effective = copy.deepcopy(original)
                suppressed = False
                reason = None
                if variant != "production" and policy == "symbol_validate":
                    work["eligibility_attempts"] += 1
                    if variant == "registered_inputs":
                        suppressed, reason = registered_decision(
                            original,
                            previous,
                            frame["before"],
                            frame["after"],
                            witness,
                            changed,
                            exact_scope(claim, provenance, context),
                        )
                    else:
                        suppressed, reason = carry_decision(
                            variant,
                            claim,
                            provenance,
                            context,
                            previous,
                            original,
                            frame["before_commit"],
                            commit,
                            frame["before"],
                            frame["after"],
                            witness,
                        )
                    if suppressed:
                        effective.update(selected=False, reasons=[])
                    elif changed:
                        effective.update(
                            selected=True,
                            reasons=sorted(
                                set(original["reasons"]) | {"registered_inputs_changed"}
                            ),
                        )
                    reason_counts[reason] += 1
                require(
                    row["original_selection"] == original
                    and row["effective_selection"] == effective
                    and row["suppressed"] == suppressed
                    and row["audit_reason"] == reason,
                    "selection/witness decision mismatch",
                )
                work["original_selected"] += original["selected"]
                work["effective_selected"] += effective["selected"]
                work["suppressed"] += suppressed
                check_validation(row["fresh"], claim, provenance, commit, frame["after"])
                if effective["selected"]:
                    check_validation(row["validation"], claim, provenance, commit, frame["after"])
                    work["actual_validation_calls"] += 1
                    if variant != "production":
                        work["witness_mint_attempts"] += 1
                        mint_function = (
                            registered_witness if variant == "registered_inputs" else mint
                        )
                        witness = mint_function(claim, provenance, context, commit, frame["after"])
                else:
                    require(row["validation"] is None, "unselected validation executed/consumed")
                state = advance(previous, commit, effective["selected"], row["validation"])
                require(
                    row["state"] == state and row["current_witness"] == witness,
                    "state/current witness recomputation mismatch",
                )
                if policy != "keep_all":
                    fresh_state = advance(previous, commit, True, row["fresh"])
                    require(
                        all(
                            state[key] == fresh_state[key]
                            for key in ["state", "available", "last_verdict", "withheld_reason"]
                        ),
                        "ordinary endpoint differs from fresh production",
                    )
                if suppressed:
                    require(
                        production_verdict(frame["after"], claim)
                        == ("contradicted", "predicate_mismatch"),
                        "suppression lost negative semantics",
                    )
                group_rows["controlled_keep_all" if policy == "keep_all" else "ordinary"].append(
                    row
                )
                previous = state
            endpoint[hid] = [
                previous[key]
                for key in [
                    "state",
                    "available",
                    "last_verdict",
                    "withheld_reason",
                    "last_checked_commit",
                ]
            ]
        counts[variant] = work
        endpoints[variant] = endpoint
        reasons[variant] = {
            ("eligible_negative_carry" if key is None else key): value
            for key, value in reason_counts.items()
        }
        correctness_groups[variant] = {
            name: {
                "records": len(records),
                "false_available": sum(
                    row["state"]["available"] and row["reference"]["verdict"] == "contradicted"
                    for row in records
                ),
                "available_unknown": sum(
                    row["state"]["available"] and row["reference"]["verdict"] == "uncertain"
                    for row in records
                ),
                "withheld_supported": sum(
                    not row["state"]["available"] and row["reference"]["verdict"] == "supported"
                    for row in records
                ),
                "reference_counts": dict(
                    collections.Counter(row["reference"]["verdict"] for row in records)
                ),
                "production_fresh_counts": dict(
                    collections.Counter(row["fresh"]["verdict"] for row in records)
                ),
            }
            for name, records in group_rows.items()
        }
    for hid, case in cases.items():
        for step in range(len(case["steps"])):
            registered = record_index[(hid, step, "registered_inputs")]
            blob = record_index[(hid, step, "module_blob_witness")]
            require(
                registered["state"] == blob["state"]
                and registered["previous_state"] == blob["previous_state"]
                and registered["suppressed"] == blob["suppressed"],
                "registered full-state comparison mismatch",
            )
    expected_work = {
        variant: {"counts": counts[variant], "endpoints": endpoints[variant]}
        for variant in VARIANTS
    }
    require(
        parse((result / "expected-work.json").read_bytes()) == expected_work,
        "per-pack work/endpoint mismatch",
    )
    comparison_result = (
        comparison_result
        or root / "reports/research-20261104/negative-carry-maintenance-evidence-v1"
    ).resolve()
    prior_manifest_raw = (comparison_result / "manifest.json").read_bytes()
    require(
        sha(prior_manifest_raw)
        == "ddee049161424b5da53aa138e4423808d217152bed9923ed3f97dfcb85bd28e5",
        "original comparison result manifest pin mismatch",
    )
    prior_manifest = parse(prior_manifest_raw)
    prior_records_raw = (comparison_result / "correctness.jsonl").read_bytes()
    require(
        sha(prior_records_raw) == prior_manifest["artifact_hashes"]["correctness.jsonl"],
        "original comparison correctness artifact hash mismatch",
    )
    prior_records = [parse(line) for line in prior_records_raw.splitlines() if line.strip()]
    unchanged_records = [row for row in correctness if row["variant"] != "registered_inputs"]
    require(
        len(prior_records) == len(unchanged_records) == 93
        and semantic_projection(prior_records) == semantic_projection(unchanged_records),
        "original three semantic-record comparison mismatch",
    )
    test_counts = {
        name: sum(
            isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
            for node in ast.walk(ast.parse(frozen(name)))
        )
        for name in [
            "tests/test_registered_negative_carry.py",
            "tests/test_negative_structural_carry.py",
        ]
    }
    require(
        test_counts
        == {
            "tests/test_registered_negative_carry.py": 17,
            "tests/test_negative_structural_carry.py": 14,
        },
        "frozen test function inventory mismatch",
    )
    size = plan["histories_per_block"]
    repetitions = plan["paired_repetitions"]
    timing_index = unique_index(
        timings, lambda row: (row["repetition"], row["variant"]), "timing row"
    )
    require(
        len(timings) == 84
        and set(timing_index)
        == {(rep, variant) for rep in range(repetitions) for variant in VARIANTS},
        "paired timing coverage mismatch",
    )
    expected_order = []
    for rep in range(repetitions):
        offset = rep % len(VARIANTS)
        order = list(VARIANTS[offset:] + VARIANTS[:offset])
        if (rep // len(VARIANTS)) % 2:
            order.reverse()
        for position, variant in enumerate(order):
            row = timing_index[(rep, variant)]
            expected_order.append((rep, variant))
            require(
                row["order_position"] == position
                and row["history_pack_repetitions"] == size
                and row["histories_in_pack"] == 17
                and row["actual_history_executions"] == 17 * size
                and row["actual_transition_executions"] == 31 * size,
                "timing workload/order metadata mismatch",
            )
            require(
                row["counts"] == {key: value * size for key, value in counts[variant].items()},
                "timing actual-work count mismatch",
            )
            require(
                all(type(row[unit]) is int and row[unit] > 0 for unit in ["wall_ns", "cpu_ns"]),
                "invalid measured clock value",
            )
    require(
        [(row["repetition"], row["variant"]) for row in timings] == expected_order,
        "timing recorded order mismatch",
    )

    complete_repetitions = (repetitions // len(VARIANTS)) * len(VARIANTS)
    balanced_positions = {
        variant: dict(
            collections.Counter(
                row["order_position"]
                for row in timings
                if row["variant"] == variant and row["repetition"] < complete_repetitions
            )
        )
        for variant in VARIANTS
    }
    require(
        all(
            value
            == {
                position: complete_repetitions // len(VARIANTS) for position in range(len(VARIANTS))
            }
            for value in balanced_positions.values()
        ),
        "four-variant complete-cycle position balance mismatch",
    )

    def distribution(values):
        return {"median": statistics.median(values), "min": min(values), "max": max(values)}

    stats = {
        variant: {
            unit: distribution([row[unit] for row in timings if row["variant"] == variant])
            for unit in ["wall_ns", "cpu_ns"]
        }
        for variant in VARIANTS
    }
    deltas = {}
    ratios = {}
    paired_facts = {}
    for variant in VARIANTS[1:]:
        deltas[variant] = [
            {
                "repetition": rep,
                **{
                    "candidate_minus_baseline_" + unit: timing_index[(rep, variant)][unit]
                    - timing_index[(rep, "production")][unit]
                    for unit in ["wall_ns", "cpu_ns"]
                },
            }
            for rep in range(repetitions)
        ]
        ratios[variant] = {
            unit: {
                "ratio_of_medians": stats[variant][unit]["median"]
                / stats["production"][unit]["median"],
                "paired_ratios": distribution(
                    [
                        timing_index[(rep, variant)][unit] / timing_index[(rep, "production")][unit]
                        for rep in range(repetitions)
                    ]
                ),
            }
            for unit in ["wall_ns", "cpu_ns"]
        }
        paired_facts[variant] = {
            unit: {
                **distribution(
                    [row["candidate_minus_baseline_" + unit] for row in deltas[variant]]
                ),
                "positive_pairs": sum(
                    row["candidate_minus_baseline_" + unit] > 0 for row in deltas[variant]
                ),
                "pairs": repetitions,
            }
            for unit in ["wall_ns", "cpu_ns"]
        }
    profile_work = parse((result / "profiling-work.json").read_bytes())
    require(
        [row["variant"] for row in profile_work] == list(VARIANTS),
        "profiling variant coverage/order",
    )
    profile_evidence = {}
    for variant in VARIANTS:
        profile = parse((result / "profiles" / (variant + ".json")).read_bytes())
        require(
            profile == next(row for row in profile_work if row["variant"] == variant),
            "profile record copy mismatch",
        )
        require(
            profile["phase"] == "separate_limiter_profile"
            and profile["history_pack_repetitions"] == plan["profile_history_pack_repetitions"] == 1
            and profile["actual_history_executions"] == 17
            and profile["included_in_timing_samples"] is False
            and profile["counts"] == counts[variant],
            "profile phase/work metadata mismatch",
        )
        table = pstats.Stats(str(result / "profiles" / (variant + ".prof"))).stats
        for key, value in table.items():
            require(
                value[0] >= 0
                and value[1] >= value[0]
                and all(math.isfinite(value[index]) and value[index] >= 0 for index in [2, 3]),
                "invalid profile function measurement",
            )
            require("/" not in key[0], "profile source paths were not stripped")
        top = sorted(table.items(), key=lambda pair: pair[1][3], reverse=True)[
            : plan["profile_top_functions"]
        ]
        expected_top = [
            {
                "function": f"{key[0]}:{key[1]}:{key[2]}",
                "primitive_calls": value[0],
                "total_calls": value[1],
                "own_seconds": value[2],
                "cumulative_seconds": value[3],
            }
            for key, value in top
        ]
        require(
            profile["top_cumulative_functions"] == expected_top and len(expected_top) == 20,
            "profile top-function metadata mismatch",
        )

        def call_count(filename, function):
            return sum(
                value[1]
                for key, value in table.items()
                if key[0] == filename and key[2] == function
            )

        expected_calls = {
            ("run_registered_negative_carry.py", "run_block"): 1,
            ("registered_negative_carry_challenge.py", "run_history"): 17,
            ("negative_carry_challenge.py", "run_history"): 0
            if variant == "registered_inputs"
            else 17,
            ("policies.py", "select_claims"): 31,
            ("policies.py", "advance_state"): 48 if variant == "registered_inputs" else 31,
            ("validation.py", "validate_claim"): counts[variant]["actual_validation_calls"],
            ("negative_carry_witness.py", "mint_witness"): 0
            if variant == "registered_inputs"
            else counts[variant]["witness_mint_attempts"],
            ("negative_carry_witness.py", "witness_gate"): 0
            if variant == "registered_inputs"
            else counts[variant]["eligibility_attempts"],
        }
        if variant == "registered_inputs":
            expected_calls.update(
                {
                    ("registered_negative_carry.py", "__init__"): 17,
                    ("registered_negative_carry.py", "register"): 48,
                    ("registered_negative_carry.py", "initialize_checked_negative"): 17,
                    ("registered_negative_carry.py", "_initialize_actual"): 17,
                    ("registered_negative_carry.py", "_install_actual"): counts[variant][
                        "witness_mint_attempts"
                    ],
                    ("registered_negative_carry.py", "_carry_reason"): 30,
                    ("registered_negative_carry.py", "step"): 31,
                    ("registered_negative_carry_challenge.py", "negative_record"): 0,
                    ("negative_carry_witness.py", "context_hash"): 0,
                    ("dataclasses.py", "asdict"): 0,
                    ("artifacts.py", "digest"): 39,
                }
            )
            require(
                table[
                    next(
                        key
                        for key in table
                        if key[0] == "registered_negative_carry.py" and key[2] == "immutable"
                    )
                ][0]
                == 3 * counts[variant]["registrations"],
                "profile deep registration count mismatch",
            )
        require(
            all(call_count(*key) == value for key, value in expected_calls.items()),
            "profile actual function-call count mismatch",
        )
        # Bind our own repository functions' filename/line/name metadata to the
        # frozen source, without importing or executing that source.
        own_sources = collections.defaultdict(list)
        for source_name in seal["files"]:
            if source_name.endswith(".py") and (
                source_name.startswith("scripts/") or source_name.startswith("src/cami/")
            ):
                own_sources[Path(source_name).name].append(ast.parse(frozen(source_name)))
        metadata_checked = 0
        for key in table:
            definitions = [
                node
                for source_tree in own_sources.get(key[0], [])
                for node in ast.walk(source_tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == key[2]
            ]
            if definitions:
                require(
                    any(
                        min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
                        == key[1]
                        for node in definitions
                    ),
                    "profile frozen-source function metadata mismatch: " + repr(key),
                )
                metadata_checked += 1
        profile_evidence[variant] = {
            "function_entries": len(table),
            "top_entries_recomputed": len(top),
            "frozen_source_function_metadata_checked": metadata_checked,
            "dependency_or_unattributed_function_entries": len(table) - metadata_checked,
            "source_attribution_limit": "Stripped filenames can collide. Known frozen function names are matched to definition/decorator start lines; other dependency entries retain binary-to-JSON integrity only and have unknown source attribution.",
            "actual_calls": {
                filename + ":" + function: call_count(filename, function)
                for filename, function in expected_calls
            },
            "digest_calls": call_count("artifacts.py", "digest"),
            "context_hash_calls": call_count("negative_carry_witness.py", "context_hash"),
            "asdict_calls": call_count("dataclasses.py", "asdict"),
            "top_functions": expected_top,
        }
    setup = parse((result / "setup.json").read_bytes())
    require(
        setup["histories"] == setup["parent_actual_validation_calls"] == 17
        and setup["transitions"]
        == setup["fresh_comparison_calls"]
        == setup["independent_reference_calls"]
        == 31,
        "setup work metadata mismatch",
    )
    context_costs = setup["candidate_only_context_binding"]
    require(
        len(context_costs) == 17
        and {row["history"] for row in context_costs} == set(cases)
        and all(row["phase"] == "candidate_only_context_binding" for row in context_costs),
        "candidate setup context coverage",
    )
    for unit in ["cpu_ns", "wall_ns"]:
        require(
            setup["candidate_context_binding_" + unit] == sum(row[unit] for row in context_costs)
            and all(row[unit] >= 0 for row in context_costs),
            "candidate context cost sum mismatch",
        )
        require(
            setup[unit] >= setup["candidate_context_binding_" + unit],
            "candidate setup exceeds total setup",
        )
    summary = parse((result / "summary.json").read_bytes())
    below = sum(row["wall_ns"] < plan["minimum_block_ns"] for row in timings)
    require(
        summary["variants"] == stats and summary["paired_deltas"] == deltas,
        "timing summary/paired delta mismatch",
    )
    require(
        summary["error_count"] == 0
        and summary["status"] == "measured_authored_workload"
        and summary["minimum_block_ns"] == plan["minimum_block_ns"]
        and summary["blocks_below_clock_noise_floor"] == below,
        "summary status/clock threshold mismatch",
    )
    require(
        summary["candidate_only_context_binding_setup"] == context_costs
        and summary["profile_work"]
        == [{"variant": variant, "counts": counts[variant]} for variant in VARIANTS],
        "summary setup/profile copies mismatch",
    )
    phases = {
        "correctness_capture": 1,
        "expected_work_calibration": 1,
        "warmup": plan["warmup_blocks"] * size,
        "timed": repetitions * size,
        "separate_profile": plan["profile_history_pack_repetitions"],
    }
    phase_work = {
        phase: {
            variant: {
                "history_pack_repetitions": packs,
                "history_executions": packs * 17,
                "transition_executions": packs * 31,
                "counts": {key: value * packs for key, value in counts[variant].items()},
            }
            for variant in VARIANTS
        }
        for phase, packs in phases.items()
    }
    totals = {
        key: sum(counts[variant].get(key, 0) * sum(phases.values()) for variant in VARIANTS)
        for key in (*COUNTERS, "registrations", "checked_result_imports")
    }
    total_validation = (
        totals["actual_validation_calls"]
        + setup["parent_actual_validation_calls"]
        + setup["fresh_comparison_calls"]
    )
    elapsed_ns = round(
        (
            datetime.fromisoformat(manifest["finished_at"])
            - datetime.fromisoformat(manifest["started_at"])
        ).total_seconds()
        * 1_000_000_000
    )
    measured_wall_ns = sum(row["wall_ns"] for row in timings)
    require(
        elapsed_ns >= setup["wall_ns"] + measured_wall_ns,
        "summed measured regions exceed run wall interval",
    )
    review = frozen_source_review(frozen)
    return {
        "schema_version": 1,
        "status": "pass",
        "frozen_result_manifest_sha256": sha((result / "manifest.json").read_bytes()),
        "protocol_sha256": PROTOCOL_SHA,
        "seal_sha256": SEAL_SHA,
        "implementation_commit": IMPLEMENTATION_COMMIT,
        "integrity": {
            "artifact_files_hashed": len(actual),
            "sealed_inputs_hashed": len(seal["files"]),
            "historical_source_files_hashed": len(historical),
            "historical_fallback_paths": inputs.history,
            "git_object_directories_in_artifact_hashes": False,
            "dangling_symlinks_in_artifact_hashes": False,
        },
        "authored_git_verification": {
            "status": "pass",
            "fixture_directory": str(fixture_root),
            "histories": len(cases),
            "snapshots": len(snapshots),
            "reference_packets": len(expected_packet_dirs),
            "commit_ids_by_history": authorized_ids,
            "scope": "Only self-contained authored fixture repositories; complete source trees checked against protocol operations. No corpus repository reads. Git object directories are outside file-hash inventory; object IDs and protocol-derived trees are checked separately.",
        },
        "correctness_rows": len(correctness),
        "comparison_checks": {
            "unchanged_source_files": len(plan["original_implementation_hashes"]),
            "unchanged_workload_fields": workload_fields,
            "original_three_semantic_records": 93,
            "original_result_manifest_sha256": sha(prior_manifest_raw),
            "registered_full_state_pairs_against_module_blob": 31,
        },
        "test_inventory": {
            "frozen_test_functions": test_counts,
            "passing_tests_declared_by_protocol": {"new_registered": 17, "original_comparison": 14},
            "audit_executed_these_tests": False,
            "limitation": "Function counts and frozen protocol declarations are checked separately; this audit does not independently prove the historical test executions.",
        },
        "complete_cycle_variant_position_counts": balanced_positions,
        "variant_position_counts": {
            variant: dict(
                collections.Counter(
                    row["order_position"] for row in timings if row["variant"] == variant
                )
            )
            for variant in VARIANTS
        },
        "correctness_by_variant_and_policy": correctness_groups,
        "per_pack_counts": counts,
        "witness_reason_counts": reasons,
        "timing_rows": len(timings),
        "paired_repetitions": repetitions,
        "timing_distributions_ns": stats,
        "candidate_to_baseline_ratios": ratios,
        "paired_delta_distributions_ns": paired_facts,
        "paired_deltas": deltas,
        "clock_threshold": {
            "minimum_wall_block_ns": plan["minimum_block_ns"],
            "wall_blocks_below_threshold": below,
            "cpu_blocks_below_same_threshold": sum(
                row["cpu_ns"] < plan["minimum_block_ns"] for row in timings
            ),
            "minimum_observed_wall_ns": min(row["wall_ns"] for row in timings),
            "minimum_observed_cpu_ns": min(row["cpu_ns"] for row in timings),
        },
        "setup": setup,
        "clock_region_totals": {
            "manifest_elapsed_wall_ns": elapsed_ns,
            "summed_timed_wall_ns": measured_wall_ns,
            "summed_timed_cpu_ns": sum(row["cpu_ns"] for row in timings),
            "setup_wall_ns": setup["wall_ns"],
        },
        "setup_work_inferred_from_frozen_source": {
            "snapshot_reads": 48,
            "index_builds_including_fresh_comparisons": 79,
            "index_comparisons": 31,
            "context_bindings": 17,
            "implementation_file_hash_reads": 85,
            "parent_and_fresh_validation_calls": 48,
            "independent_reference_calls": 31,
        },
        "maintenance_history_pack_repetitions_per_variant_all_phases": sum(phases.values()),
        "phase_work": phase_work,
        "maintenance_total_counts": totals,
        "all_phase_actual_validation_calls_including_setup": total_validation,
        "profile_evidence": profile_evidence,
        "frozen_source_measurement_review": review,
        "bounded_finding": "All three candidates execute fewer structural validations per pack but have larger median CPU and wall maintenance times; every paired CPU/wall delta is positive in this run. This is an authored workload result, not a corpus or adoption recommendation.",
        "limits": [
            "No benchmark or production/reference code was executed by this auditor; recorded elapsed times cannot be independently reconstructed from outputs.",
            "Work counts for untimed capture/calibration/warmup phases are inferred from the frozen schedule and independently checked per-pack transitions; profiling corroborates one separate actual execution per variant.",
            "The recorded source-before/after snapshots, hashes and historical Git commit bind source identity but cannot prove past execution or timing honesty.",
            "Shared CPython ast and the narrow authored syntax limit semantic independence; this is not a runtime-behavior oracle or an exhaustive cross-product test.",
            "The keep_all transition is a deliberate control with one withheld-supported state per variant; ordinary policy transitions are reported separately.",
            "cProfile is one instrumented post-timing history pack per variant. Cumulative times overlap along call trees; they must not be summed indiscriminately or treated as measured timing samples.",
            "Shared-host variability remains; paired ordering and 21 repetitions do not establish population generalization, significance, or end-to-end corpus savings.",
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
    parser.add_argument("--result", type=Path, default=Path(DEFAULT_RESULT))
    parser.add_argument(
        "--git-fixtures",
        type=Path,
        help="Raw authored git-fixtures directory if --result is the file-only mirror.",
    )
    parser.add_argument(
        "--comparison-result",
        type=Path,
        help="Original negative-carry file-only result for semantic comparison.",
    )
    parser.add_argument(
        "--out", type=Path, help="Create a new report file; refuse an existing file."
    )
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        report = audit(
            root,
            (root / args.result).resolve(),
            args.git_fixtures.resolve() if args.git_fixtures else None,
            (root / args.comparison_result).resolve() if args.comparison_result else None,
        )
    except Exception as error:
        report = {"status": "fail", "error": type(error).__name__ + ": " + str(error)}
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        with args.out.open("x") as stream:
            stream.write(encoded)
    else:
        print(encoded, end="")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
