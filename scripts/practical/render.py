"""Render retained attempts, with no change to the primary verdict."""

import json
from pathlib import Path
import sqlite3

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/practical-20261115"


def main():
    summary = json.loads((REPORT / "benchmark/summary.json").read_text())
    fig, axes = plt.subplots(1, 3, figsize=(12, 4))
    for ax, (case, data) in zip(axes, summary["cases"].items()):
        for i, arm in enumerate(["baseline", "candidate"]):
            d = data[arm]
            ax.errorbar(
                i,
                d["median"],
                yerr=[[d["median"] - d["min"]], [d["max"] - d["median"]]],
                fmt="o",
                capsize=6,
            )
        ax.set_xticks([0, 1], ["baseline", "candidate"])
        ax.set_title(case + " (5 each)")
        ax.set_ylabel("Complete local process, seconds")
        ax.set_ylim(bottom=0)
    fig.suptitle("Observed medians and min–max; candidate NOT accepted")
    fig.tight_layout()
    fig.savefig(REPORT / "timings.png", dpi=150)
    plt.close(fig)
    # Secondary semantic audit distinguishes deliberate code identity from search content.
    audits = []
    for case in ["found", "missing"]:
        for pair in range(5):
            values = []
            for arm in ["baseline", "candidate"]:
                d = json.loads((REPORT / f"benchmark/{case}-{pair}-{arm}.json").read_text())
                d.pop("observation")
                d["snapshot"].pop("fingerprint")
                d["snapshot"].pop("generation_id")
                values.append(d)
            audits.append({"case": case, "pair": pair, "semantic_equal": values[0] == values[1]})
    (REPORT / "secondary-output-audit.json").write_text(
        json.dumps(
            {
                "post_hoc": True,
                "removed_fields": ["observation", "snapshot.fingerprint", "snapshot.generation_id"],
                "pairs": audits,
                "primary_verdict_unchanged": True,
            },
            indent=2,
        )
    )
    receipts = []
    for path in sorted((REPORT / "fault-evidence").rglob("events.sqlite")):
        try:
            with sqlite3.connect(path) as c:
                kinds = c.execute("select kind,count(*) from events group by kind").fetchall()
                terminals = [
                    json.loads(r[0])
                    for r in c.execute("select data from events where kind='terminal'")
                ]
            receipts.append(
                {
                    "path": str(path.relative_to(REPORT)),
                    "events": dict(kinds),
                    "terminals": terminals,
                }
            )
        except sqlite3.DatabaseError:
            receipts.append({"path": str(path.relative_to(REPORT)), "expected_corrupt": True})
    (REPORT / "fault-audit.json").write_text(json.dumps(receipts, indent=2))
    (REPORT / "chart.html").write_text(
        '<!doctype html><meta charset="utf-8"><img style="width:100%" src="'
        + str(REPORT / "timings.png")
        + '" alt="Local timings: medians and ranges. Candidate rejected.">'
    )


if __name__ == "__main__":
    main()
