import json

import pytest
from pydantic import ValidationError

from cami.artifacts import file_hash, read_json, read_jsonl, write_json
from cami.dataset import (
    annotate_export, annotate_import, check_dataset, freeze_dataset, validate_frozen_config,
)
from cami.errors import InputError


def dataset_for(config):
    data = read_json(config)
    dataset = config.parent / "dataset.json"
    write_json(dataset, {"schema_version": 1, "dataset_id": "fixture", "protocol_version": "1.0",
        "dataset_kind": "synthetic", "repositories": [{"repo_id": "fixture",
        "url": "synthetic://fixture", "path": data["repo"]["path"], "source_roots": ["."],
        "environment_restoration": "none required"}], "runs": [{"run_id": "pair",
        "config_path": config.name, "split": "development", "cluster_id": "episode"}]})
    return dataset


def pair(repo):
    parent = repo.commit({"module.py": "def f(): return 1\n"})
    child = repo.commit({"module.py": "def f(): return 2\n"})
    return dataset_for(repo.config(parent, [child])), parent, child


def annotation(identifier, author, label="supported", claim="f", commit="a" * 40):
    return {"schema_version": 1, "annotation_id": identifier, "claim_id": claim,
        "commit": commit, "annotator_id": author, "annotator_kind": "human", "independent": True,
        "label": label, "evidence": ["Reviewed exact definition in source"],
        "confirmation_type": "human_review", "annotation_minutes": 2.0}


def import_file(tmp_path, annotations, adjudications=None, population=None):
    value = {"schema_version": 1, "annotations": annotations,
             "adjudications": adjudications or []}
    if population is not None:
        value["annotation_population"] = [{"schema_version": 1, "claim_id": claim,
                                            "commit": commit} for claim, commit in population]
    path = tmp_path / "annotations.json"
    write_json(path, value)
    return path


def test_export_blind_source_packet_and_never_reads_labels(repo):
    dataset, parent, child = pair(repo)
    manifest = read_json(dataset)
    manifest["labels_path"] = "nonexistent-labels.jsonl"
    write_json(dataset, manifest)
    packet_path = annotate_export(dataset, dataset.parent / "annotation")
    packet = read_jsonl(packet_path)[0]
    assert packet["parent_commit"] == parent
    assert packet["child_commits"] == [child]
    assert "policy" not in packet and "label" not in packet and "verdict" not in packet
    assert "parent_receipts" not in packet
    evidence = packet["source_evidence"][child][0]
    assert (packet_path.parent / evidence["evidence_path"]).read_text() == "def f(): return 2\n"
    assert file_hash(packet_path.parent / evidence["evidence_path"]) == evidence["sha256"]
    with pytest.raises(InputError, match="output already exists"):
        annotate_export(dataset, packet_path.parent)


def test_freeze_copies_inputs_resolves_refs_and_preserves_checkout(repo):
    dataset, _, child = pair(repo)
    config = read_json(dataset.parent / "run.json")
    config["child_commits"] = ["HEAD"]
    write_json(dataset.parent / "run.json", config)
    dirty = repo.root / "module.py"
    dirty.write_text("uncommitted source\n")
    before = repo.git("status", "--porcelain"), repo.git("rev-parse", "HEAD")
    target = freeze_dataset(dataset, dataset.parent / "frozen")
    protocol = read_json(target)
    assert protocol["status"] == "sealed"
    assert protocol["annotation_status"] == "awaiting_annotation"
    assert protocol["runs"][0]["child_commits"] == [child]
    assert protocol["runs"][0]["cohort"] == ["f"]
    assert protocol["runs"][0]["excluded"] == []
    assert all(file_hash(target.parent / key) == value
               for key, value in protocol["artifact_hashes"].items())
    assert before == (repo.git("status", "--porcelain"), repo.git("rev-parse", "HEAD"))
    assert dirty.read_text() == "uncommitted source\n"
    assert validate_frozen_config(dataset.parent / "run.json", target)["cohort"] == ["f"]
    with pytest.raises(InputError, match="output already exists"):
        freeze_dataset(dataset, target.parent)


