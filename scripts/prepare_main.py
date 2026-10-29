"""Prepare fixed real cohorts and blank review packets without running policies.

Selection uses Git history metadata. Candidate generation receives only parent inputs.
AST signature normalization is shared with CAMI and is NOT an independent oracle.
"""
from __future__ import annotations

import argparse
import ast
import math
import random
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cami.artifacts import (
    canonical, digest, file_hash, load, load_jsonl, read_json, read_jsonl, reserve,
    within, write_bytes, write_json, write_jsonl,
)
from cami.dataset import AnnotationImport, AnnotationItem, RawAnnotation, annotate_export, resolve_annotations
from cami.dataset_models import DatasetManifest, DatasetRepository, DatasetRun
from cami.errors import InputError
from cami.index import signature
from cami.models import Behavior, Claim, ParentReceipt, Provenance, RepoLocation, RunConfig
from cami.pilot import parent_candidates
from cami.provenance_audit import audit_provenance, import_provenance_review
from cami.repository import git, read_snapshot, resolve
from cami.structural_closure import prepare_structural_closure

SEED = 20261001
START_DATE = "2018-01-01T00:00:00Z"
PROTOCOL = "1.1"
ENRICHED = re.compile(r"\b(?:fix(?:es|ed)?|bug|api|refactor(?:ing)?|deprecat\w*|signature)\b", re.I)
REPOS = {
    "click": {"url": "https://github.com/pallets/click.git", "end_ref": "8.1.8",
              "roots": ("src", "click"), "split": "development", "replays": 0},
    "requests": {"url": "https://github.com/psf/requests.git", "end_ref": "v2.32.3",
                 "roots": ("src", "requests"), "split": "heldout", "replays": 2},
    "pytest": {"url": "https://github.com/pytest-dev/pytest.git", "end_ref": "8.3.5",
               "roots": ("src",), "split": "heldout", "replays": 1},
}
PROBES = {
    "click": ("click/utils.py", "make_default_short_help",
              "from click.utils import make_default_short_help\n\n"
              "def test_frozen_case():\n"
              "    assert make_default_short_help('One sentence. More text.', max_length=45) == 'One sentence.'\n",
              "make_default_short_help('One sentence. More text.', max_length=45) returns 'One sentence.'."),
    "requests": ("requests/utils.py", "unquote_unreserved",
                 "from requests.utils import unquote_unreserved\n\n"
                 "def test_frozen_case():\n"
                 "    assert unquote_unreserved('%7euser%2F') == '~user%2F'\n",
                 "unquote_unreserved('%7euser%2F') returns '~user%2F'."),
    "pytest": ("_pytest/compat.py", "safe_getattr",
               "from _pytest.compat import safe_getattr\n\n"
               "def test_frozen_case():\n"
               "    assert safe_getattr(object(), 'missing', 'fallback') == 'fallback'\n",
               "safe_getattr(object(), 'missing', 'fallback') returns 'fallback'."),
}


@dataclass(frozen=True)
class Transition:
    parent: str
    child: str
    message: str


def history(repo: Path, end: str, window: int) -> list[Transition | None]:
    rows = git(repo, "log", "--first-parent", f"--max-count={window}", f"--since={START_DATE}",
               "--format=%H%x09%P%x09%s", end).decode().splitlines()
    result = []
    for row in reversed(rows):
        child, parents, message = row.split("\t", 2)
        parent_ids = parents.split()
        result.append(Transition(parent_ids[0], child, message) if len(parent_ids) == 1 else None)
    return result


def episode_map(rows: list[Transition | None]) -> dict[str, str]:
    """Conservative episode clusters are maximal uninterrupted nonmerge chains."""
    result = {}
    previous = None
    episode = None
    for edge in rows:
        if edge is None:
            previous = None
            continue
        if previous is None or previous.child != edge.parent:
            episode = edge.parent
        result[edge.child] = episode
        previous = edge
    return result


