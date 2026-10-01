from __future__ import annotations

import csv
import io
from dataclasses import dataclass, replace
from pathlib import Path

from cami.artifacts import digest, file_hash, load, load_jsonl, reserve, within, write_bytes, write_json
from cami.dataset_models import DatasetManifest, DatasetRun
from cami.errors import InputError
from cami.evaluation import (
    BootstrapInterval, CostSummary, Label, Metric, MetricGroup, Observation, ScoredRun,
    _cost_summary, _score, compute_metrics, load_labels, paired_cluster_bootstrap,
)
from cami.models import Behavior, Claim, Cost, ParentReceipt, PolicyConfig, Record, RunConfig
from cami.repository import chain


class GroupDimensions(Record):
    dataset_kind: str
    split: str
    stratum: str
    scenario_id: str
    validator_settings: str
    sequence_id: str | None = None
    repo_id: str | None = None
    claim_kind: str | None = None


class MacroMetric(Record):
    value: float | None
    contributing_repositories: int
    total_repositories: int
    unavailable_reasons: dict[str, str]


class PolicyAggregate(Record):
    policy: str
    policy_parameters: PolicyConfig
    micro: MetricGroup
    macro_by_repository: dict[str, MacroMetric]
    total_clusters: int
    contradicted_clusters: int
    dataset_runs: tuple[str, ...]


class GroupReport(Record):
    dimensions: GroupDimensions
    policies: tuple[PolicyAggregate, ...]
    intervals: dict[str, dict[str, BootstrapInterval]]


class CumulativeCost(Record):
    transition: int
    commit: str
    measured_maintenance_wall_seconds: float
    reconstructed_maintenance_seconds: float
    measured_total_seconds: float
    reconstructed_total_seconds: float
    cumulative_index_seconds: float
    cumulative_logical_validations: int
    cumulative_actual_validations: int
    cumulative_cache_hits: int


class RunCosts(Record):
    dataset_run_id: str
    policy: str
    cluster_id: str
    sequence_id: str | None
    preflight: CostSummary
    maintenance: CostSummary
    initial_index_seconds: float
    later_index_seconds: float
    cumulative: tuple[CumulativeCost, ...]
    uncached_timing: Metric


class BreakEven(Record):
    dataset_run_id: str
    policy: str
    reference_policy: str
    first_observed_transition: int | None
    reason: str | None


class DatasetAnalysis(Record):
    dataset_id: str
    dataset_sha256: str
    labels_sha256: str
    protocol_version: str
    groups: tuple[GroupReport, ...]
    costs: tuple[RunCosts, ...]
    break_even: tuple[BreakEven, ...]
    run_directories: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class ExpectedRun:
    declaration: DatasetRun
    config: RunConfig
    input_hashes: dict[str, str]
    claim_hashes: dict[str, str]
    declared_policies: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssignedRun:
    declaration: DatasetRun
    scored: ScoredRun
    policy: str
    costs: tuple[Cost, ...]


@dataclass(frozen=True)
class GroupRows:
    dimensions: GroupDimensions
    runs: tuple[AssignedRun, ...]


@dataclass(frozen=True)
class PolicyRows:
    policy: str
    base_policy: str
    parameters: PolicyConfig
    observations: tuple[Observation, ...]
    clusters: dict[str, tuple[Observation, ...]]
    repositories: dict[str, tuple[Observation, ...]]
    run_ids: tuple[str, ...]


def _policy_name(policy: PolicyConfig) -> str:
    if policy.id in {"symbol_validate", "symbol_invalidate"}:
        return f"{policy.id}-depth{policy.dependency_depth}"
    return policy.id


def _population_key(config: RunConfig) -> str:
    data = config.model_dump(mode="json")
    for field in ("policy", "claims_path", "provenance_path", "parent_receipts_path",
                  "graph_views_path", "cache_dir", "frozen_protocol_path"):
        data.pop(field, None)
    data["repo"].pop("path", None)
    return digest(data)


def _validator_key(run: ScoredRun) -> str:
    config = run.manifest.config
    return digest({"validation": config.validation.model_dump(mode="json"), "environment_profiles": {
        name: profile.model_dump(mode="json")
        for name, profile in sorted(config.environment_profiles.items())},
        "allow_network": config.allow_network, "max_calls": config.max_calls,
        "replicate_id": config.replicate_id, "app_version": run.manifest.app_version,
        "validator_version": run.manifest.validator_version, "python": run.manifest.python})


