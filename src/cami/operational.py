from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from cami.artifacts import read_json, read_jsonl, reserve, write_bytes, write_json
from cami.errors import InputError


def pilot_report(run_root: Path, output: Path) -> None:
    manifests = sorted(run_root.glob("*/*/manifest.json"))
    if not manifests:
        raise InputError("no pilot runs found")
    rows: list[dict[str, Any]] = []
    totals: dict[str, dict[str, float]] = {}
    for path in manifests:
        manifest = read_json(path)
        if manifest["status"] != "complete" or manifest["config"]["dataset_kind"] != "real":
            raise InputError("pilot report requires complete real runs")
        policy = manifest["config"]["policy"]["id"]
        for cost in read_jsonl(path.parent / "costs.jsonl"):
            row = {"run_id":path.parent.parent.name,"policy":policy,"phase":cost["phase"],"commit":cost["commit"],
                   **{k:cost[k] for k in ("wall_seconds","cpu_seconds","index_seconds","logical_validations","actual_validations","cache_hits","test_executions")}}
            rows.append(row)
            group = totals.setdefault(policy, {})
            for key in ("wall_seconds","cpu_seconds","index_seconds","logical_validations","actual_validations","cache_hits","test_executions"):
                group[key] = group.get(key,0.0) + row[key]
    reserve(output)
    write_json(output / "operational_costs.json", {"schema_version":1,"dataset_kind":"real","runs":len(manifests),
        "totals_by_policy":totals,"quality_metrics":None,"quality_metrics_reason":"independent_child_labels_pending",
        "timing_design":"one fixed-order uncached pass; not a final timing comparison","raw_costs":rows})
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    write_bytes(output / "operational_costs.csv", stream.getvalue().encode())
    lines = ["# Click operational pilot", "", f"Completed {len(manifests)} policy runs on real Git revisions.", "",
             "Independent child labels are pending. No stale exposure, retention, reliability interval, or hypothesis result is reported.", "",
             "| Policy | Wall seconds | Index seconds | Logical validations | Actual validations |",
             "|---|---:|---:|---:|---:|"]
    for policy, values in sorted(totals.items()):
        lines.append(f"| {policy} | {values['wall_seconds']:.3f} | {values['index_seconds']:.3f} | {int(values['logical_validations'])} | {int(values['actual_validations'])} |")
    lines += ["", "Costs include measured preflight and maintenance. These runs used one fixed order without a shared cache. Three randomized timing repetitions were not performed for this real pilot.",
              "", "The pilot cohort contains only exact function-existence claims. Behavioral historical environments, independent child annotations, annotation effort and double-annotation agreement remain unmeasured.",
              "", "The 12 chronologically adjacent candidate transitions share one episode cluster. No held-out evaluation has been run."]
    write_bytes(output / "summary.md",("\n".join(lines)+"\n").encode())
