from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import Field

from cami.artifacts import digest, file_hash, load, load_jsonl, read_json, reserve, within, write_json
from cami.errors import IncompleteError, InputError
from cami.models import (
    Claim, Cost, MemoryState, Provenance, Record, RunConfig, Selection, ValidationResult,
)


class Label(Record):
    claim_id: str = Field(min_length=1)
    commit: str = Field(min_length=1)
    label: Literal["supported", "contradicted", "uncertain"]
    annotator_id: str = Field(min_length=1)
    evidence: tuple[str, ...] = Field(min_length=1)
    confirmation_type: str = Field(min_length=1)
    adjudication_status: str = Field(min_length=1)


class ExcludedClaim(Record):
    claim_id: str
    reason: str


class ScoredManifest(Record):
    protocol_version: str
    status: str
    evaluation_eligible: bool
    config: RunConfig
    input_hashes: dict[str, str]
    artifact_hashes: dict[str, str]
    claim_hashes: dict[str, str]
    cohort: tuple[str, ...]
    excluded: tuple[ExcludedClaim, ...]
    parent_commit: str
    child_commits: tuple[str, ...]
    app_version: str
    python: str
    started_at: str
    finished_at: str | None
    configuration_hash: str | None = None
    os: str | None = None
    git: str | None = None
    input_preflight_seconds: float = 0
    input_preflight_cpu_seconds: float = 0
    validator_version: str | None = None
    failure: str | None = None
    resource_notes: tuple[str, ...] = ()
    end_to_end_seconds: float | None = Field(default=None, ge=0)
    end_to_end_cpu_seconds: float | None = Field(default=None, ge=0)
    overhead_seconds: float | None = None


class Metric(Record):
    value: float | int | None
    numerator: int | None = None
    denominator: int | None = None
    reason: str | None = None


class MetricGroup(Record):
    group: str
    counters: dict[str, int]
    metrics: dict[str, Metric]
    exploratory: bool
    independent_clusters: int


class CostSummary(Record):
    totals: dict[str, float | int | None]
    unavailable_reasons: dict[str, str]
    selected_claims: int


class EvaluationReport(Record):
    protocol_version: str
    run_dir: str
    labels_sha256: str
    policy: str
    repo_id: str
    scenario_id: str
    dataset_kind: str
    split: str
    stratum: str
    cohort: tuple[str, ...]
    revisions: tuple[str, ...]
    excluded: tuple[ExcludedClaim, ...]
    overall: MetricGroup
    by_revision: tuple[MetricGroup, ...]
    by_claim_kind: tuple[MetricGroup, ...]
    by_validator: tuple[MetricGroup, ...]
    costs: dict[str, CostSummary]
    end_to_end_seconds: float | None = None
    overhead_seconds: float | None = None
    label_counts: dict[str, int]
    validator_reasons: dict[str, int]
    selection_reasons: dict[str, int]
    limitations: tuple[str, ...]


class BootstrapInterval(Record):
    estimate: float | None
    lower: float | None
    upper: float | None
    reason: str | None
    clusters: int
    repetitions: int = 2000
    seed: int = 42


class ComparisonReport(Record):
    protocol_version: str
    labels_sha256: str
    reports: tuple[EvaluationReport, ...]
    intervals: dict[str, dict[str, BootstrapInterval]]
    pareto_dominated_by: dict[str, tuple[str, ...]]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class Observation:
    claim: Claim
    state: MemoryState
    selection: Selection
    label: Label
    validation: ValidationResult | None


@dataclass(frozen=True)
class ScoredRun:
    manifest: ScoredManifest
    report: EvaluationReport
    observations: tuple[Observation, ...]


_VALIDATING = frozenset({"all_validate", "file_validate", "symbol_validate"})
_REQUIRED_ARTIFACTS = frozenset({
    "claims.jsonl", "provenance.jsonl", "transitions.jsonl", "selections.jsonl",
    "validations.jsonl", "states.jsonl", "costs.jsonl",
})


def load_labels(path: Path) -> tuple[Label, ...]:
    labels = load_jsonl(path, Label)
    pairs = [(label.claim_id, label.commit) for label in labels]
    if len(pairs) != len(set(pairs)):
        raise InputError("duplicate label claim_id/commit")
    return labels


def _rate(numerator: int, denominator: int, *, applicable: bool = True) -> Metric:
    if not applicable:
        return Metric(value=None, numerator=numerator, denominator=denominator,
                      reason="not_applicable")
    return Metric(value=numerator / denominator if denominator else None,
                  numerator=numerator, denominator=denominator,
                  reason=None if denominator else "zero_denominator")