def _expected_runs(dataset: DatasetManifest, dataset_path: Path) -> tuple[ExpectedRun, ...]:
    if len({row.run_id for row in dataset.runs}) != len(dataset.runs):
        raise InputError("duplicate dataset run_id")
    if len({repo.repo_id for repo in dataset.repositories}) != len(dataset.repositories):
        raise InputError("duplicate dataset repository ID")
    repos = {repo.repo_id: repo for repo in dataset.repositories}
    expected: list[ExpectedRun] = []
    for declaration in dataset.runs:
        if not declaration.run_id or not declaration.cluster_id:
            raise InputError("dataset run and cluster IDs must be nonempty")
        config_path = within(dataset_path.resolve().parent, declaration.config_path)
        config = load(config_path, RunConfig)
        repo_path = (config_path.parent / config.repo.path).resolve()
        parent, children = chain(repo_path, config.parent_commit, config.child_commits)
        config = config.model_copy(update={"parent_commit": parent, "child_commits": children,
            "repo": config.repo.model_copy(update={"path": str(repo_path)})})
        if (config.protocol_version != dataset.protocol_version
                or config.dataset_kind != dataset.dataset_kind or config.split != declaration.split):
            raise InputError("dataset and run protocol, kind, or split disagree")
        repo = repos.get(config.repo.repo_id)
        if repo is None or repo.source_roots != config.repo.source_roots:
            raise InputError("run repository or source roots absent from dataset")
        if (dataset_path.parent / repo.path).resolve() != repo_path:
            raise InputError("run repository path differs from dataset")
        if config.stratum == "replay" and not declaration.sequence_id:
            raise InputError("replay dataset runs require an explicit sequence_id")
        claims = load_jsonl(config_path.parent / config.claims_path, Claim, unique="claim_id")
        source_hashes = {name: file_hash(config_path.parent / relative) for name, relative in (
            ("claims", config.claims_path), ("provenance", config.provenance_path),
            ("parent_receipts", config.parent_receipts_path))}
        receipts = load_jsonl(config_path.parent / config.parent_receipts_path, ParentReceipt,
                              unique="claim_id")
        for receipt in receipts:
            evidence_hash = file_hash(within(config_path.parent, receipt.evidence_path))
            if evidence_hash != receipt.evidence_sha256:
                raise InputError("dataset parent evidence differs from receipt hash")
            source_hashes[f"parent_evidence/{receipt.claim_id}"] = evidence_hash
        for claim in claims:
            if isinstance(claim.predicate, Behavior):
                probe_hash = file_hash(within(config_path.parent, claim.predicate.probe_path))
                if probe_hash != claim.predicate.probe_sha256:
                    raise InputError("dataset behavior probe differs from claim hash")
                source_hashes[f"probe/{claim.claim_id}"] = probe_hash
        if config.graph_views_path is not None:
            for commit in (config.parent_commit, *config.child_commits):
                source_hashes[f"graph/{commit}"] = file_hash(
                    config_path.parent / config.graph_views_path / f"{commit}.json")
        expected.append(ExpectedRun(declaration, config, source_hashes,
                                    {claim.claim_id: digest(claim) for claim in claims}))
    populations: dict[str, ExpectedRun] = {}
    for row in expected:
        key = _population_key(row.config)
        policy = _policy_name(row.config.policy)
        previous = populations.get(key)
        if previous is None:
            populations[key] = replace(row, declared_policies=(policy,))
            continue
        if (previous.input_hashes != row.input_hashes
                or previous.claim_hashes != row.claim_hashes
                or previous.declaration.cluster_id != row.declaration.cluster_id
                or previous.declaration.sequence_id != row.declaration.sequence_id
                or policy in previous.declared_policies):
            raise InputError("ambiguous duplicate dataset populations")
        populations[key] = replace(previous, declared_policies=(*previous.declared_policies, policy))
    return tuple(populations.values())