def test_frozen_config_checks_live_input_and_seal_but_never_labels(repo):
    dataset, _, _ = pair(repo)
    target = freeze_dataset(dataset, dataset.parent / "frozen")
    assert validate_frozen_config(dataset.parent / "run.json", target)["run_id"] == "pair"
    claims = dataset.parent / "claims.jsonl"
    claims.write_text(claims.read_text().replace("f exists", "f exists in source"))
    with pytest.raises(InputError, match="hash mismatch"):
        validate_frozen_config(dataset.parent / "run.json", target)
    protocol = read_json(target)
    protocol["status"] = "tampered"
    write_json(target, protocol)
    with pytest.raises(InputError, match="seal mismatch"):
        validate_frozen_config(dataset.parent / "run.json", target)


def test_freeze_hashes_labels_but_gate_ignores_label_content(repo):
    dataset, _, child = pair(repo)
    value = {"schema_version": 1, "claim_id": "f", "commit": child, "label": "supported",
             "annotator_id": "fixture-author", "evidence": ["synthetic scenario"],
             "confirmation_type": "synthetic_manual", "adjudication_status": "single_annotator"}
    labels = dataset.parent / "labels.jsonl"
    labels.write_text(json.dumps(value) + "\n")
    manifest = read_json(dataset)
    manifest["labels_path"] = labels.name
    write_json(dataset, manifest)
    target = freeze_dataset(dataset, dataset.parent / "frozen")
    assert read_json(target)["annotation_status"] == "complete"
    labels.unlink()
    (target.parent / "labels.jsonl").write_text("not valid JSON\n")
    assert validate_frozen_config(dataset.parent / "run.json", target)["run_id"] == "pair"


@pytest.mark.parametrize("change, message", [
    ("duplicate_repo", "duplicate repository"), ("duplicate_run", "duplicate run"),
    ("split", "run split"), ("protocol", "run split"), ("path", "repository path"),
    ("roots", "source roots"),
])
def test_reject_dataset_membership_inconsistency(repo, change, message):
    dataset, _, _ = pair(repo)
    value = read_json(dataset)
    if change == "duplicate_repo":
        value["repositories"].append(value["repositories"][0])
    elif change == "duplicate_run":
        value["runs"].append(value["runs"][0])
    elif change == "split":
        value["runs"][0]["split"] = "heldout"
    elif change == "protocol":
        value["protocol_version"] = "2.0"
    elif change == "path":
        value["repositories"][0]["path"] = "other-repo"
    else:
        value["repositories"][0]["source_roots"] = ["src"]
    write_json(dataset, value)
    with pytest.raises(InputError, match=message):
        check_dataset(dataset)


def test_reject_overlap_clusters_and_split_leakage(repo):
    dataset, _, _ = pair(repo)
    config = read_json(dataset.parent / "run.json")
    config["policy"]["id"] = "keep_all"
    write_json(dataset.parent / "other.json", config)
    value = read_json(dataset)
    value["runs"].append({"run_id": "other", "config_path": "other.json",
                          "split": "development", "cluster_id": "unrelated"})
    write_json(dataset, value)
    with pytest.raises(InputError, match="same episode"):
        check_dataset(dataset)
    value["runs"][1]["split"] = "heldout"
    config["split"] = "heldout"
    write_json(dataset.parent / "other.json", config)
    write_json(dataset, value)
    with pytest.raises(InputError, match="leak"):
        check_dataset(dataset)


def test_replay_overlap_rejected_even_same_cluster(repo):
    dataset, _, _ = pair(repo)
    third = repo.commit({"module.py": "def f(): return 3\n"})
    config = read_json(dataset.parent / "run.json")
    config["child_commits"].append(third)
    config["stratum"] = "replay"
    write_json(dataset.parent / "replay.json", config)
    value = read_json(dataset)
    value["runs"].append({"run_id": "replay", "config_path": "replay.json",
                          "split": "development", "cluster_id": "episode", "sequence_id": "s"})
    write_json(dataset, value)
    with pytest.raises(InputError, match="replay histories overlap"):
        check_dataset(dataset)