def select_history(rows: list[Transition | None], excluded: set[str], replay_count: int,
                   seed: int) -> tuple[list[tuple[str, Transition]], list[list[Transition]]]:
    """Reserve disjoint replay histories, then fixed metadata strata without replacement."""
    rng = random.Random(seed)
    occupied = set(excluded)
    episodes = episode_map(rows)
    used_replay_episodes = set()
    blocks: list[list[Transition]] = []
    starts = list(range(max(0, len(rows) - 9))) if replay_count else []
    rng.shuffle(starts)
    for start in starts:
        block = rows[start:start + 10]
        if len(block) != 10 or any(edge is None for edge in block):
            continue
        edges = [edge for edge in block if edge is not None]
        if any(a.child != b.parent for a, b in zip(edges, edges[1:])):
            continue
        revisions = {edges[0].parent, *(edge.child for edge in edges)}
        episode = episodes[edges[0].child]
        if revisions & occupied or episode in used_replay_episodes:
            continue
        blocks.append(edges)
        used_replay_episodes.add(episode)
        # Reserve the complete known episode, so replay blocks and main pairs do not
        # share an episode and two replay samples cannot inflate cluster independence.
        for edge in rows:
            if edge is not None and episodes[edge.child] == episode:
                occupied.update((edge.parent, edge.child))
        if len(blocks) == replay_count:
            break
    if replay_count == 0:
        blocks = []
        occupied = set(excluded)
    elif len(blocks) != replay_count:
        raise InputError(f"need {replay_count} disjoint ten-transition replay blocks")
    eligible = [edge for edge in rows if edge is not None
                and not {edge.parent, edge.child} & occupied]
    enriched = [edge for edge in eligible if ENRICHED.search(edge.message)]
    rng.shuffle(enriched)
    selected: list[tuple[str, Transition]] = []
    for edge in enriched:
        if {edge.parent, edge.child} & occupied:
            continue
        selected.append(("enriched", edge))
        occupied.update((edge.parent, edge.child))
        if len(selected) == 10:
            break
    if len(selected) != 10:
        raise InputError("need ten metadata-enriched disjoint pairs")
    # Select nearest available edge at each chronological grid point. No outcome is inspected.
    available = [edge for edge in eligible if not {edge.parent, edge.child} & occupied]
    for target in [round(i * (len(available) - 1) / 9) for i in range(10)]:
        choices = sorted(enumerate(available), key=lambda row: (abs(row[0] - target), row[0]))
        edge = next((edge for _, edge in choices if not {edge.parent, edge.child} & occupied), None)
        if edge is None:
            raise InputError("need ten chronological disjoint pairs")
        selected.append(("chronological", edge))
        occupied.update((edge.parent, edge.child))
    return selected, blocks


def select(corpora: Path, output: Path, pilot_recipe: Path, window: int = 2000,
           seed: int = SEED) -> Path:
    pilot = read_json(pilot_recipe)
    if pilot.get("dataset_kind") != "real" or len(pilot.get("pairs", [])) != 12:
        raise InputError("require the original twelve-transition real Click pilot recipe")
    excluded = {revision for pair in pilot["pairs"]
                for revision in (pair["parent_commit"], *pair["child_commits"])}
    repositories, groups, parents = [], [], []
    for repo_index, (repo_id, spec) in enumerate(REPOS.items()):
        repo = (corpora / repo_id).resolve()
        remote = git(repo, "remote", "get-url", "origin").decode().strip().removesuffix(".git")
        if remote != str(spec["url"]).removesuffix(".git"):
            raise InputError(f"unexpected origin for {repo_id}: {remote}")
        end = resolve(repo, str(spec["end_ref"]))
        rows = history(repo, end, window)
        episodes = episode_map(rows)
        pairs, sequences = select_history(rows,
            excluded if repo_id == "click" else set(), int(spec["replays"]), seed + repo_index)
        repositories.append({"repo_id": repo_id, "path": str(repo), "url": spec["url"],
            "source_roots": spec["roots"], "end_ref": spec["end_ref"], "end_commit": end,
            "split": spec["split"]})
        for index, (stratum, edge) in enumerate(sorted(pairs, key=lambda row: (row[0], row[1].child))):
            group_id = f"{repo_id}-{digest({'parent': edge.parent})[:12]}"
            groups.append({"group_id": group_id, "repo_id": repo_id, "parent_commit": edge.parent,
                "child_commits": [edge.child], "stratum": stratum, "split": spec["split"],
                "cluster_id": f"{repo_id}-episode-{digest(episodes[edge.child])[:12]}", "sequence_id": None,
                "selection_metadata": {"subject": edge.message,
                    "enrichment_match": ENRICHED.search(edge.message).group(0) if stratum == "enriched" else None}})
        for index, edges in enumerate(sequences):
            group_id = f"{repo_id}-{digest({'parent': edges[0].parent})[:12]}"
            groups.append({"group_id": group_id, "repo_id": repo_id, "parent_commit": edges[0].parent,
                "child_commits": [edge.child for edge in edges], "stratum": "replay",
                "split": spec["split"],
                "cluster_id": f"{repo_id}-episode-{digest(episodes[edges[0].child])[:12]}", "sequence_id": group_id,
                "selection_metadata": {"subjects": [edge.message for edge in edges]}})
        for group in [group for group in groups if group["repo_id"] == repo_id]:
            # Deliberately omit children, strata, messages, changed paths, and changed symbols.
            parents.append({"schema_version": 1, "group_id": group["group_id"], "repo_id": repo_id,
                "repo_path": str(repo), "source_roots": spec["roots"],
                "parent_commit": group["parent_commit"], "seed": seed})
    reserve(output)
    write_json(output / "selection.json", {"schema_version": 1, "protocol_version": PROTOCOL,
        "seed": seed, "history_window": window, "history_start_date": START_DATE,
        "repositories": repositories, "groups": groups,
        "pilot_recipe_sha256": file_hash(pilot_recipe), "excluded_click_pilot_revisions": sorted(excluded),
        "enriched_rule": ENRICHED.pattern, "selection_basis": "first-parent metadata only; merge transitions excluded",
        "main_pair_count": 60, "replay_sequence_count": 3, "status": "selection_only"})
    write_jsonl(output / "parent_inputs.jsonl", parents)
    write_json(output / "recipe.json", {"schema_version": 1, "protocol_version": PROTOCOL,
        "script_sha256": file_hash(Path(__file__)), "seed": seed, "window": window,
        "start_date": START_DATE, "corpora_path": str(corpora.resolve()),
        "pilot_recipe_path": str(pilot_recipe.resolve()), "pilot_recipe_sha256": file_hash(pilot_recipe),
        "end_refs": {repo_id: spec["end_ref"] for repo_id, spec in REPOS.items()},
        "claims_per_group": {"symbol_exists": 4, "signature_equals": 4, "behavior_test": 1, "prose": 1},
        "replay_allocation": {repo_id: spec["replays"] for repo_id, spec in REPOS.items()},
        "selection_rules": ["metadata-only subjects for enrichment", "all revisions disjoint",
                            "complete replay episodes reserved before main pairs",
                            "clusters are maximal nonmerge first-parent episodes",
                            "original Click pilot revisions excluded"],
        "final_cohort_frozen": False})
    write_json(output / "hashes.json", {name: file_hash(output / name)
        for name in ("selection.json", "parent_inputs.jsonl", "recipe.json")})
    return output / "selection.json"