def _assign_runs(expected: tuple[ExpectedRun, ...], run_dirs: list[Path],
                 labels: tuple[Label, ...], labels_hash: str) -> tuple[AssignedRun, ...]:
    assigned: list[AssignedRun] = []
    by_key = {_population_key(row.config): row for row in expected}
    seen: set[tuple[str, str]] = set()
    for path in run_dirs:
        scored = _score(path, labels, labels_hash)
        population = by_key.get(_population_key(scored.manifest.config))
        if population is None:
            raise InputError(f"run does not match a declared dataset configuration: {path}")
        recorded_hashes = scored.manifest.input_hashes
        if (not {"claims", "provenance", "parent_receipts"}.issubset(recorded_hashes)
                or any(population.input_hashes.get(key) != value
                       for key, value in recorded_hashes.items())
                or scored.manifest.claim_hashes != population.claim_hashes):
            raise InputError("dataset source or claim hashes differ from run artifacts")
        policy = _policy_name(scored.manifest.config.policy)
        identity = (population.declaration.run_id, policy)
        if identity in seen:
            raise InputError(f"duplicate dataset run/policy: {identity}")
        seen.add(identity)
        costs = load_jsonl(path / "costs.jsonl", Cost)
        phases = [(row.phase, row.commit) for row in costs]
        required = [("preflight", scored.manifest.parent_commit),
                    *(("maintenance", commit) for commit in scored.manifest.child_commits)]
        if len(phases) != len(set(phases)) or set(phases) != set(required):
            raise InputError("costs must cover preflight and each child revision exactly once")
        assigned.append(AssignedRun(population.declaration, scored, policy, costs))
    sets = {row.declaration.run_id: {run.policy for run in assigned
                                    if run.declaration.run_id == row.declaration.run_id}
            for row in expected}
    if not assigned or any(not policies for policies in sets.values()):
        raise InputError("partial populations: every declared dataset run must be supplied")
    for row in expected:
        if (len(row.declared_policies) > 1 or row.config.split == "heldout") and (
            sets[row.declaration.run_id] != set(row.declared_policies)
        ):
            raise InputError("supplied policies differ from explicitly declared policy variants")
    if len({tuple(sorted(policies)) for policies in sets.values()}) != 1:
        raise InputError("partial policy sets across dataset populations")
    if len(next(iter(sets.values()))) < 2:
        raise InputError("dataset analysis requires at least two compared policies")
    for declaration in (row.declaration for row in expected):
        peers = tuple(run for run in assigned if run.declaration.run_id == declaration.run_id)
        first = peers[0].scored
        signature = (set(first.manifest.cohort),
                     {(row.claim_id, row.reason) for row in first.manifest.excluded},
                     _validator_key(first), first.manifest.input_hashes)
        for peer in peers:
            candidate = peer.scored
            if (set(candidate.manifest.cohort),
                {(row.claim_id, row.reason) for row in candidate.manifest.excluded},
                _validator_key(candidate), candidate.manifest.input_hashes) != signature:
                raise InputError("paired runs differ in cohort, exclusions, or validator settings")
            if candidate.manifest.config.validation.llm == "openai":
                if (candidate.manifest.config.cache_dir is None
                        or candidate.manifest.config.cache_dir != first.manifest.config.cache_dir):
                    raise InputError("LLM policies require the same immutable verdict cache")
    policy_configs: dict[str, str] = {}
    for run in assigned:
        signature_hash = digest(run.scored.manifest.config.policy)
        if run.policy in policy_configs and policy_configs[run.policy] != signature_hash:
            raise InputError("same policy label has incompatible parameters")
        policy_configs[run.policy] = signature_hash
    return tuple(sorted(assigned, key=lambda row: (row.declaration.run_id, row.policy)))


def _make_groups(runs: tuple[AssignedRun, ...]) -> tuple[GroupRows, ...]:
    grouped: dict[str, list[AssignedRun]] = {}
    dimensions: dict[str, GroupDimensions] = {}
    for run in runs:
        config = run.scored.manifest.config
        base = GroupDimensions(dataset_kind=config.dataset_kind, split=config.split,
            stratum=config.stratum, scenario_id=config.scenario_id,
            validator_settings=_validator_key(run.scored),
            sequence_id=(run.declaration.sequence_id if config.stratum == "replay" else None))
        repos: tuple[str | None, ...] = (None, config.repo.repo_id)
        kinds: tuple[str | None, ...] = (None, *sorted({row.claim.kind
                                                       for row in run.scored.observations}))
        for repo in repos:
            for kind in kinds:
                key_dimensions = base.model_copy(update={"repo_id": repo, "claim_kind": kind})
                key = digest(key_dimensions)
                dimensions[key] = key_dimensions
                grouped.setdefault(key, []).append(run)
    return tuple(GroupRows(dimensions[key], tuple(grouped[key])) for key in sorted(grouped))


