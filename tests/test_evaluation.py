from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cami.artifacts import digest, file_hash, write_json, write_jsonl
from cami.errors import IncompleteError, InputError
from cami.evaluation import (
    Label, compare_runs, paired_cluster_bootstrap, score_run,
)
from cami.models import Claim, Cost, MemoryState, Provenance, RunConfig, Selection, ValidationResult


def fixture_run(root: Path, policy: str = "symbol_validate", *,
                all_withheld: bool = False) -> tuple[Path, Path]:
    root.mkdir()
    config = RunConfig.model_validate_json('''{
        "schema_version":1,"protocol_version":"1.0",
        "repo":{"repo_id":"manual","path":"/unused"},"parent_commit":"parent",
        "child_commits":["child"],"claims_path":"claims.jsonl",
        "provenance_path":"provenance.jsonl","parent_receipts_path":"parent_receipts.jsonl",
        "dataset_kind":"synthetic","split":"development","stratum":"fixture",
        "policy":{"id":"''' + policy + '''"}}''')
    claims = tuple(Claim(claim_id=str(i), repo_id="manual", origin_commit="parent",
                         kind="symbol_exists", text=f"function f{i} exists", scope="exact",
                         subject={"path": "a.py", "qualname": f"f{i}", "node_kind": "function"},
                         predicate={"type": "symbol_exists", "expected": True})
                   for i in range(5))
    prov = tuple(Provenance(claim_id=c.claim_id, scenario_id="intact") for c in claims)
    validating = policy.endswith("validate")
    states, selections, validations = [], [], []
    for i, c in enumerate(claims):
        selected = validating and i == 3
        available = not all_withheld and i in {0, 2, 4}
        states.append(MemoryState(claim_id=c.claim_id, revision="child",
                                 state="stale" if selected else "valid",
                                 last_checked_commit="child" if selected else "parent",
                                 last_supported_commit="parent",
                                 last_verdict="contradicted" if selected else "supported",
                                 basis="validated" if selected else "carried_forward",
                                 current_provenance=prov[i], available=available))
        selections.append(Selection(claim_id=c.claim_id, commit="child", selected=selected,
                                    reasons=("manual_fixture",)))
        if selected:
            validations.append(ValidationResult(claim_id=c.claim_id, commit="child",
                                                validator="structural", verdict="contradicted",
                                                reason="predicate_mismatch", input_hash="fixture",
                                                duration_seconds=0.1))
    labels = tuple(Label(claim_id=str(i), commit="child", label=label,
                         annotator_id="manual_fixture", evidence=("fixture narrative",),
                         confirmation_type="synthetic_manual", adjudication_status="not_required")
                   for i, label in enumerate(("supported", "supported", "contradicted",
                                              "contradicted", "uncertain")))
    label_path = root / "labels.jsonl"
    write_jsonl(label_path, labels)
    artifacts: dict[str, Any] = {"claims.jsonl": claims, "provenance.jsonl": prov,
                                 "states.jsonl": states, "selections.jsonl": selections,
                                 "validations.jsonl": validations, "transitions.jsonl": [],
                                 "costs.jsonl": [Cost(phase="maintenance", commit="child")]}
    for name, rows in artifacts.items():
        write_jsonl(root / name, rows)
    write_json(root / "manifest.json", {
        "schema_version": 1, "protocol_version": "1.0", "status": "complete",
        "evaluation_eligible": True, "config": config.model_dump(mode="json"), "input_hashes": {},
        "artifact_hashes": {name: file_hash(root / name) for name in artifacts},
        "claim_hashes": {c.claim_id: digest(c) for c in claims},
        "cohort": [c.claim_id for c in claims], "excluded": [],
        "parent_commit": "parent", "child_commits": ["child"], "app_version": "test",
        "python": "3.12", "started_at": "start", "finished_at": "finish"})
    return root, label_path


