"""Descriptive public transcript volume/overlap audit; no attribution of hidden reliance."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUN = ROOT / "runs/opencode-development-v6-20261106"
READ_ONLY = {"read", "grep", "glob", "list", "ls", "todoread", "todowrite"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_parts(content):
    return "\n".join(
        part["text"]
        for part in content or []
        if isinstance(part, dict)
        and part.get("type") == "text"
        and isinstance(part.get("text"), str)
    )


def memory(name):
    return name == "memory_lookup" or name.endswith("_memory_lookup")


def timestamp(value):
    return value / 1000 if type(value) in (float, int) and math.isfinite(value) else None


def relative(path):
    if not isinstance(path, str):
        return None
    if path.startswith("/workspace/"):
        path = path[len("/workspace/") :]
    parsed = PurePosixPath(path)
    return path if path and not parsed.is_absolute() and ".." not in parsed.parts else None


def main():
    audit = json.loads((HERE / "independent-v1/report.json").read_bytes())
    bindings = json.loads((HERE / "independent-v1/input-hashes.json").read_bytes())
    rows, overlaps, long_args = [], [], []
    session_identities = []
    study = json.loads((RUN / "frozen-study.json").read_bytes())
    for admitted in audit["trial_rows"]:
        trial_id = admitted["id"]
        directory = RUN / "trials" / trial_id
        file = directory / "session/evidence/messages.json"
        assert (
            sha(file)
            == bindings[trial_id]["public_artifact_hashes"]["session/evidence/messages.json"]
        )
        messages = json.loads(file.read_bytes())
        session = json.loads((directory / "session/manifest.json").read_bytes())
        identity = json.loads((directory / "session/runtime-identity.json").read_bytes())
        expected = {
            "image_id": study["image"],
            "binary_sha256": study["binary_sha256"],
            "cami_files": study["pins"]["production"]["files"],
            "adapter_files": study["pins"]["adapter"]["files"],
        }
        assert identity == expected and session["image_id"] == study["image"]
        assert (
            session["runtime_sources"]["cami_files"] == expected["cami_files"]
            and session["runtime_sources"]["adapter_files"] == expected["adapter_files"]
        )
        assert session["runtime_sources"]["binary_sha256"] == expected["binary_sha256"]
        session_identities.append(
            {
                "trial_id": trial_id,
                "runtime_identity_sha256": sha(directory / "session/runtime-identity.json"),
                "all_frozen_runtime_fields_match": True,
            }
        )
        tools, calls = [], []
        for message in messages:
            for part in message.get("content", []):
                if part.get("type") != "tool":
                    continue
                name = part["name"]
                state, timing = part.get("state", {}), part.get("time", {})
                tool = {
                    "id": part["id"],
                    "name": name,
                    "state": state,
                    "ran": timestamp(timing.get("ran")),
                    "created": timestamp(timing.get("created")),
                    "end": timestamp(timing.get("completed")),
                }
                tools.append(tool)
                if memory(name) and state.get("status") == "completed":
                    text = text_parts(state.get("content"))
                    value = json.loads(text)
                    entries, withheld = value.get("entries", []), value.get("withheld", [])
                    calls.append(
                        {
                            **tool,
                            "wire_utf8_bytes": len(text.encode()),
                            "wire_unicode_characters": len(text),
                            "returned": entries,
                            "withheld": withheld,
                            "payload_text_utf8_bytes": sum(
                                len(entry["payload"]["expected"]["text"].encode())
                                for entry in entries
                            ),
                            "returned_prefix_truncated_count": sum(
                                entry["payload"]["expected"]["truncated"] for entry in entries
                            ),
                        }
                    )
        native = [tool for tool in tools if not memory(tool["name"])]
        prefix_bytes = sum(call["payload_text_utf8_bytes"] for call in calls)
        replay_proxy = 0
        for call in calls:
            if call["end"] is not None:
                later = sum(
                    message["type"] == "assistant"
                    and timestamp(message.get("time", {}).get("created")) is not None
                    and timestamp(message["time"]["created"]) > call["end"]
                    for message in messages
                )
                replay_proxy += call["wire_utf8_bytes"] * later
        trial_overlaps = []
        for tool in native:
            arguments = tool["state"].get("input", {})
            if tool["name"] != "read" or not isinstance(arguments, dict):
                continue
            path = relative(arguments.get("path"))
            if not path or tool["ran"] is None:
                continue
            earlier = [
                call for call in calls if call["end"] is not None and call["end"] <= tool["ran"]
            ]
            if not earlier:
                continue
            call = max(earlier, key=lambda value: value["end"])
            entries = [
                entry for entry in call["returned"] if entry["payload"]["subject"]["path"] == path
            ]
            if not entries:
                continue
            response = text_parts(tool["state"].get("content"))
            numbered = re.findall(r"^\d+: (.*)$", response, re.MULTILINE)
            normalized_read = "\n".join(numbered) + "\n" if numbered else None
            duplicates = [
                entry["id"]
                for entry in entries
                if normalized_read is not None
                and entry["payload"]["expected"]["text"] in normalized_read
            ]
            possible_write = any(
                value["name"] not in READ_ONLY
                and not memory(value["name"])
                and (value["ran"] is None or value["ran"] <= tool["ran"])
                and (value["end"] is None or value["end"] >= call["end"])
                for value in tools
                if value["id"] not in {tool["id"], call["id"]}
            )
            row = {
                "trial_id": trial_id,
                "read_call_id": tool["id"],
                "path": path,
                "preceding_memory_call_id": call["id"],
                "returned_memory_record_ids_same_file": [entry["id"] for entry in entries],
                "exact_displayed_memory_text_found_in_numbered_read_output": duplicates,
                "native_read_text_utf8_bytes": len(response.encode()),
                "possible_write_since_or_overlapping_memory": possible_write,
                "scope": "Visible text/path overlap only. Reading adjacent context, fresh source or truncated remainder can still be necessary; redundancy/causal reliance not established.",
            }
            overlaps.append(row)
            trial_overlaps.append(row)
        argument_bytes = Counter()
        native_result_bytes = Counter()
        for tool in native:
            value = tool["state"].get("input")
            encoded = json.dumps(
                value, sort_keys=True, ensure_ascii=True, separators=(",", ":")
            ).encode()
            argument_bytes[tool["name"]] += len(encoded)
            native_result_bytes[tool["name"]] += len(
                text_parts(tool["state"].get("content")).encode()
            )
            if (
                tool["created"] is not None
                and tool["ran"] is not None
                and tool["ran"] >= tool["created"]
            ):
                long_args.append(
                    {
                        "trial_id": trial_id,
                        "call_id": tool["id"],
                        "tool": tool["name"],
                        "arguments_json_utf8_bytes": len(encoded),
                        "created_to_ran_seconds_nonadditive": tool["ran"] - tool["created"],
                        "ran_to_completed_seconds": tool["end"] - tool["ran"]
                        if tool["end"] is not None
                        else None,
                    }
                )
        rows.append(
            {
                "trial_id": trial_id,
                "arm": admitted["arm"],
                "repetition": admitted["repetition"],
                "stage": admitted["stage"],
                "task": admitted["task"],
                "assistant_responses": admitted["assistant_responses"],
                "token_work": admitted["token_work"],
                "tokens": admitted["tokens"],
                "native_tool_counts": dict(Counter(tool["name"] for tool in native)),
                "native_tool_count": len(native),
                "native_tool_status_counts": dict(
                    Counter(tool["state"].get("status") for tool in native)
                ),
                "memory_calls": len(calls),
                "memory_wire_utf8_bytes": sum(call["wire_utf8_bytes"] for call in calls),
                "returned_literal_text_utf8_bytes": prefix_bytes,
                "returned_prefix_truncated_observations": sum(
                    call["returned_prefix_truncated_count"] for call in calls
                ),
                "returned_record_observations": sum(len(call["returned"]) for call in calls),
                "withheld_record_observations": sum(len(call["withheld"]) for call in calls),
                "hypothetical_replayed_memory_bytes_proxy_not_provider_tokens": replay_proxy,
                "native_argument_json_utf8_bytes": dict(argument_bytes),
                "native_result_text_utf8_bytes": dict(native_result_bytes),
                "same_file_native_read_observations_after_memory": len(trial_overlaps),
                "reads_also_containing_exact_displayed_prefix_text": sum(
                    bool(value["exact_displayed_memory_text_found_in_numbered_read_output"])
                    for value in trial_overlaps
                ),
                "same_file_reads_without_recorded_possible_intervening_write": sum(
                    not value["possible_write_since_or_overlapping_memory"]
                    for value in trial_overlaps
                ),
            }
        )
    summaries = {}
    for arm in ["plain", "static", "cami"]:
        selected = [row for row in rows if row["arm"] == arm]
        scalar = [
            "assistant_responses",
            "token_work",
            "native_tool_count",
            "memory_calls",
            "memory_wire_utf8_bytes",
            "returned_literal_text_utf8_bytes",
            "returned_prefix_truncated_observations",
            "returned_record_observations",
            "withheld_record_observations",
            "same_file_native_read_observations_after_memory",
            "reads_also_containing_exact_displayed_prefix_text",
            "same_file_reads_without_recorded_possible_intervening_write",
            "hypothetical_replayed_memory_bytes_proxy_not_provider_tokens",
        ]
        totals = {key: sum(row[key] for row in selected) for key in scalar}
        for field in [
            "native_tool_counts",
            "native_argument_json_utf8_bytes",
            "native_result_text_utf8_bytes",
        ]:
            counter = Counter()
            for row in selected:
                counter.update(row[field])
            totals[field] = dict(counter)
        summaries[arm] = totals
    result = {
        "status": "all36public_transcripts_inspected",
        "trials": rows,
        "arm_totals": summaries,
        "same_file_read_evidence": overlaps,
        "largest_created_to_ran_intervals_nonadditive": sorted(
            long_args, key=lambda value: value["created_to_ran_seconds_nonadditive"], reverse=True
        )[:25],
        "runtime_identity_all36_verified": session_identities,
        "limits": [
            "UTF8 bytes/characters are not token counts or billed units; no tokenizer/cost attribution is fabricated.",
            "Replay byte proxy assumes an entire earlier tool response is replayed in later assistant prompts; actual provider packing/cache/truncation is unknown.",
            "Same-file and exact visible-text overlap identify review candidates, not unnecessary native reads or causal stale reliance. Source guards/truncated remainder/adjacent code may require the read.",
            "Tool created-to-ran includes argument streaming/scheduling/dispatch, not pure native execution or provider-only wait; spans may overlap and are not additive.",
            "Different generated patches/tool sequences and task solutions are observations, not causal effects of memory. No historical cohort pooling.",
        ],
        "model_calls": 0,
        "heldout_reads": False,
    }
    (HERE / "visible-costs.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