def test_disagreements_omitted_and_agreement_is_pre_adjudication(tmp_path):
    raw = [annotation("a", "alice"), annotation("b", "bob", "contradicted"),
           annotation("c", "alice", "contradicted", claim="g"),
           annotation("d", "bob", "contradicted", claim="g")]
    population = [(claim, "a" * 40) for claim in ("f", "g", "unannotated")]
    source = import_file(tmp_path, raw, population=population)
    labels = annotate_import(source, tmp_path / "import")
    assert [row["claim_id"] for row in read_jsonl(labels)] == ["g"]
    report = read_json(labels.parent / "annotation_report.json")
    assert report["agreement"]["agreement"] == 0.5
    assert report["agreement"]["cohen_kappa"] == 0.0
    assert report["agreement"]["human_double_annotation_fraction"] == 2 / 3
    assert report["agreement"]["requirement_met"] is True
    assert report["unresolved"][0]["claim_id"] == "f"
    assert read_jsonl(labels.parent / "raw_annotations.jsonl") == raw
    assert (labels.parent / "original_import.json").read_bytes() == source.read_bytes()


def test_single_annotation_no_fabricated_coverage_or_kappa(tmp_path):
    source = import_file(tmp_path, [annotation("a", "alice")])
    labels = annotate_import(source, tmp_path / "import")
    report = read_json(labels.parent / "annotation_report.json")
    assert report["agreement"]["cohen_kappa"] is None
    assert report["agreement"]["requirement_met"] is None
    assert read_jsonl(labels)[0]["adjudication_status"] == "single_annotator"


def test_adjudication_chain_retains_original_and_unresolved_latest(tmp_path):
    raw = [annotation("a", "alice"), annotation("b", "bob", "contradicted")]
    first = {"schema_version": 1, "adjudication_id": "j1", "claim_id": "f", "commit": "a" * 40,
        "annotation_ids": ["a", "b"], "adjudicator_id": "carol", "status": "resolved",
        "label": "uncertain", "evidence": ["Runtime evidence absent"],
        "confirmation_type": "human_review", "annotation_minutes": 3.0,
        "previous_adjudication_id": None}
    second = {**first, "adjudication_id": "j2", "status": "unresolved", "label": None,
              "previous_adjudication_id": "j1"}
    source = import_file(tmp_path, raw, [first, second])
    labels = annotate_import(source, tmp_path / "import")
    assert read_jsonl(labels) == []
    assert read_jsonl(labels.parent / "adjudications.jsonl") == [first, second]
    assert read_jsonl(labels.parent / "raw_annotations.jsonl") == raw
    assert read_json(labels.parent / "annotation_report.json")["agreement"]["agreement"] == 0


def test_adjudicated_label_uses_explicit_author(tmp_path):
    raw = [annotation("a", "alice"), annotation("b", "bob", "contradicted")]
    adjudication = {"schema_version": 1, "adjudication_id": "j", "claim_id": "f",
        "commit": "a" * 40, "annotation_ids": ["a", "b"], "adjudicator_id": "carol",
        "status": "resolved", "label": "uncertain", "evidence": ["Insufficient evidence"],
        "confirmation_type": "human_review", "annotation_minutes": 1.0}
    labels = annotate_import(import_file(tmp_path, raw, [adjudication]), tmp_path / "import")
    assert read_jsonl(labels)[0]["annotator_id"] == "carol"
    assert read_jsonl(labels)[0]["label"] == "uncertain"


@pytest.mark.parametrize("change", ["duplicate_id", "duplicate_author", "production", "identity",
                                    "not_independent", "unknown", "missing_reference", "unchained"])