def _rows_by_policy(group: GroupRows) -> tuple[PolicyRows, ...]:
    result: list[PolicyRows] = []
    for policy in sorted({run.policy for run in group.runs}):
        runs = tuple(run for run in group.runs if run.policy == policy)
        clusters: dict[str, list[Observation]] = {}
        repositories: dict[str, list[Observation]] = {}
        observations: list[Observation] = []
        for run in runs:
            rows = tuple(row for row in run.scored.observations
                         if group.dimensions.claim_kind in {None, row.claim.kind})
            clusters.setdefault(run.declaration.cluster_id, []).extend(rows)
            repositories.setdefault(run.scored.report.repo_id, []).extend(rows)
            observations.extend(rows)
        result.append(PolicyRows(policy, runs[0].scored.report.policy,
            runs[0].scored.manifest.config.policy, tuple(observations),
            {key: tuple(rows) for key, rows in clusters.items()},
            {key: tuple(rows) for key, rows in repositories.items()},
            tuple(run.declaration.run_id for run in runs)))
    return tuple(result)


def _macro(rows: PolicyRows) -> dict[str, MacroMetric]:
    per_repo = {repo: compute_metrics(observations, rows.base_policy, repo)
                for repo, observations in rows.repositories.items()}
    result: dict[str, MacroMetric] = {}
    for name in next(iter(per_repo.values())).metrics:
        values: list[float] = []
        reasons: dict[str, str] = {}
        for repo, metrics in per_repo.items():
            metric = metrics.metrics[name]
            if metric.denominator is None:
                reasons[repo] = "not_a_rate"
            elif metric.value is None:
                reasons[repo] = metric.reason or "unavailable"
            else:
                values.append(float(metric.value))
        result[name] = MacroMetric(value=sum(values) / len(values) if values else None,
            contributing_repositories=len(values), total_repositories=len(per_repo),
            unavailable_reasons=reasons)
    return result


def _intervals(left: PolicyRows, right: PolicyRows, replay: bool) -> dict[str, BootstrapInterval]:
    left_groups = {cluster: compute_metrics(rows, left.base_policy, cluster)
                   for cluster, rows in left.clusters.items()}
    right_groups = {cluster: compute_metrics(rows, right.base_policy, cluster)
                    for cluster, rows in right.clusters.items()}
    if set(left_groups) != set(right_groups):
        raise InputError("unpaired policy clusters")
    result: dict[str, BootstrapInterval] = {}
    for name in next(iter(left_groups.values())).metrics:
        if replay:
            left_metric = compute_metrics(left.observations, left.base_policy, "sequence").metrics[name]
            right_metric = compute_metrics(right.observations, right.base_policy, "sequence").metrics[name]
            estimate = (float(left_metric.value) - float(right_metric.value)
                        if left_metric.value is not None and right_metric.value is not None else None)
            result[name] = BootstrapInterval(estimate=estimate, lower=None, upper=None,
                reason="replay_no_population_interval", clusters=len(left_groups))
            continue
        lm = {key: group.metrics[name] for key, group in left_groups.items()}
        rm = {key: group.metrics[name] for key, group in right_groups.items()}
        if any(metric.denominator is None or metric.reason == "not_applicable"
               for metric in (*lm.values(), *rm.values())):
            result[name] = BootstrapInterval(estimate=None, lower=None, upper=None,
                reason="not_applicable", clusters=len(left_groups))
            continue
        result[name] = paired_cluster_bootstrap(
            {key: (metric.numerator or 0, metric.denominator or 0) for key, metric in lm.items()},
            {key: (metric.numerator or 0, metric.denominator or 0) for key, metric in rm.items()})
    return result


