from __future__ import annotations

import platform
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from cami import __version__
from cami.artifacts import (
    digest, file_hash, load, load_jsonl, read_json, reserve, within, write_json, write_jsonl,
)
from cami.dataset_models import DatasetManifest, DatasetRun
from cami.errors import InputError
from cami.evaluation import Label
from cami.inputs import Inputs, check_inputs
from cami.models import Behavior, Record, RunConfig
from cami.repository import git, read_snapshot


@dataclass(frozen=True)
class DatasetInputs:
    manifest: DatasetManifest
    base_dir: Path
    runs: tuple[tuple[DatasetRun, Inputs], ...]


def check_dataset(dataset_path: Path) -> DatasetInputs:
    """Check dataset membership and history without evaluating claims or reading labels."""
    manifest = load(dataset_path, DatasetManifest)
    base = dataset_path.resolve().parent
    for name, values in (("repository", [r.repo_id for r in manifest.repositories]),
                         ("run", [r.run_id for r in manifest.runs])):
        if any(not value for value in values) or len(values) != len(set(values)):
            raise InputError(f"empty or duplicate {name} ID")
    repositories = {r.repo_id: r for r in manifest.repositories}
    inputs: list[tuple[DatasetRun, Inputs]] = []
    hashes: dict[str, str] = {}
    clusters: dict[str, str] = {}
    sequences: dict[str, tuple[str, str, tuple[str, ...], tuple[str, ...]]] = {}
    cohorts: dict[tuple[str, str], tuple[str, ...]] = {}
    for entry in manifest.runs:
        if not entry.cluster_id or entry.sequence_id == "":
            raise InputError("cluster and sequence IDs must not be empty")
        inp = check_inputs(within(base, entry.config_path))
        config = inp.config
        repo = repositories.get(config.repo.repo_id)
        if repo is None:
            raise InputError("run repository is absent from dataset mapping")
        if (base / repo.path).resolve() != Path(config.repo.path):
            raise InputError("dataset repository path differs from run repository")
        if repo.source_roots != config.repo.source_roots:
            raise InputError("dataset source roots differ from run source roots")
        if (entry.split != config.split or manifest.protocol_version != config.protocol_version
                or manifest.dataset_kind != config.dataset_kind):
            raise InputError("run split, protocol or dataset kind differs from dataset")
        if not set(manifest.extra_environment_paths).issubset(config.extra_environment_paths):
            raise InputError("dataset environment watch paths must be included in every run configuration")
        group = (config.repo.repo_id, config.split)
        if clusters.setdefault(entry.cluster_id, config.split) != config.split:
            raise InputError("cluster crosses split boundaries")
        cohort = tuple(claim.claim_id for claim in inp.claims)
        key = (config.repo.repo_id, config.parent_commit)
        if cohorts.setdefault(key, cohort) != cohort:
            raise InputError("runs with the same repository and parent have different cohorts")
        revisions = (config.parent_commit, *config.child_commits)
        if entry.sequence_id is not None:
            sequence = (*group, revisions, cohort)
            if sequences.setdefault(entry.sequence_id, sequence) != sequence:
                raise InputError("sequence ID refers to inconsistent histories or cohorts")
        if config.stratum == "replay" and len(config.child_commits) < 2:
            raise InputError("replay requires multiple transitions")
        for claim in inp.claims:
            if hashes.setdefault(claim.claim_id, digest(claim)) != digest(claim):
                raise InputError("claim ID reused with different immutable content")
        inputs.append((entry, inp))
    for index, (left, before) in enumerate(inputs):
        lconfig = before.config
        history = {lconfig.parent_commit, *lconfig.child_commits}
        for right, after in inputs[index + 1:]:
            rconfig = after.config
            if not history.intersection({rconfig.parent_commit, *rconfig.child_commits}):
                continue
            if left.split != right.split:
                raise InputError("overlapping histories leak across development and heldout splits")
            if left.cluster_id != right.cluster_id:
                raise InputError("overlapping histories require the same episode cluster")
            if "replay" in {lconfig.stratum, rconfig.stratum}:
                repeated = (lconfig.stratum == rconfig.stratum == "replay"
                            and left.sequence_id is not None
                            and left.sequence_id == right.sequence_id)
                if not repeated:
                    raise InputError("replay histories overlap another sequence or independent pair")
    return DatasetInputs(manifest, base, tuple(inputs))