def test_manual_five_claims(tmp_path: Path) -> None:
    run, labels = fixture_run(tmp_path / "run")
    report = score_run(run, labels, tmp_path / "report")
    metrics = report.overall.metrics
    assert metrics["stale_exposure"].value == 0.5
    assert metrics["valid_retention"].value == 0.5
    assert metrics["available_contamination"].value == 0.5
    assert metrics["uncertain_available"].value == 1
    assert metrics["invalidation_precision"].value == 1
    assert metrics["invalidation_recall"].value == 0.5
    assert report.overall.counters["stale_tp"] == 1
    assert report.overall.counters["unchecked_current_revision"] == 4
    assert report.overall.exploratory
    assert (tmp_path / "report" / "per_claim.csv").exists()


def test_clear_all_nulls(tmp_path: Path) -> None:
    run, labels = fixture_run(tmp_path / "run", "clear_all", all_withheld=True)
    report = score_run(run, labels, tmp_path / "report")
    assert report.overall.metrics["valid_retention"].value == 0
    assert report.overall.metrics["available_contamination"].value is None
    assert report.overall.metrics["available_contamination"].reason == "zero_denominator"
    for key in ("selection_recall", "false_invalidation"):
        assert report.overall.metrics[key].reason == "not_applicable"


def test_missing_labels_rejected(tmp_path: Path) -> None:
    run, labels = fixture_run(tmp_path / "run")
    labels.write_text("\n".join(labels.read_text().splitlines()[:-1]) + "\n")
    with pytest.raises(InputError, match="missing_label_coverage"):
        score_run(run, labels, tmp_path / "report")
    assert not (tmp_path / "report").exists()


def test_duplicate_labels_rejected(tmp_path: Path) -> None:
    run, labels = fixture_run(tmp_path / "run")
    with labels.open("a") as stream:
        stream.write(labels.read_text().splitlines()[0] + "\n")
    with pytest.raises(InputError, match="duplicate label"):
        score_run(run, labels, tmp_path / "report")


def test_tampered_artifacts_rejected(tmp_path: Path) -> None:
    run, labels = fixture_run(tmp_path / "run")
    with (run / "states.jsonl").open("a") as stream:
        stream.write("\n")
    with pytest.raises(InputError, match="artifact hash mismatch"):
        score_run(run, labels, tmp_path / "report")


def test_incomplete_run_rejected(tmp_path: Path) -> None:
    from cami.artifacts import read_json

    run, labels = fixture_run(tmp_path / "run")
    manifest = read_json(run / "manifest.json")
    manifest["status"] = "running"
    write_json(run / "manifest.json", manifest)
    with pytest.raises(IncompleteError):
        score_run(run, labels, tmp_path / "report")


def test_comparison_one_cluster(tmp_path: Path) -> None:
    left, labels = fixture_run(tmp_path / "left", "keep_all")
    right, _ = fixture_run(tmp_path / "right", "clear_all", all_withheld=True)
    report = compare_runs([left, right], labels, tmp_path / "comparison")
    interval = report.intervals["clear_all-minus-keep_all"]["stale_exposure"]
    assert interval.reason == "insufficient_clusters"
    assert interval.lower is None and interval.upper is None
    assert (tmp_path / "comparison" / "comparison.csv").exists()
    assert (tmp_path / "comparison" / "cost_quality.png").exists()


def test_bootstrap_pairs_and_reproducibility() -> None:
    left = {"a": (1, 2), "b": (1, 2), "c": (1, 2)}
    right = {"a": (0, 2), "b": (0, 2), "c": (0, 2)}
    interval = paired_cluster_bootstrap(left, right)
    assert interval.lower == interval.upper == interval.estimate == 0.5
    assert paired_cluster_bootstrap(left, right) == interval
    assert paired_cluster_bootstrap({}, {}).reason == "zero_denominator"
    with pytest.raises(InputError, match="identical paired"):
        paired_cluster_bootstrap(left, {"a": (0, 2)})


def test_no_overwrite(tmp_path: Path) -> None:
    run, labels = fixture_run(tmp_path / "run")
    output = tmp_path / "report"
    output.mkdir()
    with pytest.raises(InputError, match="output already exists"):
        score_run(run, labels, output)


