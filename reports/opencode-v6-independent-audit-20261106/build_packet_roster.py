"""All24 terminal-bound v6 memory packets for readonly lossless-display prototypes."""

from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUN = ROOT / "runs/opencode-development-v6-20261106"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    plan = json.loads((RUN / "plan.json").read_bytes())["trials"]
    bindings = json.loads((HERE / "independent-v1/input-hashes.json").read_bytes())
    roster = []
    for trial in plan:
        if trial["arm"] == "plain":
            continue
        directory = RUN / "trials" / trial["id"]
        message_path = directory / "session/evidence/messages.json"
        trace_path = directory / "session/evidence/memory-backend-trace.jsonl"
        assert (
            sha(message_path)
            == bindings[trial["id"]]["public_artifact_hashes"]["session/evidence/messages.json"]
        )
        assert (
            sha(trace_path)
            == bindings[trial["id"]]["public_artifact_hashes"][
                "session/evidence/memory-backend-trace.jsonl"
            ]
        )
        messages = json.loads(message_path.read_bytes())
        calls = [
            (message_index, part_index, message, part)
            for message_index, message in enumerate(messages)
            for part_index, part in enumerate(message.get("content", []))
            if part.get("type") == "tool"
            and (
                part.get("name") == "memory_lookup"
                or part.get("name", "").endswith("_memory_lookup")
            )
        ]
        lookups = [
            (line_number, json.loads(line))
            for line_number, line in enumerate(trace_path.read_text().splitlines(), 1)
            if line.strip() and json.loads(line).get("event") == "memory_lookup"
        ]
        assert len(calls) == len(lookups)
        for (message_index, part_index, message, part), (line_number, event) in zip(
            calls, lookups, strict=True
        ):
            assert part["state"]["status"] == "completed"
            assert (
                hashlib.sha256(canonical(part["state"]["input"])).hexdigest()
                == event["query_sha256"]
            )
            audit = event["response_audit"]
            assert (
                audit["receipt_payload"]["full_result_sha256"]
                == hashlib.sha256(canonical(audit["full_result"])).hexdigest()
            )
            full = json.loads(audit["full_result"]["content"][0]["text"])
            roster.append(
                {
                    "trial_id": trial["id"],
                    "arm": trial["arm"],
                    "call_id": part["id"],
                    "message_id": message["id"],
                    "messages_path": str(message_path.relative_to(ROOT)),
                    "messages_sha256": sha(message_path),
                    "model_text_json_pointer": f"/{message_index}/content/{part_index}/state/content/0/text",
                    "backend_trace_path": str(trace_path.relative_to(ROOT)),
                    "backend_trace_sha256": sha(trace_path),
                    "backend_lookup_jsonl_line_one_based": line_number,
                    "full_result_pointer_within_trace_event": "/response_audit/full_result",
                    "full_result_sha256": audit["receipt_payload"]["full_result_sha256"],
                    "model_result_sha256": audit["model_result_sha256"],
                    "receipt_sha256": audit["receipt_sha256"],
                    "arguments_sha256": event["query_sha256"],
                    "returned_records": len(full["entries"]),
                    "withheld_records": len(full["withheld"]),
                }
            )
    assert len(roster) == 24
    result = {
        "status": "all_closed_v6_memory_packets",
        "selection": "All24memory calls from the full36terminal schedule; no task/arm/outcome filtering. Plain has no memory packet.",
        "study_sha256": "b66e4d557b7b7cdf0800b4c9121e793659f3a02029a74b026c7f7c4d75243cdd",
        "roster": roster,
        "wire_accounting_sha256": sha(HERE / "wire-accounting.json"),
        "model_calls": 0,
    }
    (HERE / "memory-packet-roster.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "packets": len(roster),
                "roster_sha256": sha(HERE / "memory-packet-roster.json"),
                "wire_accounting_sha256": sha(HERE / "wire-accounting.json"),
            }
        )
    )


if __name__ == "__main__":
    main()