def annotate_export(dataset_path: Path, output: Path) -> Path:
    """Write blinded source evidence. Never read labels, receipts' evidence, or run outputs."""
    dataset = check_dataset(dataset_path)
    reserve(output)
    rows: list[dict[str, Any]] = []
    for entry, inp in dataset.runs:
        revisions = (inp.config.parent_commit, *inp.config.child_commits)
        paths = {claim.subject.path for claim in inp.claims}
        paths.update(anchor.path for prov in inp.provenance for anchor in prov.anchors)
        paths.update(node.path for prov in inp.provenance for edge in prov.dependencies for node in (edge.source, edge.target))
        evidence: dict[str, list[dict[str, Any]]] = {}
        for revision in revisions:
            snapshot = read_snapshot(inp.config.repo, revision).by_path()
            evidence[revision] = []
            for path in sorted(paths):
                blob = snapshot.get(path)
                record: dict[str, Any] = {"path": path, "commit": revision,
                    "object_id": blob.object_id if blob else None,
                    "sha256": blob.content_hash if blob and blob.content is not None else None,
                    "limitation": blob.limitation if blob else "source_absent", "evidence_path": None}
                if blob is not None and blob.content is not None:
                    target = Path("sources") / digest(inp.config.repo.repo_id)[:16] / revision / path
                    (output / target).parent.mkdir(parents=True, exist_ok=True)
                    (output / target).write_bytes(blob.content)
                    record["evidence_path"] = target.as_posix()
                evidence[revision].append(record)
        for claim in inp.claims:
            probe_record = None
            if isinstance(claim.predicate, Behavior):
                probe_relative = Path("probes") / digest(claim.claim_id)[:16] / Path(claim.predicate.probe_path).name
                probe_target = output / probe_relative
                probe_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(within(inp.base_dir, claim.predicate.probe_path), probe_target)
                probe_record = {"path": probe_relative.as_posix(), "sha256": file_hash(probe_target), "node_id": claim.predicate.node_id}
            rows.append({"schema_version": 1, "run_id": entry.run_id, "probe": probe_record,
                "repo_id": inp.config.repo.repo_id, "claim": claim.model_dump(mode="json"),
                "claim_sha256": digest(claim), "parent_commit": revisions[0],
                "child_commits": revisions[1:], "source_evidence": evidence})
    write_jsonl(output / "packets.jsonl", rows)
    write_json(output / "manifest.json", {"schema_version": 1,
        "dataset_id": dataset.manifest.dataset_id,
        "protocol_version": dataset.manifest.protocol_version, "blinded": True,
        "packets_sha256": file_hash(output / "packets.jsonl"), "packet_count": len(rows),
        "limitations": ["Source evidence does not establish behavioral truth.",
                         "Annotators must supply independent evidence and decisions."]})
    return output / "packets.jsonl"


Decision = Literal["supported", "contradicted", "uncertain"]
Confirmation = Literal["human_review", "independent_oracle", "independent_test", "synthetic_manual"]


class RawAnnotation(Record):
    annotation_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    commit: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    annotator_id: str = Field(min_length=1)
    annotator_kind: Literal["human", "independent_oracle", "synthetic_author"]
    independent: Literal[True]
    label: Decision
    evidence: tuple[str, ...] = Field(min_length=1)
    confirmation_type: Confirmation
    annotation_minutes: float = Field(ge=0)

    @field_validator("independent", mode="before")
    @classmethod
    def exact_independence(cls, value: object) -> object:
        if value is not True:
            raise ValueError("independent must be JSON true")
        return value

    @model_validator(mode="after")
    def authorship(self) -> RawAnnotation:
        kinds = {"human_review": "human", "independent_oracle": "independent_oracle",
                 "independent_test": "independent_oracle", "synthetic_manual": "synthetic_author"}
        if self.annotator_kind != kinds[self.confirmation_type]:
            raise ValueError("confirmation type contradicts annotator kind")
        if any(not evidence.strip() for evidence in self.evidence):
            raise ValueError("annotation evidence must not be empty")
        return self


class Adjudication(Record):
    adjudication_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    commit: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    annotation_ids: tuple[str, ...] = Field(min_length=1)
    adjudicator_id: str = Field(min_length=1)
    status: Literal["resolved", "unresolved"]
    label: Decision | None
    evidence: tuple[str, ...] = Field(min_length=1)
    confirmation_type: Confirmation
    annotation_minutes: float = Field(ge=0)
    previous_adjudication_id: str | None = None

    @model_validator(mode="after")
    def decision(self) -> Adjudication:
        if (self.status == "resolved") != (self.label is not None):
            raise ValueError("only resolved adjudication has a label")
        if any(not item.strip() for item in self.evidence):
            raise ValueError("adjudication evidence must not be empty")
        return self


