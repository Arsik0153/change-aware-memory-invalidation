"""Keep admission failures separate from primary comparisons, without dropping usage."""

import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "runs/practical-complete-20261115"
REPORT = ROOT / "reports/practical-complete-20261115"
FIELDS = ["input", "cache_read", "cache_write", "output", "reasoning"]


def main():
    admissions = []
    for database in sorted((RUN / "ordinary-smoke").glob("journals*/*/events.sqlite")):
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            terminals = [
                json.loads(row[0])
                for row in connection.execute(
                    "select data from events where kind='terminal' order by seq"
                )
            ]
        finally:
            connection.close()
        if not terminals:
            admissions.append(
                {"journal": str(database.relative_to(ROOT)), "complete": False, "usage_total": None}
            )
            continue
        record = terminals[-1]
        admissions.append(
            {
                "journal": str(database.relative_to(ROOT)),
                "complete": record["telemetry"]["complete"],
                "quality": record["quality"],
                "execution": record["execution"],
                "usage_total": record["telemetry"]["total"],
                "known_subtotal": record["telemetry"]["known_subtotal"],
                "requests": record["telemetry"]["requests"],
                "role": "authored admission; excluded from production hit rate and primary experiment",
            }
        )
    assert admissions
    primary = []
    for directory in sorted((RUN / "model").iterdir()):
        terminal = directory / "terminal.json"
        if not terminal.exists():
            continue
        row = json.loads(terminal.read_text())
        primary.append(
            {
                "id": row["trial"]["id"],
                "quality_pass": row["quality_pass"],
                "complete": row["usage_complete"],
                "usage_total": row["usage"] if row["usage_complete"] else None,
                "known_subtotal": row["usage"],
                "role": "predeclared primary comparison",
            }
        )
    complete = len(primary) == 72 and all(row["complete"] for row in admissions + primary)
    lower_bounds = {
        field: sum(
            (row.get("known_subtotal") or {}).get(field) or 0 for row in admissions + primary
        )
        for field in FIELDS
    }
    result = {
        "scope": "Observed normalized usage for all OpenCode admissions and primary comparison attempts in this execution; not parent-chat usage or an account invoice.",
        "primary_terminal_attempts": len(primary),
        "primary_planned_attempts": 72,
        "admission_attempts": len(admissions),
        "admission_records": admissions,
        "primary_records": primary,
        "observed_accounting_complete": complete,
        "known_token_component_lower_bounds": lower_bounds,
        "observed_token_components_total": lower_bounds if complete else None,
        "actual_invoice_amount": None,
        "billing_reconciliation": "No independent invoice source configured.",
        "failures_policy": "Failed admission calls are retained separately; none enters the primary sample. Unknown usage never becomes an exact zero.",
    }
    (REPORT / "all-opencode-attempt-accounting.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in ["admission_records", "primary_records"]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
