from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from cami.artifacts import file_hash, read_json, read_jsonl, write_json, write_jsonl
from cami.errors import InputError
from cami.index import ChangeSet
from cami.models import Claim, MemoryState, PolicyConfig, Provenance
from cami.policies import SelectionContext, select_claims
import cami.provenance_audit as audit_module

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/prepare_main.py"
MODULE_SPEC = importlib.util.spec_from_file_location("prepare_main", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
prepare = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = prepare
MODULE_SPEC.loader.exec_module(prepare)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True).stdout.decode().strip()


@pytest.fixture
def parent_repo(tmp_path):
    repo = tmp_path / "source repo"
    repo.mkdir()
    git(repo, "init")
    utils = repo / "src/click/utils.py"
    utils.parent.mkdir(parents=True)
    # Repository functions contain host-write code. Generation must never execute it.
    source = "".join(f'def function_{i}(x: int = {i}, *, flag=False) -> int:\n'
                     f'    """Documented function {i}."""\n'
                     '    raise RuntimeError("must not execute repository code")\n\n'
                     for i in range(12))
    source += ('def make_default_short_help(text, max_length=45):\n'
               '    """Build a short help string."""\n'
               '    raise RuntimeError("must not execute repository code")\n')
    utils.write_text(source)
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-m", "parent fixture")
    parent = git(repo, "rev-parse", "HEAD")
    utils.write_text(source + "\n# child comment\n")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-m", "fix fixture")
    child = git(repo, "rev-parse", "HEAD")
    return {"schema_version": 1, "group_id": "click-opaque-parent", "repo_id": "click",
            "repo_path": str(repo), "source_roots": ["src"], "parent_commit": parent,
            "seed": prepare.SEED}, child


def assemble_fixture(parent_repo, tmp_path):
    spec, child = parent_repo
    candidates = tmp_path / "candidates"
    prepare.generate_parent(spec, candidates / spec["group_id"])
    selection = {"schema_version": 1, "seed": prepare.SEED, "protocol_version": "1.1",
        "repositories": [{"repo_id": "click", "path": spec["repo_path"], "source_roots": ["src"],
            "url": "synthetic://test-only-fixture"}],
        "groups": [{"group_id": spec["group_id"], "repo_id": "click",
            "parent_commit": spec["parent_commit"], "child_commits": [child], "stratum": "chronological",
            "split": "development", "cluster_id": "fixture-episode", "sequence_id": None}]}
    selection_path = tmp_path / "selection.json"
    write_json(selection_path, selection)
    return prepare.assemble(selection_path, candidates, tmp_path / "assembled")


def test_selection_is_deterministic_disjoint_and_preserves_replay_episode():
    rows = [prepare.Transition(f"{i:040x}", f"{i + 1:040x}", "fix API" if i % 3 else "routine change")
            if i % 40 else None for i in range(400)]
    excluded = {f"{i:040x}" for i in range(12)}
    selected, blocks = prepare.select_history(rows, excluded, 3, 42)
    assert (selected, blocks) == prepare.select_history(rows, excluded, 3, 42)
    assert sum(stratum == "chronological" for stratum, _ in selected) == 10
    assert sum(stratum == "enriched" for stratum, _ in selected) == 10
    occupied = set(excluded)
    episodes = prepare.episode_map(rows)
    replay_episode_ids = set()
    for block in blocks:
        assert len(block) == 10
        assert all(a.child == b.parent for a, b in zip(block, block[1:]))
        revisions = {block[0].parent, *(edge.child for edge in block)}
        assert len(revisions) == 11
        assert episodes[block[0].child] not in replay_episode_ids
        replay_episode_ids.add(episodes[block[0].child])
        assert not occupied & revisions
        occupied.update(revisions)
    for _, edge in selected:
        assert not occupied & {edge.parent, edge.child}
        assert episodes[edge.child] not in replay_episode_ids
        occupied.update((edge.parent, edge.child))


def test_known_episodes_share_cluster_until_a_merge_boundary():
    a = prepare.Transition("parent", "one", "first")
    b = prepare.Transition("one", "two", "second")
    c = prepare.Transition("merge-parent", "three", "third")
    assert prepare.episode_map([a, b, None, c]) == {"one": "parent", "two": "parent", "three": "merge-parent"}