class AnnotationItem(Record):
    claim_id: str = Field(min_length=1)
    commit: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class AnnotationImport(Record):
    annotations: tuple[RawAnnotation, ...] = Field(min_length=1)
    adjudications: tuple[Adjudication, ...] = ()
    annotation_population: tuple[AnnotationItem, ...] | None = None


def _agreement(groups: dict[tuple[str, str], list[RawAnnotation]],
               population: int | None) -> dict[str, Any]:
    pairs = [tuple(sorted(rows, key=lambda row: (row.annotator_id, row.annotation_id))[:2])
             for rows in groups.values() if len(rows) >= 2]
    # A predeclared second human review is the coverage requirement; oracles are disclosed separately.
    human_double = sum(sum(row.annotator_kind == "human" for row in rows) >= 2
                       for rows in groups.values())
    matched = sum(left.label == right.label for left, right in pairs)
    agreement = matched / len(pairs) if pairs else None
    reason = "no_double_annotations" if not pairs else None
    kappa: float | None = None
    if pairs:
        left_counts = Counter(left.label for left, _ in pairs)
        right_counts = Counter(right.label for _, right in pairs)
        expected = sum(left_counts[label] * right_counts[label]
                       for label in left_counts) / len(pairs) ** 2
        if expected == 1:
            reason = "degenerate_marginals"
        else:
            assert agreement is not None
            kappa = (agreement - expected) / (1 - expected)
    paired_groups: dict[tuple[str, str], list[tuple[RawAnnotation, RawAnnotation]]] = {}
    for left, right in pairs:
        paired_groups.setdefault((left.annotator_id, right.annotator_id), []).append((left, right))
    pair_statistics = []
    for identities, values in sorted(paired_groups.items()):
        observed = sum(left.label == right.label for left, right in values) / len(values)
        left_counts = Counter(left.label for left, _ in values)
        right_counts = Counter(right.label for _, right in values)
        expected = sum(left_counts[label] * right_counts[label] for label in left_counts) / len(values) ** 2
        pair_statistics.append({"annotators": identities, "items": len(values), "agreement": observed,
            "cohen_kappa": (observed - expected) / (1 - expected) if expected != 1 else None,
            "reason": "degenerate_marginals" if expected == 1 else None})
    if len(paired_groups) > 1:
        kappa, reason = None, "heterogeneous_annotator_pairs"
    fraction = human_double / population if population else None
    return {"items": len(groups), "by_annotator_pair": pair_statistics, "double_annotated_items": len(pairs),
        "human_double_annotated_items": human_double, "human_double_annotation_fraction": fraction,
        "required_fraction": 0.2, "requirement_met": fraction >= 0.2 if fraction is not None else None,
        "population_items": population,
        "coverage_reason": None if population else "full_population_not_supplied",
        "agreement": agreement, "cohen_kappa": kappa, "kappa_reason": reason,
        "pairing": "first two independent annotator IDs in lexical order per claim/revision",
        "computed_before_adjudication": True}


