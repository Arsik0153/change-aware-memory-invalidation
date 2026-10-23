from __future__ import annotations

import platform
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cami import __version__
from cami.artifacts import digest, file_hash, load, load_jsonl, reserve, within, write_bytes, write_immutable, write_json, write_jsonl
from cami.errors import IncompleteError, ResourceError
from cami.index import ChangeSet, CodeIndex, IndexConfig, Module, build_index, compare_indexes
from cami.inputs import Inputs, check_inputs
from cami.models import Behavior, Cost, GraphView, MemoryState, Selection, ValidationResult
from cami.policies import SelectionContext, advance_state, select_claims
from cami.repository import changed_files, git, read_snapshot
from cami.validation import VALIDATOR_VERSION, ValidationContext, validate_claim


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _graph(inputs: Inputs, index: CodeIndex) -> CodeIndex:
    path = inputs.config.graph_views_path
    if path is None:
        return index
    view = load(inputs.base_dir / path / f"{index.revision}.json", GraphView)
    if view.commit != index.revision:
        raise ValueError("graph view revision mismatch")
    return replace(index, edges=view.edges,
                   unresolved=frozenset(view.unresolved) | frozenset(view.known_incomplete_nodes),
                   global_unresolved=view.global_unresolved)


def run_experiment(config_path: Path, output_dir: Path) -> dict[str, Any]:
    preflight_start, preflight_cpu = time.perf_counter(), time.process_time()
    inputs = check_inputs(config_path)
    config = inputs.config
    frozen_run = None
    if config.split == "heldout":
        from cami.dataset import validate_frozen_config
        if config.frozen_protocol_path is None:
            raise ValueError("heldout run requires a frozen_protocol_path")
        frozen_run = validate_frozen_config(config_path, inputs.base_dir / config.frozen_protocol_path)
    reserve(output_dir)
    (output_dir / "evidence").mkdir()
    (output_dir / "logs").mkdir()
    manifest: dict[str, Any] = {
        "schema_version": 1, "protocol_version": config.protocol_version, "status": "running",
        "evaluation_eligible": not config.preview, "config": config.model_dump(mode="json"),
        "configuration_hash": digest(config), "input_hashes": {
            "claims": file_hash(inputs.base_dir / config.claims_path),
            "provenance": file_hash(inputs.base_dir / config.provenance_path),
            "parent_receipts": file_hash(inputs.base_dir / config.parent_receipts_path)},
        "claim_hashes": {c.claim_id: digest(c) for c in inputs.claims}, "cohort": [], "excluded": [],
        "parent_commit": config.parent_commit, "child_commits": config.child_commits,
        "app_version": __version__, "python": sys.version, "os": platform.platform(),
        "resource_notes": ["cpu_seconds measures analyzer process CPU; child-process and Docker container CPU are not measured."],
        "git": git(Path(config.repo.path), "--version").decode().strip(),
        "input_preflight_seconds": time.perf_counter() - preflight_start,
        "input_preflight_cpu_seconds": time.process_time() - preflight_cpu,
        "started_at": now(), "finished_at": None, "validator_version": VALIDATOR_VERSION,
    }
    write_json(output_dir / "manifest.json", manifest)
    try:
        if config.graph_views_path is not None:
            for revision in (config.parent_commit, *config.child_commits):
                manifest["input_hashes"][f"graph/{revision}"] = file_hash(inputs.base_dir / config.graph_views_path / f"{revision}.json")
        for receipt in inputs.receipts:
            evidence = within(inputs.base_dir, receipt.evidence_path)
            manifest["input_hashes"][f"parent_evidence/{receipt.claim_id}"] = file_hash(evidence)
            write_bytes(output_dir / "evidence" / "parent" / receipt.evidence_sha256, evidence.read_bytes())
        for claim in inputs.claims:
            if isinstance(claim.predicate, Behavior):
                manifest["input_hashes"][f"probe/{claim.claim_id}"] = claim.predicate.probe_sha256
        write_jsonl(output_dir / "parent_receipts.jsonl", inputs.receipts)
        manifest["input_preflight_seconds"] = time.perf_counter() - preflight_start
        manifest["input_preflight_cpu_seconds"] = time.process_time() - preflight_cpu
        _execute(inputs, output_dir, manifest, frozen_run)
        phase_costs = load_jsonl(output_dir / "costs.jsonl", Cost)
        manifest["end_to_end_seconds"] = time.perf_counter() - preflight_start
        manifest["end_to_end_cpu_seconds"] = time.process_time() - preflight_cpu
        manifest["overhead_seconds"] = (manifest["end_to_end_seconds"]
                                        - sum(cost.wall_seconds for cost in phase_costs))
        manifest["resource_notes"].append(
            "end_to_end_seconds includes input checks, run output serialization and artifact hashing; "
            "it excludes the final accounting manifest rewrite. overhead_seconds is the measured "
            "difference from the preflight and maintenance phase components.")
        write_json(output_dir / "manifest.json", manifest)
    except BaseException as exc:
        manifest.update(status="failed", finished_at=now(), failure=f"{type(exc).__name__}: {exc}")
        write_json(output_dir / "manifest.json", manifest)
        if isinstance(exc, (ResourceError, KeyboardInterrupt)):
            raise
        raise IncompleteError(str(exc)) from exc
    return manifest


