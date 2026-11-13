"""Synthetic decision checks; deliberately no tasks or model outcomes."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from format_probe import native_reads, summarize  # noqa: E402
from study_schema import FORMAT_DESIGN, format_conditions, plan  # noqa: E402


def rows():
    study = dict(schema_version=2, design=FORMAT_DESIGN, bundle_kind="development",
        repetitions=1, arms=["plain", "static", "cami"], conditions=format_conditions(),
        memory_response_format="compact", normalized={"sequence": ["a", "a", "b", "b"]})
    return [{**r, "terminal_present": True, "quality_eligible": True, "tokens_complete": True,
        "native_reads_complete": True, "wall_complete": True, "charged_wall_seconds": 100,
        "token_work": 9 if r["response_format"] == "readable" else 10,
        "native_read_bytes": 99 if r["response_format"] == "readable" else 100,
        "service_tier": {"configuration_valid": True, "provider_reported_complete": True,
                         "provider_reported_values": ["default"]}} for r in plan(study)]


def test_both_backends_both_metrics_required_and_no_superiority():
    data = rows()
    report = summarize(data)
    assert report["direction_supported"] and report["superiority_claim"] is None
    assert not report["wall_comparison_eligible"]
    for condition in ("static_readable", "cami_readable"):
        for metric in ("token_work", "native_read_bytes"):
            changed = deepcopy(data)
            for row in changed:
                if row["condition"] == condition:
                    row[metric] = 1000
            assert not summarize(changed)["direction_supported"]


@pytest.mark.parametrize("key", ["quality_eligible", "tokens_complete", "wall_complete", "native_reads_complete"])
def test_one_failure_including_plain_prevents_support(key):
    data = rows()
    data[0][key] = False
    assert not summarize(data)["direction_supported"]
    assert not summarize(data[:-1])["direction_supported"]


def messages(text="π\n"):
    return [{"type": "assistant", "content": [{"id": "read1", "type": "tool", "name": "read",
             "state": {"status": "completed", "content": [{"type": "text", "text": text}],
                       "output": "duplicate projection must not be counted"}}]}]


def test_utf8_bytes_counted_once_and_shell_not_inferred():
    data = messages()
    data[0]["content"].append({"id": "shell1", "type": "tool", "name": "shell",
                              "state": {"status": "completed", "output": "cat source.py"}})
    assert native_reads(data) == {"bytes": 3, "observed_subtotal": 3, "calls": 1,
                                  "complete": True, "errors": []}
    assert not native_reads(messages("[REDACTED_EMAIL]"))["complete"]
    assert not native_reads(None)["complete"]
    assert not native_reads([])["complete"]
    data[0]["content"].append(deepcopy(data[0]["content"][0]))
    assert not native_reads(data)["complete"]