def _predicted(row: Observation) -> bool:
    return (row.state.state in {"stale", "retired"}
            and row.state.last_checked_commit == row.state.revision
            and row.state.last_verdict == "contradicted"
            and row.validation is not None and row.validation.verdict == "contradicted")


def compute_metrics(rows: tuple[Observation, ...], policy: str, group: str,
                    independent_clusters: int = 1) -> MetricGroup:
    counts = dict.fromkeys([
        "supported", "contradicted", "uncertain", "available_supported",
        "available_contradicted", "uncertain_available", "available_binary",
        "selected_contradicted", "false_invalidated", "withheld_supported",
        "tp", "fp", "fn", "stale_tp", "stale_fp", "retired_tp", "retired_fp",
        "insufficient_evidence", "carried_forward", "unchecked_current_revision",
    ], 0)
    for row in rows:
        label, state = row.label.label, row.state
        counts[label] += 1
        if state.available:
            if label == "uncertain":
                counts["uncertain_available"] += 1
            else:
                counts[f"available_{label}"] += 1
                counts["available_binary"] += 1
        if label == "contradicted" and row.selection.selected:
            counts["selected_contradicted"] += 1
        if label == "supported":
            counts["withheld_supported"] += int(not state.available)
            counts["false_invalidated"] += int(state.state in {"stale", "retired"})
        if label != "uncertain" and _predicted(row):
            category = "tp" if label == "contradicted" else "fp"
            counts[category] += 1
            counts[f"{state.state}_{category}"] += 1
        if label == "contradicted" and not _predicted(row):
            counts["fn"] += 1
        counts["carried_forward"] += int(state.basis == "carried_forward")
        counts["unchecked_current_revision"] += int(state.last_checked_commit != state.revision)
        counts["insufficient_evidence"] += int(
            row.validation is not None and row.validation.verdict == "insufficient_evidence")
    applicable = policy in _VALIDATING
    metrics = {
        "stale_exposure": _rate(counts["available_contradicted"], counts["contradicted"]),
        "valid_retention": _rate(counts["available_supported"], counts["supported"]),
        "available_contamination": _rate(counts["available_contradicted"],
                                         counts["available_binary"]),
        "selection_recall": _rate(counts["selected_contradicted"], counts["contradicted"],
                                  applicable=applicable),
        "false_invalidation": _rate(counts["false_invalidated"], counts["supported"],
                                    applicable=applicable),
        "valid_withholding": _rate(counts["withheld_supported"], counts["supported"]),
        "uncertain_available": Metric(value=counts["uncertain_available"],
                                      numerator=counts["uncertain_available"]),
        "invalidation_precision": _rate(counts["tp"], counts["tp"] + counts["fp"],
                                        applicable=applicable),
        "invalidation_recall": _rate(counts["tp"], counts["tp"] + counts["fn"],
                                     applicable=applicable),
        "invalidation_f1": _rate(2 * counts["tp"],
                                 2 * counts["tp"] + counts["fp"] + counts["fn"],
                                 applicable=applicable),
    }
    return MetricGroup(group=group, counters=counts, metrics=metrics,
                       exploratory=counts["contradicted"] < 50 or independent_clusters < 20,
                       independent_clusters=independent_clusters)


def _cost_summary(costs: tuple[Cost, ...], selected: int) -> CostSummary:
    totals: dict[str, float | int | None] = {}
    reasons: dict[str, str] = {}
    for name in Cost.model_fields:
        if name in {"schema_version", "phase", "commit"}:
            continue
        values: list[float | int | None] = [getattr(cost, name) for cost in costs]
        if not values or any(value is None for value in values):
            totals[name] = None
            reasons[name] = "not_measured"
        else:
            totals[name] = sum(value for value in values if value is not None)
    return CostSummary(totals=totals, unavailable_reasons=reasons, selected_claims=selected)


