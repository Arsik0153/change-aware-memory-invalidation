"""Parent-only observations and independent provenance reviews, outside policy inputs."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from cami.artifacts import (
    canonical, digest, file_hash, load, load_jsonl, parse, read_json, read_jsonl, reserve,
    within, write_bytes, write_json, write_jsonl,
)
from cami.dataset_models import DatasetManifest
from cami.errors import InputError
from cami.index import INDEX_VERSION, IndexConfig, Module, build_index, parse_module
from cami.models import Behavior, Claim, Dependency, Node, Provenance, Record, RunConfig, safe_path
from cami.repository import Snapshot, read_snapshot

CRITERION_MISSING = "completeness_criterion_undefined_in_protocol"
LIMITS = [
    "Automatic checks reuse CAMI's static parser; they are not independent review or claim truth labels.",
    "Only recorded anchors and dependency endpoints are checked; omitted support is not discovered.",
    "Endpoint existence does not establish a dependency relation or its sufficiency.",
    "No runtime probes or behavior are executed; external and dynamic dependencies remain unverified.",
    "An empty declared dependency list is not a completeness assertion.",
    "No child snapshot, label, receipt, selection, or policy result is read.",
]


class ProvenanceReview(Record):
    claim_id: str = Field(min_length=1)
    parent_commit: str = Field(min_length=1)
    claim_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer_id: str = Field(min_length=1)
    independent: Literal[True]
    status: Literal["confirmed", "incomplete", "uncertain"]
    confirmed_dependencies: tuple[Dependency, ...]
    omitted_dependencies: tuple[Dependency, ...]
    evidence: tuple[str, ...] = Field(min_length=1)
    notes: str | None

    @field_validator("reviewer_id")
    @classmethod
    def nonblank_reviewer(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reviewer_id must be nonblank")
        return value

    @field_validator("independent", mode="before")
    @classmethod
    def exact_independent(cls, value: object) -> object:
        if value is not True:
            raise ValueError("review requires an explicit independent decision")
        return value

    @field_validator("evidence")
    @classmethod
    def local_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            safe_path(value)
        if len(set(values)) != len(values):
            raise ValueError("duplicate evidence path")
        return values


class ParentObservations:
    def __init__(self, snapshot: Snapshot, output: Path):
        self.blobs = snapshot.by_path()
        self.output = output
        self.modules: dict[str, Module] = {}

    def node(self, node: Node) -> dict[str, Any]:
        node = Node(path=node.path, qualname=node.qualname)
        blob = self.blobs.get(node.path)
        result: dict[str, Any] = {"node": node.model_dump(mode="json"), "status": "missing"}
        if blob is None:
            return result
        result.update({"object_id": blob.object_id, "limitation": blob.limitation})
        if blob.content is None:
            result["status"] = "source_unavailable"
            return result
        evidence = "sources/" + blob.content_hash
        write_bytes(self.output / evidence, blob.content)
        result.update({"status": "verified", "source_evidence_path": evidence,
                       "content_sha256": blob.content_hash, "line_count": len(blob.content.splitlines())})
        if node.qualname is None:
            return result
        if node.path not in self.modules:
            self.modules[node.path] = parse_module(blob, node.path)
        module = self.modules[node.path]
        matches = [definition for definition in module.definitions if definition.node == node]
        if module.limitation:
            result.update(status="analysis_limitation", limitation=module.limitation)
        elif len(matches) != 1 or matches[0].ambiguous:
            result["status"] = "symbol_missing_or_ambiguous"
        else:
            definition = matches[0]
            result.update(start_line=definition.start_line, end_line=definition.end_line,
                          node_kind=definition.node_kind)
        return result


def _outside_source(output: Path, base: Path) -> None:
    if output.resolve().is_relative_to(base.resolve()):
        raise InputError("audit output must not be inside source inputs")


def _seal(output: Path, manifest: dict[str, Any]) -> Path:
    manifest["files"] = {path.relative_to(output).as_posix(): file_hash(path)
                         for path in sorted(output.rglob("*"))
                         if path.is_file() and path != output / "audit_manifest.json"}
    write_json(output / "audit_manifest.json", manifest)
    return output / "audit_manifest.json"


def audit_provenance(dataset_path: Path, output: Path) -> Path:
    """Record parent evidence without admitting claims or changing source provenance."""
    manifest = load(dataset_path, DatasetManifest)
    base = dataset_path.resolve().parent
    _outside_source(output, base)
    groups = []
    ids: set[str] = set()
    run_ids: set[str] = set()
    for entry in manifest.runs:
        safe_path(entry.run_id)
        if len(Path(entry.run_id).parts) != 1 or entry.run_id in run_ids:
            raise InputError("audit requires unique single-component run IDs")
        run_ids.add(entry.run_id)
        config_path = within(base, entry.config_path)
        config = load(config_path, RunConfig)
        claims_path = within(config_path.parent, config.claims_path)
        provenance_path = within(config_path.parent, config.provenance_path)
        claims = load_jsonl(claims_path, Claim, "claim_id")
        provenance = load_jsonl(provenance_path, Provenance, "claim_id")
        if not claims or {p.claim_id for p in provenance} != {c.claim_id for c in claims}:
            raise InputError(f"claim/provenance mismatch in {entry.run_id}")
        if ids & {c.claim_id for c in claims}:
            raise InputError("audit requires globally unique claim IDs")
        ids.update(c.claim_id for c in claims)
        groups.append((entry, config_path, config, claims_path, provenance_path, claims, provenance))
    reserve(output)
    all_rows = []
    group_audits = []
    for entry, config_path, config, claims_path, provenance_path, claims, provenance in groups:
        repo = config.repo.model_copy(update={"path": str((config_path.parent / config.repo.path).resolve())})
        snapshot = read_snapshot(repo, config.parent_commit)
        if any(c.origin_commit != snapshot.revision or c.repo_id != repo.repo_id for c in claims):
            raise InputError("claims must belong to the resolved parent and repository")
        if any(p.scenario_id != config.scenario_id for p in provenance):
            raise InputError("provenance scenario mismatch")
        index = build_index(snapshot, IndexConfig(source_roots=repo.source_roots))
        index_unresolved = sorted(index.unresolved, key=lambda node: (node.path, node.qualname or ""))
        index_limits = index.limitations()
        group_dir = output / "groups" / entry.run_id
        observations = ParentObservations(snapshot, group_dir)
        for name, path in (("claims.jsonl", claims_path), ("provenance.jsonl", provenance_path)):
            write_bytes(group_dir / "source_inputs" / name, path.read_bytes())
        pmap = {p.claim_id: p for p in provenance}
        rows = []
        for claim in claims:
            prov = pmap[claim.claim_id]
            reasons = {CRITERION_MISSING, "independent_provenance_review_required"}
            subject = observations.node(claim.subject)
            if subject["status"] != "verified":
                reasons.add("subject_" + subject["status"])
            elif subject["node_kind"] != claim.subject.node_kind:
                reasons.add("subject_kind_mismatch")
            anchors = []
            if not prov.anchors:
                reasons.add("no_anchors_recorded")
            for anchor in prov.anchors:
                checked = observations.node(Node(path=anchor.path,
                                                 qualname=anchor.qualname if anchor.scope == "symbol" else None))
                issues = []
                if checked["status"] != "verified":
                    issues.append(checked["status"])
                if anchor.observed_commit != snapshot.revision:
                    issues.append("observed_commit_not_parent")
                if checked.get("content_sha256") != anchor.content_hash:
                    issues.append("hash_mismatch")
                if any(line is not None and line > checked.get("line_count", 0)
                       for line in (anchor.start_line, anchor.end_line)):
                    issues.append("line_range_invalid")
                anchors.append({"anchor": anchor.model_dump(mode="json"), "observation": checked,
                                "status": issues[0] if issues else "verified", "issues": issues})
                reasons.update("anchor_" + issue for issue in issues)
            dependencies = []
            for dependency in prov.dependencies:
                source = observations.node(dependency.source)
                target = observations.node(dependency.target)
                resolved = source["status"] == target["status"] == "verified"
                dependencies.append({"dependency": dependency.model_dump(mode="json", by_alias=True),
                                     "source": source, "target": target,
                                     "endpoints_resolved_at_parent": resolved,
                                     "relation_status": "not_independently_confirmed"})
                if not resolved:
                    reasons.add("unresolved_declared_dependency")
            if prov.known_incomplete:
                reasons.add("source_known_incomplete_flag")
            reasons.update("source_unresolved:" + reason for reason in prov.unresolved_reasons)
            probe: dict[str, Any] | None = None
            if isinstance(claim.predicate, Behavior):
                path = within(config_path.parent, claim.predicate.probe_path)
                probe = {"expected_sha256": claim.predicate.probe_sha256,
                         "source_path": claim.predicate.probe_path, "executed": False}
                if path.is_file():
                    data = path.read_bytes()
                    sha = hashlib.sha256(data).hexdigest()
                    evidence = "probes/" + sha
                    write_bytes(group_dir / evidence, data)
                    probe.update(content_sha256=sha, source_evidence_path=evidence,
                                 status="verified" if sha == claim.predicate.probe_sha256 else "hash_mismatch")
                else:
                    probe["status"] = "missing"
                if probe["status"] != "verified":
                    reasons.add("behavior_probe_" + probe["status"])
            support_nodes = {Node(path=claim.subject.path, qualname=claim.subject.qualname)}
            support_nodes.update(Node(path=a.path, qualname=a.qualname) for a in prov.anchors)
            support_nodes.update(d.source for d in prov.dependencies)
            support_nodes.update(d.target for d in prov.dependencies)
            support_paths = {node.path for node in support_nodes}
            support_unresolved = [node.model_dump(mode="json") for node in index_unresolved
                                  if node in support_nodes or node.qualname is None and node.path in support_paths]
            rows.append({"schema_version": 1, "run_id": entry.run_id, "claim_id": claim.claim_id,
                         "parent_commit": snapshot.revision, "subject": claim.subject.model_dump(mode="json"),
                         "claim": claim.model_dump(mode="json"), "claim_sha256": digest(claim),
                         "source_provenance": prov.model_dump(mode="json", by_alias=True),
                         "provenance_sha256": digest(prov),
                         "source_evidence_base": f"groups/{entry.run_id}",
                         "claim_kind": claim.kind, "anchors": anchors, "dependencies": dependencies,
                         "automatic_checks": {"subject": subject,
                             "frozen_probe": probe,
                             "indexed_unresolved_in_recorded_support": support_unresolved,
                             "indexed_limitations_in_recorded_support": {
                                 path: limit for path, limit in index_limits.items() if path in support_paths}},
                         "analysis_limits": LIMITS,
                         "source_known_incomplete": prov.known_incomplete,
                         "source_unresolved_reasons": list(prov.unresolved_reasons),
                         "incompleteness_reasons": sorted(reasons),
                         "review_status": "unreviewed", "independent_review": None,
                         "known_incomplete": True})
        write_jsonl(group_dir / "provenance_audit.jsonl", rows)
        all_rows.extend(rows)
        group_audits.append({"run_id": entry.run_id, "parent_commit": snapshot.revision,
                             "claim_count": len(rows),
                             "snapshot_index": {
                                 "unresolved": [node.model_dump(mode="json") for node in index_unresolved],
                                 "limitations": index_limits, "global_unresolved": index.global_unresolved,
                                 "interpretation": "Static observations, not independently confirmed dependencies."},
                             "audit_path": f"groups/{entry.run_id}/provenance_audit.jsonl"})
    write_jsonl(output / "provenance_audit.jsonl", all_rows)
    write_jsonl(output / "review_form.jsonl", [{"schema_version": 1, "claim_id": row["claim_id"],
        "parent_commit": row["parent_commit"], "claim_sha256": row["claim_sha256"],
        "provenance_sha256": row["provenance_sha256"], "reviewer_id": None, "independent": None,
        "status": None, "confirmed_dependencies": [], "omitted_dependencies": [],
        "evidence": [], "notes": None} for row in all_rows])
    implementation_root = Path(__file__).resolve().parents[2]
    implementation_files = ("scripts/prepare_main.py", "src/cami/provenance_audit.py",
                            "src/cami/index.py", "src/cami/repository.py", "src/cami/models.py")
    return _seal(output, {"schema_version": 1, "source_dataset": str(dataset_path.resolve()),
        "implementation_sha256": {name: file_hash(implementation_root / name) for name in implementation_files},
        "index_version": INDEX_VERSION,
        "source_dataset_sha256": file_hash(dataset_path), "claim_count": len(all_rows),
        "groups": group_audits, "parent_only": True, "child_data_used": False,
        "completeness_criterion": "undefined_by_current_protocol", "known_incomplete_cleared": 0,
        "review_import": "import-provenance-review", "status": "audit_complete_review_pending"})


def import_provenance_review(audit_path: Path, reviews_path: Path, output: Path) -> Path:
    """Retain actual reviewer decisions and evidence without authorizing flag closure."""
    audit = read_json(audit_path)
    base = audit_path.resolve().parent
    _outside_source(output, base)
    if audit.get("schema_version") != 1 or audit.get("status") != "audit_complete_review_pending":
        raise InputError("review import requires an original completed audit")
    for name, expected in audit["files"].items():
        if file_hash(within(base, name)) != expected:
            raise InputError(f"audit artifact hash mismatch: {name}")
    rows = read_jsonl(within(base, "provenance_audit.jsonl"))
    by_id = {row["claim_id"]: row for row in rows}
    raw_answers = reviews_path.read_bytes()
    reviews = [ProvenanceReview.model_validate_json(canonical(parse(line)))
               for line in raw_answers.decode("utf-8").splitlines() if line.strip()]
    if not reviews:
        raise InputError("provenance review import requires completed independent reviews")
    reviewed = {}
    evidence_bytes: dict[str, bytes] = {}
    for review in reviews:
        if review.claim_id not in by_id or review.claim_id in reviewed:
            raise InputError("unknown or duplicate provenance review")
        row = by_id[review.claim_id]
        if review.parent_commit != row["parent_commit"]:
            raise InputError("provenance review commit must match parent")
        if review.claim_sha256 != row["claim_sha256"] or review.provenance_sha256 != row["provenance_sha256"]:
            raise InputError("provenance review claim/provenance digest mismatch")
        declared = {canonical(item["dependency"]) for item in row["dependencies"]}
        if any(canonical(dep) not in declared for dep in review.confirmed_dependencies):
            raise InputError("confirmed dependencies must be recorded dependencies")
        if review.status == "confirmed" and review.omitted_dependencies:
            raise InputError("confirmed review cannot declare omitted dependencies")
        retained = []
        for name in review.evidence:
            evidence = within(reviews_path.resolve().parent, name)
            if not evidence.is_file():
                raise InputError(f"review evidence is not a file: {name}")
            data = evidence.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            destination = "review_evidence/" + sha
            evidence_bytes[destination] = data
            retained.append({"source_path": name, "retained_path": destination, "sha256": sha})
        reviewed[review.claim_id] = (review, retained)
    reserve(output)
    for name in audit["files"]:
        write_bytes(within(output, name), within(base, name).read_bytes())
    write_bytes(output / "source_audit_manifest.json", audit_path.read_bytes())
    write_bytes(output / "raw_provenance_reviews.jsonl", raw_answers)
    for name, data in evidence_bytes.items():
        write_bytes(output / name, data)
    updated = []
    for row in rows:
        row = dict(row)
        if row["claim_id"] in reviewed:
            review, evidence_records = reviewed[row["claim_id"]]
            row["review_status"] = review.status
            row["independent_review"] = {"answer": review.model_dump(mode="json", by_alias=True),
                                         "retained_evidence": evidence_records}
            reasons = set(row["incompleteness_reasons"])
            reasons.discard("independent_provenance_review_required")
            if review.status != "confirmed":
                reasons.add("independent_review_" + review.status)
            if review.omitted_dependencies:
                reasons.add("review_declared_omitted_dependencies")
            row["incompleteness_reasons"] = sorted(reasons)
        row["known_incomplete"] = True
        updated.append(row)
    write_jsonl(output / "provenance_audit.jsonl", updated)
    for group in audit["groups"]:
        write_jsonl(within(output, group["audit_path"]),
                    [row for row in updated if row["run_id"] == group["run_id"]])
    audit.update({"reviewed": len(reviewed), "unreviewed": len(rows) - len(reviewed),
                  "source_reviews_sha256": hashlib.sha256(raw_answers).hexdigest(),
                  "known_incomplete_cleared": 0,
                  "status": "review_imported_completeness_criterion_still_undefined"})
    return _seal(output, audit)
