from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from cami.artifacts import read_json, read_jsonl

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/demo_structural_closure.py"
SPEC = importlib.util.spec_from_file_location("structural_closure_demo", SCRIPT)
assert SPEC and SPEC.loader
demonstration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demonstration)


def test_independent_fixture_oracle_uses_authored_expectations(monkeypatch):
    import cami.index
    import cami.validation

    def forbidden(*args, **kwargs):
        raise AssertionError("CAMI parser/validator must not supply the fixture oracle")

    monkeypatch.setattr(cami.index, "signature", forbidden)
    monkeypatch.setattr(cami.index, "parse_module", forbidden)
    monkeypatch.setattr(cami.validation, "validate_claim", forbidden)
    scenario = read_json(demonstration.SCENARIO)
    for step in scenario["transitions"]:
        for claim in scenario["claims"]:
            expected = ("supported" if claim["name"] == "stable" else
                        step["f_exists" if claim["kind"] == "symbol_exists" else "f_signature"])
            assert demonstration.lexical_observation(
                step["source"], claim["name"], claim["kind"],
            ) == expected


def test_cli_demonstrates_selection_fallback_and_recovery(tmp_path):
    output = tmp_path / "development demo with spaces"
    result = subprocess.run([
        sys.executable, str(SCRIPT), "--out", str(output), "--repeats", "1",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    summary = read_json(output / "summary.json")
    assert summary["status"] == "passed"
    assert summary["oracle_checks"] == 28
    assert summary["source_preservation"]["verified"] is True
    variants = summary["variants"]
    assert [variants[key]["actual_validations"] for key in demonstration.VARIANTS] == [24, 24, 10]
    closed = variants["closed_structural"]["transitions"]
    assert [row["selected"] for row in closed] == [0, 2, 2, 2, 2, 2]
    assert closed[2]["verdicts"]["f-signature"]["reason"] == "predicate_mismatch"
    assert {row["reason"] for row in closed[3]["verdicts"].values()} == {"subject_absent"}
    assert {row["reason"] for row in closed[4]["verdicts"].values()} == {"ambiguous_subject"}
    assert {row["verdict"] for row in closed[5]["verdicts"].values()} == {"supported"}
    assert all("known_incomplete" in reasons
               for row in variants["original_incomplete"]["transitions"]
               for reasons in row["selection_reasons"].values())
    assert all(row["cli_wall_seconds_median"] > 0 for row in variants.values())
    states = read_jsonl(output / "runs/00-closed_structural/states.jsonl")
    assert all(row["last_checked_commit"] == summary["parent_commit"]
               for row in states if row["claim_id"].startswith("stable-"))
    again = subprocess.run([
        sys.executable, str(SCRIPT), "--out", str(output), "--repeats", "1",
    ], capture_output=True, text=True, check=False)
    assert again.returncode != 0
    assert read_json(output / "summary.json") == summary


def test_fixture_verification_rejects_oracle_disagreement(tmp_path):
    scenario, claims, parent = demonstration.fixture(tmp_path / "parent")
    children = demonstration.create_children(tmp_path / "parent", scenario)
    scenario["transitions"][2]["f_signature"] = "supported"
    with pytest.raises(ValueError, match="independent oracle disagrees"):
        demonstration.verify_fixture(tmp_path / "parent", scenario, claims, parent, children)