def _score(run_dir: Path, labels: tuple[Label, ...], labels_hash: str) -> ScoredRun:
    raw_manifest = read_json(run_dir / "manifest.json")
    if isinstance(raw_manifest, dict) and raw_manifest.get("status") != "complete":
        raise IncompleteError("scoring requires a complete run")
    manifest = load(run_dir / "manifest.json", ScoredManifest)
    if manifest.status != "complete" or manifest.finished_at is None:
        raise IncompleteError("scoring requires a complete run")
    if not manifest.evaluation_eligible or manifest.config.preview:
        raise InputError("run is not evaluation eligible")
    if (manifest.protocol_version != manifest.config.protocol_version
            or manifest.parent_commit != manifest.config.parent_commit
            or manifest.child_commits != manifest.config.child_commits):
        raise InputError("manifest and resolved configuration disagree")
    if not _REQUIRED_ARTIFACTS.issubset(manifest.artifact_hashes):
        raise InputError("manifest missing required artifact hashes")
    for name, expected_hash in manifest.artifact_hashes.items():
        if file_hash(within(run_dir, name)) != expected_hash:
            raise InputError(f"artifact hash mismatch: {name}")
    if manifest.configuration_hash is not None:
        if manifest.configuration_hash != digest(raw_manifest["config"]):
            raise InputError("configuration hash mismatch")
    claims = load_jsonl(run_dir / "claims.jsonl", Claim, unique="claim_id")
    claim_map = {claim.claim_id: claim for claim in claims}
    if any(manifest.claim_hashes.get(claim.claim_id) != digest(claim) for claim in claims):
        raise InputError("claim content hash mismatch")
    provenance = load_jsonl(run_dir / "provenance.jsonl", Provenance, unique="claim_id")
    if {row.claim_id for row in provenance} != set(claim_map):
        raise InputError("provenance population differs from claims")
    cohort = set(manifest.cohort)
    excluded = {row.claim_id for row in manifest.excluded}
    if (len(cohort) != len(manifest.cohort) or len(excluded) != len(manifest.excluded)
            or cohort & excluded or cohort | excluded != set(manifest.claim_hashes)
            or not cohort.issubset(claim_map)
            or not set(claim_map).issubset(manifest.claim_hashes)):
        raise InputError("invalid cohort or excluded population")
    revisions = manifest.child_commits
    if len(set(revisions)) != len(revisions):
        raise InputError("duplicate child revision")
    expected = {(claim_id, commit) for commit in revisions for claim_id in cohort}
    states = load_jsonl(run_dir / "states.jsonl", MemoryState)
    state_map = {(row.claim_id, row.revision): row for row in states}
    selections = load_jsonl(run_dir / "selections.jsonl", Selection)
    selection_map = {(row.claim_id, row.commit): row for row in selections}
    if len(state_map) != len(states) or set(state_map) != expected:
        raise InputError("states must contain exactly one cohort claim per child revision")
    if len(selection_map) != len(selections) or set(selection_map) != expected:
        raise InputError("selections must contain exactly one cohort claim per child revision")
    validations = load_jsonl(run_dir / "validations.jsonl", ValidationResult)
    validation_map = {(row.claim_id, row.commit): row for row in validations}
    selected = {key for key, selection in selection_map.items() if selection.selected}
    validating = manifest.config.policy.id in _VALIDATING
    if (len(validation_map) != len(validations)
            or set(validation_map) != (selected if validating else set())):
        raise InputError("validation results do not match selected claims")
    label_map = {(row.claim_id, row.commit): row for row in labels}
    missing = expected - set(label_map)
    if missing:
        raise InputError(f"missing_label_coverage: {len(missing)} cohort claim/revision pairs")
    for claim_id in cohort:
        parent_label = label_map.get((claim_id, manifest.parent_commit))
        if parent_label is not None and parent_label.label != "supported":
            raise InputError(f"invalid_parent_label: {claim_id}")
    observations = tuple(Observation(claim_map[claim_id], state_map[(claim_id, commit)],
                                    selection_map[(claim_id, commit)], label_map[(claim_id, commit)],
                                    validation_map.get((claim_id, commit)))
                         for commit in revisions for claim_id in sorted(cohort))
    costs = load_jsonl(run_dir / "costs.jsonl", Cost)
    if any(row.commit not in {*revisions, manifest.parent_commit} for row in costs):
        raise InputError("cost references an unknown revision")
    policy = manifest.config.policy.id
    config = manifest.config
    validator_reasons: dict[str, int] = {}
    selection_reasons: dict[str, int] = {}
    for result in validations:
        validator_reasons[result.reason] = validator_reasons.get(result.reason, 0) + 1
    for selection in selections:
        for reason in selection.reasons:
            selection_reasons[reason] = selection_reasons.get(reason, 0) + 1
    validator_groups = {"symbol_exists":"structural", "signature_equals":"structural",
                        "behavior_test":"behavior", "prose":"prose"}
    by_validator = tuple(compute_metrics(tuple(row for row in observations
                                              if validator_groups[row.claim.kind] == validator),
                                         policy, validator)
                         for validator in sorted({validator_groups[row.claim.kind] for row in observations}))
    used_labels = tuple(label_map[key] for key in expected)
    limitations = [*manifest.resource_notes, "Reliability estimates are exploratory below 50 contradicted cases or 20 "
                   "independent clusters.", "One run is one independent cluster. Replay revisions "
                   "are dependent observations.", "Uncached timing replicates were not supplied.",
                   "Availability does not measure usefulness on coding tasks."]
    if config.dataset_kind == "synthetic":
        limitations.append("These are synthetic observations, not results on real repositories.")
    if len({label.annotator_id for label in used_labels}) < 2:
        limitations.append("Single-annotator limitation; independent double annotation is unverified.")
    else:
        limitations.append("Labels contain final decisions only; double-annotation coverage and "
                           "Cohen's kappa require retained independent annotation histories.")
    report = EvaluationReport(
        protocol_version=manifest.protocol_version, run_dir=str(run_dir.resolve()),
        labels_sha256=labels_hash, policy=policy, repo_id=config.repo.repo_id,
        scenario_id=config.scenario_id, dataset_kind=config.dataset_kind, split=config.split,
        stratum=config.stratum, cohort=manifest.cohort, revisions=revisions,
        excluded=manifest.excluded, overall=compute_metrics(observations, policy, "micro"),
        by_revision=tuple(compute_metrics(tuple(row for row in observations
                                               if row.state.revision == revision), policy, revision)
                          for revision in revisions),
        by_claim_kind=tuple(compute_metrics(tuple(row for row in observations
                                                 if row.claim.kind == kind), policy, kind)
                            for kind in sorted({row.claim.kind for row in observations})),
        by_validator=by_validator, end_to_end_seconds=manifest.end_to_end_seconds,
        overhead_seconds=manifest.overhead_seconds,
        costs={phase: _cost_summary(tuple(row for row in costs if row.phase == phase),
                                   len(selected) if phase == "maintenance" else 0)
               for phase in ("preflight", "maintenance")},
        label_counts={name: sum(row.label.label == name for row in observations)
                      for name in ("supported", "contradicted", "uncertain")},
        validator_reasons=validator_reasons, selection_reasons=selection_reasons,
        limitations=tuple(limitations))
    return ScoredRun(manifest, report, observations)


