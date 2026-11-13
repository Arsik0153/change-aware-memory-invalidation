"""Freeze the ranking intervention and reject silent protocol drift."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness"))
from study_schema import (  # noqa: E402
    RANKING_DESIGN, LEXICAL_RANKING, IDENTIFIER_RANKING, ranking_conditions,
    plan, validate_design, trial_ranking_policy, trial_response_format,
)
from study_runtime import validate_memory_command, validate_ranking_trace  # noqa: E402
from container_session import configuration  # noqa: E402


def study():
    return dict(schema_version=3, design=RANKING_DESIGN, bundle_kind="development",
                arms=["plain", "cami"], repetitions=1, conditions=ranking_conditions(),
                memory_response_format="readable", normalized={"sequence": ["a", "a", "b", "b"]})


def test_twelve_trials_have_independent_condition_histories_and_rotating_order():
    data = study()
    rows = plan(data)
    assert len(rows) == len({r["id"] for r in rows}) == 12
    conditions = [c["id"] for c in ranking_conditions()]
    for stage in range(1, 5):
        offset = (stage - 1) % 3
        assert [r["condition"] for r in rows if r["stage"] == stage] == conditions[offset:] + conditions[:offset]
    seen = {}
    for row in rows:
        if row["predecessor"]:
            previous = seen[row["predecessor"]]
            assert previous["condition"] == row["condition"]
            assert previous["stage"] + 1 == row["stage"]
        assert trial_response_format(data, row) == "readable"
        assert trial_ranking_policy(data, row) == row["ranking_policy"]
        seen[row["id"]] = row


@pytest.mark.parametrize("change", [
    {"bundle_kind": "heldout"}, {"repetitions": 3}, {"conditions": []},
    {"memory_response_format": "compact"}, {"design": "unregistered"},
    {"arms": ["plain", "static", "cami"]}, {"ranking_policy": IDENTIFIER_RANKING},
    {"schema_version": 2},
])
def test_design_override_rejected(change):
    data = study()
    data.update(change)
    with pytest.raises(ValueError):
        validate_design(data)


def test_trial_ranking_override_rejected_and_legacy_remains_default():
    data = study()
    row = deepcopy(plan(data)[1])
    row["ranking_policy"] = IDENTIFIER_RANKING
    with pytest.raises(ValueError, match="frozen"):
        trial_ranking_policy(data, row)
    assert trial_ranking_policy({"schema_version": 1}, {}) == LEXICAL_RANKING
    with pytest.raises(ValueError, match="override"):
        trial_ranking_policy({"schema_version": 1}, row)


@pytest.mark.parametrize("condition", ranking_conditions())
def test_effective_command_and_trace_must_match_registered_policy(condition):
    arm, fmt, policy = (condition[k] for k in ("arm", "response_format", "ranking_policy"))
    config = configuration(arm, "prepared/binding.json", fmt, ranking_policy=policy)
    validate_memory_command(config, arm, fmt, policy)
    if arm == "plain":
        validate_ranking_trace([], arm, policy)
        with pytest.raises(ValueError):
            configuration(arm, None, ranking_policy=IDENTIFIER_RANKING)
        return
    traces = [{"event": event, **({"ranking_policy": policy} if policy != LEXICAL_RANKING else {})}
              for event in ("server_start", "memory_lookup")]
    validate_ranking_trace(traces, arm, policy)
    with pytest.raises(ValueError):
        validate_ranking_trace([], arm, policy)
    wrong = IDENTIFIER_RANKING if policy == LEXICAL_RANKING else LEXICAL_RANKING
    with pytest.raises(ValueError):
        validate_memory_command(config, arm, fmt, wrong)
    traces[-1]["ranking_policy"] = wrong
    with pytest.raises(ValueError):
        validate_ranking_trace(traces, arm, policy)


@pytest.mark.parametrize("condition", ranking_conditions())
def test_session_passes_policy_before_launch(monkeypatch, tmp_path, condition):
    import study_runtime as runtime
    data = study()
    data.update(harness="fake.py", runtime_manifest_path="fake.json", reported_token_budget=1000000,
                image="image", cami_source="source", adapter="adapter", service_tier="priority",
                model="openai/gpt-6.1-sol#high")
    row = next(r for r in plan(data) if r["condition"] == condition["id"])
    def stop(argv, timeout):
        assert argv[argv.index("--memory-ranking-policy") + 1] == row["ranking_policy"]
        assert argv[argv.index("--memory-response-format") + 1] == "readable"
        raise RuntimeError("authored stop")
    monkeypatch.setattr(runtime, "command", stop)
    with pytest.raises(RuntimeError, match="authored stop"):
        runtime.session(data, row, tmp_path, tmp_path, tmp_path, tmp_path / "session")
