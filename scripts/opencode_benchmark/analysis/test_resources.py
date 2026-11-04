import copy

import pytest

from summarize_resources import combine, components, summarize


def terminal(arm="cami", stage=1):
    return {"trial": {"id": f"r1-{arm}-s{stage}", "repetition": 1, "arm": arm, "stage": stage},
            "memory_bytes_after": 100,
            "costs": {"construction_cgroup": {"cpu_seconds": 2, "peak_memory_bytes": 70},
                      "session_cgroup": {"cpu_seconds": 3, "peak_memory_bytes": 90}}}


def test_nonoverlapping_cpu_sum_and_peak_maximum():
    row = components(terminal())
    assert row["container_cpu_seconds"] == 5
    assert row["maximum_container_peak_bytes"] == 90
    assert row["controller_self_cpu_seconds"] is None


@pytest.mark.parametrize("arm,stage", [("plain", 1), ("cami", 2), ("static", 4)])
def test_no_construction_stage_is_explicit_zero(arm, stage):
    value = terminal(arm, stage)
    del value["costs"]["construction_cgroup"]
    row = components(value)
    assert not row["construction_required"]
    assert row["construction_cpu_seconds"] == 0
    assert row["container_cpu_seconds"] == 3


@pytest.mark.parametrize("missing", [None, True, -1, float("nan")])
def test_unknown_or_invalid_required_measurement_is_not_zero(missing):
    value = terminal()
    value["costs"]["construction_cgroup"]["cpu_seconds"] = missing
    assert components(value)["container_cpu_seconds"] is None
    result = combine([1, None, 3, 4], sum)
    assert result["value"] is None and result["observed_partial"] == 8
    assert not result["complete"]


def test_storage_maximum_and_final_are_distinct_and_duplicate_stages_rejected():
    rows = []
    for rep in range(1, 4):
        for arm in ("plain", "static", "cami"):
            for stage in range(1, 5):
                row = components(terminal(arm, stage))
                row.update(repetition=rep, persistent_memory_bytes_after=[1, 10, 4, 3][stage - 1])
                rows.append(row)
    block = summarize(rows)[0]
    assert block["maximum_observed_persistent_memory_bytes"]["value"] == 10
    assert block["final_persistent_memory_bytes"] == 3
    invalid = copy.deepcopy(rows)
    invalid[0]["stage"] = 2
    with pytest.raises(ValueError, match="four terminal stages"):
        summarize(invalid)