def test_merge_boundary_is_not_a_replay_transition():
    rows = [prepare.Transition(f"{i:040x}", f"{i+1:040x}", "fix API")
            if i % 10 else None for i in range(200)]
    with pytest.raises(InputError, match="replay"):
        prepare.select_history(rows, set(), 1, 42)


def test_parent_generator_all_kinds_zero_receipts_and_checkout_unchanged(parent_repo, tmp_path):
    spec, child = parent_repo
    repo = Path(spec["repo_path"])
    before = git(repo, "status", "--porcelain"), git(repo, "rev-parse", "HEAD"), git(repo, "ls-files", "--stage")
    output = tmp_path / "draft"
    prepare.generate_parent(spec, output)
    claims = read_jsonl(output / "claims.jsonl")
    assert [claim["kind"] for claim in claims] == (["symbol_exists"] * 4 + ["signature_equals"] * 4
                                                    + ["behavior_test", "prose"])
    assert read_jsonl(output / "parent_receipts.jsonl") == []
    assert not list(output.rglob("*labels*"))
    assert read_json(output / "draft.json")["admitted_claim_ids"] == []
    assert all(claim["origin_commit"] == spec["parent_commit"] for claim in claims)
    assert all(anchor["observed_commit"] == spec["parent_commit"]
               for row in read_jsonl(output / "provenance.jsonl") for anchor in row["anchors"])
    assert (git(repo, "status", "--porcelain"), git(repo, "rev-parse", "HEAD"), git(repo, "ls-files", "--stage")) == before
    second = tmp_path / "same-parent"
    prepare.generate_parent(spec, second)
    assert file_hash(output / "claims.jsonl") == file_hash(second / "claims.jsonl")
    assert child not in (output / "draft.json").read_text()