def generate_parent(spec: dict[str, Any], output: Path) -> None:
    allowed = {"schema_version", "group_id", "repo_id", "repo_path", "source_roots", "parent_commit", "seed"}
    if set(spec) != allowed:
        raise InputError("parent generator input contains unexpected fields or future information")
    repo = RepoLocation(repo_id=spec["repo_id"], path=spec["repo_path"],
                        source_roots=tuple(spec["source_roots"]))
    snapshot = read_snapshot(repo, spec["parent_commit"])
    candidates, parent_functions = [], []
    for blob in snapshot.blobs:
        if not blob.path.endswith(".py") or blob.content is None:
            continue
        if not any(blob.path.startswith(root + "/") for root in repo.source_roots):
            continue
        try:
            source = blob.content.decode("utf-8")
            tree = ast.parse(source)
            names = {name for name, _ in parent_candidates(source)}
        except (SyntaxError, UnicodeError, IndentationError):
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                parent_functions.append((blob, node, source))
                if node.name in names:
                    candidates.append((blob, node, source))
    candidates.sort(key=lambda row: (row[0].path, row[1].name))
    if len(candidates) < 8:
        raise InputError(f"fewer than eight parent function candidates for {spec['group_id']}")
    rng = random.Random(int(digest({"parent": spec["parent_commit"], "seed": spec["seed"]})[:16], 16))
    selected = rng.sample(candidates, 8)
    claims, provenance = [], []
    output.mkdir(parents=True, exist_ok=False)
    sources = {}

    def append(kind: str, candidate: Any, text: str, predicate: dict[str, Any], scope: str) -> None:
        blob, node, source = candidate
        claim_id = f"{spec['group_id']}-{len(claims):02d}"
        claim = Claim.model_validate_json(canonical({"schema_version": 1, "claim_id": claim_id,
            "repo_id": repo.repo_id, "origin_commit": snapshot.revision, "kind": kind, "text": text,
            "subject": {"path": blob.path, "qualname": node.name, "node_kind": "function"},
            "predicate": predicate, "scope": scope}))
        claims.append(claim)
        provenance.append(Provenance.model_validate_json(canonical({"claim_id": claim_id,
            "scenario_id": "intact", "anchors": [{"path": blob.path, "qualname": node.name, "scope": "symbol",
                "observed_commit": snapshot.revision, "content_hash": blob.content_hash,
                "origin": "static", "start_line": node.lineno, "end_line": node.end_lineno}],
            "dependencies": [], "known_incomplete": True,
            "unresolved_reasons": ["Draft parent-only anchors; dependency extraction and review pending."]})))
        sources[blob.path] = source

    for index, candidate in enumerate(selected):
        blob, node, _ = candidate
        if index < 4:
            append("symbol_exists", candidate,
                f"{blob.path} contains the exact top-level function definition {node.name}.",
                {"type": "symbol_exists", "expected": True}, "Exact syntactic definition identity only.")
        else:
            expected = signature(node).model_dump(mode="json")
            append("signature_equals", candidate,
                f"The exact definition {blob.path}:{node.name} has normalized signature {canonical(expected).decode()}.",
                {"type": "signature_equals", "expected_signature": expected},
                "Exact normalized syntax, including defaults, annotations, decorators, and async status.")
    suffix, name, probe_source, behavior_text = PROBES[repo.repo_id]
    targets = [candidate for candidate in parent_functions if candidate[1].name == name
               and (candidate[0].path == suffix or candidate[0].path == "src/" + suffix)]
    if len(targets) != 1:
        raise InputError(f"fixed behavior subject absent at parent {snapshot.revision}; selection is not repaired using outcomes")
    target = targets[0]
    probe = output / "probes/test_frozen_probe.py"
    write_bytes(probe, probe_source.encode())
    append("behavior_test", target, behavior_text,
        {"type": "behavior_test", "probe_path": "probes/test_frozen_probe.py",
         "probe_sha256": file_hash(probe), "node_id": "test_frozen_probe.py::test_frozen_case",
         "environment_id": f"{repo.repo_id}-parent-review-pending"},
        "Only the single frozen input and expected output in the hashed probe. "
        "Untested candidate; independent parent test and pinned Docker environment are required.")
    documented = [candidate for candidate in candidates if ast.get_docstring(candidate[1])]
    if not documented:
        raise InputError("parent has no documented function for bounded prose candidate")
    target = rng.choice(documented)
    line = next(line.strip() for line in ast.get_docstring(target[1]).splitlines() if line.strip())
    append("prose", target,
        f"The docstring of the exact function {target[0].path}:{target[1].name} states: {line}",
        {"type": "prose"}, "First nonempty docstring line only; no inference about runtime behavior. "
        "Requires human review; excluded from offline evaluation.")
    write_jsonl(output / "claims.jsonl", claims)
    write_jsonl(output / "provenance.jsonl", provenance)
    write_jsonl(output / "parent_receipts.jsonl", [])
    for path, source in sources.items():
        write_bytes(output / "parent_sources" / path, source.encode())
    write_json(output / "draft.json", {"schema_version": 1, "parent_input": spec,
        "parent_input_sha256": digest(spec), "claims_sha256": file_hash(output / "claims.jsonl"),
        "kind_counts": dict(Counter(claim.kind for claim in claims)), "status": "parent_confirmation_pending",
        "admitted_claim_ids": [], "normalization": "shared cami.index.signature; candidate construction only",
        "behavior_probe_executed": False, "prose_offline_excluded": True})


