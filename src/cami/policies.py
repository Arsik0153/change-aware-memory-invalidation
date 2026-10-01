from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from cami.index import ChangeSet, impacted
from cami.models import Claim, MemoryState, Node, PolicyConfig, Provenance, Selection, ValidationResult


@dataclass(frozen=True)
class SelectionContext:
    commit: str
    claims: tuple[Claim, ...]
    provenance: tuple[Provenance, ...]
    previous: tuple[MemoryState, ...]
    changes: ChangeSet
    extra_environment_paths: tuple[str, ...] = ()


def environment_changed(paths: frozenset[str], extra: tuple[str, ...]) -> bool:
    names = {"pyproject.toml", "setup.py", "setup.cfg", "tox.ini", "pytest.ini", "conftest.py", "Dockerfile", "Pipfile", "Pipfile.lock", "poetry.lock", "uv.lock", "pdm.lock"}
    return any(path in extra or PurePosixPath(path).name in names
               or PurePosixPath(path).name.startswith("requirements")
               or path.endswith(".lock") for path in paths)


def select_claims(context: SelectionContext, policy: PolicyConfig) -> tuple[Selection, ...]:
    prov = {p.claim_id: p for p in context.provenance}
    previous = {s.claim_id: s for s in context.previous}
    checking = policy.id.endswith("_validate")
    symbol = policy.id.startswith("symbol_")
    affected = impacted(context.changes, policy.dependency_depth) if symbol else frozenset()
    selections: list[Selection] = []
    for claim in context.claims:
        reasons: list[str] = []
        p = prov[claim.claim_id]
        if policy.id == "all_validate":
            reasons.append("all_claims")
        elif policy.id not in {"keep_all", "clear_all"}:
            nodes = {Node(path=a.path, qualname=a.qualname) for a in p.anchors}
            nodes.add(Node(path=claim.subject.path, qualname=claim.subject.qualname))
            nodes.update(d.target for d in p.dependencies)
            frontier = set(nodes)
            while frontier:
                dependencies = {edge.target for edge in context.changes.edges if edge.source in frontier}
                frontier = dependencies - nodes
                nodes.update(frontier)
            paths = {n.path for n in nodes}
            if p.known_incomplete or p.unresolved_reasons or not p.anchors:
                reasons.append("known_incomplete")
            if paths & context.changes.limited_paths:
                reasons.append("analysis_limitation")
            if nodes & context.changes.unresolved or any(Node(path=path) in context.changes.unresolved for path in paths):
                reasons.append("unresolved_dependency")
            if not symbol and context.changes.unresolved:
                reasons.append("graph_free_unresolved_fallback")
            if claim.kind in {"behavior_test", "prose"}:
                if context.changes.global_unresolved:
                    reasons.append("global_unresolved_fallback")
                if environment_changed(context.changes.files, context.extra_environment_paths):
                    reasons.append("environment_changed")
            subject_node = Node(path=claim.subject.path, qualname=claim.subject.qualname)
            if symbol and subject_node in affected:
                reasons.append("subject_changed")
            elif not symbol and claim.subject.path in context.changes.files:
                reasons.append("subject_file_changed")
            for anchor in p.anchors:
                node = Node(path=anchor.path, qualname=anchor.qualname)
                if (not symbol or anchor.scope == "file") and anchor.path in context.changes.files:
                    reasons.append("anchor_file_changed")
                elif symbol and node in affected:
                    reasons.append("symbol_or_dependency_changed")
            if symbol and any(d.target in affected for d in p.dependencies):
                reasons.append("explicit_dependency_changed")
        if checking and not previous[claim.claim_id].available:
            reasons.append("previously_unavailable")
        selections.append(Selection(claim_id=claim.claim_id, commit=context.commit,
                                    selected=bool(reasons), reasons=tuple(sorted(set(reasons)))))
    return tuple(selections)


def advance_state(previous: MemoryState, selection: Selection, policy: PolicyConfig,
                  result: ValidationResult | None, structural: bool) -> MemoryState:
    updates: dict[str, object] = {"revision": selection.commit, "basis": "carried_forward"}
    if policy.id == "clear_all":
        updates.update(available=False, withheld_reason="policy_reset")
    elif policy.id.endswith("_invalidate") and selection.selected:
        updates.update(state="needs_validation", basis="heuristic", available=False,
                       withheld_reason="heuristic_invalidation")
    elif policy.id.endswith("_invalidate") and not previous.available:
        updates["basis"] = "heuristic"
    elif result is not None:
        updates.update(last_checked_commit=result.commit, last_verdict=result.verdict, basis="validated")
        if result.verdict == "supported":
            updates.update(state="valid", available=True, last_supported_commit=result.commit, withheld_reason=None)
        elif result.verdict == "contradicted":
            updates.update(state="retired" if structural and result.reason == "subject_absent" else "stale",
                           available=False, withheld_reason=result.reason)
        else:
            updates.update(state="needs_validation", available=False, withheld_reason=result.reason)
    elif selection.selected and policy.id.endswith("_validate"):
        updates.update(state="needs_validation", available=False, withheld_reason="validation_pending")
    return previous.model_copy(update=updates)