def score_run(run_dir: Path, labels_path: Path, output_dir: Path) -> EvaluationReport:
    from cami.reporting import write_score

    result = _score(run_dir, load_labels(labels_path), file_hash(labels_path))
    reserve(output_dir)
    write_score(result.report, result.observations, output_dir)
    return result.report


def paired_cluster_bootstrap(
    left: dict[str, tuple[int, int]], right: dict[str, tuple[int, int]], *,
    repetitions: int = 2000, seed: int = 42,
) -> BootstrapInterval:
    """Bootstrap the difference of micro rates, left minus right, using paired clusters."""
    if set(left) != set(right):
        raise InputError("bootstrap requires identical paired cluster IDs")
    if repetitions < 1:
        raise InputError("bootstrap repetitions must be positive")
    keys = sorted(left)
    if any(num < 0 or den < 0 or num > den for num, den in (*left.values(), *right.values())):
        raise InputError("bootstrap counters require 0 <= numerator <= denominator")
    left_den, right_den = sum(left[k][1] for k in keys), sum(right[k][1] for k in keys)
    estimate = (sum(left[k][0] for k in keys) / left_den
                - sum(right[k][0] for k in keys) / right_den) if left_den and right_den else None
    reason = "insufficient_clusters" if len(keys) < 2 else None
    if estimate is None:
        reason = "zero_denominator"
    if reason:
        return BootstrapInterval(estimate=estimate, lower=None, upper=None, reason=reason,
                                 clusters=len(keys), repetitions=repetitions, seed=seed)
    rng = np.random.default_rng(seed)
    differences: list[float] = []
    for _ in range(repetitions):
        sampled = [keys[int(i)] for i in rng.integers(0, len(keys), size=len(keys))]
        ld, rd = sum(left[k][1] for k in sampled), sum(right[k][1] for k in sampled)
        if not ld or not rd:
            return BootstrapInterval(estimate=estimate, lower=None, upper=None,
                                     reason="zero_denominator_in_resample", clusters=len(keys),
                                     repetitions=repetitions, seed=seed)
        differences.append(sum(left[k][0] for k in sampled) / ld
                           - sum(right[k][0] for k in sampled) / rd)
    lower, upper = np.quantile(differences, [0.025, 0.975])
    return BootstrapInterval(estimate=estimate, lower=float(lower), upper=float(upper), reason=None,
                             clusters=len(keys), repetitions=repetitions, seed=seed)