def annotate_import(input_path: Path, output: Path) -> Path:
    data = load(input_path, AnnotationImport)
    groups: dict[tuple[str, str], list[RawAnnotation]] = {}
    annotation_ids: set[str] = set()
    authors: set[tuple[str, str, str]] = set()
    for row in data.annotations:
        key = (row.claim_id, row.commit)
        author = (*key, row.annotator_id)
        if row.annotation_id in annotation_ids or author in authors:
            raise InputError("duplicate annotation ID or annotator response for one item")
        annotation_ids.add(row.annotation_id)
        authors.add(author)
        groups.setdefault(key, []).append(row)
    latest: dict[tuple[str, str], Adjudication] = {}
    adjudication_ids: set[str] = set()
    for adjudication_row in data.adjudications:
        row_adjudication = adjudication_row
        key = (row_adjudication.claim_id, row_adjudication.commit)
        expected_ids = {annotation.annotation_id for annotation in groups.get(key, [])}
        if (row_adjudication.adjudication_id in adjudication_ids or not expected_ids
                or len(row_adjudication.annotation_ids) != len(set(row_adjudication.annotation_ids))
                or set(row_adjudication.annotation_ids) != expected_ids):
            raise InputError("adjudication must reference exactly the independent originals for its item")
        previous = latest.get(key)
        if row_adjudication.previous_adjudication_id != (previous.adjudication_id if previous else None):
            raise InputError("adjudication history must be an ordered chain without discarded originals")
        adjudication_ids.add(row_adjudication.adjudication_id)
        latest[key] = row_adjudication
    labels: list[Label] = []
    unresolved: list[dict[str, str]] = []
    for key, rows in sorted(groups.items()):
        adjudication = latest.get(key)
        if adjudication is not None:
            if adjudication.label is None:
                unresolved.append({"claim_id": key[0], "commit": key[1], "reason": "unresolved_adjudication"})
                continue
            labels.append(Label(claim_id=key[0], commit=key[1], label=adjudication.label,
                annotator_id=adjudication.adjudicator_id, evidence=adjudication.evidence,
                confirmation_type=adjudication.confirmation_type, adjudication_status="adjudicated"))
        elif len({row.label for row in rows}) == 1:
            original = sorted(rows, key=lambda row: row.annotation_id)[0]
            labels.append(Label(claim_id=key[0], commit=key[1], label=original.label,
                annotator_id=original.annotator_id,
                evidence=tuple(dict.fromkeys(item for row in rows for item in row.evidence)),
                confirmation_type=original.confirmation_type,
                adjudication_status="agreement" if len(rows) > 1 else "single_annotator"))
        else:
            unresolved.append({"claim_id": key[0], "commit": key[1], "reason": "disagreement"})
    population: int | None = None
    if data.annotation_population is not None:
        population_keys = {(row.claim_id, row.commit) for row in data.annotation_population}
        if len(population_keys) != len(data.annotation_population) or not population_keys:
            raise InputError("annotation population must have unique nonempty claim/revision items")
        if not set(groups) <= population_keys:
            raise InputError("annotation falls outside declared population")
        population = len(population_keys)
    reserve(output)
    shutil.copyfile(input_path, output / "original_import.json")
    write_jsonl(output / "raw_annotations.jsonl", data.annotations)
    write_jsonl(output / "adjudications.jsonl", data.adjudications)
    write_jsonl(output / "labels.jsonl", labels)
    agreement = _agreement(groups, population)
    limitations = ["Authorship and independence are declared metadata; software cannot verify human identity.",
                  "Coverage is unverified unless the complete annotation_population is supplied.",
                  "Cohen kappa is reported per fixed annotator pair; heterogeneous pairs have no pooled kappa."]
    if agreement["requirement_met"] is not True:
        limitations.append("Single-annotator limitation: the 20% independent second-human requirement is unmet or unverified.")
    write_json(output / "annotation_report.json", {"schema_version": 1,
        "input_sha256": file_hash(input_path), "agreement": agreement,
        "final_labels": len(labels), "unresolved": unresolved,
        "annotation_minutes": sum(row.annotation_minutes for row in data.annotations),
        "adjudication_minutes": sum(row.annotation_minutes for row in data.adjudications),
        "limitations": limitations,
        "artifact_hashes": {name: file_hash(output / name) for name in
                            ("original_import.json", "raw_annotations.jsonl", "adjudications.jsonl", "labels.jsonl")}})
    return output / "labels.jsonl"