def _group_report(group: GroupRows) -> GroupReport:
    rows = _rows_by_policy(group)
    aggregates: list[PolicyAggregate] = []
    for policy in rows:
        contradicted_clusters = sum(any(row.label.label == "contradicted" for row in observations)
                                    for observations in policy.clusters.values())
        metrics = compute_metrics(policy.observations, policy.base_policy, "micro",
                                  len(policy.clusters))
        metrics = metrics.model_copy(update={
            "exploratory": metrics.counters["contradicted"] < 50 or contradicted_clusters < 20})
        aggregates.append(PolicyAggregate(policy=policy.policy, policy_parameters=policy.parameters,
            micro=metrics, macro_by_repository=_macro(policy), total_clusters=len(policy.clusters),
            contradicted_clusters=contradicted_clusters, dataset_runs=policy.run_ids))
    intervals = {f"{policy.policy}-minus-{rows[0].policy}":
                 _intervals(policy, rows[0], group.dimensions.stratum == "replay")
                 for policy in rows[1:]}
    return GroupReport(dimensions=group.dimensions, policies=tuple(aggregates), intervals=intervals)


def _run_costs(run: AssignedRun) -> RunCosts:
    config = run.scored.manifest.config
    preflight = tuple(cost for cost in run.costs if cost.phase == "preflight")
    maintenance_by_commit = {cost.commit: cost for cost in run.costs if cost.phase == "maintenance"}
    maintenance = tuple(maintenance_by_commit[commit] for commit in config.child_commits)
    initial = sum(cost.wall_seconds for cost in preflight)
    wall = reconstructed = index = 0.0
    logical = actual = hits = 0
    curve: list[CumulativeCost] = []
    for transition, cost in enumerate(maintenance, 1):
        wall += cost.wall_seconds
        reconstructed += (cost.wall_seconds - cost.actual_validation_seconds
                          + cost.reconstructed_validation_seconds)
        index += cost.index_seconds
        logical += cost.logical_validations
        actual += cost.actual_validations
        hits += cost.cache_hits
        curve.append(CumulativeCost(transition=transition, commit=cost.commit,
            measured_maintenance_wall_seconds=wall, reconstructed_maintenance_seconds=reconstructed,
            measured_total_seconds=initial + wall, reconstructed_total_seconds=initial + reconstructed,
            cumulative_index_seconds=index, cumulative_logical_validations=logical,
            cumulative_actual_validations=actual, cumulative_cache_hits=hits))
    return RunCosts(dataset_run_id=run.declaration.run_id, policy=run.policy,
        cluster_id=run.declaration.cluster_id, sequence_id=run.declaration.sequence_id,
        preflight=_cost_summary(preflight, 0),
        maintenance=_cost_summary(maintenance, sum(row.selection.selected
                                                  for row in run.scored.observations)),
        initial_index_seconds=sum(cost.initial_index_seconds for cost in maintenance),
        later_index_seconds=sum(cost.incremental_index_seconds for cost in maintenance),
        cumulative=tuple(curve), uncached_timing=Metric(value=None,
            reason="three_uncached_shuffled_replicates_not_supplied"))


def _break_even(costs: tuple[RunCosts, ...]) -> tuple[BreakEven, ...]:
    result: list[BreakEven] = []
    by_run: dict[str, dict[str, RunCosts]] = {}
    for cost in costs:
        by_run.setdefault(cost.dataset_run_id, {})[cost.policy] = cost
    for run_id, policies in sorted(by_run.items()):
        reference = policies.get("all_validate")
        for name, policy in sorted(policies.items()):
            if not name.endswith("validate") and not name.startswith("symbol_validate-depth"):
                continue
            if name == "all_validate":
                continue
            transition = None
            if reference is not None:
                for point, baseline in zip(policy.cumulative, reference.cumulative, strict=True):
                    if point.reconstructed_total_seconds < baseline.reconstructed_total_seconds:
                        transition = point.transition
                        break
            result.append(BreakEven(dataset_run_id=run_id, policy=name,
                reference_policy="all_validate", first_observed_transition=transition,
                reason=None if transition is not None else (
                    "reference_policy_missing" if reference is None else "not_observed")))
    return tuple(result)