def generate(parent_inputs: Path, output: Path) -> None:
    specs = read_jsonl(parent_inputs)
    ids = [row["group_id"] for row in specs]
    if len(ids) != len(set(ids)):
        raise InputError("duplicate parent group")
    reserve(output)
    for spec in specs:
        within(output, spec["group_id"])
        generate_parent(spec, output / spec["group_id"])
    write_json(output / "generation.json", {"schema_version": 1,
        "parent_inputs_sha256": file_hash(parent_inputs), "group_count": len(specs),
        "script_sha256": file_hash(Path(__file__)), "status": "draft_only", "parent_receipts": 0})


def assemble(selection_path: Path, candidates: Path, output: Path) -> Path:
    selection = read_json(selection_path)
    if selection["protocol_version"] != PROTOCOL:
        raise InputError("selection protocol version differs from current preparation recipe")
    runs = []
    # Validate the relationship before making the immutable output.
    for group in selection["groups"]:
        candidate_dir = within(candidates, group["group_id"])
        draft = read_json(candidate_dir / "draft.json")
        if (draft["parent_input"]["repo_id"] != group["repo_id"]
                or draft["parent_input"]["parent_commit"] != group["parent_commit"]
                or draft["claims_sha256"] != file_hash(candidates / group["group_id"] / "claims.jsonl")):
            raise InputError("selection/candidate parent or hash mismatch")
    reserve(output)
    write_json(output / "selection.json", selection)
    for group in selection["groups"]:
        group_dir = output / "groups" / group["group_id"]
        shutil.copytree(candidates / group["group_id"], group_dir)
        repo_spec = next(repo for repo in selection["repositories"] if repo["repo_id"] == group["repo_id"])
        config = RunConfig.model_validate_json(canonical({"schema_version": 1, "protocol_version": PROTOCOL,
            "repo": {"repo_id": group["repo_id"], "path": repo_spec["path"],
                     "source_roots": repo_spec["source_roots"]}, "parent_commit": group["parent_commit"],
            "child_commits": group["child_commits"], "claims_path": "claims.jsonl",
            "provenance_path": "provenance.jsonl", "parent_receipts_path": "parent_receipts.jsonl",
            "dataset_kind": "real", "split": group["split"], "stratum": group["stratum"],
            "policy": {"id": "symbol_validate", "dependency_depth": 1},
            "validation": {"execution": "disabled", "llm": "disabled"}, "preview": True,
            "allow_network": False, "max_calls": 0, "seed": selection["seed"]}))
        write_json(group_dir / "run.json", config)
        runs.append(DatasetRun(run_id=group["group_id"], config_path=f"groups/{group['group_id']}/run.json",
            split=group["split"], cluster_id=group["cluster_id"], sequence_id=group["sequence_id"]))
    manifest = DatasetManifest(dataset_id="main-preparation-20261001", protocol_version=PROTOCOL,
        dataset_kind="real", repositories=tuple(DatasetRepository(repo_id=repo["repo_id"],
            url=repo["url"], path=repo["path"], source_roots=tuple(repo["source_roots"]),
            environment_restoration="Pending pinned offline Docker profiles and independent finite-probe parent review.")
            for repo in selection["repositories"]), runs=tuple(runs), notes=(
            "Draft cohort, no admission, labels, parent receipts, policy execution, or frozen final protocol.",
            "All ten candidates are immutable drafts until independent parent confirmation.",
            "Prose is reserved for human review and excluded from offline evaluation.",
            "Behavior candidates are unexecuted; pinned Docker environment and independent parent test remain pending.",
            "Shared production AST signature normalization is candidate generation, not a truth oracle.",
            "Selection uses commit subjects only; metadata-enriched does not guarantee API changes or stale claims.",
            "Pairs and replay histories have disjoint revisions; maximal nonmerge episodes define clusters.",
            "Draft provenance records known missing dependencies; complete graph/provenance review is pending."))
    write_json(output / "dataset.json", manifest)
    annotate_export(output / "dataset.json", output / "annotation")
    packets = read_jsonl(output / "annotation/packets.jsonl")
    primary, secondary, parent_forms, population = [], [], [], []
    child_forms, main_population, replay_population = [], [], []
    rng = random.Random(selection["seed"])
    second_claims = set()
    for packet_group in selection["groups"]:
        ids = sorted(packet["claim"]["claim_id"] for packet in packets
                     if packet["run_id"] == packet_group["group_id"])
        second_claims.update(rng.sample(ids, math.ceil(len(ids) * 0.2)))
    main_items = replay_items = main_second = replay_second = 0
    replay_groups = {group["group_id"] for group in selection["groups"] if group["stratum"] == "replay"}
    for packet in packets:
        claim_id = packet["claim"]["claim_id"]
        for commit in (packet["parent_commit"], *packet["child_commits"]):
            form = {"schema_version": 1, "claim_id": claim_id, "commit": commit,
                "annotation_id": None, "annotator_id": None, "annotator_kind": None,
                "independent": None, "label": None, "evidence": [],
                "confirmation_type": None, "annotation_minutes": None}
            primary.append(form)
            if packet["run_id"] in replay_groups:
                replay_items += 1
            else:
                main_items += 1
            if commit != packet["parent_commit"]:
                item = {"schema_version": 1, "claim_id": claim_id, "commit": commit}
                population.append(item)
                child_forms.append(form)
                (replay_population if packet["run_id"] in replay_groups else main_population).append(item)
            if claim_id in second_claims:
                secondary.append(dict(form))
                if packet["run_id"] in replay_groups:
                    replay_second += 1
                else:
                    main_second += 1
            if commit == packet["parent_commit"]:
                parent_forms.append(dict(form))
    write_jsonl(output / "annotation/primary_form.jsonl", primary)
    write_jsonl(output / "annotation/second_form.jsonl", secondary)
    write_jsonl(output / "annotation/parent_confirmation_form.jsonl", parent_forms)
    write_jsonl(output / "annotation/population.jsonl", population)
    write_jsonl(output / "annotation/child_form.jsonl", child_forms)
    write_jsonl(output / "annotation/main_population.jsonl", main_population)
    write_jsonl(output / "annotation/replay_population.jsonl", replay_population)
    write_json(output / "annotation/assignments.json", {"schema_version": 1, "seed": selection["seed"],
        "assignment_unit": "claim, with every selected parent/child revision assigned to second review",
        "second_claim_ids": sorted(second_claims), "primary_items": len(primary),
        "second_items": len(secondary), "second_fraction": len(secondary) / len(primary),
        "main_items": main_items, "main_second_items": main_second,
        "main_second_fraction": main_second / main_items if main_items else None,
        "replay_items": replay_items, "replay_second_items": replay_second,
        "replay_second_fraction": replay_second / replay_items if replay_items else None,
        "second_assignment_requires": "two distinct independent humans on assigned items",
        "reviewer_identities": None, "status": "reviewers_and_annotations_pending"})
    main_groups = sum(group["stratum"] != "replay" for group in selection["groups"])
    replay_count = len(selection["groups"]) - main_groups
    write_json(output / "preparation_status.json", {"schema_version": 1, "status": "draft_parent_review_pending",
        "main_pairs": main_groups, "main_candidate_claims": main_groups * 10, "replay_sequences": replay_count,
        "replay_initial_claims": replay_count * 10, "replay_transitions_per_sequence": 10,
        "admitted_claims": 0, "parent_receipts": 0, "labels": 0,
        "offline_excluded_kinds": ["prose", "behavior_test"],
        "behavior_exclusion_reason": "Parent test and Docker profiles pending; eligible only after those checks.",
        "heldout_policy_execution": False, "final_protocol_frozen": False})
    write_json(output / "preparation_hashes.json", {name: file_hash(output / name)
        for name in ("dataset.json", "selection.json", "annotation/packets.jsonl",
                     "annotation/primary_form.jsonl", "annotation/second_form.jsonl",
                     "annotation/parent_confirmation_form.jsonl", "annotation/assignments.json")})
    return output / "dataset.json"


