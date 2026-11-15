"""Count chronological exact repeats from captured, declared user tasks only."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "integrations/opencode"))
from task_replay import identity, inventory  # noqa: E402


def summarize(root):
    rows, excluded = [], []
    for database in sorted(root.glob("*/events.sqlite")):
        try:
            connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
            try:
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("corrupt journal")
                events = [
                    (clock, kind, json.loads(data))
                    for clock, kind, data in connection.execute(
                        "select time_ns,kind,data from events order by seq"
                    )
                ]
            finally:
                connection.close()
            start, _, config = next(row for row in events if row[1] == "prepared")
            context = json.loads(config["context"])
            if context.get("origin") != "user":
                excluded.append(
                    {
                        "journal": str(database.parent),
                        "reason": "not_declared_user_origin",
                        "origin": context.get("origin"),
                    }
                )
                continue
            if config["key"] != identity(config["files"], config["task"], config["context"]):
                raise ValueError("input identity mismatch")
            if inventory(database.parent / "before") != config["files"]:
                raise ValueError("preserved input differs from recorded inventory")
            terminal = next((row for row in reversed(events) if row[1] == "terminal"), None)
            solution_verified = False
            if terminal and "solution_files" in terminal[2]:
                try:
                    solution_verified = (
                        inventory(database.parent / "solution") == terminal[2]["solution_files"]
                    )
                except (OSError, ValueError):
                    pass
            rows.append(
                {
                    "journal": str(database.parent),
                    "started_ns": start,
                    "key": config["key"],
                    "finished_ns": terminal[0] if terminal else None,
                    "terminal": terminal[2] if terminal else None,
                    "solution_verified": solution_verified,
                }
            )
        except (OSError, sqlite3.Error, ValueError, StopIteration, KeyError, TypeError) as error:
            excluded.append(
                {
                    "journal": str(database.parent),
                    "reason": type(error).__name__ + ": " + str(error),
                }
            )
    rows.sort(key=lambda row: (row["started_ns"], row["journal"]))
    seen = {}
    repeats, graded_opportunities, eligible_opportunities = 0, 0, 0
    for row in rows:
        earlier = seen.get(row["key"], [])
        repeats += bool(earlier)
        available = [
            r
            for r in earlier
            if r["finished_ns"] is not None
            and r["finished_ns"] <= row["started_ns"]
            and r["solution_verified"]
        ]
        graded_opportunities += any(
            r["terminal"].get("quality") == "pass" and r["terminal"].get("execution") == "success"
            for r in available
        )
        eligible_opportunities += any(
            r["terminal"].get("cache_eligible") is True for r in available
        )
        seen.setdefault(row["key"], []).append(row)
    return {
        "scope": "Declared user-origin logs only; origin is a caller declaration. Admission and experiment logs are excluded. No text-similarity matching or reconstruction of missing inputs.",
        "captured_user_requests": len(rows),
        "unique_exact_inputs": len(seen),
        "exact_repeat_requests": repeats,
        "observed_exact_repeat_fraction": repeats / len(rows) if rows else None,
        "opportunities_with_previously_completed_quality_passing_solution": graded_opportunities,
        "opportunities_with_previously_cache_eligible_solution": eligible_opportunities,
        "unfinished_user_requests": sum(r["terminal"] is None for r in rows),
        "excluded": excluded,
        "chronological_input_keys": [r["key"] for r in rows],
        "interpretation": "Repeat frequency is not measured model savings. A prior result must have completed before the new request to be available for replay. Fresh validation remains mandatory.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("journal_root", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = summarize(args.journal_root)
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
