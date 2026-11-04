"""Bounded translation of frozen finite-model transitions to actual CAMI functions."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
from typing import Any, Callable

from cami.artifacts import digest, file_hash, read_json, reserve, within, write_json
from cami.index import ChangeSet
from cami.models import (
    Anchor, Behavior, Claim, MemoryState, PolicyConfig, Provenance, Selection, Subject,
    ValidationResult,
)
from cami.policies import SelectionContext, advance_state, select_claims
from scripts.periodic_audit_adapter import PeriodicAudit
from scripts.verify_cami import source_snapshot

ROOT = next(parent for parent in Path(__file__).resolve().parents
            if (parent / "src/cami/policies.py").is_file())
GRAPH_NAME = re.compile(r"(exact_binary|sound_positive_only)-K([1-9][0-9]*)\.json\Z")
REASONS = {"supported": "modeled_supported", "contradicted": "modeled_contradiction",
           "insufficient_evidence": "modeled_insufficient"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def state_id(state: dict[str, Any]) -> str:
    return f"t{int(state['truth'])}:a{int(state['available'])}@{state['age']}"


def validate_state(state: dict[str, Any], interval: int) -> None:
    require(set(state) == {"state_id", "truth", "available", "age"}, "Unexpected finite-state fields")
    require(type(state["truth"]) is bool and type(state["available"]) is bool, "Finite-state booleans required")
    require(type(state["age"]) is int and 0 <= state["age"] < interval, "Invalid finite-state age")
    require(state["state_id"] == state_id(state), "Finite-state identity mismatch")


def metadata_variants(state: dict[str, Any]) -> tuple[str, ...]:
    return ("supported",) if state["available"] else ("contradicted", "insufficient_evidence")


def canonical_memory(interval: int, source: dict[str, Any], variant: str,
                     baseline_trigger: bool = False) -> tuple[tuple[str, ...], Claim, MemoryState]:
    require(type(interval) is int and interval >= 1, "Positive integer interval required")
    validate_state(source, interval)
    require(variant in metadata_variants(source), "Metadata variant contradicts model availability")
    require(type(baseline_trigger) is bool, "Baseline trigger must be boolean")
    history = tuple(f"synthetic-revision-{index:04d}" for index in range(interval + 3))
    previous_ordinal = interval + 1
    checked = history[previous_ordinal - source["age"]]
    claim = Claim(claim_id="synthetic-behavior-claim", repo_id="synthetic-translation",
                  origin_commit=history[0], kind="behavior_test",
                  text="Modeled validation input only; no probe is executed.",
                  scope="Synthetic finite-model to engine transition correspondence.",
                  subject=Subject(path="synthetic.py", qualname="subject", node_kind="function"),
                  predicate=Behavior(type="behavior_test", probe_path="not-executed.py",
                                     probe_sha256="0" * 64, node_id="not-executed.py::test_model",
                                     environment_id="not-executed"))
    provenance = Provenance(claim_id=claim.claim_id, scenario_id="synthetic-translation",
                            anchors=(Anchor(path="synthetic.py", qualname="subject", scope="symbol",
                                            observed_commit=history[0], content_hash="0" * 64,
                                            origin="manual"),),
                            known_incomplete=baseline_trigger)
    state = "valid" if source["available"] else ("stale" if variant == "contradicted" else "needs_validation")
    previous = MemoryState(claim_id=claim.claim_id, revision=history[previous_ordinal], state=state,
                           last_checked_commit=checked,
                           last_supported_commit=checked if source["available"] else history[0],
                           last_verdict=variant, basis="carried_forward" if source["age"] else "validated",
                           current_provenance=provenance,
                           available=source["available"],
                           withheld_reason=None if source["available"] else REASONS[variant])
    return history, claim, previous


@dataclass(frozen=True)
class TranslationCase:
    interval: int
    source: dict[str, Any]
    target: dict[str, Any]
    edge: dict[str, Any]
    variant: str
    history: tuple[str, ...]
    context: SelectionContext
    policy: PolicyConfig
    result: ValidationResult | None
    expected_reasons: tuple[str, ...]
    expected_state: dict[str, Any]


def translate_edge(interval: int, source: dict[str, Any], target: dict[str, Any],
                   edge: dict[str, Any], variant: str) -> TranslationCase:
    validate_state(target, interval)
    require(set(edge) == {"from", "to", "baseline_trigger", "audit_due", "selected", "verdict", "next_truth"},
            "Unexpected transition fields")
    require(edge["from"] == source["state_id"] and edge["to"] == target["state_id"], "Transition endpoint mismatch")
    require(all(type(edge[key]) is bool for key in ("baseline_trigger", "audit_due", "selected", "next_truth")),
            "Transition booleans required")
    require(edge["next_truth"] == target["truth"], "Transition target truth mismatch")
    due = source["age"] + 1 >= interval
    selected = edge["baseline_trigger"] or not source["available"] or due
    require(edge["audit_due"] == due and edge["selected"] == selected, "Model selection formula mismatch")
    verdict = edge["verdict"]
    require((isinstance(verdict, str) and verdict in REASONS) if selected else verdict is None,
            "Modeled verdict must exist exactly when selected")
    next_available = verdict == "supported" if selected else source["available"]
    next_age = 0 if selected else source["age"] + 1
    require((target["available"], target["age"]) == (next_available, next_age), "Model availability/age formula mismatch")
    history, claim, previous = canonical_memory(interval, source, variant, edge["baseline_trigger"])
    current = history[interval + 2]
    context = SelectionContext(commit=current, claims=(claim,), provenance=(previous.current_provenance,),
                               previous=(previous,), changes=ChangeSet(frozenset(), frozenset(), (),
                                                                      frozenset(), frozenset(), False),
                               protocol_version="1.1")
    reasons = tuple(sorted(reason for reason, present in (
        ("known_incomplete", edge["baseline_trigger"]),
        ("previously_unavailable", not source["available"]), ("periodic_audit", due)) if present))
    result = None if verdict is None else ValidationResult(
        claim_id=claim.claim_id, commit=current, validator="modeled_input_not_a_probe", verdict=verdict,
        reason=REASONS[verdict], evidence=("Synthetic model input, not independent truth evidence.",),
        input_hash=digest(edge), duration_seconds=0, test_executions=0)
    # Declarative expected record; do not derive it by invoking advance_state.
    expected = previous.model_dump(mode="json")
    expected.update(revision=current, basis="validated" if selected else "carried_forward")
    if selected:
        expected.update(last_checked_commit=current, last_verdict=verdict,
                        state={"supported": "valid", "contradicted": "stale",
                               "insufficient_evidence": "needs_validation"}[verdict],
                        available=verdict == "supported",
                        withheld_reason=None if verdict == "supported" else REASONS[verdict])
        if verdict == "supported":
            expected["last_supported_commit"] = current
    return TranslationCase(interval, source, target, edge, variant, history, context,
                           PolicyConfig(id="symbol_validate"), result, reasons, expected)


Selector = Callable[[SelectionContext, PolicyConfig], tuple[Selection, ...]]
Transition = Callable[..., MemoryState]


def check_case(case: TranslationCase, *, selector: Selector | None = None,
               transition: Transition = advance_state) -> dict[str, Any]:
    previous = case.context.previous[0]
    before = previous.model_dump(mode="json")
    selections = (selector or PeriodicAudit(case.history, case.interval))(case.context, case.policy)
    require(len(selections) == 1, "Expected one selection per synthetic claim")
    selection = selections[0]
    # A selector mutation that skips must also skip its modeled validation input.
    result = case.result if selection.selected else None
    actual = transition(previous, selection, case.policy, result, structural=False)
    actual_record = actual.model_dump(mode="json")
    positions = {revision: index for index, revision in enumerate(case.history)}
    checked = positions.get(actual.last_checked_commit)
    age = None if checked is None else positions[case.context.commit] - checked
    checks = {"selection_claim_id": selection.claim_id == previous.claim_id,
              "selection_revision": selection.commit == case.context.commit,
              "selection_selected": selection.selected == case.edge["selected"],
              "selection_reasons": selection.reasons == case.expected_reasons,
              "model_availability": actual.available == case.target["available"],
              "model_age": age == case.target["age"],
              "previous_unmodified": previous.model_dump(mode="json") == before,
              **{f"state.{key}": actual_record[key] == value for key, value in case.expected_state.items()}}
    return {"passed": all(checks.values()), "checks": checks,
            "selection": selection.model_dump(mode="json"), "expected_reasons": list(case.expected_reasons),
            "previous": before, "actual_state": actual_record, "expected_state": case.expected_state,
            "projected_age": age, "modeled_target": case.target,
            "validation_input": None if result is None else result.model_dump(mode="json")}


def carry_on_insufficient(previous: MemoryState, selection: Selection, policy: PolicyConfig,
                          result: ValidationResult | None, structural: bool) -> MemoryState:
    state = advance_state(previous, selection, policy, result, structural)
    if result is not None and result.verdict == "insufficient_evidence":
        return state.model_copy(update={"available": previous.available})
    return state


def negative_controls(cases: list[tuple[str, TranslationCase]]) -> dict[str, Any]:
    witnesses = {
        "suppress_periodic_deadline": next(((name, case) for name, case in cases
            if case.source["available"] and not case.edge["baseline_trigger"] and case.edge["audit_due"]), None),
        "carry_previous_availability_after_insufficient": next(((name, case) for name, case in cases
            if case.source["available"] and case.edge["verdict"] == "insufficient_evidence"), None)}
    reports = {}
    for control, witness in witnesses.items():
        require(witness is not None, f"No eligible negative-control witness: {control}")
        name, case = witness
        report = (check_case(case, selector=select_claims) if control == "suppress_periodic_deadline"
                  else check_case(case, transition=carry_on_insufficient))
        require(not report["passed"], f"Negative control was not detected: {control}")
        reports[control] = {"detected": True, "witness_case": name,
                            "failed_checks": [key for key, passed in report["checks"].items() if not passed],
                            "report": report}
    return reports


def verified_inputs(root: Path, protocol: dict[str, Any]) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, str]]:
    require(protocol.get("schema_version") == 1
            and protocol.get("experiment") == "finite-model-to-engine-translation-v1", "Unexpected translation protocol")
    expected = protocol["input_sha256"]
    require(isinstance(expected, dict) and bool(expected), "Missing frozen input hashes")
    paths = {}
    for relative, expected_hash in expected.items():
        path = within(root, relative)
        require(path.is_file() and file_hash(path) == expected_hash, f"Frozen input hash mismatch: {relative}")
        paths[relative] = path
    manifests = [path for path in paths.values() if path.name == "manifest.json"]
    summaries = [path for path in paths.values() if path.name == "summary.json"]
    require(len(manifests) == len(summaries) == 1, "Expected one frozen model manifest and summary")
    manifest, summary = read_json(manifests[0]), read_json(summaries[0])
    require(manifest["status"] == "complete" and manifest["source_before"] == manifest["source_after"],
            "Incomplete or source-changing finite model run")
    require(manifest["actual_probe_executions"] == summary["actual_probe_executions"] == 0,
            "Finite model inputs must not represent probe executions")
    graphs = []
    for relative, path in paths.items():
        if path == manifests[0]:
            continue
        require(path.parent == manifests[0].parent, "Frozen model files must share the manifest directory")
        require(manifest["artifact_hashes"].get(path.name) == expected[relative], "Model manifest artifact hash mismatch")
        if path == summaries[0]:
            continue
        match = GRAPH_NAME.fullmatch(path.name)
        require(match is not None, f"Unexpected model input: {relative}")
        graph = read_json(path)
        require(graph["interval"] == int(match[2]), "Model interval differs from filename")
        require(graph["state_count"] == len(graph["states"])
                and graph["transition_count"] == len(graph["transitions"]), "Model graph counts differ")
        recorded = summary["models"][path.stem]
        require(recorded["state_count"] == graph["state_count"]
                and recorded["transition_count"] == graph["transition_count"]
                and recorded["interval"] == graph["interval"], "Model summary differs from graph")
        graphs.append((path.stem, graph))
    require(bool(graphs) and {name for name, _ in graphs} == set(summary["models"]), "Incomplete frozen model graph set")
    return sorted(graphs), expected.copy()


def prepare_cases(graphs: list[tuple[str, dict[str, Any]]]) -> tuple[list[tuple[str, TranslationCase]], list[dict[str, Any]], int]:
    cases, contexts = [], []
    source_transitions = 0
    for name, graph in graphs:
        interval = graph["interval"]
        require(type(interval) is int and interval >= 1, "Invalid graph interval")
        states = {}
        for state in graph["states"]:
            validate_state(state, interval)
            require(state["state_id"] not in states, "Duplicate model state ID")
            states[state["state_id"]] = state
            for variant in metadata_variants(state):
                history, _, previous = canonical_memory(interval, state, variant)
                contexts.append({"id": f"{name}/{state['state_id']}/{variant}", "model": name,
                                 "source_state": state, "predecessor_metadata": variant,
                                 "history": list(history), "previous": previous.model_dump(mode="json")})
        require(graph["initial_state"] in states, "Missing initial model state")
        for index, edge in enumerate(graph["transitions"]):
            require(edge["from"] in states and edge["to"] in states, "Unknown transition endpoint")
            source_transitions += 1
            for variant in metadata_variants(states[edge["from"]]):
                case = translate_edge(interval, states[edge["from"]], states[edge["to"]], edge, variant)
                cases.append((f"{name}/edge-{index:04d}/{variant}", case))
    return cases, contexts, source_transitions


def run(protocol_path: Path, out: Path, *, root: Path = ROOT) -> dict[str, Any]:
    before = source_snapshot(root)
    require(not before["source_status"], "Commit source before model-to-engine translation")
    require(not out.exists() and not out.is_symlink(), "Output directory must be new")
    plan, plan_hash = read_json(protocol_path), file_hash(protocol_path)
    graphs, input_hashes = verified_inputs(root, plan)
    require(all(not out.resolve().is_relative_to(within(root, relative).parent) for relative in input_hashes),
            "Output must be outside frozen model input directories")
    cases, contexts, source_transitions = prepare_cases(graphs)
    counts = {"source_transitions": source_transitions, "canonical_memory_contexts": len(contexts),
              "translation_cases": len(cases)}
    require(all(type(plan.get(f"expected_{key}")) is int and plan[f"expected_{key}"] == count
                for key, count in counts.items()), f"Frozen expected counts differ: {counts}")
    reserve(out)
    shutil.copyfile(protocol_path, out / "protocol.json")
    manifest = {"status": "running", "source_before": before, "protocol_sha256": plan_hash,
                "input_hashes": input_hashes, "checker_sha256": file_hash(Path(__file__)),
                "actual_probe_executions": 0, "production_policy_changed": False,
                "evaluation_eligible": False, "input_kind": "modeled_validation_results_not_probes"}
    write_json(out / "manifest.json", manifest)
    try:
        write_json(out / "canonical_contexts.json", contexts)
        reports = []
        graph_inputs = {Path(relative).stem: {"source_graph": relative, "source_graph_sha256": expected_hash}
                        for relative, expected_hash in input_hashes.items()
                        if GRAPH_NAME.fullmatch(Path(relative).name)}
        for name, case in cases:
            report = check_case(case)
            model_name, edge_name, _ = name.rsplit("/", 2)
            reports.append({"id": name, **graph_inputs[model_name], "edge_index": int(edge_name.removeprefix("edge-")),
                            "model_edge": case.edge, "predecessor_metadata": case.variant, **report})
        write_json(out / "translations.json", reports)
        require(all(report["passed"] for report in reports), "Model-to-engine transition mismatch")
        controls = negative_controls(cases)
        write_json(out / "negative_controls.json", controls)
        summary = {"status": "complete", **counts, "matched_cases": sum(report["passed"] for report in reports),
                   "negative_controls_detected": len(controls), "models": [name for name, _ in graphs],
                   "actual_probe_executions": 0, "limits": plan["limits"]}
        write_json(out / "summary.json", summary)
        require(file_hash(protocol_path) == plan_hash, "Protocol changed during translation")
        for relative, expected_hash in input_hashes.items():
            require(file_hash(within(root, relative)) == expected_hash, f"Input changed during translation: {relative}")
        require(file_hash(Path(__file__)) == manifest["checker_sha256"], "Translation checker changed during run")
        after = source_snapshot(root)
        require(after == before, "Runtime source changed during translation")
        manifest.update(status="complete", source_after=after, **counts)
        return summary
    except (Exception, KeyboardInterrupt) as error:
        manifest.update(status="failed", failure={"type": type(error).__name__, "message": str(error)},
                        source_after=source_snapshot(root))
        raise
    finally:
        manifest["artifact_hashes"] = {path.name: file_hash(path) for path in out.iterdir()
                                       if path.is_file() and path.name != "manifest.json"}
        write_json(out / "manifest.json", manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    print(run(arguments.protocol.resolve(), arguments.out.resolve()))
