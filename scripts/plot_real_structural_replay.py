"""Plot frozen real-development replay counts, not a runtime speedup estimate."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def run(source: Path, out: Path) -> None:
    report_path = source / "report.json"
    observations_path = source / "observations.jsonl"
    report = json.loads(report_path.read_bytes())
    observations = [json.loads(line) for line in observations_path.read_text().splitlines()]
    variants = ["symbol_anchor", "file_anchor", "known_incomplete", "all_validate"]
    labels = ["Symbol anchor", "File anchor", "Known incomplete", "Validate all"]
    counts = [report["variants"][v]["actual_validation_calls"] for v in variants]
    denominators = {report["variants"][v]["scored_observations"] for v in variants}
    if len(denominators) != 1:
        raise ValueError("plot requires a shared scored denominator")
    denominator = denominators.pop()
    contradicted_ids = {r["claim_id"] for r in observations if r["reference"]["verdict"] == "contradicted"}
    if len(contradicted_ids) != 1:
        raise ValueError("this case-study plot requires exactly one contradicted claim")
    claim_id = next(iter(contradicted_ids))
    timeline = [r for r in observations if r["variant"] == "symbol_anchor" and r["claim_id"] == claim_id]
    if any(report["variants"][v][key] != 0 for v in variants
           for key in ("false_available", "available_unknown", "withheld_supported")):
        raise ValueError("quality annotation does not describe this run")
    out.mkdir(parents=True, exist_ok=False)
    fig, (left, right) = plt.subplots(1, 2, figsize=(10.8, 4.4), constrained_layout=True,
                                    gridspec_kw={"width_ratios": [1.25, 1]})
    bars = left.barh(labels[::-1], counts[::-1], color=["#637180", "#939da6", "#39968f", "#286c8e"])
    left.bar_label(bars, padding=4)
    left.set_xlim(0, denominator * 1.18)
    left.set_title(f"Child validation calls / {denominator} observations", fontsize=11)
    left.set_xlabel("Calls; parent initialization counted separately")
    left.grid(axis="x", alpha=.2)
    left.set_axisbelow(True)
    positions = list(range(1, len(timeline) + 1))
    right.step(positions, [int(r["reference"]["verdict"] == "supported") for r in timeline],
               where="post", color="#286c8e", label="Reference support")
    right.scatter(positions, [int(r["state"]["available"]) for r in timeline],
                  color="#b9583c", marker="x", s=60, label="Symbol-policy availability", zorder=3)
    right.set_xticks(positions)
    right.set_yticks([0, 1], ["No", "Yes"])
    right.set_ylim(-.17, 1.2)
    right.set_title("One claim across 12 child commits", fontsize=11)
    right.set_xlabel("Child ordinal in the longer Click trajectory")
    right.legend(loc="upper right", fontsize=8, frameon=False)
    right.grid(alpha=.2)
    for axis in (left, right):
        axis.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Real Click development replay: 24 fixed structural claims", fontsize=13)
    fig.supxlabel("All four strategies: zero false availability and zero withheld support.\n"
                  "Eight contradicted observations belong to one claim; no runtime or held-out claim.", fontsize=9)
    fig.savefig(out / "real-structural-replay.png", dpi=180)
    fig.savefig(out / "real-structural-replay.svg")
    plt.close(fig)

    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"inputs": {str(p): sha(p) for p in (report_path, observations_path)},
                "script_sha256": sha(Path(__file__)), "timeline_claim_id": claim_id,
                "artifacts": {p.name: sha(p) for p in out.iterdir() if p.is_file()}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.out)