def import_parent(dataset_path: Path, annotations_path: Path, output: Path) -> Path:
    """Import one external decision per parent claim; use batch import for multiple answers."""
    annotations = load_jsonl(annotations_path, RawAnnotation, "annotation_id")
    if not annotations:
        raise InputError("parent import requires actual completed independent reviews")
    if len({row.claim_id for row in annotations}) != len(annotations):
        raise InputError("duplicate parent annotation; use import-parent-batch to retain multiple answers")
    return _import_parent(dataset_path, AnnotationImport(annotations=annotations),
                          annotations_path, output)


def import_parent_batch(dataset_path: Path, reviews_path: Path, output: Path) -> Path:
    """Retain original answers and adjudication chains without granting cohort admission."""
    return _import_parent(dataset_path, load(reviews_path, AnnotationImport), reviews_path, output)


def _import_parent(dataset_path: Path, data: AnnotationImport, source: Path, output: Path) -> Path:
    manifest = load(dataset_path, DatasetManifest)
    base = dataset_path.resolve().parent
    if (base / "parent_raw_annotations.jsonl").exists():
        raise InputError("parent import requires original unreviewed dataset; retain all answers in one batch")
    claims_by_id = {}
    for entry in manifest.runs:
        config_path = within(base, entry.config_path)
        config = load(config_path, RunConfig)
        if not config.preview:
            raise InputError("parent review import requires preview preparation")
        if load_jsonl(config_path.parent / config.parent_receipts_path, ParentReceipt):
            raise InputError("import requires original empty receipts; combine reviews explicitly before importing")
        for claim in load_jsonl(config_path.parent / config.claims_path, Claim, "claim_id"):
            if claim.origin_commit != config.parent_commit:
                raise InputError("parent claim origin differs from prepared run parent")
            if claim.claim_id in claims_by_id:
                raise InputError("duplicate cohort claim")
            claims_by_id[claim.claim_id] = (claim, config_path.parent.relative_to(base), config)
    expected = {(claim.claim_id, claim.origin_commit) for claim, _, _ in claims_by_id.values()}
    preparation_hashes = read_json(base / "preparation_hashes.json")
    packets_path = base / "annotation/packets.jsonl"
    if file_hash(packets_path) != preparation_hashes["annotation/packets.jsonl"]:
        raise InputError("prepared review packet hash mismatch")
    packets = read_jsonl(packets_path)
    if (len(packets) != len(expected)
            or {(row["claim"]["claim_id"], row["parent_commit"]) for row in packets} != expected):
        raise InputError("prepared review packet differs from candidate population")
    for packet in packets:
        claim, relative, _ = claims_by_id[packet["claim"]["claim_id"]]
        if digest(claim) != packet["claim_sha256"] or digest(packet["claim"]) != digest(claim):
            raise InputError("parent claim differs from frozen review packet")
        for record in packet["source_evidence"][claim.origin_commit]:
            if record["commit"] != claim.origin_commit:
                raise InputError("parent source evidence names a different revision")
            if record["evidence_path"] is not None:
                evidence = within(base / "annotation", record["evidence_path"])
                if file_hash(evidence) != record["sha256"]:
                    raise InputError("parent source evidence differs from frozen review packet")
        if isinstance(claim.predicate, Behavior):
            probe = within(base / relative, claim.predicate.probe_path)
            exported_probe = within(base / "annotation", packet["probe"]["path"])
            if (file_hash(probe) != packet["probe"]["sha256"]
                    or file_hash(exported_probe) != packet["probe"]["sha256"]):
                raise InputError("parent probe differs from frozen review packet")
    if data.annotation_population is not None:
        supplied = {(row.claim_id, row.commit) for row in data.annotation_population}
        if supplied != expected or len(supplied) != len(data.annotation_population):
            raise InputError("parent annotation population must equal the complete candidate population")
    data = AnnotationImport(annotations=data.annotations, adjudications=data.adjudications,
        annotation_population=tuple(AnnotationItem(claim_id=claim, commit=commit)
                                    for claim, commit in sorted(expected)))
    for decision in (*data.annotations, *data.adjudications):
        if decision.claim_id not in claims_by_id:
            raise InputError("unknown parent annotation")
        claim, _, _ = claims_by_id[decision.claim_id]
        if decision.commit != claim.origin_commit:
            raise InputError("parent import rejects child decisions")
        if decision.confirmation_type == "synthetic_manual":
            raise InputError("real cohort rejects synthetic confirmation")
        if claim.kind == "prose" and decision.confirmation_type != "human_review":
            raise InputError("prose parent confirmation requires human review")
        if (claim.kind == "behavior_test" and decision.label == "supported"
                and decision.confirmation_type != "independent_test"):
            raise InputError("behavior parent confirmation requires independent frozen-probe testing")
    resolution = resolve_annotations(data)
    second_form = base / "annotation/second_form.jsonl"
    if file_hash(second_form) != preparation_hashes["annotation/second_form.jsonl"]:
        raise InputError("prepared second-review assignments hash mismatch")
    assigned = {(row["claim_id"], row["commit"]) for row in read_jsonl(second_form)} & expected
    human_authors: dict[tuple[str, str], set[str]] = {}
    for row in data.annotations:
        if row.annotator_kind == "human":
            human_authors.setdefault((row.claim_id, row.commit), set()).add(row.annotator_id)
    missing_second = sorted(key for key in assigned if len(human_authors.get(key, set())) < 2)
    if output.resolve().is_relative_to(base):
        raise InputError("parent import output must not be inside source dataset")
    reserve(output)
    shutil.copytree(base, output, dirs_exist_ok=True)
    shutil.copyfile(source, output / "parent_review_original_input.txt")
    receipts_by_path: dict[Path, list[ParentReceipt]] = {}
    for label in resolution.labels:
        claim, relative, config = claims_by_id[label.claim_id]
        originals = [row for row in data.annotations if row.claim_id == label.claim_id]
        history = [row for row in data.adjudications if row.claim_id == label.claim_id]
        target = output / relative
        evidence_path = f"parent_review/{digest(claim.claim_id)}.json"
        evidence = {"schema_version": 1, "claim_sha256": digest(claim),
                    "annotations": [row.model_dump(mode="json") for row in originals],
                    "adjudications": [row.model_dump(mode="json") for row in history],
                    "resolution": label.model_dump(mode="json"),
                    "source": "external_independent_review"}
        write_json(target / evidence_path, evidence)
        if label.label == "supported":
            receipts_by_path.setdefault(within(target, config.parent_receipts_path), []).append(ParentReceipt(claim_id=claim.claim_id,
                origin_commit=claim.origin_commit, status="supported",
                confirmation_type=label.confirmation_type, evidence_path=evidence_path,
                evidence_sha256=file_hash(target / evidence_path),
                annotation_minutes=sum(row.annotation_minutes for row in [*originals, *history])))
    for receipts_path, receipts in receipts_by_path.items():
        write_jsonl(receipts_path, receipts)
    write_jsonl(output / "parent_raw_annotations.jsonl", data.annotations)
    write_jsonl(output / "parent_adjudications.jsonl", data.adjudications)
    write_jsonl(output / "parent_resolved_decisions.jsonl", resolution.labels)
    status = read_json(output / "preparation_status.json")
    status.update({"status": "parent_decisions_imported_preview_preserved",
                   "parent_receipts": sum(map(len, receipts_by_path.values())), "admitted_claims": 0})
    write_json(output / "preparation_status.json", status)
    write_json(output / "parent_review_status.json", {"schema_version": 1,
        "reviewed": len(data.annotations), "reviewed_claims": len({r.claim_id for r in data.annotations}),
        "supported_receipts": sum(map(len, receipts_by_path.values())),
        "unreviewed_claims": len(claims_by_id) - len({r.claim_id for r in data.annotations}),
        "unresolved": resolution.unresolved, "agreement": resolution.agreement,
        "assigned_second_review": {"assigned_parent_items": len(assigned),
            "completed_parent_items": len(assigned) - len(missing_second),
            "missing": [{"claim_id": claim, "commit": commit} for claim, commit in missing_second],
            "requirement_met": bool(assigned) and not missing_second,
            "assignments_sha256": file_hash(second_form)},
        "annotation_minutes": sum(row.annotation_minutes for row in data.annotations),
        "adjudication_minutes": sum(row.annotation_minutes for row in data.adjudications),
        "source_annotations_sha256": file_hash(source), "evaluation_eligible": False,
        "prepared_packet_sha256": file_hash(packets_path),
        "artifact_hashes": {name: file_hash(output / name) for name in (
            "parent_review_original_input.txt", "parent_raw_annotations.jsonl",
            "parent_adjudications.jsonl", "parent_resolved_decisions.jsonl")},
        "status": "parent_decisions_imported_preview_preserved", "final_protocol_frozen": False,
        "limitations": ["Authorship and independence are declared, not verified by software.",
                        "Review coverage does not admit a cohort or authorize heldout execution."],
        "remaining": ["final cohort admission decisions", "provenance review", "Docker profile restoration",
                      "independent child annotations", "protocol freeze before any heldout execution"]})
    return output / "dataset.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    selection = commands.add_parser("select")
    selection.add_argument("--corpora", type=Path, required=True)
    selection.add_argument("--pilot-recipe", type=Path, required=True)
    selection.add_argument("--window", type=int, default=2000)
    selection.add_argument("--seed", type=int, default=SEED)
    selection.add_argument("--out", type=Path, required=True)
    generation = commands.add_parser("generate")
    generation.add_argument("--parents", type=Path, required=True)
    generation.add_argument("--out", type=Path, required=True)
    assembly = commands.add_parser("assemble")
    assembly.add_argument("--selection", type=Path, required=True)
    assembly.add_argument("--candidates", type=Path, required=True)
    assembly.add_argument("--out", type=Path, required=True)
    importer = commands.add_parser("import-parent")
    importer.add_argument("--dataset", type=Path, required=True)
    importer.add_argument("--annotations", type=Path, required=True)
    importer.add_argument("--out", type=Path, required=True)
    batch = commands.add_parser("import-parent-batch")
    batch.add_argument("--dataset", type=Path, required=True)
    batch.add_argument("--reviews", type=Path, required=True)
    batch.add_argument("--out", type=Path, required=True)
    audit = commands.add_parser("audit-provenance")
    audit.add_argument("--dataset", type=Path, required=True)
    audit.add_argument("--out", type=Path, required=True)
    review_import = commands.add_parser("import-provenance-review")
    review_import.add_argument("--audit", type=Path, required=True)
    review_import.add_argument("--reviews", type=Path, required=True)
    review_import.add_argument("--out", type=Path, required=True)
    closure = commands.add_parser("close-structural-provenance")
    closure.add_argument("--parents", type=Path, required=True)
    closure.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "select":
            result = select(args.corpora, args.out, args.pilot_recipe, args.window, args.seed)
        elif args.command == "generate":
            generate(args.parents, args.out)
            result = args.out / "generation.json"
        elif args.command == "assemble":
            result = assemble(args.selection, args.candidates, args.out)
        elif args.command == "import-parent":
            result = import_parent(args.dataset, args.annotations, args.out)
        elif args.command == "import-parent-batch":
            result = import_parent_batch(args.dataset, args.reviews, args.out)
        elif args.command == "audit-provenance":
            result = audit_provenance(args.dataset, args.out)
        elif args.command == "close-structural-provenance":
            result = prepare_structural_closure(args.parents, args.out)
        else:
            result = import_provenance_review(args.audit, args.reviews, args.out)
    except (InputError, ValueError) as exc:
        parser.exit(2, f"preparation error: {exc}\n")
    print(result.resolve())


if __name__ == "__main__":
    main()