def _comparison_key(run: ScoredRun) -> str:
    config = run.manifest.config.model_dump(mode="json")
    for field in ("policy", "claims_path", "provenance_path", "parent_receipts_path",
                  "graph_views_path", "cache_dir"):
        config.pop(field)
    repo = run.manifest.config.repo.model_dump(mode="json")
    repo.pop("path")
    config["repo"] = repo
    return digest({"config": config, "claims": run.manifest.claim_hashes,
                   "cohort": sorted(run.manifest.cohort),
                   "excluded": sorted((row.claim_id, row.reason) for row in run.manifest.excluded),
                   "inputs": run.manifest.input_hashes, "app_version": run.manifest.app_version,
                   "python": run.manifest.python, "validator_version": run.manifest.validator_version})


def compare_runs(run_dirs: list[Path], labels_path: Path, output_dir: Path) -> ComparisonReport:
    from cami.reporting import write_comparison, write_score

    if len(run_dirs) < 2:
        raise InputError("comparison requires at least two runs")
    labels, labels_hash = load_labels(labels_path), file_hash(labels_path)
    runs = tuple(_score(path, labels, labels_hash) for path in run_dirs)
    if len({_comparison_key(run) for run in runs}) != 1:
        raise InputError("incompatible populations, revisions, scenarios, or validator settings")
    if len({run.report.policy for run in runs}) != len(runs):
        raise InputError("duplicate policy in same-population comparison")
    if runs[0].manifest.config.validation.llm == "openai":
        caches = {run.manifest.config.cache_dir for run in runs}
        if None in caches or len(caches) != 1:
            raise InputError("LLM comparisons require a shared verdict cache")
    intervals: dict[str, dict[str, BootstrapInterval]] = {}
    baseline = runs[0].report
    for run in runs[1:]:
        metrics: dict[str, BootstrapInterval] = {}
        for name, metric in run.report.overall.metrics.items():
            reference = baseline.overall.metrics[name]
            if (metric.reason == "not_applicable" or reference.reason == "not_applicable"
                    or metric.denominator is None or reference.denominator is None):
                metrics[name] = BootstrapInterval(estimate=None, lower=None, upper=None,
                                                  reason="not_applicable", clusters=1)
            else:
                metrics[name] = paired_cluster_bootstrap(
                    {"run": (metric.numerator or 0, metric.denominator)},
                    {"run": (reference.numerator or 0, reference.denominator)})
        intervals[f"{run.report.policy}-minus-{baseline.policy}"] = metrics
    dominated: dict[str, tuple[str, ...]] = {}
    for run in runs:
        peers: list[str] = []
        target = _pareto_values(run.report)
        for other in runs:
            candidate = _pareto_values(other.report)
            if target is not None and candidate is not None and candidate != target:
                if all(a <= b for a, b in zip(candidate, target, strict=True)):
                    peers.append(other.report.policy)
        dominated[run.report.policy] = tuple(peers)
    report = ComparisonReport(protocol_version=baseline.protocol_version,
                              labels_sha256=labels_hash, reports=tuple(run.report for run in runs),
                              intervals=intervals, pareto_dominated_by=dominated,
                              limitations=("Only one independent cluster was supplied; confidence "
                                           "intervals are unavailable.",
                                           "Pareto dominance describes observed tradeoffs.",
                                           "Macro across repositories is unavailable for one repo."))
    reserve(output_dir)
    for run in runs:
        target_dir = output_dir / run.report.policy
        target_dir.mkdir()
        write_score(run.report, run.observations, target_dir)
    write_json(output_dir / "metrics.json", report)
    write_json(output_dir / "intervals.json", report.model_dump(mode="json")["intervals"])
    write_comparison(report, output_dir)
    return report


def reconstructed_run_seconds(report: EvaluationReport) -> float | None:
    components = [cost.totals for cost in report.costs.values()]
    if any(row.get(key) is None for row in components for key in
           ("wall_seconds", "actual_validation_seconds", "reconstructed_validation_seconds")):
        return None
    wall = report.end_to_end_seconds
    if wall is None:
        wall = sum(float(row["wall_seconds"] or 0) for row in components)
    return wall + sum(float(row["reconstructed_validation_seconds"] or 0)
                      - float(row["actual_validation_seconds"] or 0) for row in components)


def _pareto_values(report: EvaluationReport) -> tuple[float, float, float] | None:
    total = reconstructed_run_seconds(report)
    exposure = report.overall.metrics["stale_exposure"].value
    retention = report.overall.metrics["valid_retention"].value
    if total is None or exposure is None or retention is None:
        return None
    return total, float(exposure), -float(retention)
