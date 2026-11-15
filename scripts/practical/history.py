"""Read-only local history inventory. No prompt text is exported to reports."""

import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/practical-20261115"


def main():
    rows, sessions, errors = [], [], []
    for path in sorted(Path("/root/.codex/sessions").rglob("*.jsonl")):
        meta = None
        messages = []
        try:
            for line_no, line in enumerate(path.open(), 1):
                d = json.loads(line)
                if d["type"] == "session_meta":
                    meta = d["payload"]
                # event_msg is the user submission; response_item also includes injected context.
                if d["type"] == "response_item" and d["payload"].get("role") == "user":
                    text = "".join(x.get("text", "") for x in d["payload"].get("content", []))
                    if text.startswith(
                        (
                            "# AGENTS.md",
                            "<environment_context>",
                            "<recommended_plugins>",
                            "<skill>",
                            "<codex_internal_context",
                            "Background command completed",
                            "Delegated task ",
                            "[Thread:",
                        )
                    ):
                        continue
                    messages.append((line_no, d["timestamp"], text))
        except (ValueError, OSError) as error:
            errors.append({"path": str(path), "error": type(error).__name__})
        if not meta or "change-aware-memory-invalidation" not in meta.get("cwd", ""):
            continue
        source = meta.get("source")
        sessions.append({"path": str(path), "source": source, "messages": len(messages)})
        for line_no, timestamp, text in messages:
            delegated = (isinstance(source, dict) and "subagent" in str(source).lower()) or any(
                t in text.lower()
                for t in [
                    "sub-agent",
                    "subagent",
                    "read-only architecture task",
                    "authoritativeupstreamevent:",
                ]
            )
            experimental = any(
                s in text.lower()
                for s in [
                    "you are reviewer",
                    "benchmark trial",
                    "exact-task-replay-development",
                    "canonical a,a,b,b",
                ]
            )
            rows.append(
                {
                    "source": str(path),
                    "line": line_no,
                    "timestamp": timestamp,
                    "prompt_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "class": "delegated"
                    if delegated
                    else "experiment"
                    if experimental
                    else "user_submission",
                    "eligible": False,
                    "reasons": [
                        "no_launch_workspace_bytes_and_modes",
                        "no_bound_external_context",
                        "no_per_task_quality_and_complete_cost_binding",
                    ],
                }
            )
    db = Path("/root/.local/share/opencode/opencode.db")
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    found = c.execute(
        "select id,directory,title from session_v2 where directory like '%change-aware-memory-invalidation%'"
    ).fetchall()
    for sid, directory, title in found:
        for mid, timestamp, data in c.execute(
            "select id,time_created,data from session_message where session_id=? and type='user'",
            (sid,),
        ):
            rows.append(
                {
                    "source": str(db),
                    "session": sid,
                    "message": mid,
                    "timestamp": timestamp,
                    "prompt_record_sha256": hashlib.sha256(data.encode()).hexdigest(),
                    "class": "experiment"
                    if title
                    and any(s in title.lower() for s in ["trial", "benchmark", "probe", "cami-"])
                    else "user_submission",
                    "eligible": False,
                    "reasons": [
                        "no_launch_workspace_bytes_and_modes",
                        "no_bound_external_context",
                        "no_per_task_quality_and_complete_cost_binding",
                    ],
                }
            )
    c.close()
    users = [r for r in rows if r["class"] == "user_submission"]
    result = {
        "scope": "local histories for this repository, user submissions are an upper bound on independent tasks (followups not inferred)",
        "codex_sessions": sessions,
        "opencode_sessions": len(found),
        "rows": rows,
        "errors": errors,
        "counts": {
            "all_records": len(rows),
            "user_submissions": len(users),
            "excluded": len(rows) - len(users),
            "eligible": 0,
            "ineligible": len(users),
            "exact_repeats": None,
            "chronological_hit_rate": None,
        },
        "verdict": "historical suitability failed; exact repetition is unidentifiable, not zero",
        "billing": "local session cumulative counters cannot attribute missing provider responses; no invoice ledger available; no money inferred",
    }
    (OUT / "history.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result["counts"]))


if __name__ == "__main__":
    main()
