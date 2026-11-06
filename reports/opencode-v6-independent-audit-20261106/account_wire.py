"""Exact model-visible JSON byte partition; no tokenizer or causal token apportionment."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUN = ROOT / "runs/opencode-development-v6-20261106"


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode()


def main():
    plan = json.loads((RUN / "plan.json").read_bytes())["trials"]
    bindings = json.loads((HERE / "independent-v1/input-hashes.json").read_bytes())
    totals = {arm: Counter() for arm in ["plain", "static", "cami"]}
    calls, large, shell = [], [], {arm: Counter() for arm in totals}
    for trial in plan:
        path = RUN / "trials" / trial["id"] / "session/evidence/messages.json"
        assert (
            hashlib.sha256(path.read_bytes()).hexdigest()
            == bindings[trial["id"]]["public_artifact_hashes"]["session/evidence/messages.json"]
        )
        messages = json.loads(path.read_bytes())
        for message in messages:
            for part in message.get("content", []):
                if part.get("type") != "tool":
                    continue
                text = "\n".join(
                    value["text"]
                    for value in part.get("state", {}).get("content", [])
                    if value.get("type") == "text"
                )
                if part["name"] == "shell":
                    status = part["state"].get("metadata", {}).get("exit")
                    shell[trial["arm"]]["calls"] += 1
                    shell[trial["arm"]]["text_utf8_bytes"] += len(text.encode())
                    if type(status) is int and status != 0:
                        shell[trial["arm"]]["nonzero_exit_calls"] += 1
                        shell[trial["arm"]]["nonzero_exit_text_utf8_bytes"] += len(text.encode())
                    if len(text.encode()) > 15000:
                        large.append(
                            {
                                "trial_id": trial["id"],
                                "call_id": part["id"],
                                "text_utf8_bytes": len(text.encode()),
                                "shell_exit": status,
                                "command": part["state"]["input"].get("command"),
                                "scope": "Actual local developer test/debug output; nonzero exit is not final fixed-quality failure.",
                            }
                        )
                if not (part["name"] == "memory_lookup" or part["name"].endswith("_memory_lookup")):
                    continue
                value = json.loads(text)
                wire = text.encode()
                assert wire == canonical(value), (
                    "Canonical inner model-visible JSON required for exact partition"
                )
                count = len(value["entries"])
                raw, encoded = 0, 0
                subtrees = Counter()
                for entry in value["entries"]:
                    payload = entry["payload"]
                    literal = payload["expected"]["text"]
                    raw += len(literal.encode())
                    encoded += len(canonical(literal))
                    for name in ["subject", "origin_source", "origin_span"]:
                        subtrees[name + "_json_value_bytes"] += len(canonical(payload[name]))
                    subtrees["literal_format_json_string_bytes"] += len(
                        canonical(payload["expected"]["format"])
                    )
                content_encoded = encoded - 2 * count
                remainder = len(wire) - encoded
                row = {
                    "trial_id": trial["id"],
                    "arm": trial["arm"],
                    "call_id": part["id"],
                    "returned_records": count,
                    "model_visible_json_utf8_bytes": len(wire),
                    "literal_raw_utf8_bytes": raw,
                    "literal_json_string_content_bytes": content_encoded,
                    "literal_json_escape_expansion_bytes": content_encoded - raw,
                    "literal_json_quote_delimiter_bytes": 2 * count,
                    "literal_json_string_token_bytes": encoded,
                    "nonliteral_json_remainder_bytes": remainder,
                    **dict(subtrees),
                }
                assert (
                    len(wire)
                    == raw
                    + row["literal_json_escape_expansion_bytes"]
                    + row["literal_json_quote_delimiter_bytes"]
                    + remainder
                )
                calls.append(row)
                totals[trial["arm"]].update(
                    {key: val for key, val in row.items() if type(val) is int}
                )
    result = {
        "status": "exact_inner_json_byte_partition_passed",
        "arm_totals": {arm: dict(value) for arm, value in totals.items()},
        "memory_calls": calls,
        "native_shell_output": {arm: dict(value) for arm, value in shell.items()},
        "large_native_test_outputs": sorted(
            large, key=lambda value: value["text_utf8_bytes"], reverse=True
        ),
        "equation": "model-visible JSON bytes = raw literal UTF8 + JSON escape expansion + literal string quote delimiters + all nonliteral JSON remainder",
        "subtree_scope": "Subject/origin_source/origin_span/format token values are disjoint samples within nonliteral remainder; other fields/key names/list/object/punctuation/trust/budget/withholding/receipt remain there. These meaningful fields are not assumed removable.",
        "limits": [
            "This is text handed to the model, not TLS/MCP transport byte volume or measured BPE tokens.",
            "wire minus raw literal bytes is not pure metadata: it includes JSON escaping and quotes. No subtraction is labeled all avoidable.",
            "Full receipts and exact source prefix/truncation/subject/trust are mandatory for any future lossless projection; both arms must use the same format and ranking/budget.",
            "Different local test failures/solutions are not a causal effect of memory; shell nonzero exits remain normal visible debugging attempts with final quality checked independently.",
        ],
        "model_calls": 0,
    }
    (HERE / "wire-accounting.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result["arm_totals"], indent=2))


if __name__ == "__main__":
    main()
