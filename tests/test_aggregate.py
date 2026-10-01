from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cami.aggregate import DatasetAnalysis, GroupReport, analyze_dataset
from cami.artifacts import digest, file_hash, read_json, write_json, write_jsonl
from cami.errors import InputError
from cami.evaluation import Label
from cami.models import (
    Claim, Cost, MemoryState, PolicyConfig, Provenance, RunConfig, Selection, ValidationResult,
)


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args]).decode().strip()


def population(base: Path, name: str, *, stratum: str = "fixture",
               policies: tuple[PolicyConfig, ...] | None = None,
               replay: bool = False) -> tuple[dict[str, object], dict[str, object],
                                               list[Path], list[Label]]:
    root = base / name
    root.mkdir(parents=True)
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Synthetic fixture")
    (repo / "a.py").write_text("def f():\n    return 1\n")
    git(repo, "add", "a.py")
    git(repo, "commit", "-qm", f"independent synthetic parent {name}")
    parent = git(repo, "rev-parse", "HEAD")
    (repo / "a.py").write_text("def f():\n    return 2\n")
    git(repo, "commit", "-qam", "child")
    children = [git(repo, "rev-parse", "HEAD")]
    if replay:
        (repo / "a.py").write_text("def f():\n    return 1\n")
        git(repo, "commit", "-qam", "revert")
        children.append(git(repo, "rev-parse", "HEAD"))
    claims = tuple(Claim(claim_id=f"{name}-{i}", repo_id=name, origin_commit=parent,
                        kind="symbol_exists", text=f"manual fixture claim {i}", scope="exact",
                        subject={"path": "a.py", "qualname": f"f{i}", "node_kind": "function"},
                        predicate={"type": "symbol_exists", "expected": True})
                   for i in range(2))
    provenance = tuple(Provenance(claim_id=c.claim_id, scenario_id="intact") for c in claims)
    write_jsonl(root / "claims.jsonl", claims)
    write_jsonl(root / "provenance.jsonl", provenance)
    write_jsonl(root / "receipts.jsonl", [])
    config = RunConfig.model_validate_json('''{
        "repo":{"repo_id":"''' + name + '''","path":"repo"},
        "parent_commit":"''' + parent + '''","child_commits":["''' + '","'.join(children) + '''"],
        "claims_path":"claims.jsonl","provenance_path":"provenance.jsonl",
        "parent_receipts_path":"receipts.jsonl","dataset_kind":"synthetic",
        "split":"development","stratum":"''' + stratum + '''","policy":{"id":"keep_all"}}
    ''')
    write_json(root / "config.json", config)
    labels = [Label(claim_id=c.claim_id, commit=commit,
                    label="supported" if i == 0 else "contradicted",
                    annotator_id="fixture", evidence=("manually specified scenario",),
                    confirmation_type="synthetic_manual", adjudication_status="not_required")
              for commit in children for i, c in enumerate(claims)]
    run_paths: list[Path] = []
    for policy in policies or (PolicyConfig(id="keep_all"), PolicyConfig(id="all_validate")):
        folder = root / f"{policy.id}-{policy.dependency_depth}"
        folder.mkdir()
        run_paths.append(folder)
        resolved = config.model_copy(update={"repo": config.repo.model_copy(
            update={"path": str(repo.resolve())}), "policy": policy})
        states, selections, validations = [], [], []
        validating = policy.id.endswith("validate")
        for commit in children:
            for i, claim in enumerate(claims):
                verdict = "supported" if i == 0 else "contradicted"
                states.append(MemoryState(claim_id=claim.claim_id, revision=commit,
                    state="valid" if not validating or i == 0 else "retired",
                    last_checked_commit=commit if validating else parent,
                    last_supported_commit=commit if validating and i == 0 else parent,
                    last_verdict=verdict if validating else "supported",
                    basis="validated" if validating else "carried_forward",
                    current_provenance=provenance[i], available=not validating or i == 0))
                selections.append(Selection(claim_id=claim.claim_id, commit=commit,
                    selected=validating, reasons=("manual",)))
                if validating:
                    validations.append(ValidationResult(claim_id=claim.claim_id, commit=commit,
                        validator="structural", verdict=verdict,
                        reason="subject_absent" if i else "predicate_match", input_hash="fixture",
                        duration_seconds=0.1))
        costs = [Cost(phase="preflight", commit=parent, wall_seconds=1.0),
                 *(Cost(phase="maintenance", commit=commit, wall_seconds=0.4,
                        actual_validation_seconds=0.2 if validating else 0.0,
                        reconstructed_validation_seconds=0.2 if validating else 0.0,
                        index_seconds=0.1 if validating else 0.0,
                        logical_validations=2 if validating else 0,
                        actual_validations=2 if validating else 0) for commit in children)]
        for filename, records in (("claims", claims), ("provenance", provenance),
                                  ("states", states), ("selections", selections),
                                  ("validations", validations), ("costs", costs)):
            write_jsonl(folder / f"{filename}.jsonl", records)
        write_jsonl(folder / "transitions.jsonl", [])
        hashes = {path.name: file_hash(path) for path in folder.iterdir()}
        write_json(folder / "manifest.json", {"schema_version": 1, "protocol_version": "1.0",
            "status": "complete", "evaluation_eligible": True,
            "config": resolved.model_dump(mode="json"), "configuration_hash": digest(resolved),
            "input_hashes": {key: file_hash(root / file) for key, file in (
                ("claims", "claims.jsonl"), ("provenance", "provenance.jsonl"),
                ("parent_receipts", "receipts.jsonl"))}, "artifact_hashes": hashes,
            "claim_hashes": {c.claim_id: digest(c) for c in claims},
            "cohort": [c.claim_id for c in claims], "excluded": [], "parent_commit": parent,
            "child_commits": children, "app_version": "fixture", "python": "3.12",
            "validator_version": "independent-artifact-fixture", "started_at": "start",
            "finished_at": "finish"})
    declaration: dict[str, object] = {"run_id": name, "config_path": f"{name}/config.json",
        "split": "development", "cluster_id": f"{name}-cluster",
        "sequence_id": f"{name}-sequence" if replay else None}
    repository: dict[str, object] = {"repo_id": name, "url": "synthetic://manual-fixture",
        "path": f"{name}/repo", "source_roots": ["."],
        "environment_restoration": "synthetic fixture, no execution"}
    return declaration, repository, run_paths, labels


