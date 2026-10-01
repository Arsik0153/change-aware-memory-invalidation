from __future__ import annotations

import shutil
from pathlib import Path
from typing import Literal

from cami.artifacts import digest, load, reserve, within, write_json, write_jsonl
from cami.dataset_models import DatasetManifest
from cami.errors import InputError
from cami.index import IndexConfig, build_index
from cami.inputs import check_inputs
from cami.models import Behavior, Dependency, GraphView, Node
from cami.repository import read_snapshot


def edge_integer(repo_id: str, edge: Dependency, seed: int) -> int:
    return int(digest({"repo_id": repo_id, "from": edge.source.model_dump(mode="json"),
                       "to": edge.target.model_dump(mode="json"), "relation": edge.relation,
                       "seed": seed}), 16)


def edge_fraction(repo_id: str, edge: Dependency, seed: int) -> float:
    return edge_integer(repo_id, edge, seed) / 2**256


def prepare_scenario(dataset_path: Path, mode: Literal["known_missing", "hidden_missing"],
                     drop: float, seed: int, output: Path) -> Path:
    if drop not in {0.0, 0.25, 0.5, 0.75}:
        raise InputError("protocol 1.0 drop must be 0, 0.25, 0.50 or 0.75")
    if seed not in {17, 42, 73}:
        raise InputError("protocol 1.0 seeds are 17, 42 and 73")
    dataset = load(dataset_path, DatasetManifest)
    base = dataset_path.resolve().parent
    inputs = [check_inputs(base / run.config_path) for run in dataset.runs]
    if any(i.config.graph_views_path is not None for i in inputs):
        raise InputError("scenarios must be generated from intact input")
    reserve(output)
    public, research = output / "public", output / "research"
    public.mkdir()
    research.mkdir()
    scenario_id = f"{mode}-drop{drop:g}-seed{seed}"
    configs = []
    total_edges: set[str] = set()
    removed_edges: set[str] = set()
    for entry, inp in zip(dataset.runs, inputs, strict=True):
        run_dir = public / "runs" / digest(entry.run_id)[:16]
        run_dir.mkdir(parents=True)
        config = inp.config
        revisions = (config.parent_commit, *config.child_commits)
        graph_dir = run_dir / "graphs"
        full_dir = research / digest(entry.run_id)[:16]
        graph_dir.mkdir()
        full_dir.mkdir()
        known_sources: set[Node] = set()
        for revision in revisions:
            index = build_index(read_snapshot(config.repo, revision), IndexConfig(config.repo.source_roots))
            edges = set(index.edges)
            for prov in inp.provenance:
                edges.update(prov.dependencies)
            ordered = tuple(sorted(edges, key=digest))
            removed = tuple(e for e in ordered if edge_integer(config.repo.repo_id, e, seed) < int(drop * 2**256))
            kept = tuple(e for e in ordered if e not in removed)
            if revision == config.parent_commit:
                known_sources.update(e.source for e in removed)
            write_json(full_dir / f"{revision}.json", GraphView(commit=revision, edges=ordered,
                unresolved=tuple(sorted(index.unresolved, key=digest)), global_unresolved=index.global_unresolved))
            write_json(full_dir / f"{revision}-removed.json", {"schema_version": 1, "edges": [e.model_dump(mode="json", by_alias=True) for e in removed]})
            write_json(graph_dir / f"{revision}.json", GraphView(commit=revision, edges=kept,
                unresolved=tuple(sorted(index.unresolved, key=digest)), global_unresolved=index.global_unresolved,
                known_incomplete_nodes=tuple(sorted({e.source for e in removed}, key=digest)) if mode == "known_missing" else ()))
            total_edges.update(digest({"repo": config.repo.repo_id, "edge": e.model_dump(mode="json", by_alias=True)}) for e in ordered)
            removed_edges.update(digest({"repo": config.repo.repo_id, "edge": e.model_dump(mode="json", by_alias=True)}) for e in removed)
        visible = []
        for prov in inp.provenance:
            removed = tuple(e for e in prov.dependencies if edge_integer(config.repo.repo_id, e, seed) < int(drop * 2**256))
            subject_nodes = {Node(path=a.path, qualname=a.qualname) for a in prov.anchors}
            affected = bool(removed) or bool(subject_nodes & known_sources)
            visible.append(prov.model_copy(update={"scenario_id": scenario_id,
                "dependencies": tuple(e for e in prov.dependencies if e not in removed),
                "known_incomplete": prov.known_incomplete or (mode == "known_missing" and affected)}))
        write_jsonl(full_dir / "provenance.jsonl", inp.provenance)
        write_jsonl(run_dir / "claims.jsonl", inp.claims)
        write_jsonl(run_dir / "provenance.jsonl", visible)
        write_jsonl(run_dir / "parent_receipts.jsonl", inp.receipts)
        for receipt in inp.receipts:
            target = within(run_dir, receipt.evidence_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(within(inp.base_dir, receipt.evidence_path), target)
        for claim in inp.claims:
            if isinstance(claim.predicate, Behavior):
                target = within(run_dir, claim.predicate.probe_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(within(inp.base_dir, claim.predicate.probe_path), target)
        masked = config.model_copy(update={"scenario_id": scenario_id, "claims_path": "claims.jsonl",
            "provenance_path": "provenance.jsonl", "parent_receipts_path": "parent_receipts.jsonl",
            "graph_views_path": "graphs", "cache_dir": None})
        write_json(run_dir / "run.json", masked)
        configs.append(entry.model_copy(update={"config_path": str((run_dir / "run.json").relative_to(public))}))
    public_dataset = dataset.model_copy(update={"dataset_id": dataset.dataset_id + "-" + scenario_id,
        "runs": tuple(configs), "repositories": tuple(r.model_copy(update={"path": str((base / r.path).resolve())}) for r in dataset.repositories), "labels_path": None, "raw_annotations_path": None})
    write_json(public / "dataset.json", public_dataset)
    write_json(research / "mask_report.json", {"schema_version": 1, "mode": mode, "drop_fraction": drop,
        "seed": seed, "unique_edges": len(total_edges), "removed_edges": len(removed_edges),
        "actual_removed_fraction": len(removed_edges) / len(total_edges) if total_edges else None,
        "reason": None if total_edges else "no_dependencies"})
    return public / "dataset.json"
