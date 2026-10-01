from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from cami.artifacts import write_bytes, write_json

if TYPE_CHECKING:
    from cami.evaluation import ComparisonReport, EvaluationReport, Observation


def _csv(path: Path, fields: list[str], rows: Iterable[dict[str, object]]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    write_bytes(path, stream.getvalue().encode("utf-8"))


def write_score(report: EvaluationReport, observations: tuple[Observation, ...],
                output_dir: Path) -> None:
    write_json(output_dir / "metrics.json", report)
    fields = ["claim_id", "commit", "kind", "label", "available", "state", "basis", "selected",
              "last_checked_commit", "last_verdict", "current_validator", "current_verdict",
              "validation_reason", "withheld_reason"]
    rows: list[dict[str, object]] = [{"claim_id": row.claim.claim_id, "commit": row.state.revision,
             "kind": row.claim.kind, "label": row.label.label, "available": row.state.available,
             "state": row.state.state, "basis": row.state.basis, "selected": row.selection.selected,
             "last_checked_commit": row.state.last_checked_commit,
             "last_verdict": row.state.last_verdict,
             "current_validator": row.validation.validator if row.validation else None,
             "current_verdict": row.validation.verdict if row.validation else None,
             "validation_reason": row.validation.reason if row.validation else None,
             "withheld_reason": row.state.withheld_reason} for row in observations]
    _csv(output_dir / "per_claim.csv", fields, rows)
    lines = [f"# Policy {report.policy}", "",
             f"Dataset: {report.dataset_kind}. Repository: {report.repo_id}. "
             f"Split: {report.split}. Stratum: {report.stratum}. Provenance: {report.scenario_id}.",
             "", "Metrics pool claim/revision counters over the fixed cohort. "
             "Each revision is also reported separately in metrics.json.", "",
             "| Metric | Value | Numerator | Denominator | Unavailable reason |",
             "|---|---:|---:|---:|---|"]
    for name, metric in report.overall.metrics.items():
        value = f"{metric.value:.6g}" if metric.value is not None else "null"
        lines.append(f"| {name} | {value} | {metric.numerator} | {metric.denominator} | "
                     f"{metric.reason or ''} |")
    lines += ["", f"Unknown labels: {report.label_counts['uncertain']}. "
              "Missing cohort labels: 0; missing coverage is rejected before scoring.",
              f"Unchecked current-revision claims: "
              f"{report.overall.counters['unchecked_current_revision']}.",
              f"Insufficient evidence results: {report.overall.counters['insufficient_evidence']}.",
              "", "Excluded claims:", ""]
    lines += ([f"- {row.claim_id}: {row.reason}" for row in report.excluded] or ["None."])
    lines += ["", "Validator reason counts:", ""]
    lines += ([f"- {reason}: {count}" for reason, count in sorted(report.validator_reasons.items())]
              or ["No validations were performed."])
    lines += ["", "Costs:", ""]
    for phase, cost in report.costs.items():
        lines += [f"- {phase}: {cost.totals}"]
        if cost.unavailable_reasons:
            lines += [f"- Unavailable {phase} costs: {cost.unavailable_reasons}"]
    lines += ["", "Cached runtime reconstruction estimates policy validation cost; "
              "it is not a measured end-to-end runtime.", "", "Limitations:", ""]
    lines += [f"- {limitation}" for limitation in report.limitations]
    write_bytes(output_dir / "summary.md", ("\n".join(lines) + "\n").encode("utf-8"))


def write_comparison(report: ComparisonReport, output_dir: Path) -> None:
    fields = ["policy", "dataset_kind", "repo_id", "stratum", "scenario_id", "metric", "value",
              "numerator", "denominator", "reason", "wall_seconds", "actual_validation_seconds",
              "reconstructed_validation_seconds"]
    rows: list[dict[str, object]] = []
    for run in report.reports:
        costs = run.costs["maintenance"].totals
        for name, metric in run.overall.metrics.items():
            rows.append({"policy": run.policy, "dataset_kind": run.dataset_kind,
                         "repo_id": run.repo_id, "stratum": run.stratum,
                         "scenario_id": run.scenario_id, "metric": name, "value": metric.value,
                         "numerator": metric.numerator, "denominator": metric.denominator,
                         "reason": metric.reason, "wall_seconds": costs["wall_seconds"],
                         "actual_validation_seconds": costs["actual_validation_seconds"],
                         "reconstructed_validation_seconds":
                         costs["reconstructed_validation_seconds"]})
    _csv(output_dir / "comparison.csv", fields, rows)
    lines = ["# Policy comparison", "", "Each policy has a separate summary and per-claim report.",
             "", "Observed Pareto dominance uses reconstructed maintenance cost, stale exposure, "
             "and valid retention.", ""]
    for policy, peers in report.pareto_dominated_by.items():
        lines.append(f"- {policy}: dominated by {', '.join(peers) if peers else 'none observed'}.")
    lines += ["", "Limitations:", ""]
    lines += [f"- {limitation}" for limitation in report.limitations]
    write_bytes(output_dir / "summary.md", ("\n".join(lines) + "\n").encode("utf-8"))
    _plot_comparison(report, output_dir)


def _plot_comparison(report: ComparisonReport, output_dir: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(12, 4))
    policies = [run.policy for run in report.reports]
    for axis, metric, title in zip(axes, ["cost", "stale_exposure", "valid_retention"],
                                   ["Reconstructed maintenance seconds", "Stale exposure",
                                    "Valid retention"], strict=True):
        values: list[float] = []
        for run in report.reports:
            if metric == "cost":
                totals = run.costs["maintenance"].totals
                wall, actual = totals["wall_seconds"], totals["actual_validation_seconds"]
                reconstructed = totals["reconstructed_validation_seconds"]
                value = (wall - actual + reconstructed
                         if wall is not None and actual is not None and reconstructed is not None
                         else None)
            else:
                value = run.overall.metrics[metric].value
            values.append(float(value) if value is not None else float("nan"))
        axis.bar(policies, values)
        axis.set_title(title)
        axis.tick_params(axis="x", labelrotation=45)
        if metric != "cost":
            axis.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(output_dir / "cost_quality.png", dpi=150)
    plt.close(fig)