def dataset_fixture(root: Path, *, strata: tuple[str, ...] = ("fixture", "fixture"),
                    policies: tuple[PolicyConfig, ...] | None = None,
                    replay: bool = False) -> tuple[Path, list[Path], Path]:
    root.mkdir()
    declarations, repositories, runs, labels = [], [], [], []
    for i, stratum in enumerate(strata):
        declaration, repository, paths, truth = population(root, f"population{i}",
            stratum=stratum, policies=policies, replay=replay)
        declarations.append(declaration)
        repositories.append(repository)
        runs.extend(paths)
        labels.extend(truth)
    path = root / "dataset.json"
    write_json(path, {"schema_version": 1, "dataset_id": "independent-synthetic-artifacts",
        "protocol_version": "1.0", "dataset_kind": "synthetic", "repositories": repositories,
        "runs": declarations, "notes": ["Manually specified labels, no production validator."]})
    label_path = root / "labels.jsonl"
    write_jsonl(label_path, labels)
    return path, runs, label_path


def overall(report: DatasetAnalysis) -> tuple[GroupReport, ...]:
    return tuple(group for group in report.groups
                 if group.dimensions.repo_id is None and group.dimensions.claim_kind is None)


def test_two_cluster_bootstrap_and_macro(tmp_path: Path) -> None:
    dataset, runs, labels = dataset_fixture(tmp_path / "dataset")
    report = analyze_dataset(dataset, runs, labels, tmp_path / "report")
    group = overall(report)[0]
    policies = {policy.policy: policy for policy in group.policies}
    assert policies["keep_all"].micro.metrics["stale_exposure"].value == 1
    assert policies["all_validate"].micro.metrics["stale_exposure"].value == 0
    assert policies["keep_all"].total_clusters == 2
    assert policies["keep_all"].contradicted_clusters == 2
    assert policies["keep_all"].macro_by_repository["valid_retention"].value == 1
    assert policies["keep_all"].macro_by_repository["valid_retention"].total_repositories == 2
    interval = group.intervals["keep_all-minus-all_validate"]["stale_exposure"]
    assert interval.estimate == interval.lower == interval.upper == 1
    assert interval.clusters == 2
    assert policies["all_validate"].micro.counters["retired_tp"] == 2
    for filename in ("metrics.json", "intervals.json", "comparison.csv", "per_claim.csv",
                     "cumulative_cost.csv", "summary.md", "cost_quality.png"):
        assert (tmp_path / "report" / filename).exists()


