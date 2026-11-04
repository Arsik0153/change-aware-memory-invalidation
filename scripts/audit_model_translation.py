#!/usr/bin/env python3
"""Post hoc stdlib audit of saved model/engine correspondence; imports no CAMI code."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file())
STAGING = Path(__file__).resolve().parent
GRAPH = re.compile(r"(exact_binary|sound_positive_only)-K(1|2|4|8)\.json\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")
EXPECTED_COUNTS = {"source_transitions": 403, "canonical_memory_contexts": 76, "translation_cases": 499}
MODEL_NAMES = {f"{model}-K{interval}" for model in ("exact_binary", "sound_positive_only") for interval in (1, 2, 4, 8)}
REASON = {"supported": "modeled_supported", "contradicted": "modeled_contradiction",
          "insufficient_evidence": "modeled_insufficient"}


class AuditError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


def require(condition: bool, code: str, detail: str) -> None:
    if not condition:
        raise AuditError(code, detail)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def same(left: Any, right: Any) -> bool:
    return canonical(left) == canonical(right)


def equal(actual: Any, expected: Any, code: str, context: str) -> None:
    require(same(actual, expected), code, context)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in items:
        require(key not in result, "duplicate_json_key", key)
        result[key] = value
    return result


def read(path: Path) -> Any:
    def reject_constant(value: str) -> None:
        raise AuditError("nonfinite_json", value)
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=reject_constant)


def write_new(path: Path, value: Any) -> None:
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def contained(base: Path, relative: str) -> Path:
    require(isinstance(relative, str) and bool(relative), "unsafe_path", repr(relative))
    path = PurePosixPath(relative)
    require(not path.is_absolute() and ".." not in path.parts and path.as_posix() == relative
            and "\\" not in relative and "\x00" not in relative, "unsafe_path", relative)
    resolved = (base / relative).resolve(strict=True)
    require(resolved.is_relative_to(base.resolve()) and resolved.is_file(), "unsafe_path", relative)
    return resolved


def verify_hashes(base: Path, inventory: dict[str, str]) -> int:
    require(isinstance(inventory, dict) and bool(inventory), "hash_inventory", str(base))
    for relative, expected in inventory.items():
        require(isinstance(expected, str) and HEX.fullmatch(expected) is not None, "hash_shape", relative)
        require(sha(contained(base, relative)) == expected, "hash_mismatch", relative)
    return len(inventory)


def verify_snapshot(manifest: dict[str, Any]) -> None:
    before, after = manifest["source_before"], manifest["source_after"]
    equal(before, after, "source_changed", "saved source snapshots differ")
    require(before["source_status"] == "", "dirty_source", "runtime snapshot was not committed")
    require(re.fullmatch(r"[0-9a-f]{40}", before["git_head"]) is not None, "source_identity", "invalid Git object ID")
    require(all(isinstance(value, str) and HEX.fullmatch(value) for value in before["files"].values()),
            "source_identity", "missing or malformed source file hashes")
    # This is the independently reproduced encoding of verify_cami's snapshot digest.
    encoded = json.dumps(before["files"], sort_keys=True, ensure_ascii=True).encode()
    equal(before["sha256"], hashlib.sha256(encoded).hexdigest(), "source_identity", "snapshot inventory digest differs")


def variants(state: dict[str, Any]) -> tuple[str, ...]:
    return ("supported",) if state["available"] else ("contradicted", "insufficient_evidence")


def state_name(truth: bool, available: bool, age: int) -> str:
    return f"t{int(truth)}:a{int(available)}@{age}"


def check_model_state(state: dict[str, Any], interval: int) -> None:
    equal(sorted(state), ["age", "available", "state_id", "truth"], "model_state", "unexpected state fields")
    require(type(state["truth"]) is bool and type(state["available"]) is bool,
            "model_state", "truth and availability must be booleans")
    require(type(state["age"]) is int and 0 <= state["age"] < interval, "model_state", "invalid age")
    equal(state["state_id"], state_name(state["truth"], state["available"], state["age"]),
          "model_state", "incorrect state ID")


def predecessor(interval: int, source: dict[str, Any], variant: str, hint: bool) -> tuple[list[str], dict[str, Any]]:
    history = [f"synthetic-revision-{number:04d}" for number in range(interval + 3)]
    checked = history[interval + 1 - source["age"]]
    provenance = {"schema_version": 1, "claim_id": "synthetic-behavior-claim", "scenario_id": "synthetic-translation",
                  "anchors": [{"path": "synthetic.py", "qualname": "subject", "scope": "symbol",
                               "observed_commit": history[0], "content_hash": "0" * 64, "origin": "manual",
                               "start_line": None, "end_line": None}],
                  "dependencies": [], "known_incomplete": hint, "unresolved_reasons": []}
    return history, {"schema_version": 1, "claim_id": "synthetic-behavior-claim", "revision": history[interval + 1],
                     "state": "valid" if source["available"] else ("stale" if variant == "contradicted" else "needs_validation"),
                     "last_checked_commit": checked, "last_supported_commit": checked if source["available"] else history[0],
                     "last_verdict": variant, "basis": "carried_forward" if source["age"] > 0 else "validated",
                     "current_provenance": provenance, "available": source["available"],
                     "withheld_reason": None if source["available"] else REASON[variant]}


def manual_step(previous: dict[str, Any], current: str, verdict: str | None) -> dict[str, Any]:
    result = copy.deepcopy(previous)
    result.update(revision=current, basis="carried_forward")
    if verdict is not None:
        result.update(last_checked_commit=current, last_verdict=verdict, basis="validated",
                      state={"supported": "valid", "contradicted": "stale", "insufficient_evidence": "needs_validation"}[verdict],
                      available=verdict == "supported", withheld_reason=None if verdict == "supported" else REASON[verdict])
        if verdict == "supported":
            result["last_supported_commit"] = current
    return result


def validation_input(edge: dict[str, Any], current: str) -> dict[str, Any] | None:
    verdict = edge["verdict"]
    if verdict is None:
        return None
    return {"schema_version": 1, "claim_id": "synthetic-behavior-claim", "commit": current,
            "validator": "modeled_input_not_a_probe", "verdict": verdict, "reason": REASON[verdict],
            "evidence": ["Synthetic model input, not independent truth evidence."],
            "input_hash": hashlib.sha256(canonical(edge)).hexdigest(), "duration_seconds": 0.0, "cpu_seconds": 0.0,
            "test_executions": 0, "input_tokens": 0, "output_tokens": 0, "logs": [], "cache_hit": False,
            "original_measurement": None}


def independently_prepare(graphs: dict[str, tuple[str, dict[str, Any]]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], int]:
    cases, contexts = {}, {}
    edge_count = 0
    for model, (relative, graph) in sorted(graphs.items()):
        interval = graph["interval"]
        states = {}
        for state in graph["states"]:
            check_model_state(state, interval)
            require(state["state_id"] not in states, "model_state", "duplicate state ID")
            states[state["state_id"]] = state
            for variant in variants(state):
                history, previous = predecessor(interval, state, variant, False)
                key = f"{model}/{state['state_id']}/{variant}"
                contexts[key] = {"id": key, "model": model, "source_state": state, "predecessor_metadata": variant,
                                 "history": history, "previous": previous}
        require(graph["initial_state"] in states, "model_state", "missing initial state")
        equal(graph["state_count"], len(states), "model_counts", model)
        equal(graph["transition_count"], len(graph["transitions"]), "model_counts", model)
        for index, edge in enumerate(graph["transitions"]):
            equal(sorted(edge), ["audit_due", "baseline_trigger", "from", "next_truth", "selected", "to", "verdict"],
                  "model_edge", "unexpected fields")
            require(edge["from"] in states and edge["to"] in states, "model_edge", "missing endpoint")
            source, target = states[edge["from"]], states[edge["to"]]
            require(all(type(edge[key]) is bool for key in ("audit_due", "baseline_trigger", "next_truth", "selected")),
                    "model_edge", "nonboolean transition metadata")
            due = source["age"] + 1 >= interval
            selected = edge["baseline_trigger"] or not source["available"] or due
            equal(edge["audit_due"], due, "model_edge", "deadline formula")
            equal(edge["selected"], selected, "model_edge", "selection formula")
            equal(edge["next_truth"], target["truth"], "model_edge", "target truth")
            verdict = edge["verdict"]
            require((isinstance(verdict, str) and verdict in REASON) if selected else verdict is None,
                    "model_edge", "verdict exists exactly when selected")
            equal(target["available"], verdict == "supported" if selected else source["available"],
                  "model_edge", "availability formula")
            equal(target["age"], 0 if selected else source["age"] + 1, "model_edge", "age formula")
            if selected:
                require(verdict != "supported" or target["truth"], "model_edge", "positive soundness")
                if model.startswith("exact_binary"):
                    equal(verdict, "supported" if target["truth"] else "contradicted", "model_edge", "exact binary contract")
            edge_count += 1
            for variant in variants(source):
                key = f"{model}/edge-{index:04d}/{variant}"
                history, previous = predecessor(interval, source, variant, edge["baseline_trigger"])
                reasons = sorted([name for name, needed in (("known_incomplete", edge["baseline_trigger"]),
                                  ("previously_unavailable", not source["available"]), ("periodic_audit", due)) if needed])
                cases[key] = {"id": key, "model": model, "source_graph": relative, "source": source,
                              "target": target, "edge_index": index, "edge": edge, "variant": variant,
                              "history": history, "previous": previous, "reasons": reasons,
                              "selection": {"schema_version": 1, "claim_id": previous["claim_id"],
                                            "commit": history[-1], "selected": selected, "reasons": reasons},
                              "expected_state": manual_step(previous, history[-1], verdict)}
    return cases, contexts, edge_count


def index_unique(rows: Any, expected: set[str], code: str) -> dict[str, dict[str, Any]]:
    require(isinstance(rows, list), code, "expected a list")
    indexed = {}
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get("id"), str), code, "invalid record ID")
        require(row["id"] not in indexed, code, "duplicate ID: " + row["id"])
        indexed[row["id"]] = row
    require(set(indexed) == expected, code,
            f"exact ID coverage differs: missing={sorted(expected-set(indexed))[:3]}, extra={sorted(set(indexed)-expected)[:3]}")
    return indexed


def verify_report(saved: dict[str, Any], case: dict[str, Any], *, mutation: str | None = None) -> list[dict[str, Any]]:
    key = case["id"]
    equal(saved["previous"], case["previous"], "predecessor_metadata", key)
    equal(saved["modeled_target"], case["target"], "target_metadata", key)
    equal(saved["expected_reasons"], case["reasons"], "expected_metadata", key)
    equal(saved["expected_state"], case["expected_state"], "expected_metadata", key)
    actual_selection = copy.deepcopy(case["selection"])
    actual_state = copy.deepcopy(case["expected_state"])
    expected_input = validation_input(case["edge"], case["history"][-1])
    if mutation == "suppress_periodic_deadline":
        require(case["source"]["available"] and not case["edge"]["baseline_trigger"] and case["edge"]["audit_due"],
                "control_witness", key)
        actual_selection.update(selected=False, reasons=[])
        actual_state = manual_step(case["previous"], case["history"][-1], None)
        expected_input = None
    elif mutation == "carry_previous_availability_after_insufficient":
        require(case["source"]["available"] and case["edge"]["verdict"] == "insufficient_evidence",
                "control_witness", key)
        actual_state["available"] = case["previous"]["available"]
    equal(saved["selection"], actual_selection, "selection_transition", key)
    equal(saved["actual_state"], actual_state, "state_transition", key)
    equal(saved["validation_input"], expected_input, "validation_metadata", key)
    actual = saved["actual_state"]
    require(actual["last_checked_commit"] in case["history"], "state_transition", "unknown last checked revision")
    age = len(case["history"]) - 1 - case["history"].index(actual["last_checked_commit"])
    equal(saved["projected_age"], age, "projected_age", key)
    comparisons = {
        "selection_claim_id": (saved["selection"]["claim_id"], case["previous"]["claim_id"]),
        "selection_revision": (saved["selection"]["commit"], case["history"][-1]),
        "selection_selected": (saved["selection"]["selected"], case["edge"]["selected"]),
        "selection_reasons": (saved["selection"]["reasons"], case["reasons"]),
        "model_availability": (actual["available"], case["target"]["available"]),
        "model_age": (age, case["target"]["age"]),
        "previous_unmodified": (saved["previous"], case["previous"]),
        **{f"state.{name}": (actual[name], expected) for name, expected in case["expected_state"].items()}}
    recomputed = {name: same(actual_value, expected) for name, (actual_value, expected) in comparisons.items()}
    equal(saved["checks"], recomputed, "forged_checks", key)
    equal(saved["passed"], all(recomputed.values()), "forged_passed_flag", key)
    require(all(recomputed.values()) if mutation is None else not all(recomputed.values()),
            "correspondence", key)
    return [{"check": name, "actual": actual_value, "expected": expected}
            for name, (actual_value, expected) in comparisons.items() if not same(actual_value, expected)]


def audit(report: Path, repo: Path) -> dict[str, Any]:
    report, repo = report.resolve(), repo.resolve()
    manifest_path = contained(report, "manifest.json")
    manifest_digest = sha(manifest_path)
    manifest = read(manifest_path)
    equal(manifest["status"], "complete", "run_status", "translation report incomplete")
    verify_snapshot(manifest)
    require(manifest["checker_sha256"] == manifest["source_before"]["files"]["scripts/check_model_translation.py"],
            "checker_identity", "checker hash differs from runtime snapshot")
    for name in ("actual_probe_executions", "production_policy_changed", "evaluation_eligible"):
        equal(manifest[name], 0 if name == "actual_probe_executions" else False, "run_scope", name)
    equal(manifest["input_kind"], "modeled_validation_results_not_probes", "run_scope", "input kind")
    expected_artifacts = {"protocol.json", "canonical_contexts.json", "translations.json", "negative_controls.json", "summary.json"}
    equal(set_as_list(manifest["artifact_hashes"]), sorted(expected_artifacts), "artifact_inventory", "unexpected manifest artifact set")
    actual_files = {path.relative_to(report).as_posix() for path in report.rglob("*") if path.is_file()}
    equal(sorted(actual_files), sorted(expected_artifacts | {"manifest.json"}), "artifact_inventory", "actual file set differs")
    artifact_checks = verify_hashes(report, manifest["artifact_hashes"])
    protocol = read(contained(report, "protocol.json"))
    equal(sha(contained(report, "protocol.json")), manifest["protocol_sha256"], "protocol_identity", "retained protocol")
    equal(manifest["protocol_sha256"], sha(contained(repo, "examples/behavior_dependency/translation_protocol.json")),
          "protocol_identity", "current frozen protocol differs")
    equal(protocol["experiment"], "finite-model-to-engine-translation-v1", "protocol_identity", "experiment")
    equal(protocol["schema_version"], 1, "protocol_identity", "schema version")
    equal(manifest["input_hashes"], protocol["input_sha256"], "input_inventory", "manifest differs from frozen protocol")
    input_checks = verify_hashes(repo, manifest["input_hashes"])
    model_manifests = [relative for relative in manifest["input_hashes"] if Path(relative).name == "manifest.json"]
    require(len(model_manifests) == 1, "input_inventory", "expected one model manifest")
    model_manifest_path = contained(repo, model_manifests[0])
    model_manifest = read(model_manifest_path)
    equal(model_manifest["status"], "complete", "model_run", "incomplete model run")
    verify_snapshot(model_manifest)
    model_artifact_checks = verify_hashes(model_manifest_path.parent, model_manifest["artifact_hashes"])
    equal(model_manifest["actual_probe_executions"], 0, "model_run", "model probes")
    graphs = {}
    graph_hashes = {}
    model_summary = None
    for relative, expected in manifest["input_hashes"].items():
        name = Path(relative).name
        if name == "manifest.json":
            continue
        path = contained(repo, relative)
        equal(path.parent.as_posix(), model_manifest_path.parent.as_posix(), "input_inventory", "model artifact outside source directory")
        equal(model_manifest["artifact_hashes"][name], expected, "model_run", "artifact binding")
        if name == "summary.json":
            model_summary = read(path)
            continue
        match = GRAPH.fullmatch(name)
        require(match is not None, "input_inventory", "unexpected frozen input: " + relative)
        graph = read(path)
        equal(graph["interval"], int(match[2]), "model_run", "interval identity")
        require(Path(name).stem not in graphs, "input_inventory", "duplicate model identity")
        graphs[Path(name).stem] = (relative, graph)
        graph_hashes[relative] = expected
    equal(sorted(graphs), sorted(MODEL_NAMES), "input_inventory", "missing model or interval")
    require(isinstance(model_summary, dict), "model_run", "missing model summary")
    equal(model_summary["actual_probe_executions"], 0, "model_run", "model summary probes")
    equal(sorted(model_summary["models"]), sorted(graphs), "model_run", "summary model coverage")
    for name, (_, graph) in graphs.items():
        for key in ("interval", "state_count", "transition_count"):
            equal(model_summary["models"][name][key], graph[key], "model_run", name + ": " + key)
    cases, contexts, source_edges = independently_prepare(graphs)
    counts = {"source_transitions": source_edges, "canonical_memory_contexts": len(contexts), "translation_cases": len(cases)}
    equal(counts, EXPECTED_COUNTS, "derived_counts", "frozen population differs")
    for key, value in counts.items():
        equal(protocol[f"expected_{key}"], value, "derived_counts", "protocol: " + key)
        equal(manifest[key], value, "derived_counts", "manifest: " + key)
    recorded_contexts = index_unique(read(contained(report, "canonical_contexts.json")), set(contexts), "context_coverage")
    for key, expected in contexts.items():
        equal(recorded_contexts[key], expected, "canonical_metadata", key)
    rows = index_unique(read(contained(report, "translations.json")), set(cases), "edge_variant_coverage")
    for key, expected in cases.items():
        saved = rows[key]
        for name, value in (("source_graph", expected["source_graph"]), ("edge_index", expected["edge_index"]),
                            ("source_graph_sha256", graph_hashes[expected["source_graph"]]),
                            ("predecessor_metadata", expected["variant"]), ("model_edge", expected["edge"])):
            equal(saved[name], value, "edge_lineage", key + ": " + name)
        verify_report(saved, expected)
    controls = read(contained(report, "negative_controls.json"))
    control_names = {"suppress_periodic_deadline", "carry_previous_availability_after_insufficient"}
    equal(sorted(controls), sorted(control_names), "control_coverage", "negative controls")
    mismatches = {}
    for name, control in controls.items():
        require(control["witness_case"] in cases, "control_witness", name)
        case = cases[control["witness_case"]]
        concrete = verify_report(control["report"], case, mutation=name)
        require(bool(concrete), "control_detection", name)
        equal(control["detected"], True, "control_detection", name)
        equal(sorted(control["failed_checks"]), sorted(item["check"] for item in concrete), "control_detection", name)
        mismatches[name] = {"witness_case": case["id"], "mismatches": concrete}
    summary = read(contained(report, "summary.json"))
    for key, value in {**counts, "status": "complete", "matched_cases": len(cases), "negative_controls_detected": 2,
                       "actual_probe_executions": 0, "models": sorted(graphs), "limits": protocol["limits"]}.items():
        equal(summary[key], value, "summary", key)
    # Seal checks bracket the independent semantic pass as well.
    equal(sha(manifest_path), manifest_digest, "report_changed", "manifest changed during audit")
    verify_hashes(report, manifest["artifact_hashes"])
    verify_hashes(repo, manifest["input_hashes"])
    return {"status": "passed", "audit_kind": "post_hoc_independent_stdlib_translation_audit", **counts,
            "artifact_hashes_checked": artifact_checks, "input_hashes_checked": input_checks,
            "source_model_artifact_hashes_checked": model_artifact_checks,
            "source_commit": manifest["source_before"]["git_head"], "source_inventory_digest": manifest["source_before"]["sha256"],
            "report_manifest_sha256": manifest_digest, "protocol_sha256": manifest["protocol_sha256"],
            "auditor_sha256": sha(Path(__file__)), "normal_cases_manually_recomputed": len(cases),
            "canonical_contexts_manually_recomputed": len(contexts), "negative_controls": mismatches,
            "limits": ["Post hoc saved-artifact audit; not a new primary experiment.",
                       "No CAMI or original checker imports, validator execution or probe execution.",
                       "Saved previous records are checked against the canonical construction; live object immutability cannot be replayed from JSON.",
                       "Hash consistency and semantic correspondence do not independently prove that saved execution records were produced by the claimed runtime.",
                       "No human review, truth labels, admission decision or universal production-history proof."]}


def set_as_list(value: Any) -> list[str]:
    require(isinstance(value, dict), "artifact_inventory", "expected hash map")
    return sorted(value)


def run_tamper_controls(report: Path, repo: Path) -> list[dict[str, Any]]:
    results = []
    for name in ("missing_edge_variant", "incorrect_metadata", "forged_passed_flag"):
        with tempfile.TemporaryDirectory(dir=STAGING, prefix="rehashed-tamper-") as temporary:
            copied = Path(temporary) / "report"
            shutil.copytree(report, copied)
            artifact = "negative_controls.json" if name == "forged_passed_flag" else "translations.json"
            payload = read(copied / artifact)
            if name == "missing_edge_variant":
                removed = payload.pop()
                detail = {"removed_id": removed["id"]}
            elif name == "incorrect_metadata":
                payload[0]["actual_state"]["last_supported_commit"] = "forged-revision"
                payload[0]["expected_state"]["last_supported_commit"] = "forged-revision"
                # Keep all original `checks` and `passed` declarations true.
                detail = {"modified_id": payload[0]["id"], "field": "last_supported_commit"}
            else:
                control = payload["carry_previous_availability_after_insufficient"]
                control["report"]["passed"] = True
                detail = {"modified_control": "carry_previous_availability_after_insufficient", "field": "report.passed"}
            (copied / artifact).write_bytes(canonical(payload) + b"\n")
            manifest = read(copied / "manifest.json")
            manifest["artifact_hashes"][artifact] = sha(copied / artifact)
            (copied / "manifest.json").write_bytes(canonical(manifest) + b"\n")
            # Explicitly establish that ordinary artifact hashing accepts the mutation.
            verify_hashes(copied, manifest["artifact_hashes"])
            try:
                audit(copied, repo)
            except AuditError as error:
                results.append({"control": name, "detected": True, "artifact_rehashed": artifact,
                                "ordinary_artifact_hashes_passed": True, "failure_code": error.code,
                                "failure": str(error), **detail})
            else:
                raise AuditError("tamper_control_failed", name)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tamper-controls", action="store_true")
    args = parser.parse_args()
    require(not args.out.exists() and not args.out.is_symlink(), "output_exists", str(args.out))
    result = audit(args.report, args.repo_root)
    if args.tamper_controls:
        result["rehashed_tamper_controls"] = run_tamper_controls(args.report, args.repo_root)
        # Confirm the untouched sealed report still passes after all disposable copies.
        equal(audit(args.report, args.repo_root)["report_manifest_sha256"], result["report_manifest_sha256"],
              "report_changed", "original report changed after tamper controls")
    write_new(args.out, result)
    print(json.dumps({key: result[key] for key in ("status", "source_transitions", "translation_cases", "canonical_memory_contexts")}, sort_keys=True))
    print("Independent negative controls:", len(result["negative_controls"]))
    for item in result.get("rehashed_tamper_controls", []):
        print(f"Rehashed tamper caught: {item['control']} -> {item['failure_code']}")


if __name__ == "__main__":
    main()