@pytest.mark.parametrize("future_field", ["child_commit", "diff", "changed_symbols", "stratum"])
def test_parent_generator_rejects_future_inputs(parent_repo, tmp_path, future_field):
    spec, _ = parent_repo
    with pytest.raises(InputError, match="future information"):
        prepare.generate_parent({**spec, future_field: "forbidden"}, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()


def test_review_forms_blank_seeded_and_blinded(parent_repo, tmp_path):
    dataset = assemble_fixture(parent_repo, tmp_path)
    base = dataset.parent
    primary = read_jsonl(base / "annotation/primary_form.jsonl")
    second = read_jsonl(base / "annotation/second_form.jsonl")
    assert len(read_jsonl(base / "annotation/population.jsonl")) == 10
    assert len(read_jsonl(base / "annotation/child_form.jsonl")) == 10
    assert len(read_jsonl(base / "annotation/main_population.jsonl")) == 10
    assert not read_jsonl(base / "annotation/replay_population.jsonl")
    assert len(primary) == 20
    assert len(second) == 4
    assert len({row["claim_id"] for row in second}) == 2
    assert all(row["label"] is None and row["annotator_id"] is None
               and row["independent"] is None and row["evidence"] == [] for row in primary + second)
    assert read_json(base / "annotation/assignments.json")["main_second_fraction"] == 0.2
    packets = read_jsonl(base / "annotation/packets.jsonl")
    assert len(packets) == 10
    assert all("policy" not in row and "verdict" not in row for row in packets)
    for row in packets:
        for records in row["source_evidence"].values():
            for record in records:
                assert record["evidence_path"] is None or (base / "annotation" / record["evidence_path"]).exists()
    assert not (base / "labels.jsonl").exists()
    assert all(read_json(base / run["config_path"])["preview"] for run in read_json(dataset)["runs"])


def review_for(claim, **changes):
    # Synthetic annotation used only by a temporary test fixture, never a real corpus.
    return {"schema_version": 1, "annotation_id": "fixture-annotation", "claim_id": claim["claim_id"],
            "commit": claim["origin_commit"], "annotator_id": "fixture-reviewer", "annotator_kind": "human",
            "independent": True, "label": "supported", "evidence": ["Test fixture source manually specified."],
            "confirmation_type": "human_review", "annotation_minutes": 1.0, **changes}


def test_import_parent_records_only_external_supported_reviews_and_preserves_preview(parent_repo, tmp_path):
    dataset = assemble_fixture(parent_repo, tmp_path)
    group = dataset.parent / "groups" / parent_repo[0]["group_id"]
    claim = read_jsonl(group / "claims.jsonl")[0]
    reviews = tmp_path / "external_test_reviews.jsonl"
    write_jsonl(reviews, [review_for(claim)])
    imported = prepare.import_parent(dataset, reviews, tmp_path / "reviewed")
    target = imported.parent / "groups" / parent_repo[0]["group_id"]
    receipts = read_jsonl(target / "parent_receipts.jsonl")
    assert len(receipts) == 1
    assert receipts[0]["claim_id"] == claim["claim_id"]
    assert file_hash(target / receipts[0]["evidence_path"]) == receipts[0]["evidence_sha256"]
    assert read_jsonl(group / "parent_receipts.jsonl") == []
    assert read_json(target / "run.json")["preview"] is True
    assert read_json(imported.parent / "parent_review_status.json")["evaluation_eligible"] is False


@pytest.mark.parametrize("label", ["contradicted", "uncertain"])
def test_parent_nonsupported_decisions_never_get_receipts(parent_repo, tmp_path, label):
    dataset = assemble_fixture(parent_repo, tmp_path)
    group = dataset.parent / "groups" / parent_repo[0]["group_id"]
    reviews = tmp_path / "external_test_reviews.jsonl"
    write_jsonl(reviews, [review_for(read_jsonl(group / "claims.jsonl")[0], label=label)])
    imported = prepare.import_parent(dataset, reviews, tmp_path / "reviewed")
    target = imported.parent / "groups" / parent_repo[0]["group_id"]
    assert read_jsonl(target / "parent_receipts.jsonl") == []
    assert read_jsonl(imported.parent / "parent_raw_annotations.jsonl")[0]["label"] == label


def test_parent_import_rejects_child_decisions(parent_repo, tmp_path):
    dataset = assemble_fixture(parent_repo, tmp_path)
    group = dataset.parent / "groups" / parent_repo[0]["group_id"]
    reviews = tmp_path / "external_test_reviews.jsonl"
    write_jsonl(reviews, [review_for(read_jsonl(group / "claims.jsonl")[0], commit=parent_repo[1])])
    with pytest.raises(InputError, match="child decisions"):
        prepare.import_parent(dataset, reviews, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()


def test_behavior_parent_import_requires_independent_test(parent_repo, tmp_path):
    dataset = assemble_fixture(parent_repo, tmp_path)
    group = dataset.parent / "groups" / parent_repo[0]["group_id"]
    behavior = next(row for row in read_jsonl(group / "claims.jsonl") if row["kind"] == "behavior_test")
    reviews = tmp_path / "external_test_reviews.jsonl"
    write_jsonl(reviews, [review_for(behavior)])
    with pytest.raises(InputError, match="independent frozen-probe"):
        prepare.import_parent(dataset, reviews, tmp_path / "rejected")


def provenance_path(dataset):
    run = read_json(dataset)["runs"][0]
    config_path = dataset.parent / run["config_path"]
    return config_path.parent / read_json(config_path)["provenance_path"]


def fixture_provenance_review(audit_path, tmp_path, **changes):
    row = read_jsonl(audit_path.parent / "review_form.jsonl")[0]
    (tmp_path / "review-evidence.txt").write_bytes(b"Synthetic fixture evidence\r\n\x00original bytes")
    return {**row, "reviewer_id": "fixture-independent-reviewer", "independent": True,
            "status": "confirmed", "evidence": ["review-evidence.txt"], **changes}


def test_provenance_audit_context_and_parent_evidence(parent_repo, tmp_path):
    dataset = assemble_fixture(parent_repo, tmp_path)
    before = {p: p.read_bytes() for p in dataset.parent.rglob("*") if p.is_file()}
    audit_path = prepare.audit_provenance(dataset, tmp_path / "audit")
    manifest = read_json(audit_path)
    rows = read_jsonl(audit_path.parent / "provenance_audit.jsonl")
    assert len(rows) == 10
    assert all(row["automatic_checks"]["subject"]["status"] == "verified" for row in rows)
    original_claims = read_jsonl(provenance_path(dataset).parent / "claims.jsonl")
    assert [row["claim"] for row in rows] == original_claims
    assert all(row["dependencies"] == [] for row in rows)
    assert all("no_explicit_dependencies_recorded" not in row["incompleteness_reasons"] for row in rows)
    assert all(row["review_status"] == "unreviewed" and row["known_incomplete"] for row in rows)
    for row in rows:
        evidence = row["automatic_checks"]["subject"]
        retained = audit_path.parent / row["source_evidence_base"] / evidence["source_evidence_path"]
        assert file_hash(retained) == evidence["content_sha256"]
        assert retained.read_bytes() == subprocess.check_output([
            "git", "-C", parent_repo[0]["repo_path"], "show",
            parent_repo[0]["parent_commit"] + ":" + row["subject"]["path"]])
    behavior = next(row for row in rows if row["claim_kind"] == "behavior_test")
    probe = behavior["automatic_checks"]["frozen_probe"]
    assert probe["status"] == "verified" and probe["executed"] is False
    assert file_hash(audit_path.parent / behavior["source_evidence_base"] / probe["source_evidence_path"]) == probe["expected_sha256"]
    assert manifest["index_version"] and manifest["implementation_sha256"]
    for name, expected in manifest["files"].items():
        assert file_hash(audit_path.parent / name) == expected
    assert before == {p: p.read_bytes() for p in dataset.parent.rglob("*") if p.is_file()}


@pytest.mark.parametrize("damage,reason", [
    ("missing_anchor", "anchor_missing"), ("empty_anchors", "no_anchors_recorded"),
    ("target_file", "unresolved_declared_dependency"),
    ("target_symbol", "unresolved_declared_dependency"),
    ("source_symbol", "unresolved_declared_dependency"),
    ("anchor_commit", "anchor_observed_commit_not_parent"),
    ("anchor_hash", "anchor_hash_mismatch"), ("anchor_lines", "anchor_line_range_invalid"),
])
def test_provenance_audit_reports_parent_defects(parent_repo, tmp_path, damage, reason):
    dataset = assemble_fixture(parent_repo, tmp_path)
    path = provenance_path(dataset)
    records = read_jsonl(path)
    provenance = records[0]
    anchor = provenance["anchors"][0]
    valid_node = {"path": anchor["path"], "qualname": anchor["qualname"]}
    if damage in {"source_symbol", "target_symbol", "target_file"}:
        source, target = dict(valid_node), dict(valid_node)
        if damage == "source_symbol":
            source["qualname"] = "nonexistent_symbol"
        elif damage == "target_symbol":
            target["qualname"] = "nonexistent_symbol"
        else:
            target["path"] = "src/absent.py"
        provenance["dependencies"] = [{"from": source, "to": target, "relation": "calls", "origin": "manual"}]
    elif damage == "missing_anchor":
        anchor["path"] = "src/missing.py"
    elif damage == "empty_anchors":
        provenance["anchors"] = []
    elif damage == "anchor_commit":
        anchor["observed_commit"] = parent_repo[1]
    elif damage == "anchor_hash":
        anchor["content_hash"] = "0" * 64
    else:
        anchor["end_line"] = 1000000
    write_jsonl(path, records)
    audit = prepare.audit_provenance(dataset, tmp_path / "audit")
    row = read_jsonl(audit.parent / "provenance_audit.jsonl")[0]
    assert reason in row["incompleteness_reasons"]
    assert row["known_incomplete"]
    if provenance["dependencies"]:
        assert row["dependencies"][0]["endpoints_resolved_at_parent"] is False


def test_provenance_audit_records_snapshot_unresolved_and_limits(parent_repo, tmp_path):
    dataset = assemble_fixture(parent_repo, tmp_path)
    spec, _ = parent_repo
    repo = Path(spec["repo_path"])
    (repo / "src/click/unknown.py").write_text("import missing_external\ndef f(): return missing_external.call()\n")
    (repo / "src/click/broken.py").write_text("def invalid(\n")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-m", "audit snapshot fixture")
    parent = git(repo, "rev-parse", "HEAD")
    config_path = provenance_path(dataset).parent / "run.json"
    config = read_json(config_path)
    config["parent_commit"] = parent
    write_json(config_path, config)
    claims_path = config_path.parent / "claims.jsonl"
    claims = read_jsonl(claims_path)
    for claim in claims:
        claim["origin_commit"] = parent
    write_jsonl(claims_path, claims)
    result = prepare.audit_provenance(dataset, tmp_path / "audit")
    indexed = read_json(result)["groups"][0]["snapshot_index"]
    assert indexed["global_unresolved"] is True
    assert {"path": "src/click/unknown.py", "qualname": None} in indexed["unresolved"]
    assert indexed["limitations"]["src/click/broken.py"] == "parse_error"


@pytest.mark.parametrize("start,end,invalid", [(1, None, False), (None, 1, False),
                                               (1, 1, False), (1000000, None, True)])
def test_anchor_display_range_does_not_require_symbol_coverage(parent_repo, tmp_path, start, end, invalid):
    dataset = assemble_fixture(parent_repo, tmp_path)
    path = provenance_path(dataset)
    records = read_jsonl(path)
    records[0]["anchors"][0].update(start_line=start, end_line=end)
    write_jsonl(path, records)
    result = prepare.audit_provenance(dataset, tmp_path / "audit")
    anchor = read_jsonl(result.parent / "provenance_audit.jsonl")[0]["anchors"][0]
    assert anchor["anchor"]["start_line"] == start and anchor["anchor"]["end_line"] == end
    assert anchor["observation"]["start_line"] <= anchor["observation"]["end_line"]
    assert ("line_range_invalid" in anchor["issues"]) is invalid
    assert anchor["status"] == ("line_range_invalid" if invalid else "verified")


@pytest.mark.parametrize("policy", ["file_validate", "symbol_validate", "file_invalidate", "symbol_invalidate"])
def test_parent_only_audit_preserves_conservative_selection(parent_repo, tmp_path, monkeypatch, policy):
    dataset = assemble_fixture(parent_repo, tmp_path)
    path = provenance_path(dataset)
    config_path = path.parent / "run.json"
    config = read_json(config_path)
    config["child_commits"] = ["unresolvable-child-sentinel"]
    config["parent_receipts_path"] = "do-not-read-receipts.jsonl"
    config["graph_views_path"] = "do-not-read-graphs"
    write_json(config_path, config)
    data = read_json(dataset)
    data["labels_path"] = "do-not-read-labels.jsonl"
    data["raw_annotations_path"] = "do-not-read-answers.jsonl"
    write_json(dataset, data)
    original_snapshot = audit_module.read_snapshot
    seen = []
    def only_parent(repo, revision):
        assert revision == parent_repo[0]["parent_commit"]
        seen.append(revision)
        return original_snapshot(repo, revision)
    monkeypatch.setattr(audit_module, "read_snapshot", only_parent)
    original_read = Path.read_text
    def guarded_read(file, *args, **kwargs):
        assert "do-not-read" not in str(file) and "annotation/" not in str(file)
        return original_read(file, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", guarded_read)
    before = path.read_bytes()
    result = prepare.audit_provenance(dataset, tmp_path / "audit")
    assert len(seen) == 1 and read_json(result)["child_data_used"] is False
    assert path.read_bytes() == before
    claims = tuple(Claim.model_validate_json(json.dumps(row)) for row in read_jsonl(path.parent / "claims.jsonl"))
    provenance = tuple(Provenance.model_validate_json(json.dumps(row)) for row in read_jsonl(path))
    states = tuple(MemoryState(claim_id=claim.claim_id, revision=claim.origin_commit, state="valid",
        last_checked_commit=claim.origin_commit, last_supported_commit=claim.origin_commit,
        last_verdict="supported", basis="validated", current_provenance=prov, available=True)
        for claim, prov in zip(claims, provenance, strict=True))
    changes = ChangeSet(frozenset(), frozenset(), (), frozenset(), frozenset(), False)
    context = SelectionContext("unused-child", claims, provenance, states, changes, protocol_version="1.1")
    selected = select_claims(context, PolicyConfig(id=policy))
    assert all(decision.selected and "known_incomplete" in decision.reasons for decision in selected)


def test_provenance_review_preserves_bytes_evidence_and_group_rows(parent_repo, tmp_path):
    dataset = assemble_fixture(parent_repo, tmp_path)
    original_provenance = provenance_path(dataset).read_bytes()
    audit = prepare.audit_provenance(dataset, tmp_path / "audit")
    review = fixture_provenance_review(audit, tmp_path)
    reviews_path = tmp_path / "reviews.jsonl"
    raw = ("\r\n" + json.dumps(review, ensure_ascii=False, separators=(", ", ": ")) + "\r\n\r\n").encode()
    reviews_path.write_bytes(raw)
    original_rows = (audit.parent / "provenance_audit.jsonl").read_bytes()
    imported = prepare.import_provenance_review(audit, reviews_path, tmp_path / "reviewed")
    rows = read_jsonl(imported.parent / "provenance_audit.jsonl")
    assert (imported.parent / "raw_provenance_reviews.jsonl").read_bytes() == raw
    evidence = rows[0]["independent_review"]["retained_evidence"][0]
    assert (imported.parent / evidence["retained_path"]).read_bytes() == (tmp_path / "review-evidence.txt").read_bytes()
    assert file_hash(imported.parent / evidence["retained_path"]) == evidence["sha256"]
    assert rows[0]["review_status"] == "confirmed" and rows[1]["review_status"] == "unreviewed"
    assert all(row["known_incomplete"] for row in rows)
    assert "completeness_criterion_undefined_in_protocol" in rows[0]["incompleteness_reasons"]
    assert "independent_provenance_review_required" not in rows[0]["incompleteness_reasons"]
    manifest = read_json(imported)
    assert read_jsonl(imported.parent / manifest["groups"][0]["audit_path"]) == rows
    assert (audit.parent / "provenance_audit.jsonl").read_bytes() == original_rows
    assert provenance_path(dataset).read_bytes() == original_provenance
    assert manifest["known_incomplete_cleared"] == 0


@pytest.mark.parametrize("damage", ["blank", "not_independent", "numeric_independent", "missing_evidence",
    "wrong_parent", "wrong_claim_hash", "wrong_provenance_hash", "dependency_shape", "duplicate"])
def test_provenance_review_rejects_unconfirmed_or_unbound_answers(parent_repo, tmp_path, damage):
    dataset = assemble_fixture(parent_repo, tmp_path)
    audit = prepare.audit_provenance(dataset, tmp_path / "audit")
    review = fixture_provenance_review(audit, tmp_path)
    if damage == "blank":
        review["status"] = None
    elif damage == "not_independent":
        review["independent"] = False
    elif damage == "numeric_independent":
        review["independent"] = 1
    elif damage == "missing_evidence":
        review["evidence"] = ["missing.txt"]
    elif damage == "wrong_parent":
        review["parent_commit"] = parent_repo[1]
    elif damage == "wrong_claim_hash":
        review["claim_sha256"] = "0" * 64
    elif damage == "wrong_provenance_hash":
        review["provenance_sha256"] = "0" * 64
    elif damage == "dependency_shape":
        review["confirmed_dependencies"] = ["unstructured assertion"]
    reviews_path = tmp_path / "reviews.jsonl"
    write_jsonl(reviews_path, [review, review] if damage == "duplicate" else [review])
    with pytest.raises((InputError, ValueError)):
        prepare.import_provenance_review(audit, reviews_path, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()


@pytest.mark.parametrize("changed", ["claim", "provenance"])
def test_review_cannot_follow_changed_claim_or_provenance(parent_repo, tmp_path, changed):
    dataset = assemble_fixture(parent_repo, tmp_path)
    audit = prepare.audit_provenance(dataset, tmp_path / "audit-one")
    review = fixture_provenance_review(audit, tmp_path)
    path = provenance_path(dataset)
    path = path.parent / "claims.jsonl" if changed == "claim" else path
    rows = read_jsonl(path)
    if changed == "claim":
        rows[0]["scope"] += " Changed fixture scope."
    else:
        rows[0]["unresolved_reasons"].append("Additional fixture limitation")
    write_jsonl(path, rows)
    second = prepare.audit_provenance(dataset, tmp_path / "audit-two")
    reviews_path = tmp_path / "reviews.jsonl"
    write_jsonl(reviews_path, [review])
    with pytest.raises(InputError, match="digest mismatch"):
        prepare.import_provenance_review(second, reviews_path, tmp_path / "rejected")


def test_review_rejects_nested_output_and_tampered_audit(parent_repo, tmp_path):
    dataset = assemble_fixture(parent_repo, tmp_path)
    audit = prepare.audit_provenance(dataset, tmp_path / "audit")
    review = fixture_provenance_review(audit, tmp_path)
    reviews_path = tmp_path / "reviews.jsonl"
    write_jsonl(reviews_path, [review])
    with pytest.raises(InputError, match="inside source"):
        prepare.import_provenance_review(audit, reviews_path, audit.parent / "nested")
    assert not (audit.parent / "nested").exists()
    (audit.parent / "provenance_audit.jsonl").write_bytes(b"tampered\n")
    with pytest.raises(InputError, match="hash mismatch"):
        prepare.import_provenance_review(audit, reviews_path, tmp_path / "rejected")