def test_reject_partial_policy_set(tmp_path: Path) -> None:
    dataset, runs, labels = dataset_fixture(tmp_path / "dataset")
    with pytest.raises(InputError, match="partial policy sets"):
        analyze_dataset(dataset, runs[:-1], labels, tmp_path / "report")
    assert not (tmp_path / "report").exists()


def test_separate_chronological_and_enriched(tmp_path: Path) -> None:
    dataset, runs, labels = dataset_fixture(tmp_path / "dataset",
                                           strata=("chronological", "enriched"))
    report = analyze_dataset(dataset, runs, labels, tmp_path / "report")
    groups = overall(report)
    assert {group.dimensions.stratum for group in groups} == {"chronological", "enriched"}
    for group in groups:
        assert group.policies[0].total_clusters == 1
        assert group.intervals["keep_all-minus-all_validate"]["stale_exposure"].reason == (
            "insufficient_clusters")


def test_distinct_dependency_depth_policies(tmp_path: Path) -> None:
    dataset, runs, labels = dataset_fixture(tmp_path / "dataset", policies=(
        PolicyConfig(id="symbol_validate", dependency_depth=0),
        PolicyConfig(id="symbol_validate", dependency_depth=1)))
    report = analyze_dataset(dataset, runs, labels, tmp_path / "report")
    assert {policy.policy for policy in overall(report)[0].policies} == {
        "symbol_validate-depth0", "symbol_validate-depth1"}
    assert all(item.reason == "reference_policy_missing" for item in report.break_even)


def test_replay_sequences_separate_without_population_ci(tmp_path: Path) -> None:
    dataset, runs, labels = dataset_fixture(tmp_path / "dataset",
                                           strata=("replay", "replay"), replay=True)
    report = analyze_dataset(dataset, runs, labels, tmp_path / "report")
    groups = overall(report)
    assert {group.dimensions.sequence_id for group in groups} == {
        "population0-sequence", "population1-sequence"}
    for group in groups:
        assert group.intervals["keep_all-minus-all_validate"]["stale_exposure"].reason == (
            "replay_no_population_interval")
    assert all(len(cost.cumulative) == 2 for cost in report.costs)
    for cost in report.costs:
        assert cost.cumulative[-1].measured_total_seconds == pytest.approx(1.8)
        assert cost.uncached_timing.value is None


def test_cluster_is_not_claim(tmp_path: Path) -> None:
    dataset, runs, labels = dataset_fixture(tmp_path / "dataset")
    data = read_json(dataset)
    for row in data["runs"]:
        row["cluster_id"] = "shared-episode"
    write_json(dataset, data)
    report = analyze_dataset(dataset, runs, labels, tmp_path / "report")
    group = overall(report)[0]
    assert group.policies[0].total_clusters == 1
    assert group.policies[0].micro.counters["contradicted"] == 2
    assert group.intervals["keep_all-minus-all_validate"]["stale_exposure"].lower is None