def freeze_dataset(dataset_path: Path, output: Path) -> Path:
    """Seal inputs and source evidence without executing a validator or granting protocol approval."""
    dataset = check_dataset(dataset_path)
    labels: tuple[Label, ...] = ()
    if dataset.manifest.labels_path is not None:
        labels = load_jsonl(within(dataset.base_dir, dataset.manifest.labels_path), Label)
        keys = [(label.claim_id, label.commit) for label in labels]
        if len(keys) != len(set(keys)):
            raise InputError("duplicate final label for claim/revision")
        expected = {(claim.claim_id, revision) for _, inp in dataset.runs
                    for claim in inp.claims for revision in inp.config.child_commits}
        if not set(keys) <= expected:
            raise InputError("final labels refer to claims or revisions outside the dataset")
    reserve(output)
    input_hashes: dict[str, str] = {}
    artifacts: dict[str, str] = {}

    def copy(source: Path, relative: Path) -> None:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and file_hash(source) != file_hash(target):
            raise InputError("referenced input paths collide in frozen directory")
        shutil.copyfile(source, target)
        input_hashes[relative.as_posix()] = file_hash(source)
        artifacts[relative.as_posix()] = file_hash(target)

    copy(dataset_path, Path("original_dataset.json"))
    run_records: list[dict[str, Any]] = []
    for entry, inp in dataset.runs:
        config = inp.config
        run_dir = Path("runs") / digest(entry.run_id)[:16]
        copy(within(dataset.base_dir, entry.config_path), run_dir / "original_config.json")
        for relative in (config.claims_path, config.provenance_path, config.parent_receipts_path):
            copy(within(inp.base_dir, relative), run_dir / relative)
        for receipt in inp.receipts:
            copy(within(inp.base_dir, receipt.evidence_path), run_dir / receipt.evidence_path)
        for claim in inp.claims:
            if isinstance(claim.predicate, Behavior):
                copy(within(inp.base_dir, claim.predicate.probe_path), run_dir / claim.predicate.probe_path)
        if config.graph_views_path is not None:
            for revision in (config.parent_commit, *config.child_commits):
                graph_relative = Path(config.graph_views_path) / f"{revision}.json"
                copy(within(inp.base_dir, graph_relative.as_posix()), run_dir / graph_relative)
        source_records: list[dict[str, Any]] = []
        for revision in (config.parent_commit, *config.child_commits):
            snapshot = read_snapshot(config.repo, revision)
            blobs: list[dict[str, Any]] = []
            for blob in snapshot.blobs:
                target = Path("snapshots") / digest(config.repo.repo_id)[:16] / revision / blob.path
                if blob.content is not None:
                    (output / target).parent.mkdir(parents=True, exist_ok=True)
                    (output / target).write_bytes(blob.content)
                    artifacts[target.as_posix()] = file_hash(output / target)
                blobs.append({"path": blob.path, "object_id": blob.object_id, "mode": blob.mode,
                    "sha256": blob.content_hash if blob.content is not None else None,
                    "limitation": blob.limitation,
                    "snapshot_path": target.as_posix() if blob.content is not None else None})
            source_records.append({"commit": revision, "blobs": blobs})
        if (output / run_dir / "expanded_config.json").exists():
            raise InputError("input path collides with frozen expanded configuration")
        write_json(output / run_dir / "expanded_config.json", config)
        artifacts[(run_dir / "expanded_config.json").as_posix()] = file_hash(output / run_dir / "expanded_config.json")
        receipts = {row.claim_id for row in inp.receipts}
        excluded = []
        cohort = []
        pending = []
        for claim in inp.claims:
            reason = None
            if claim.claim_id not in receipts:
                reason = "missing_parent_confirmation"
            elif claim.kind == "prose" or (claim.kind == "behavior_test" and config.validation.execution != "docker"):
                reason = "validator_unavailable"
            if reason:
                excluded.append({"claim_id": claim.claim_id, "reason": reason})
            elif claim.kind == "behavior_test":
                pending.append(claim.claim_id)
                cohort.append(claim.claim_id)
            else:
                cohort.append(claim.claim_id)
        run_records.append({"run_id": entry.run_id, "split": entry.split,
            "cluster_id": entry.cluster_id, "sequence_id": entry.sequence_id,
            "config_path": (run_dir / "expanded_config.json").as_posix(),
            "configuration_sha256": _config_digest(config), "parent_commit": config.parent_commit,
            "child_commits": config.child_commits, "repo_id": config.repo.repo_id,
            "cohort": cohort, "excluded": excluded, "pending_parent_preflight": pending,
            "claim_hashes": {claim.claim_id: digest(claim) for claim in inp.claims},
            "source_snapshots": source_records})
    if dataset.manifest.labels_path is not None:
        copy(within(dataset.base_dir, dataset.manifest.labels_path), Path("labels.jsonl"))
    if dataset.manifest.raw_annotations_path is not None:
        copy(within(dataset.base_dir, dataset.manifest.raw_annotations_path), Path("raw_annotations.jsonl"))
    required = {(claim.claim_id, revision) for _, inp in dataset.runs
                for claim in inp.claims for revision in inp.config.child_commits}
    available = {(row.claim_id, row.commit) for row in labels}
    annotation_status = "complete" if required <= available else "awaiting_annotation"
    protocol = {"schema_version": 1, "protocol_version": dataset.manifest.protocol_version,
        "dataset_id": dataset.manifest.dataset_id, "dataset_kind": dataset.manifest.dataset_kind,
        "status": "sealed", "annotation_status": annotation_status,
        "missing_annotation_items": len(required - available),
        "app_version": __version__, "python": sys.version, "os": platform.platform(),
        "git": git(Path(dataset.runs[0][1].config.repo.path), "--version").decode().strip(),
        "repositories": [repo.model_dump(mode="json") for repo in dataset.manifest.repositories],
        "runs": run_records, "input_hashes": input_hashes, "artifact_hashes": artifacts,
        "limitations": ["This seal records protocol fixation; it does not assert independent annotation.",
            "Behavioral parent preflight remains pending; freeze executes no tests or containers.",
            "Source snapshots are portable evidence. Execution still requires the recorded local Git repositories."]}
    write_json(output / "protocol.json", protocol)
    write_json(output / "seal.json", {"schema_version": 1,
        "protocol_sha256": file_hash(output / "protocol.json"), "artifact_hashes": artifacts})
    return output / "protocol.json"


