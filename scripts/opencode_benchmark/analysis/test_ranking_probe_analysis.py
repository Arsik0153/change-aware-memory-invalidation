"""Prospective decision checks using authored outcomes only."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ranking_probe import summarize  # noqa: E402
from study_schema import RANKING_DESIGN, ranking_conditions, plan  # noqa: E402


def rows():
    study = dict(schema_version=3, design=RANKING_DESIGN, bundle_kind="development",
        repetitions=1, arms=["plain", "cami"], conditions=ranking_conditions(),
        memory_response_format="readable", normalized={"sequence": ["a", "a", "b", "b"]})
    return [{**r, "terminal_present": True, "quality_eligible": True, "tokens_complete": True,
        "native_reads_complete": True, "wall_complete": True, "charged_wall_seconds": 100,
        "ranking_verified": True, "token_work": 9 if r["condition"] == "cami_identifier" else 10,
        "native_read_bytes": 99 if r["condition"] == "cami_identifier" else 100,
        "service_tier": {"configuration_valid": True, "provider_reported_complete": True,
                         "provider_reported_values": ["default"]}} for r in plan(study)]


def test_both_metrics_strictly_lower_and_no_superiority_claim():
    data = rows()
    result = summarize(data)
    assert result["direction_supported"] and result["superiority_claim"] is None
    assert not result["wall_comparison_eligible"]
    for name in ("token_work", "native_read_bytes"):
        changed = deepcopy(data)
        for row in changed:
            if row["condition"] == "cami_identifier":
                row[name] = 10 if name == "token_work" else 100
        assert not summarize(changed)["direction_supported"]


@pytest.mark.parametrize("key", ["quality_eligible", "tokens_complete", "wall_complete", "native_reads_complete", "ranking_verified"])
def test_incomplete_trial_including_plain_prevents_support(key):
    data = rows()
    data[0][key] = False
    assert not summarize(data)["direction_supported"]
    assert not summarize(data[:-1])["direction_supported"]


def test_mixed_or_missing_provider_tier_prevents_support():
    for key, value in (("provider_reported_values", ["priority"]), ("provider_reported_complete", False)):
        data = rows()
        data[1]["service_tier"][key] = value
        assert not summarize(data)["direction_supported"]
