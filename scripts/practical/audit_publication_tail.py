"""Account for the terminal-publication boundary without changing primary records."""

import json
from pathlib import Path
import sqlite3
import statistics

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/practical-complete-20261115"
RUN = ROOT / "runs/practical-complete-20261115/model"


def main():
    protocol = json.loads((REPORT / "protocol.json").read_text())
    rows = []
    for trial in protocol["schedule"]:
        directory = RUN / trial["id"]
        terminal = json.loads((directory / "terminal.json").read_text())
        db = sqlite3.connect(f"file:{directory / 'events.sqlite'}?mode=ro", uri=True)
        try:
            clock = db.execute("select time_ns from events where kind='quality'").fetchone()[0]
        finally:
            db.close()
        # quality acknowledgement precedes the recorded stop. JSON publication
        # follows the terminal journal's durable commit. This deliberately wide
        # interval contains that omitted receipt tail, without guessing zero.
        upper = ((directory / "terminal.json").stat().st_mtime_ns - clock) / 1e9
        assert upper >= 0
        rows.append(
            {
                "trial": trial,
                "recorded_pipeline_seconds": terminal["pipeline_wall_seconds"],
                "publication_tail_upper_seconds": upper,
            }
        )
    pairs = []
    for task in protocol["tasks"]:
        groups = {
            arm: [r for r in rows if r["trial"]["task"] == task["id"] and r["trial"]["arm"] == arm]
            for arm in ["plain", "cami"]
        }
        mean = {
            arm: statistics.mean(r["recorded_pipeline_seconds"] for r in group)
            for arm, group in groups.items()
        }
        upper = {
            arm: statistics.mean(r["publication_tail_upper_seconds"] for r in group)
            for arm, group in groups.items()
        }
        pairs.append(
            {
                "task": task["id"],
                "most_favorable_cami_ratio": mean["cami"] / (mean["plain"] + upper["plain"]),
                "least_favorable_cami_ratio": (mean["cami"] + upper["cami"]) / mean["plain"],
            }
        )
    result = {
        "status": "verified",
        "analysis_timing": "Post-run endpoint audit, separate from the predeclared primary result. Original records and criteria unchanged.",
        "deviation": "Protocol wording ended after the durable terminal journal; implementation stopped immediately before terminal journal/publication. Source/quality journal commits and all substantive work are inside the recorded span.",
        "observed_tail_upper_max_seconds": max(r["publication_tail_upper_seconds"] for r in rows),
        "observed_tail_upper_median_seconds": statistics.median(
            r["publication_tail_upper_seconds"] for r in rows
        ),
        "corrected_median_time_ratio_bounds": [
            statistics.median(r["most_favorable_cami_ratio"] for r in pairs),
            statistics.median(r["least_favorable_cami_ratio"] for r in pairs),
        ],
        "bound_scope": "Observed same-host UTC clocks and immutable terminal-file mtimes; a conservative interval from quality acknowledgement to later JSON write, not a new timed run.",
        "verdict": "Default recommendation remains rejected: the independent primary token-work gate already fails, and even the most favorable observed publication-tail correction does not approach the required time ratio <=0.90.",
        "rows": rows,
        "pairs": pairs,
    }
    assert result["corrected_median_time_ratio_bounds"][0] > 0.90
    (REPORT / "publication-tail-audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ["rows", "pairs"]}, indent=2))


if __name__ == "__main__":
    main()