def _config_digest(config: RunConfig) -> str:
    expanded = config.model_dump(mode="json")
    expanded.pop("frozen_protocol_path", None)
    return digest(expanded)


def validate_frozen_config(config_path: Path, protocol_path: Path) -> dict[str, Any]:
    """Validate a sealed heldout input without opening annotation or label files."""
    inp = check_inputs(config_path)
    protocol = read_json(protocol_path)
    seal = read_json(protocol_path.parent / "seal.json")
    if not isinstance(protocol, dict) or not isinstance(seal, dict):
        raise InputError("invalid frozen protocol or seal")
    if (protocol.get("schema_version") != 1 or protocol.get("status") != "sealed"
            or seal.get("schema_version") != 1
            or seal.get("protocol_sha256") != file_hash(protocol_path)):
        raise InputError("frozen protocol seal mismatch")
    runs = protocol.get("runs")
    hashes = protocol.get("input_hashes")
    artifacts = protocol.get("artifact_hashes")
    if not isinstance(runs, list) or not isinstance(hashes, dict) or not isinstance(artifacts, dict):
        raise InputError("invalid frozen protocol input metadata")
    matches = [run for run in runs if isinstance(run, dict)
               and run.get("configuration_sha256") == _config_digest(inp.config)]
    if not matches:
        raise InputError("configuration is not part of the frozen protocol")
    matching = matches[0]
    if (matching.get("split") != inp.config.split
            or protocol.get("protocol_version") != inp.config.protocol_version
            or protocol.get("dataset_kind") != inp.config.dataset_kind):
        raise InputError("frozen protocol membership mismatch")
    frozen_config = matching.get("config_path")
    if not isinstance(frozen_config, str):
        raise InputError("invalid frozen configuration path")
    run_dir = Path(frozen_config).parent
    archived_config = within(protocol_path.parent, frozen_config)
    if (artifacts.get(frozen_config) != file_hash(archived_config)
            or _config_digest(load(archived_config, RunConfig)) != _config_digest(inp.config)):
        raise InputError("frozen expanded configuration hash mismatch")
    original_manifest = within(protocol_path.parent, "original_dataset.json")
    if (hashes.get("original_dataset.json") != file_hash(original_manifest)
            or artifacts.get("original_dataset.json") != file_hash(original_manifest)):
        raise InputError("frozen dataset manifest hash mismatch")
    current = {relative: within(inp.base_dir, relative) for relative in
               (inp.config.claims_path, inp.config.provenance_path, inp.config.parent_receipts_path)}
    for receipt in inp.receipts:
        current[receipt.evidence_path] = within(inp.base_dir, receipt.evidence_path)
    for claim in inp.claims:
        if isinstance(claim.predicate, Behavior):
            current[claim.predicate.probe_path] = within(inp.base_dir, claim.predicate.probe_path)
    if inp.config.graph_views_path is not None:
        for revision in (inp.config.parent_commit, *inp.config.child_commits):
            relative = f"{inp.config.graph_views_path}/{revision}.json"
            current[relative] = within(inp.base_dir, relative)
    for relative, source in current.items():
        archived = (run_dir / relative).as_posix()
        expected = hashes.get(archived)
        if (not isinstance(expected, str) or file_hash(source) != expected
                or artifacts.get(archived) != expected
                or file_hash(within(protocol_path.parent, archived)) != expected):
            raise InputError(f"frozen input hash mismatch: {relative}")
    if matching.get("claim_hashes") != {claim.claim_id: digest(claim) for claim in inp.claims}:
        raise InputError("frozen immutable claim hashes differ")
    return matching