def test_reject_invalid_annotation_histories(tmp_path, change):
    rows = [annotation("a", "alice"), annotation("b", "bob")]
    adjudications = []
    if change == "duplicate_id":
        rows[1]["annotation_id"] = "a"
    elif change == "duplicate_author":
        rows[1]["annotator_id"] = "alice"
    elif change == "production":
        rows[0]["confirmation_type"] = "production_validator"
    elif change == "identity":
        rows[0]["annotator_kind"] = "independent_oracle"
    elif change == "not_independent":
        rows[0]["independent"] = False
    elif change == "unknown":
        rows[0]["verdict"] = "supported"
    else:
        adjudications = [{"schema_version": 1, "adjudication_id": "j", "claim_id": "f",
            "commit": "a" * 40, "annotation_ids": ["a"], "adjudicator_id": "carol",
            "status": "resolved", "label": "supported", "evidence": ["Reviewed source"],
            "confirmation_type": "human_review", "annotation_minutes": 1.0}]
        if change == "unchained":
            adjudications[0]["annotation_ids"] = ["a", "b"]
            adjudications[0]["previous_adjudication_id"] = "missing"
    with pytest.raises((InputError, ValidationError)):
        annotate_import(import_file(tmp_path, rows, adjudications), tmp_path / "import")
    assert not (tmp_path / "import").exists()


def test_protocol_locator_does_not_change_sealed_configuration(repo):
    dataset, _, _ = pair(repo)
    target = freeze_dataset(dataset, dataset.parent / "frozen")
    config_path = dataset.parent / "run.json"
    config = read_json(config_path)
    config["frozen_protocol_path"] = "frozen/protocol.json"
    write_json(config_path, config)
    assert validate_frozen_config(config_path, target)["cohort"] == ["f"]


def test_heldout_cli_requires_seal_and_runs_without_labels(repo, capsys):
    from cami.cli import main

    dataset, _, _ = pair(repo)
    config_path = dataset.parent / "run.json"
    config = read_json(config_path)
    config["split"] = "heldout"
    write_json(config_path, config)
    manifest = read_json(dataset)
    manifest["runs"][0]["split"] = "heldout"
    manifest["labels_path"] = None
    write_json(dataset, manifest)
    output = dataset.parent / "heldout-run"
    args = ["run", "--config", str(config_path), "--out", str(output)]
    assert main(args) == 2
    assert not output.exists()
    freeze_dataset(dataset, dataset.parent / "frozen")
    config["frozen_protocol_path"] = "frozen/protocol.json"
    write_json(config_path, config)
    assert main(args) == 0
    assert read_json(output / "manifest.json")["status"] == "complete"
    provenance = dataset.parent / "provenance.jsonl"
    provenance.write_text(provenance.read_text() + "\n")
    assert main(args[:-1] + [str(dataset.parent / "tampered-run")]) == 2
    assert not (dataset.parent / "tampered-run").exists()
    assert "frozen input hash mismatch" in capsys.readouterr().err


def test_degenerate_kappa_has_reason_and_full_population_denominator(tmp_path):
    raw = [annotation("a", "alice"), annotation("b", "bob")]
    population = [(f"item-{i}", "a" * 40) for i in range(5)] + [("f", "a" * 40)]
    labels = annotate_import(import_file(tmp_path, raw, population=population), tmp_path / "import")
    agreement = read_json(labels.parent / "annotation_report.json")["agreement"]
    assert agreement["agreement"] == 1.0
    assert agreement["cohen_kappa"] is None
    assert agreement["kappa_reason"] == "degenerate_marginals"
    assert agreement["human_double_annotation_fraction"] == 1 / 6
    assert agreement["requirement_met"] is False


def test_reject_numeric_independence_spoof(tmp_path):
    raw = annotation("a", "alice")
    raw["independent"] = 1
    with pytest.raises(ValidationError, match="JSON true"):
        annotate_import(import_file(tmp_path, [raw]), tmp_path / "import")


def test_export_reports_absent_child_source(repo):
    parent = repo.commit({"module.py": "def f(): return 1\n"})
    child = repo.commit({"module.py": None})
    dataset = dataset_for(repo.config(parent, [child]))
    packet = read_jsonl(annotate_export(dataset, dataset.parent / "annotation"))[0]
    source = packet["source_evidence"][child][0]
    assert source["limitation"] == "source_absent"
    assert source["evidence_path"] is None and source["sha256"] is None


def test_kappa_does_not_pool_different_annotator_pairs(tmp_path):
    records = [annotation("1","alice","supported",claim="first"),
               annotation("2","bob","contradicted",claim="first"),
               annotation("3","carol","supported",claim="second"),
               annotation("4","david","supported",claim="second")]
    path = import_file(tmp_path, records)
    annotate_import(path,tmp_path / "out")
    report = read_json(tmp_path / "out/annotation_report.json")["agreement"]
    assert report["cohen_kappa"] is None
    assert report["kappa_reason"] == "heterogeneous_annotator_pairs"
    assert len(report["by_annotator_pair"]) == 2


