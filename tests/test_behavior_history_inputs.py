import pytest

from cami.artifacts import read_json, read_jsonl
from cami.inputs import check_inputs
from scripts.check_behavior_history import PLAN, create_fixture, prepare_inputs


def test_frozen_behavior_inputs_keep_synthetic_truth_out_of_public_masks(tmp_path):
    plan = read_json(PLAN)
    parent, children, observations = create_fixture(tmp_path, plan)
    configs = prepare_inputs(tmp_path, plan, parent, children, observations)
    assert [row["value"] for row in observations] == [1, 2, 2, 1, 3, 1, 1]
    for name, path in configs.items():
        inputs = check_inputs(path)
        assert inputs.config.dataset_kind == "synthetic"
        assert inputs.receipts[0].confirmation_type == "synthetic_authored_finite_oracle"
        evidence = read_json(path.parent / inputs.receipts[0].evidence_path)
        assert evidence["human_annotation"] is False
        assert evidence["observation"]["commit"] == parent
        assert "observations" not in evidence
        if name.endswith("missing"):
            assert not (path.parent / "labels.jsonl").exists()
            assert not (path.parent / "oracle.json").exists()
    labels = read_jsonl(tmp_path / "labels.jsonl")
    assert all(row["confirmation_type"] == "synthetic_authored_finite_oracle" for row in labels)


def test_authored_expectation_mismatch_stops_before_policy_execution(tmp_path):
    plan = read_json(PLAN)
    plan["steps"][0]["oracle_value"] = 42
    with pytest.raises(AssertionError):
        create_fixture(tmp_path, plan)
    assert not (tmp_path / "runs").exists()