def analyze_dataset(dataset_path: Path, run_dirs: list[Path], labels_path: Path,
                    output_dir: Path) -> DatasetAnalysis:
    from cami.dataset import check_dataset
    dataset = check_dataset(dataset_path).manifest
    expected = _expected_runs(dataset, dataset_path)
    labels, labels_hash = load_labels(labels_path), file_hash(labels_path)
    assigned = _assign_runs(expected, run_dirs, labels, labels_hash)
    groups = tuple(_group_report(group) for group in _make_groups(assigned))
    costs = tuple(_run_costs(run) for run in assigned)
    limitations = ["Micro rates sum counters; macro rates average repositories with defined rates.",
        "Chronological, enriched, provenance scenarios, splits, and validator settings are separate.",
        "Replay sequences are separate descriptive results with no population confidence intervals.",
        "Reliability is exploratory below 50 contradicted claim/revision cases or 20 independent "
        "clusters containing contradictions.",
        "Cached validation durations reconstruct logical cost and are not measured end-to-end times.",
        "Three cold uncached replicates in seed-42 shuffled policy order were not supplied.",
        "Annotation histories are required to verify double-annotation coverage and Cohen's kappa.",
        "Cluster declarations are authoritative; independent history and episode membership must "
        "be fixed before outcomes are inspected."]
    limitations.extend(sorted({note for run in assigned
                               for note in run.scored.manifest.resource_notes}))
    if len({row.label.annotator_id for run in assigned
            for row in run.scored.observations}) < 2:
        limitations.append("Single-annotator limitation; independent double annotation is unverified.")
    if dataset.dataset_kind == "synthetic":
        limitations.append("This dataset is synthetic and does not support real-repository claims.")
    report = DatasetAnalysis(dataset_id=dataset.dataset_id, dataset_sha256=file_hash(dataset_path),
        labels_sha256=labels_hash, protocol_version=dataset.protocol_version, groups=groups,
        costs=costs, break_even=_break_even(costs),
        run_directories=tuple(str(path.resolve()) for path in run_dirs), limitations=tuple(limitations))
    reserve(output_dir)
    _write_analysis(report, assigned, output_dir)
    return report


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    write_bytes(path, stream.getvalue().encode("utf-8"))


def _write_analysis(report: DatasetAnalysis, runs: tuple[AssignedRun, ...], output: Path) -> None:
    write_json(output / "metrics.json", report)
    write_json(output / "intervals.json", [group.model_dump(mode="json") for group in report.groups])
    rows: list[dict[str, object]] = []
    fields = ["dataset_kind", "split", "stratum", "scenario_id", "validator_settings", "sequence_id",
              "repo_id", "claim_kind", "policy", "aggregation", "metric", "value", "numerator",
              "denominator", "reason", "clusters", "contradicted_clusters", "exploratory"]
    for group in report.groups:
        dimensions = group.dimensions.model_dump(mode="json")
        dimensions.pop("schema_version")
        for policy in group.policies:
            for name, metric in policy.micro.metrics.items():
                metric_row: dict[str, object] = {**dimensions, "policy": policy.policy,
                    "aggregation": "micro", "metric": name, "value": metric.value,
                    "numerator": metric.numerator, "denominator": metric.denominator,
                    "reason": metric.reason, "clusters": policy.total_clusters,
                    "contradicted_clusters": policy.contradicted_clusters,
                    "exploratory": policy.micro.exploratory}
                rows.append(metric_row)
            for name, macro in policy.macro_by_repository.items():
                rows.append({**dimensions, "policy": policy.policy, "aggregation": "macro",
                    "metric": name, "value": macro.value, "numerator": None,
                    "denominator": macro.contributing_repositories,
                    "reason": "no_defined_repository_rates" if macro.value is None else None,
                    "clusters": policy.total_clusters,
                    "contradicted_clusters": policy.contradicted_clusters,
                    "exploratory": policy.micro.exploratory})
    _write_csv(output / "comparison.csv", fields, rows)
    claim_rows: list[dict[str, object]] = []
    for run in runs:
        for row in run.scored.observations:
            claim_rows.append({"dataset_run_id": run.declaration.run_id,
                "cluster_id": run.declaration.cluster_id, "policy": run.policy,
                "claim_id": row.claim.claim_id, "commit": row.state.revision,
                "kind": row.claim.kind, "label": row.label.label, "state": row.state.state,
                "available": row.state.available, "basis": row.state.basis,
                "selected": row.selection.selected})
    _write_csv(output / "per_claim.csv", ["dataset_run_id", "cluster_id", "policy", "claim_id",
        "commit", "kind", "label", "state", "available", "basis", "selected"], claim_rows)
    curves: list[dict[str, object]] = []
    for cost in report.costs:
        for point in cost.cumulative:
            data = point.model_dump(mode="json")
            data.pop("schema_version")
            curves.append({"dataset_run_id": cost.dataset_run_id, "policy": cost.policy, **data})
    _write_csv(output / "cumulative_cost.csv", ["dataset_run_id", "policy", "transition", "commit",
        "measured_maintenance_wall_seconds", "reconstructed_maintenance_seconds",
        "measured_total_seconds", "reconstructed_total_seconds", "cumulative_index_seconds",
        "cumulative_logical_validations", "cumulative_actual_validations", "cumulative_cache_hits"],
        curves)
    lines = [f"# Dataset analysis {report.dataset_id}", "",
        f"Analyzed {len(report.costs)} policy runs. Labels SHA-256: {report.labels_sha256}.", "",
        "All declared populations have complete matched policy sets. Missing labels and incompatible "
        "cohorts are rejected before report creation.", "", "Excluded claims:", ""]
    exclusions = sorted({(run.declaration.run_id, excluded.claim_id, excluded.reason)
                         for run in runs for excluded in run.scored.report.excluded})
    lines.extend([f"- {run_id}/{claim_id}: {reason}" for run_id, claim_id, reason in exclusions]
                 or ["None."])
    lines += ["", "Uncertainty and technical outcomes:", ""]
    for run in runs:
        counts = run.scored.report.overall.counters
        lines.append(f"- {run.declaration.run_id}/{run.policy}: uncertain labels "
                     f"{counts['uncertain']}, insufficient evidence {counts['insufficient_evidence']}, "
                     f"unchecked at current revision {counts['unchecked_current_revision']}.")
        for reason, count in sorted(run.scored.report.validator_reasons.items()):
            lines.append(f"- {run.declaration.run_id}/{run.policy} validator reason {reason}: {count}.")
    lines += ["", "Observed break-even against all_validate:", ""]
    lines.extend([f"- {item.dataset_run_id}/{item.policy}: "
                  f"{item.first_observed_transition if item.first_observed_transition else item.reason}."
                  for item in report.break_even] or ["No selective validation policies supplied."])
    lines += ["", "Limitations:", ""]
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    write_bytes(output / "summary.md", ("\n".join(lines) + "\n").encode("utf-8"))
    _plot_analysis(report, output)