def test_carried_forward_contradiction_not_current_prediction(tmp_path: Path) -> None:
    from cami.artifacts import load_jsonl, read_json

    run, labels = fixture_run(tmp_path / "run")
    states = list(load_jsonl(run / "states.jsonl", MemoryState))
    states[2] = states[2].model_copy(update={"state": "stale", "last_checked_commit": "parent",
                                           "last_verdict": "contradicted"})
    write_jsonl(run / "states.jsonl", states)
    manifest = read_json(run / "manifest.json")
    manifest["artifact_hashes"]["states.jsonl"] = file_hash(run / "states.jsonl")
    write_json(run / "manifest.json", manifest)
    report = score_run(run, labels, tmp_path / "report")
    assert report.overall.counters["tp"] == 1
    assert report.overall.counters["fn"] == 1


def test_failed_run_without_artifacts_is_incomplete(tmp_path: Path) -> None:
    run = tmp_path / "failed"
    run.mkdir()
    write_json(run / "manifest.json", {"status": "failed", "failure": "resource unavailable"})
    labels = tmp_path / "labels.jsonl"
    labels.write_text("")
    with pytest.raises(IncompleteError):
        score_run(run, labels, tmp_path / "report")


def test_f1_zero_with_false_negative(tmp_path: Path) -> None:
    from cami.artifacts import load_jsonl, read_json

    run, labels = fixture_run(tmp_path / "run")
    labelled = list(load_jsonl(labels, Label))
    labelled[3] = labelled[3].model_copy(update={"label": "supported"})
    write_jsonl(labels, labelled)
    report = score_run(run, labels, tmp_path / "report")
    assert report.overall.counters["tp"] == 0
    assert report.overall.counters["fp"] == 1
    assert report.overall.counters["fn"] == 1
    assert report.overall.metrics["invalidation_f1"].value == 0
    assert report.overall.metrics["false_invalidation"].value == pytest.approx(1 / 3)
    assert read_json(tmp_path / "report" / "metrics.json")["overall"]["metrics"][
        "invalidation_f1"]["value"] == 0


def test_uncertain_not_counted_as_false_positive(tmp_path: Path) -> None:
    from cami.artifacts import load_jsonl

    run, labels = fixture_run(tmp_path / "run")
    labelled = list(load_jsonl(labels, Label))
    labelled[3] = labelled[3].model_copy(update={"label": "uncertain"})
    write_jsonl(labels, labelled)
    report = score_run(run, labels, tmp_path / "report")
    assert report.overall.counters["tp"] == report.overall.counters["fp"] == 0
    assert report.overall.counters["fn"] == 1
    assert report.overall.metrics["invalidation_precision"].reason == "zero_denominator"
    assert report.overall.metrics["invalidation_f1"].value == 0


def test_population_mismatch_rejected(tmp_path: Path) -> None:
    from cami.artifacts import read_json

    left, labels = fixture_run(tmp_path / "left", "keep_all")
    right, _ = fixture_run(tmp_path / "right", "clear_all", all_withheld=True)
    manifest = read_json(right / "manifest.json")
    manifest["config"]["dataset_kind"] = "real"
    write_json(right / "manifest.json", manifest)
    with pytest.raises(InputError, match="incompatible populations"):
        compare_runs([left, right], labels, tmp_path / "comparison")
    assert not (tmp_path / "comparison").exists()


def test_duplicate_states_rejected_even_with_valid_hash(tmp_path: Path) -> None:
    from cami.artifacts import read_json

    run, labels = fixture_run(tmp_path / "run")
    states_path = run / "states.jsonl"
    with states_path.open("a") as stream:
        stream.write(states_path.read_text().splitlines()[0] + "\n")
    manifest = read_json(run / "manifest.json")
    manifest["artifact_hashes"]["states.jsonl"] = file_hash(states_path)
    write_json(run / "manifest.json", manifest)
    with pytest.raises(InputError, match="exactly one cohort"):
        score_run(run, labels, tmp_path / "report")