def test_extra_environment_paths_belong_to_git_snapshot(repo):
    parent = repo.commit({"module.py":"def f(): pass\n","custom-env.txt":"first"})
    child = repo.commit({"custom-env.txt":"second"})
    config_path = repo.config(parent,[child])
    config = read_json(config_path)
    config["extra_environment_paths"] = ["custom-env.txt"]
    write_json(config_path,config)
    dataset = dataset_for(config_path)
    manifest = read_json(dataset)
    manifest["extra_environment_paths"] = ["custom-env.txt"]
    write_json(dataset,manifest)
    protocol = freeze_dataset(dataset,dataset.parent / "frozen")
    assert read_json(protocol)["status"] == "sealed"
    validate_frozen_config(config_path,protocol)


def test_heldout_preserves_exclusions_already_frozen(repo):
    from cami.cli import main

    dataset, _, _ = pair(repo)
    config_path = dataset.parent / "run.json"
    config = read_json(config_path)
    config["split"] = "heldout"
    write_json(config_path, config)
    manifest = read_json(dataset)
    manifest["runs"][0]["split"] = "heldout"
    write_json(dataset, manifest)
    for name in ("claims.jsonl", "provenance.jsonl"):
        path = dataset.parent / name
        rows = read_jsonl(path)
        extra = dict(rows[0], claim_id="no-receipt")
        path.write_text(''.join(json.dumps(row) + '\n' for row in [*rows, extra]))
    frozen = freeze_dataset(dataset, dataset.parent / "frozen")
    assert read_json(frozen)["runs"][0]["cohort"] == ["f"]
    config["frozen_protocol_path"] = "frozen/protocol.json"
    write_json(config_path, config)
    out = dataset.parent / "out"
    assert main(["run", "--config", str(config_path), "--out", str(out)]) == 0
    result = read_json(out / "manifest.json")
    assert result["cohort"] == ["f"]
    assert result["excluded"] == [{"claim_id": "no-receipt", "reason": "missing_parent_confirmation"}]


def test_heldout_multiple_frozen_policies_analyze_as_one_population(repo):
    from cami.aggregate import analyze_dataset
    from cami.artifacts import write_jsonl
    from cami.cli import main
    from cami.evaluation import Label

    dataset, _, child = pair(repo)
    config_path = dataset.parent / "run.json"
    original = read_json(config_path)
    original["split"] = "heldout"
    manifest = read_json(dataset)
    manifest["runs"] = []
    configs = []
    for policy in ("keep_all", "all_validate"):
        config = dict(original, policy={"id": policy})
        path = dataset.parent / f"{policy}.json"
        write_json(path, config)
        configs.append(path)
        manifest["runs"].append({"run_id": policy, "config_path": path.name,
                                 "split": "heldout", "cluster_id": "episode"})
    write_json(dataset, manifest)
    freeze_dataset(dataset, dataset.parent / "frozen")
    outputs = []
    for path in configs:
        config = read_json(path)
        config["frozen_protocol_path"] = "frozen/protocol.json"
        write_json(path, config)
        out = dataset.parent / f"out-{path.stem}"
        assert main(["run", "--config", str(path), "--out", str(out)]) == 0
        outputs.append(out)
    labels = dataset.parent / "labels.jsonl"
    write_jsonl(labels, [Label(claim_id="f", commit=child, label="supported",
                              annotator_id="synthetic-fixture", evidence=("manual fixture",),
                              confirmation_type="synthetic_manual", adjudication_status="not_required")])
    report = analyze_dataset(dataset, outputs, labels, dataset.parent / "analysis")
    assert len(report.costs) == 2
    assert len({row.dataset_run_id for row in report.costs}) == 1
    with pytest.raises(InputError, match="declared policy variants"):
        analyze_dataset(dataset, outputs[:1], labels, dataset.parent / "partial")
