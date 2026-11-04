#!/usr/bin/env python3
"""Independent stdlib post hoc audit of the three saved reference alignment runs."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
from typing import Any

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
STAGING = Path(__file__).resolve().parent
RUNS = ("before-v1", "before-v2", "after-v2")
PROTOCOL = "examples/structural_closure/reference_alignment_protocol.json"
ADDENDUM = "examples/structural_closure/reference_alignment_v2_addendum.json"
HEX = re.compile(r"[0-9a-f]{64}\Z")


class AuditError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


def require(condition: bool, code: str, detail: str) -> None:
    if not condition:
        raise AuditError(code, detail)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def equal(actual: Any, expected: Any, code: str, detail: str) -> None:
    require(canonical(actual) == canonical(expected), code, detail)


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in items:
        require(key not in result, "duplicate_json_key", key)
        result[key] = value
    return result


def parse(text: str) -> Any:
    def reject(value: str) -> None:
        raise AuditError("nonfinite_json", value)
    return json.loads(text, object_pairs_hook=pairs, parse_constant=reject)


def read(path: Path) -> Any:
    return parse(path.read_text(encoding="utf-8"))


def read_lines(path: Path) -> list[dict[str, Any]]:
    return [parse(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def safe_relative(value: str) -> None:
    require(isinstance(value, str) and bool(value), "unsafe_path", repr(value))
    path = PurePosixPath(value)
    require(not path.is_absolute() and ".." not in path.parts and path.as_posix() == value
            and "\\" not in value and "\x00" not in value and "\n" not in value, "unsafe_path", value)


def contained(base: Path, relative: str) -> Path:
    safe_relative(relative)
    path = (base / relative).resolve(strict=True)
    require(path.is_relative_to(base.resolve()) and path.is_file(), "unsafe_path", relative)
    return path


def verify_hashes(base: Path, hashes: dict[str, str]) -> None:
    require(isinstance(hashes, dict) and bool(hashes), "hash_inventory", str(base))
    for relative, expected in hashes.items():
        require(isinstance(expected, str) and HEX.fullmatch(expected) is not None, "hash_shape", relative)
        equal(sha(contained(base, relative)), expected, "hash_mismatch", relative)


def git(repo: Path, *arguments: str, data: bytes | None = None) -> bytes:
    return subprocess.check_output(["git", "--no-replace-objects", "--no-optional-locks", "-C", str(repo),
                                    *arguments], input=data)


def historical_source(repo: Path, manifest: dict[str, Any]) -> dict[str, bytes]:
    before = manifest["source_before"]
    equal(before, manifest["source_after"], "runtime_source_changed", "before/after snapshots differ")
    equal(before["source_status"], "", "dirty_runtime_source", "recorded source was dirty")
    require(isinstance(before["git_head"], str) and re.fullmatch(r"[0-9a-f]{40}", before["git_head"]) is not None,
            "source_identity", "invalid historical commit")
    expected = before["files"]
    encoded = json.dumps(expected, sort_keys=True, ensure_ascii=True).encode()
    equal(hashlib.sha256(encoded).hexdigest(), before["sha256"], "source_identity", "source inventory digest")
    names = sorted(expected)
    for name in names:
        safe_relative(name)
        require(isinstance(expected[name], str) and HEX.fullmatch(expected[name]) is not None,
                "source_identity", name)
    queries = b"".join(f"{before['git_head']}:{name}\n".encode() for name in names)
    raw = git(repo, "cat-file", "--batch", data=queries)
    offset, blobs = 0, {}
    for name in names:
        end = raw.index(b"\n", offset)
        header = raw[offset:end].split()
        require(len(header) == 3 and header[1] == b"blob", "historical_blob", name)
        size = int(header[2])
        value = raw[end + 1:end + 1 + size]
        require(len(value) == size and raw[end + 1 + size:end + 2 + size] == b"\n", "historical_blob", name)
        equal(hashlib.sha256(value).hexdigest(), expected[name], "historical_source_hash", name)
        blobs[name] = value
        offset = end + size + 2
    equal(offset, len(raw), "historical_blob", "trailing batch data")
    return blobs


def signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    def dump(value):
        return ast.dump(value, include_attributes=False) if value is not None else None
    args = node.args
    positions = [*args.posonlyargs, *args.args]
    defaults = [None] * (len(positions) - len(args.defaults)) + list(args.defaults)
    parameters = [{"name": arg.arg, "kind": "positional_only" if index < len(args.posonlyargs) else "positional_or_keyword",
                   "default_ast": dump(default), "annotation_ast": dump(arg.annotation)}
                  for index, (arg, default) in enumerate(zip(positions, defaults))]
    if args.vararg:
        parameters.append({"name": args.vararg.arg, "kind": "var_positional", "default_ast": None,
                           "annotation_ast": dump(args.vararg.annotation)})
    parameters += [{"name": arg.arg, "kind": "keyword_only", "default_ast": dump(default), "annotation_ast": dump(arg.annotation)}
                   for arg, default in zip(args.kwonlyargs, args.kw_defaults)]
    if args.kwarg:
        parameters.append({"name": args.kwarg.arg, "kind": "var_keyword", "default_ast": None,
                           "annotation_ast": dump(args.kwarg.annotation)})
    return {"parameters": parameters, "returns_ast": dump(node.returns),
            "decorators_ast": [dump(node) for node in node.decorator_list], "is_async": isinstance(node, ast.AsyncFunctionDef)}


def source_features(source: str, class_mode: str) -> dict[str, Any]:
    tree = ast.parse(source)
    definitions, rebound = [], False

    def class_global(node, deep):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return False
        if isinstance(node, ast.ClassDef) and not deep:
            return False
        return ((isinstance(node, ast.Global) and "f" in node.names)
                or any(class_global(child, deep) for child in ast.iter_child_nodes(node)))

    def visit(node, direct=False):
        nonlocal rebound
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "f":
                definitions.append((node, direct))
            return
        if isinstance(node, (ast.Lambda, ast.ClassDef)):
            if isinstance(node, ast.ClassDef) and class_mode != "none":
                rebound |= any(class_global(statement, class_mode == "deep") for statement in node.body)
            return
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id == "f":
            rebound = True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            rebound |= any(alias.name == "*" or (alias.asname or alias.name.split(".")[0]) == "f" for alias in node.names)
        if isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name == "f":
            rebound = True
        for child in ast.iter_child_nodes(node):
            visit(child)

    for statement in tree.body:
        visit(statement, True)
    ambiguous = rebound or len(definitions) > 1 or any(not direct for _, direct in definitions)
    fingerprint = {"definitions": [ast.dump(node, include_attributes=False) for node, _ in definitions],
                   "direct": [direct for _, direct in definitions], "ambiguous": ambiguous}
    return {"definitions": definitions, "ambiguous": ambiguous, "fingerprint": fingerprint}


def manual_verdict(source: str, kind: str, class_mode: str, expected_signature: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    features = source_features(source, class_mode)
    definitions = features["definitions"]
    facts = {"definition_count": len(definitions), "unconditional_definition_count": sum(direct for _, direct in definitions)}
    if features["ambiguous"]:
        return "uncertain", facts
    facts["exists"] = bool(definitions)
    if not definitions:
        return "contradicted", facts
    facts["signature"] = signature(definitions[0][0])
    return ("supported" if kind == "symbol_exists" or canonical(facts["signature"]) == canonical(expected_signature)
            else "contradicted"), facts


def revision(source: str) -> str:
    return "constructed-" + digest({"source": source, "mode": "100644", "limitation": None})


def claim_for(mutation: str, kind: str, parent: str, expected_signature: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": 1, "claim_id": f"{mutation}:{kind}", "repo_id": "synthetic-carry", "origin_commit": parent,
            "kind": kind, "text": f"Exact syntax: {kind} for f", "scope": "Exact syntactic definition; no runtime claim",
            "subject": {"path": "module.py", "qualname": "f", "node_kind": "function"},
            "predicate": ({"type": kind, "expected": True} if kind == "symbol_exists"
                          else {"type": kind, "expected_signature": expected_signature})}


def provenance(claim_id: str, parent: str, parent_hash: str, file_scope: bool = False) -> dict[str, Any]:
    return {"schema_version": 1, "claim_id": claim_id, "scenario_id": "authored-synthetic", "dependencies": [],
            "known_incomplete": False, "unresolved_reasons": [],
            "anchors": [{"path": "module.py", "qualname": "f", "scope": "file" if file_scope else "symbol",
                         "observed_commit": parent, "content_hash": parent_hash, "origin": "manual", "start_line": None, "end_line": None}]}


def index_unique(rows: list[dict[str, Any]], keys: tuple[str, ...], expected: set[tuple[str, ...]], code: str) -> dict:
    result = {}
    for row in rows:
        key = tuple(row[name] for name in keys)
        require(key not in result, code, "duplicate key " + repr(key))
        result[key] = row
    require(set(result) == expected, code, f"missing={sorted(expected-set(result))[:3]}, extra={sorted(set(result)-expected)[:3]}")
    return result


def verify_validation(result: dict[str, Any], claim: dict[str, Any], prov: dict[str, Any], commit: str,
                      expected_verdict: str, subject_exists: bool, version: str) -> None:
    expected_evidence = [f"{commit}:module.py:f"]
    reason = ("ambiguous_subject" if expected_verdict == "insufficient_evidence" else "predicate_matches" if expected_verdict == "supported"
              else "subject_absent" if not subject_exists else "predicate_mismatch")
    for name, expected in {"schema_version": 1, "claim_id": claim["claim_id"], "commit": commit, "validator": "structural",
                           "verdict": expected_verdict, "reason": reason, "evidence": expected_evidence,
                           "input_hash": digest({"claim": claim, "commit": commit, "evidence": expected_evidence,
                                                 "validator_version": version, "provenance": prov}),
                           "test_executions": 0, "input_tokens": 0, "output_tokens": 0, "logs": [], "cache_hit": False,
                           "original_measurement": None}.items():
        equal(result[name], expected, "production_validation_metadata", claim["claim_id"] + ": " + name)
    require(all(type(result[name]) in (int, float) and result[name] >= 0 for name in ("cpu_seconds", "duration_seconds")),
            "production_validation_metadata", "invalid duration")


def adapted_reference(claim_id: str, child: str, reference: dict[str, Any]) -> dict[str, Any]:
    verdict = reference["verdict"]
    reason = ("reference_uncertain" if verdict == "uncertain" else "subject_absent" if reference["facts"].get("exists") is False
              else "reference_" + verdict)
    return {"schema_version": 1, "claim_id": claim_id, "commit": child, "validator": "research_independent_reference",
            "verdict": "insufficient_evidence" if verdict == "uncertain" else verdict, "reason": reason,
            "evidence": [reference["reason"]], "input_hash": digest(reference), "duration_seconds": 0.0, "cpu_seconds": 0.0,
            "test_executions": 0, "input_tokens": 0, "output_tokens": 0, "logs": [], "cache_hit": False, "original_measurement": None}


def manually_advance(previous: dict[str, Any], child: str, validation: dict[str, Any] | None) -> dict[str, Any]:
    state = copy.deepcopy(previous)
    state.update(revision=child, basis="carried_forward")
    if validation is not None:
        verdict, reason = validation["verdict"], validation["reason"]
        state.update(last_checked_commit=child, last_verdict=verdict, basis="validated", available=verdict == "supported",
                     state="valid" if verdict == "supported" else "retired" if verdict == "contradicted" and reason == "subject_absent"
                     else "stale" if verdict == "contradicted" else "needs_validation",
                     withheld_reason=None if verdict == "supported" else reason)
        if verdict == "supported":
            state["last_supported_commit"] = child
    return state


def metrics(rows: list[dict[str, Any]]) -> dict[str, int]:
    available = [row for row in rows if row["state"]["available"]]
    counts = {"states": len(rows), "selected": sum(row["selection"]["selected"] for row in rows), "available": len(available),
              "available_when_reference_not_supported": sum(row["reference_results"]["child"]["verdict"] != "supported" for row in available),
              "available_when_provably_contradicted": sum(row["reference_results"]["child"]["verdict"] == "contradicted" for row in available),
              "available_when_reference_uncertain": sum(row["reference_results"]["child"]["verdict"] == "uncertain" for row in available)}
    equal(counts["available_when_reference_not_supported"], counts["available_when_provably_contradicted"] + counts["available_when_reference_uncertain"],
          "uncertainty_separation", "unsupported must partition into uncertain and contradicted")
    return counts


def audit_one(report: Path, run_name: str, repo: Path, plan: dict[str, Any], addendum: dict[str, Any]) -> dict[str, Any]:
    manifest_path = contained(report, "manifest.json")
    initial_manifest_hash = sha(manifest_path)
    manifest = read(manifest_path)
    equal(manifest["status"], "complete", "run_status", run_name)
    equal(manifest["produces_labels_or_receipts"], False, "scope", run_name)
    verify_hashes(report, manifest["artifact_hashes"])
    substantive = {p.relative_to(report).as_posix() for p in report.rglob("*") if p.is_file()
                   and "__pycache__" not in p.relative_to(report).parts and p.name != "manifest.json"}
    equal(sorted(substantive), sorted(manifest["artifact_hashes"]), "artifact_inventory", run_name)
    ignored = [p.relative_to(report).as_posix() for p in report.rglob("*") if p.is_file() and "__pycache__" in p.relative_to(report).parts]
    require(all(Path(name).suffix == ".pyc" for name in ignored), "artifact_inventory", "unexpected unsealed cache file")
    equal(sha(contained(report, "protocol.json")), manifest["protocol_sha256"], "protocol_identity", run_name)
    equal(manifest["protocol_sha256"], sha(contained(repo, PROTOCOL)), "protocol_identity", run_name)
    equal(read(contained(report, "protocol.json")), plan, "protocol_identity", run_name)
    equal(manifest["protocol_reference_sha256"], plan["frozen_reference_sha256"], "reference_identity", run_name)
    v1 = run_name == "before-v1"
    expected_reference = addendum["reference_v1_sha256" if v1 else "reference_v2_sha256"]
    equal(manifest["reference_sha256"], expected_reference, "reference_identity", run_name)
    equal(sha(contained(report, "frozen-reference.py")), expected_reference, "reference_identity", run_name)
    equal(manifest["reference_override_explicit"], not v1, "reference_identity", run_name)
    blobs = historical_source(repo, manifest)
    for path_key, hash_key in (("reference_path", "reference_sha256"), ("runner_path", "runner_sha256")):
        relative = Path(manifest[path_key]).relative_to(repo.resolve()).as_posix()
        equal(hashlib.sha256(blobs[relative]).hexdigest(), manifest[hash_key], "source_binding", run_name + ": " + relative)
    source_files = manifest["source_before"]["files"]
    before_fix = run_name != "after-v2"
    for path, pin in (("src/cami/index.py", "before_index_sha256"), ("src/cami/validation.py", "before_validation_sha256")):
        if before_fix:
            equal(source_files[path], addendum[pin], "production_source_pin", run_name + ": " + path)
        else:
            require(source_files[path] != addendum[pin], "production_source_pin", "after source did not change: " + path)
    constants = ast.parse(blobs["src/cami/validation.py"].decode())
    versions = [node.value.value for node in constants.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "VALIDATOR_VERSION" for target in node.targets)
                and isinstance(node.value, ast.Constant)]
    require(len(versions) == 1 and isinstance(versions[0], str), "production_source_pin", "missing validator version")
    validator_version = versions[0]
    expected_signature = signature(ast.parse(plan["parent_source"]).body[0])
    mutations = {row["id"]: row for row in plan["mutations"]}
    require(len(mutations) == len(plan["mutations"]), "protocol_coverage", "duplicate mutation")
    predicates, selectors = plan["predicates"], plan["selector_variants"]
    equal(predicates, ["symbol_exists", "signature_equals"], "protocol_coverage", "predicate set")
    equal(selectors, ["symbol_anchor", "file_anchor", "all_validate"], "protocol_coverage", "selector set")
    inputs = index_unique(read_lines(contained(report, "inputs.jsonl")), ("mutation",), {(name,) for name in mutations}, "input_coverage")
    comparisons = index_unique(read_lines(contained(report, "comparisons.jsonl")), ("mutation", "claim_kind"),
                               {(name, kind) for name in mutations for kind in predicates}, "comparison_coverage")
    states = index_unique(read_lines(contained(report, "states.jsonl")), ("mutation", "claim_kind", "selector_variant"),
                          {(name, kind, selector) for name in mutations for kind in predicates for selector in selectors}, "state_coverage")
    expected_artifacts = {"protocol.json", "inputs.jsonl", "comparisons.jsonl", "states.jsonl", "summary.json", "frozen-reference.py"}
    expected_artifacts |= {f"sources/{name}/{phase}.py" for name in mutations for phase in ("parent", "child")}
    equal(sorted(manifest["artifact_hashes"]), sorted(expected_artifacts), "artifact_inventory", "not every source pair is sealed")
    authored_mismatches = []
    for mutation, definition in mutations.items():
        source_pair = {}
        for phase, source in (("parent", plan["parent_source"]), ("child", definition["child_source"])):
            relative = f"sources/{mutation}/{phase}.py"
            raw = source.encode()
            equal(contained(report, relative).read_bytes().hex(), raw.hex(), "source_bytes", mutation + ": " + phase)
            source_pair[phase] = {"path": relative, "encoding": "utf-8", "source": source,
                                  "byte_count": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        parent, child = revision(plan["parent_source"]), revision(definition["child_source"])
        expected_input = {"mutation": mutation, "parent_revision": parent, "child_revision": child, "sources": source_pair}
        equal(inputs[(mutation,)], expected_input, "input_metadata", mutation)
        for kind in predicates:
            comparison = comparisons[(mutation, kind)]
            claim = claim_for(mutation, kind, parent, expected_signature)
            full_prov = provenance(claim["claim_id"], parent, source_pair["parent"]["sha256"])
            for name, expected in {"claim": claim, "claim_id": claim["claim_id"], "sources": source_pair,
                                   "parent_revision": parent, "child_revision": child, "authored_expected": definition["authored_expected"][kind],
                                   "full_validator_provenance": full_prov, "warm_index_equals_fresh": True}.items():
                equal(comparison[name], expected, "comparison_metadata", mutation + ": " + name)
            changes = comparison["changes"]
            equal(sorted(changes), ["edges", "files", "global_unresolved", "limited_paths", "symbols", "unresolved"], "changes", mutation)
            equal(changes["files"], [] if parent == child else ["module.py"], "changes", mutation + ": files")
            equal(changes["edges"], [], "changes", mutation + ": edges")
            equal(changes["limited_paths"], [], "changes", mutation + ": limitations")
            class_mode = "none" if before_fix else "deep"
            features_parent = source_features(plan["parent_source"], class_mode)
            features_child = source_features(definition["child_source"], class_mode)
            changed_target = canonical(features_parent["fingerprint"]) != canonical(features_child["fingerprint"])
            equal({"path": "module.py", "qualname": "f"} in changes["symbols"], changed_target, "changes", mutation + ": target symbol")
            for phase, source in (("parent", plan["parent_source"]), ("child", definition["child_source"])):
                reference_case = {"id": claim["claim_id"] + ":" + phase, "kind": kind, "subject": claim["subject"],
                                  "predicate": claim["predicate"], "text": claim["text"], "scope": claim["scope"],
                                  "source_path": source_pair[phase]["path"], "source_sha256": source_pair[phase]["sha256"]}
                equal(comparison["reference_cases"][phase], reference_case, "reference_input", mutation + ": " + phase)
                reference = comparison["reference_results"][phase]
                reference_verdict, facts = manual_verdict(source, kind, "shallow" if v1 else "deep", expected_signature)
                for name, expected in {"id": reference_case["id"], "source_sha256": source_pair[phase]["sha256"],
                                       "declared_source_sha256": source_pair[phase]["sha256"], "verdict": reference_verdict, "facts": facts}.items():
                    equal(reference[name], expected, "reference_metadata", mutation + ": " + phase + ": " + name)
                require(isinstance(reference["reason"], str) and bool(reference["reason"]), "reference_metadata", "empty reason")
                equal(reference["checker"]["version"], "1.0.0-development" if v1 else "1.1.0-development", "reference_identity", run_name)
                for evidence in reference["evidence"]:
                    require(type(evidence["start_line"]) is int and type(evidence["end_line"]) is int
                            and 1 <= evidence["start_line"] <= evidence["end_line"] <= len(source.splitlines()), "reference_evidence", mutation)
                production_verdict, production_facts = manual_verdict(source, kind, class_mode, expected_signature)
                verify_validation(comparison["full_validator_results"][phase], claim, full_prov, parent if phase == "parent" else child,
                                  "insufficient_evidence" if production_verdict == "uncertain" else production_verdict,
                                  production_facts.get("exists", False), validator_version)
            ref_child = comparison["reference_results"]["child"]["verdict"]
            mismatch_flags = {"production_reference_parent_mismatch": comparison["full_validator_results"]["parent"]["verdict"] != "supported",
                              "production_reference_child_mismatch": comparison["full_validator_results"]["child"]["verdict"]
                              != ("insufficient_evidence" if ref_child == "uncertain" else ref_child),
                              "reference_authored_expected_mismatch": ref_child != definition["authored_expected"][kind]}
            for name, value in mismatch_flags.items():
                equal(comparison[name], value, "comparison_flags", mutation + ": " + name)
            if mismatch_flags["reference_authored_expected_mismatch"]:
                authored_mismatches.append(claim["claim_id"])
            for selector in selectors:
                row = states[(mutation, kind, selector)]
                for name, value in comparison.items():
                    equal(row[name], value, "state_comparison_binding", mutation + ": " + selector + ": " + name)
                prov = provenance(claim["claim_id"], parent, source_pair["parent"]["sha256"], selector == "file_anchor")
                policy = {"id": "all_validate" if selector == "all_validate" else "symbol_validate", "dependency_depth": 1}
                reasons = (["all_claims"] if selector == "all_validate" else
                           sorted((["subject_changed"] if changed_target else []) +
                                  (["anchor_file_changed"] if selector == "file_anchor" and changes["files"] else
                                   ["symbol_or_dependency_changed"] if selector != "file_anchor" and changed_target else [])))
                selection = {"schema_version": 1, "claim_id": claim["claim_id"], "commit": child,
                             "selected": bool(reasons), "reasons": reasons}
                previous = {"schema_version": 1, "claim_id": claim["claim_id"], "revision": parent, "state": "valid",
                            "last_checked_commit": parent, "last_supported_commit": parent, "last_verdict": "supported", "basis": "validated",
                            "current_provenance": prov, "available": True, "withheld_reason": None}
                validation = adapted_reference(claim["claim_id"], child, comparison["reference_results"]["child"]) if reasons else None
                state = manually_advance(previous, child, validation)
                for name, value in {"policy": policy, "provenance": prov, "previous_state": previous,
                                   "selection": selection, "selected_validation_result": validation, "state": state}.items():
                    equal(row[name], value, "state_transition", mutation + ": " + kind + ": " + selector + ": " + name)
                for name, verdict in (("available_when_reference_not_supported", ref_child != "supported"),
                                      ("available_when_provably_contradicted", ref_child == "contradicted"),
                                      ("available_when_reference_uncertain", ref_child == "uncertain")):
                    equal(row[name], state["available"] and verdict, "uncertainty_metric", mutation + ": " + selector + ": " + name)
    expected_authored_mismatches = sorted(f"nested_class_global:{kind}" for kind in predicates) if v1 else []
    equal(sorted(authored_mismatches), expected_authored_mismatches, "reference_authored_gap", run_name)
    comparisons_list, states_list = list(comparisons.values()), list(states.values())
    measurement_1 = {"comparisons": len(comparisons), "parent_mismatches": sum(row["production_reference_parent_mismatch"] for row in comparisons_list),
                     "child_mismatches": sum(row["production_reference_child_mismatch"] for row in comparisons_list),
                     "reference_authored_expected_mismatches": len(authored_mismatches),
                     "production_child_verdicts": dict(Counter(row["full_validator_results"]["child"]["verdict"] for row in comparisons_list)),
                     "reference_child_verdicts": dict(Counter(row["reference_results"]["child"]["verdict"] for row in comparisons_list))}
    measurement_2 = {"overall": metrics(states_list), "by_selector_variant": {
        selector: metrics([row for row in states_list if row["selector_variant"] == selector]) for selector in selectors}}
    summary = read(contained(report, "summary.json"))
    for name, expected in {"input_pairs": len(inputs), "claim_transitions": len(comparisons), "policy_states": len(states),
                           "measurement_1_full_production_vs_reference": measurement_1,
                           "measurement_2_research_reference_pipeline": measurement_2, "limits": plan["limits"]}.items():
        equal(summary[name], expected, "summary_recomputation", run_name + ": " + name)
    equal([len(inputs), len(comparisons), len(states)], [plan["expected_input_pairs"], plan["expected_claim_transitions"], plan["expected_policy_states"]],
          "protocol_coverage", run_name)
    equal(summary["uncertainty_interpretation"], "Reference uncertain is not proof of a false claim; unavailable support and provable contradiction are separate metrics.",
          "uncertainty_separation", run_name)
    verify_hashes(report, manifest["artifact_hashes"])
    equal(sha(manifest_path), initial_manifest_hash, "report_changed", run_name)
    return {"manifest_sha256": initial_manifest_hash, "source_commit": manifest["source_before"]["git_head"],
            "source_files_verified_against_git": len(blobs), "artifact_hashes_verified": len(manifest["artifact_hashes"]),
            "production_index_sha256": source_files["src/cami/index.py"], "production_validation_sha256": source_files["src/cami/validation.py"],
            "reference_sha256": expected_reference, "unsealed_runtime_bytecode_excluded": ignored,
            "authored_reference_mismatches": authored_mismatches, "recomputed_measurement_1": measurement_1,
            "recomputed_measurement_2": measurement_2, "input_pairs": inputs, "comparisons": comparisons, "states": states}


def audit_all(reports: dict[str, Path], repo: Path) -> dict[str, Any]:
    repo = repo.resolve()
    plan, addendum = read(contained(repo, PROTOCOL)), read(contained(repo, ADDENDUM))
    equal(sha(contained(repo, PROTOCOL)), addendum["original_protocol_sha256"], "addendum_binding", "original protocol hash")
    equal(plan["frozen_reference_sha256"], addendum["reference_v1_sha256"], "addendum_binding", "v1 identity")
    equal([plan["expected_input_pairs"], plan["expected_claim_transitions"], plan["expected_policy_states"]], [21, 42, 126], "protocol_coverage", "frozen counts")
    results = {name: audit_one(reports[name], name, repo, plan, addendum) for name in RUNS}
    before1, before2, after = (results[name] for name in RUNS)
    for name in ("before-v2", "after-v2"):
        current = results[name]
        equal(list(current["input_pairs"].values()), list(before1["input_pairs"].values()), "cross_run_inputs", name)
        for key, baseline in before1["comparisons"].items():
            equal(current["comparisons"][key]["claim"], baseline["claim"], "cross_run_claims", name + ": " + repr(key))
    equal(before2["reference_sha256"], after["reference_sha256"], "cross_run_reference", "v2 changed between before/after")
    for key, row in before2["comparisons"].items():
        equal(row["reference_results"], after["comparisons"][key]["reference_results"], "cross_run_reference", repr(key))
        equal(row["changes"], before1["comparisons"][key]["changes"], "cross_run_production_before", repr(key))
        for phase in ("parent", "child"):
            left, right = row["full_validator_results"][phase], before1["comparisons"][key]["full_validator_results"][phase]
            equal({k:v for k,v in left.items() if k not in ("duration_seconds", "cpu_seconds")},
                  {k:v for k,v in right.items() if k not in ("duration_seconds", "cpu_seconds")}, "cross_run_production_before", repr(key))
    differences = {}
    for label, left, right in (("reference_v1_to_v2_at_before_production", before1, before2),
                               ("production_before_to_after_with_reference_v2_fixed", before2, after)):
        differences[label] = {"measurement_1_child_mismatches_delta": right["recomputed_measurement_1"]["child_mismatches"] - left["recomputed_measurement_1"]["child_mismatches"],
                              "policy_metrics_delta": {selector: {metric: right["recomputed_measurement_2"]["by_selector_variant"][selector][metric]
                                                                               - left["recomputed_measurement_2"]["by_selector_variant"][selector][metric]
                                                                         for metric in left["recomputed_measurement_2"]["overall"]}
                                                       for selector in plan["selector_variants"]},
                              "changed_policy_states": [list(key) for key in left["states"]
                                                        if canonical(left["states"][key]["state"]) != canonical(right["states"][key]["state"])]}
    public = {name: {key:value for key,value in result.items() if key not in ("input_pairs", "comparisons", "states")} for name,result in results.items()}
    return {"status": "passed", "audit_kind": "post_hoc_stdlib_reference_alignment_audit", "auditor_sha256": sha(Path(__file__)),
            "protocol_sha256": sha(contained(repo, PROTOCOL)), "v2_addendum_sha256": sha(contained(repo, ADDENDUM)),
            "coverage_per_run": {"input_pairs": len(before1["input_pairs"]), "claim_transitions": len(before1["comparisons"]), "policy_states": len(before1["states"])},
            "runs": public, "cross_run_immutable_inputs_and_claims": True, "reference_v2_unchanged_before_after": True,
            "differences": differences, "uncertainty_separation": "Available with reference uncertain is unsupported carry, not a proved false claim. Contradicted availability is counted separately.",
            "limits": ["Post hoc saved-artifact audit, not a new primary experiment or independent truth labels.",
                       "No CAMI/checker imports and no source execution; historical source bytes were verified through read-only Git blob reads.",
                       "The bounded AST model cross-checks target f changes and verdicts on these authored sources; ancillary unresolved-node lists are not a new full-parser verification.",
                       "Source hashing does not independently prove historical runtime execution or establish general parser/reference soundness.",
                       "Unsealed __pycache__/*.pyc are disclosed and excluded from evidence; all substantive report/source artifacts must be sealed."]}


def tamper_controls(reports: dict[str, Path], repo: Path) -> list[dict[str, Any]]:
    results = []
    for name in ("wrong_availability", "missing_state_row", "forged_summary", "uncertain_as_proved_false"):
        with tempfile.TemporaryDirectory(dir=STAGING, prefix="rehashed-tamper-") as temporary:
            run_name = "before-v2" if name == "uncertain_as_proved_false" else "after-v2"
            copied = Path(temporary) / run_name
            shutil.copytree(reports[run_name], copied)
            artifact = "summary.json" if name in ("forged_summary", "uncertain_as_proved_false") else "states.jsonl"
            if artifact == "states.jsonl":
                rows = read_lines(copied / artifact)
                if name == "wrong_availability":
                    row = next(row for row in rows if row["selector_variant"] == "symbol_anchor" and row["mutation"] == "class_global")
                    row["state"]["available"] = True
                else:
                    rows.pop()
                (copied / artifact).write_bytes(b"".join(canonical(row) + b"\n" for row in rows))
            else:
                payload = read(copied / artifact)
                overall = payload["measurement_2_research_reference_pipeline"]["overall"]
                if name == "forged_summary":
                    overall["available"] += 1
                else:
                    overall["available_when_provably_contradicted"] += overall["available_when_reference_uncertain"]
                    overall["available_when_reference_uncertain"] = 0
                (copied / artifact).write_bytes(canonical(payload) + b"\n")
            manifest = read(copied / "manifest.json")
            manifest["artifact_hashes"][artifact] = sha(copied / artifact)
            (copied / "manifest.json").write_bytes(canonical(manifest) + b"\n")
            verify_hashes(copied, manifest["artifact_hashes"])
            try:
                plan, addendum = read(contained(repo, PROTOCOL)), read(contained(repo, ADDENDUM))
                audit_one(copied, run_name, repo, plan, addendum)
            except AuditError as error:
                results.append({"control": name, "detected": True, "ordinary_artifact_hashes_passed": True,
                                "artifact_rehashed": artifact, "failure_code": error.code, "failure": str(error)})
            else:
                raise AuditError("tamper_not_detected", name)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--reports-root", type=Path, default=ROOT / "reports/research-20261104")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tamper-controls", action="store_true")
    args = parser.parse_args()
    require(not args.out.exists() and not args.out.is_symlink(), "output_exists", str(args.out))
    reports = {name: args.reports_root / ("reference-alignment-" + name) for name in RUNS}
    head_before = git(args.repo_root, "rev-parse", "HEAD").decode().strip()
    result = audit_all(reports, args.repo_root)
    if args.tamper_controls:
        result["rehashed_tamper_controls"] = tamper_controls(reports, args.repo_root)
    equal(git(args.repo_root, "rev-parse", "HEAD").decode().strip(), head_before, "current_head_changed", "HEAD changed during audit")
    result["head_unchanged_during_audit"] = head_before
    with args.out.open("xb") as stream:
        stream.write(canonical(result) + b"\n")
    print("Post hoc audit:", result["status"], "coverage per run:", result["coverage_per_run"])
    for name, row in result["runs"].items():
        m1, m2 = row["recomputed_measurement_1"], row["recomputed_measurement_2"]
        print(name, "production/reference mismatches:", m1["child_mismatches"], "authored/reference mismatches:", m1["reference_authored_expected_mismatches"],
              "policy metrics:", m2["overall"])
    for row in result.get("rehashed_tamper_controls", []):
        print("Rehashed tamper caught:", row["control"], "->", row["failure_code"])


if __name__ == "__main__":
    main()