def _execute(inputs: Inputs, output: Path, manifest: dict[str, Any],
             frozen_run: dict[str, Any] | None = None) -> None:
    config = inputs.config
    start, cpu_start = time.perf_counter(), time.process_time()
    if config.validation.llm == "openai":
        from cami.llm import require_optional_llm
        require_optional_llm()
    receipt_ids = {r.claim_id for r in inputs.receipts}
    admitted = []
    preflight_results: list[ValidationResult] = []
    parent_snapshot = None
    if config.validation.execution == "docker":
        from cami.behavior import check_docker
        for profile in config.environment_profiles.values():
            check_docker(profile)
    for claim in inputs.claims:
        reason = None
        if claim.claim_id not in receipt_ids:
            reason = "missing_parent_confirmation"
        elif claim.kind == "prose":
            reason = "validator_unavailable"
        elif isinstance(claim.predicate, Behavior):
            if config.validation.execution != "docker":
                reason = "validator_unavailable"
            else:
                from cami.behavior import ProbeContext, execute_probe
                if parent_snapshot is None:
                    parent_snapshot = read_snapshot(config.repo, config.parent_commit)
                result = execute_probe(claim, ProbeContext(parent_snapshot,
                    config.environment_profiles[claim.predicate.environment_id], inputs.base_dir, output, "preflight"))
                preflight_results.append(result)
                if result.verdict != "supported":
                    reason = "parent_probe_" + result.reason
        if reason:
            manifest["excluded"].append({"claim_id": claim.claim_id, "reason": reason})
        if reason is None or config.preview:
            admitted.append(claim)
    write_jsonl(output / "preflight_validations.jsonl", preflight_results)
    if frozen_run is not None and (
        [claim.claim_id for claim in admitted] != frozen_run["cohort"]
        or manifest["excluded"] != frozen_run["excluded"]
    ):
        raise ResourceError("heldout preflight cannot change the frozen cohort or exclusions")
    if not admitted:
        raise ResourceError("no eligible claims; inspect manifest exclusions")
    claims = tuple(admitted)
    ids = {c.claim_id for c in claims}
    provenance = tuple(p for p in inputs.provenance if p.claim_id in ids)
    by_prov = {p.claim_id: p for p in provenance}
    manifest["cohort"] = [c.claim_id for c in claims]
    write_jsonl(output / "claims.jsonl", claims)
    write_jsonl(output / "provenance.jsonl", provenance)
    previous = tuple(MemoryState(claim_id=c.claim_id, revision=config.parent_commit,
        state="valid", last_checked_commit=config.parent_commit, last_supported_commit=config.parent_commit,
        last_verdict="supported", basis="validated", current_provenance=by_prov[c.claim_id], available=True)
        for c in claims)
    costs = [Cost(phase="preflight", commit=config.parent_commit,
                  wall_seconds=time.perf_counter()-start + manifest["input_preflight_seconds"],
                  cpu_seconds=time.process_time()-cpu_start + manifest["input_preflight_cpu_seconds"],
                  logical_validations=len(preflight_results), actual_validations=len(preflight_results),
                  test_executions=sum(r.test_executions for r in preflight_results),
                  actual_validation_seconds=sum(r.duration_seconds for r in preflight_results),
                  reconstructed_validation_seconds=sum(r.duration_seconds for r in preflight_results))]
    all_states: list[MemoryState] = []
    selections: list[Selection] = []
    validations: list[ValidationResult] = []
    transitions: list[dict[str, Any]] = []
    ast_cache: dict[tuple[str, str, str, str, str], Module] = {}
    before = None
    old_index = None
    symbol_policy = config.policy.id.startswith("symbol_")
    file_policy = config.policy.id.startswith("file_")
    checking = config.policy.id.endswith("_validate")
    build_graph = symbol_policy and config.graph_views_path is None
    index_config = IndexConfig(config.repo.source_roots, build_graph)
    previous_commit = config.parent_commit
    for commit in config.child_commits:
        start, cpu_start = time.perf_counter(), time.process_time()
        index_seconds = 0.0
        initial_index_seconds = 0.0
        snap = None
        index = None
        changes = ChangeSet(frozenset(), frozenset(), (), frozenset(), frozenset(), False)
        if symbol_policy or file_policy or checking:
            snap = read_snapshot(config.repo, commit)
        if symbol_policy or file_policy:
            if before is None:
                before = read_snapshot(config.repo, previous_commit)
            assert snap is not None
            changes = replace(changes, files=changed_files(before, snap))
        if symbol_policy or file_policy or checking:
            assert snap is not None
            tick = time.perf_counter()
            if symbol_policy and old_index is None:
                assert before is not None
                initial_tick = time.perf_counter()
                old_index = _graph(inputs, build_index(before, index_config, ast_cache))
                initial_index_seconds = time.perf_counter() - initial_tick
            index = _graph(inputs, build_index(snap, index_config, ast_cache))
            if symbol_policy:
                assert before is not None and old_index is not None
                changes = compare_indexes(old_index, index, before, snap)
                edges = set(changes.edges)
                for p in provenance:
                    edges.update(p.dependencies)
                changes = replace(changes, edges=tuple(edges))
            elif file_policy:
                changes = replace(changes, unresolved=index.unresolved,
                                  limited_paths=frozenset(index.limitations()),
                                  global_unresolved=index.global_unresolved)
            index_seconds = time.perf_counter() - tick
            if not symbol_policy and previous_commit == config.parent_commit:
                initial_index_seconds = index_seconds
        tick = time.perf_counter()
        selected = select_claims(SelectionContext(commit, claims, provenance, previous, changes,
                                 config.extra_environment_paths, config.protocol_version), config.policy)
        selection_seconds = time.perf_counter() - tick
        selections.extend(selected)
        results: dict[str, ValidationResult] = {}
        by_claim = {c.claim_id: c for c in claims}
        if checking:
            assert snap is not None
            for decision in selected:
                if not decision.selected:
                    continue
                claim = by_claim[decision.claim_id]
                prov = by_prov[claim.claim_id]
                key = digest({"claim": digest(claim), "commit": commit, "provenance": digest(prov),
                              "validator_version": VALIDATOR_VERSION, "python": sys.version,
                              "replicate_id": config.replicate_id,
                              "validation": config.validation.model_dump(mode="json"),
                              "environment_profiles": {k: v.model_dump(mode="json") for k,v in config.environment_profiles.items()},
                              "source_roots": config.repo.source_roots})
                cache_path = (inputs.base_dir / config.cache_dir / f"{key}.json") if config.cache_dir else None
                if cache_path is not None and cache_path.exists():
                    result = load(cache_path, ValidationResult)
                    if result.claim_id != claim.claim_id or result.commit != commit:
                        raise ValueError("cache identity mismatch")
                    result = result.model_copy(update={"cache_hit": True, "original_measurement": str(cache_path.resolve())})
                else:
                    if isinstance(claim.predicate, Behavior) and config.validation.execution == "docker":
                        from cami.behavior import ProbeContext, execute_probe
                        result = execute_probe(claim, ProbeContext(snap,
                            config.environment_profiles[claim.predicate.environment_id], inputs.base_dir, output))
                    else:
                        result = validate_claim(claim, ValidationContext(snap, index, prov, inputs.base_dir, output))
                    if cache_path is not None:
                        cached_result = result.model_copy(update={"logs": tuple(str((output / log).resolve()) for log in result.logs)})
                        if not write_immutable(cache_path, cached_result):
                            raise IncompleteError("concurrent cache fill; repeat in a new output directory")
                results[claim.claim_id] = result
                validations.append(result)
                blob = snap.by_path().get(claim.subject.path)
                write_json(output / "evidence" / f"{key}.json", {
                    "schema_version": 1, "claim_id": claim.claim_id, "commit": commit,
                    "path": claim.subject.path,
                    "source": blob.content.decode("utf-8", errors="replace") if blob and blob.content else None,
                    "input_hash": result.input_hash})
        previous = tuple(advance_state(state, decision, config.policy, results.get(state.claim_id),
                         by_claim[state.claim_id].kind in {"symbol_exists", "signature_equals"})
                         for state, decision in zip(previous, selected, strict=True))
        all_states.extend(previous)
        current = tuple(results.values())
        actual = tuple(r for r in current if not r.cache_hit)
        costs.append(Cost(phase="maintenance", commit=commit,
            wall_seconds=time.perf_counter()-start, cpu_seconds=time.process_time()-cpu_start,
            index_seconds=index_seconds, initial_index_seconds=initial_index_seconds,
            incremental_index_seconds=index_seconds-initial_index_seconds, selection_seconds=selection_seconds,
            logical_validations=len(current), actual_validations=len(actual), cache_hits=len(current)-len(actual),
            test_executions=sum(r.test_executions for r in actual),
            input_tokens=sum(r.input_tokens for r in actual), output_tokens=sum(r.output_tokens for r in actual),
            reconstructed_validation_seconds=sum(r.duration_seconds for r in current),
            actual_validation_seconds=sum(r.duration_seconds for r in actual)))
        transitions.append({"schema_version": 1, "parent_commit": previous_commit, "commit": commit,
                            "changed_files": sorted(changes.files)})
        for name, rows in (("states", all_states), ("selections", selections), ("validations", validations),
                           ("costs", costs), ("transitions", transitions)):
            write_jsonl(output / f"{name}.jsonl", rows)
        before, old_index, previous_commit = snap, index, commit
    if len(all_states) != len(claims) * len(config.child_commits):
        raise IncompleteError("incomplete state coverage")
    manifest["artifact_hashes"] = {str(path.relative_to(output)): file_hash(path)
        for path in sorted(output.rglob("*")) if path.is_file() and path.name != "manifest.json"}
    manifest.update(status="complete", finished_at=now())
    write_json(output / "manifest.json", manifest)
