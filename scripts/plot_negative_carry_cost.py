"""Plot measured complete maintenance cost alongside validator-call counts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def run(source: Path, out: Path) -> None:
    summary = json.loads((source / "summary.json").read_bytes())
    work = json.loads((source / "expected-work.json").read_bytes())
    manifest = json.loads((source / "manifest.json").read_bytes())
    if manifest["status"] != "complete" or manifest["source_before"] != manifest["source_after"]:
        raise ValueError("requires complete measurement with stable source")
    variants = ["production", "signature_witness", "module_blob_witness"]
    labels = ["Production retry", "Signature witness", "Module-blob witness"]
    colors = ["#286c8e", "#b9583c", "#bf8651"]
    registered = "registered_inputs" in summary["variants"]
    if registered:
        variants.append("registered_inputs")
        labels.append("Registered inputs")
        colors.append("#826398")
    if any(row["candidate_minus_baseline_cpu_ns"] <= 0
           for rows in summary["paired_deltas"].values() for row in rows):
        raise ValueError("this figure describes candidates slower in every paired CPU block")
    counts = [work[v]["counts"]["actual_validation_calls"] for v in variants]
    samples = [summary["variants"][v]["cpu_ns"] for v in variants]
    medians = [x["median"] / 1e6 for x in samples]
    errors = [[(x["median"] - x["min"]) / 1e6 for x in samples],
              [(x["max"] - x["median"]) / 1e6 for x in samples]]
    plan = manifest["protocol"]
    out.mkdir(parents=True, exist_ok=False)
    fig, (left, right) = plt.subplots(1, 2, figsize=(10.5, 4.7 if registered else 4.1), constrained_layout=True)
    bars = left.barh(labels[::-1], counts[::-1], color=colors[::-1])
    left.bar_label(bars, padding=4)
    left.set_xlim(0, max(counts) * 1.2)
    left.set_title("Validation calls per 17-history pack", fontsize=11)
    right.barh(labels[::-1], medians[::-1], color=colors[::-1],
               xerr=[x[::-1] for x in errors], capsize=4)
    for y, value in enumerate(medians[::-1]):
        right.text(8, y, f"{value:.1f} ms", va="center", color="white", fontsize=10)
    right.set_xlim(0, max(x["max"] / 1e6 for x in samples) * 1.12)
    right.set_title(f"CPU time per {plan['histories_per_block']} whole packs", fontsize=11)
    right.set_xlabel(f"Median and min–max across {plan['paired_repetitions']} paired blocks")
    left.set_xlabel("Witness creation and eligibility are extra work")
    for axis in (left, right):
        axis.spines[["top", "right"]].set_visible(False)
        axis.grid(axis="x", alpha=.2)
        axis.set_axisbelow(True)
    fig.suptitle("Registered inputs still cost more than ordinary retry" if registered
                 else "Fewer validator calls, higher total maintenance cost", fontsize=13)
    fig.supxlabel("17 authored histories / 31 transitions. All candidates are slower in every paired CPU block.\n"
                  "Index, Git and reference setup excluded and reported separately; no corpus speedup claim.", fontsize=9)
    fig.savefig(out / "negative-carry-cost.png", dpi=180)
    fig.savefig(out / "negative-carry-cost.svg")
    plt.close(fig)

    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    record = {"sources": {str(source / name): sha(source / name)
                          for name in ("summary.json", "expected-work.json", "manifest.json")},
              "script_sha256": sha(Path(__file__)),
              "artifacts": {p.name: sha(p) for p in out.iterdir() if p.is_file()}}
    (out / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.out)