def _plot_analysis(report: DatasetAnalysis, output: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    groups = tuple(group for group in report.groups
                   if group.dimensions.repo_id is None and group.dimensions.claim_kind is None)
    fig, axes = plt.subplots(max(len(groups), 1), 2, figsize=(12, 4 * max(len(groups), 1)),
                             squeeze=False)
    for index, group in enumerate(groups):
        dimension = group.dimensions
        labels = [policy.policy for policy in group.policies]
        axis = axes[index][0]
        positions = list(range(len(labels)))
        for offset, name, title in ((-0.2, "stale_exposure", "Stale exposure"),
                                   (0.2, "valid_retention", "Valid retention")):
            values = [float(policy.micro.metrics[name].value or 0)
                      if policy.micro.metrics[name].value is not None else float("nan")
                      for policy in group.policies]
            axis.bar([position + offset for position in positions], values, width=0.4, label=title)
        axis.set_xticks(positions, labels, rotation=45, ha="right")
        axis.set_ylim(0, 1)
        axis.legend()
        axis.set_title(f"{dimension.split}/{dimension.stratum}/{dimension.scenario_id} "
                       f"{dimension.sequence_id or ''}")
        cost_axis = axes[index][1]
        run_ids = {run_id for policy in group.policies for run_id in policy.dataset_runs}
        for cost in report.costs:
            if cost.dataset_run_id in run_ids:
                cost_axis.plot([point.transition for point in cost.cumulative],
                    [point.reconstructed_total_seconds for point in cost.cumulative],
                    marker="o", label=f"{cost.dataset_run_id}/{cost.policy}")
        cost_axis.set_title("Cumulative reconstructed seconds including preflight")
        cost_axis.set_xlabel("Transition")
        cost_axis.legend(fontsize="small")
    fig.tight_layout()
    fig.savefig(output / "cost_quality.png", dpi=150)
    plt.close(fig)
