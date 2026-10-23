from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from cami.artifacts import file_hash, read_json, read_jsonl, write_json, write_jsonl
from cami.errors import InputError

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