def test_source_tampering_rejected(tmp_path: Path) -> None:
    dataset, runs, labels = dataset_fixture(tmp_path / "dataset")
    with (dataset.parent / "population0" / "receipts.jsonl").open("a") as stream:
        stream.write("\n")
    with pytest.raises(InputError, match="source or claim hashes"):
        analyze_dataset(dataset, runs, labels, tmp_path / "report")


def test_duplicate_policy_artifacts_rejected(tmp_path: Path) -> None:
    dataset, runs, labels = dataset_fixture(tmp_path / "dataset")
    with pytest.raises(InputError, match="duplicate dataset run/policy"):
        analyze_dataset(dataset, [*runs, runs[0]], labels, tmp_path / "report")


def test_optional_parent_evidence_hashes_verified(tmp_path: Path) -> None:
    from cami.models import ParentReceipt

    dataset, runs, labels = dataset_fixture(tmp_path / "dataset")
    source = dataset.parent / "population0"
    evidence = source / "parent-evidence.txt"
    evidence.write_text("Independent synthetic evidence statement.\n")
    config = read_json(source / "config.json")
    write_jsonl(source / "receipts.jsonl", [ParentReceipt(claim_id="population0-0",
        origin_commit=config["parent_commit"], status="supported",
        confirmation_type="synthetic_manual", evidence_path=evidence.name,
        evidence_sha256=file_hash(evidence))])
    for path in runs[:2]:
        manifest = read_json(path / "manifest.json")
        manifest["input_hashes"]["parent_receipts"] = file_hash(source / "receipts.jsonl")
        manifest["input_hashes"]["parent_evidence/population0-0"] = file_hash(evidence)
        write_json(path / "manifest.json", manifest)
    report = analyze_dataset(dataset, runs, labels, tmp_path / "report")
    assert len(report.costs) == 4
    manifest = read_json(runs[0] / "manifest.json")
    manifest["input_hashes"]["parent_evidence/population0-0"] = "0" * 64
    write_json(runs[0] / "manifest.json", manifest)
    with pytest.raises(InputError, match="source or claim hashes"):
        analyze_dataset(dataset, runs, labels, tmp_path / "tampered-report")


def test_break_even_observed_only(tmp_path: Path) -> None:
    dataset, runs, labels = dataset_fixture(tmp_path / "dataset", policies=(
        PolicyConfig(id="all_validate"), PolicyConfig(id="symbol_validate", dependency_depth=1)))
    report = analyze_dataset(dataset, runs, labels, tmp_path / "report")
    assert all(item.first_observed_transition is None for item in report.break_even)
    assert all(item.reason == "not_observed" for item in report.break_even)
    path = runs[1]
    costs = read_json(path / "manifest.json")
    cost_records = [Cost(phase="preflight", commit=costs["parent_commit"], wall_seconds=1.0),
                    Cost(phase="maintenance", commit=costs["child_commits"][0], wall_seconds=0.3,
                         initial_index_seconds=0.1, incremental_index_seconds=0.05,
                         index_seconds=0.15, actual_validation_seconds=0.2,
                         reconstructed_validation_seconds=0.2)]
    write_jsonl(path / "costs.jsonl", cost_records)
    costs["artifact_hashes"]["costs.jsonl"] = file_hash(path / "costs.jsonl")
    write_json(path / "manifest.json", costs)
    changed = analyze_dataset(dataset, runs, labels, tmp_path / "changed-report")
    first = next(item for item in changed.break_even if item.dataset_run_id == "population0")
    assert first.first_observed_transition == 1 and first.reason is None
    changed_cost = next(item for item in changed.costs
                        if item.dataset_run_id == "population0" and item.policy.startswith("symbol"))
    assert changed_cost.initial_index_seconds == 0.1
    assert changed_cost.later_index_seconds == 0.05
