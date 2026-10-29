from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cami.artifacts import file_hash, load, load_jsonl, within
from cami.errors import InputError
from cami.models import (
    INDEPENDENT_CONFIRMATIONS, Behavior, Claim, GraphView, ParentReceipt, Provenance, RunConfig,
)
from cami.repository import chain, git, resolve


@dataclass(frozen=True)
class Inputs:
    config: RunConfig
    base_dir: Path
    claims: tuple[Claim, ...]
    provenance: tuple[Provenance, ...]
    receipts: tuple[ParentReceipt, ...]


def check_inputs(config_path: Path) -> Inputs:
    config = load(config_path, RunConfig)
    base = config_path.resolve().parent
    repo_path = (base / config.repo.path).resolve()
    parent, children = chain(repo_path, config.parent_commit, config.child_commits)
    config = config.model_copy(update={
        "repo": config.repo.model_copy(update={"path": str(repo_path)}),
        "parent_commit": parent, "child_commits": children,
    })
    claims = load_jsonl(base / config.claims_path, Claim, "claim_id")
    provenance = load_jsonl(base / config.provenance_path, Provenance, "claim_id")
    receipts = load_jsonl(base / config.parent_receipts_path, ParentReceipt, "claim_id")
    claim_by_id = {claim.claim_id: claim for claim in claims}
    ids = set(claim_by_id)
    if not ids:
        raise InputError("empty cohort")
    if {p.claim_id for p in provenance} != ids:
        raise InputError("provenance must cover exactly the original claims")
    if not {r.claim_id for r in receipts} <= ids:
        raise InputError("receipt refers to an unknown claim")
    for claim in claims:
        if claim.repo_id != config.repo.repo_id or claim.origin_commit != parent:
            raise InputError("claims must belong to the repository and resolved parent commit")
        if isinstance(claim.predicate, Behavior):
            probe = within(base, claim.predicate.probe_path)
            if file_hash(probe) != claim.predicate.probe_sha256:
                raise InputError("probe hash mismatch")
            if claim.predicate.environment_id not in config.environment_profiles and not config.preview:
                raise InputError("missing probe environment profile")
            node = claim.predicate.node_id.split("::", 1)
            if len(node) != 2 or node[0] != probe.name or not node[1] or node[1].startswith("-"):
                raise InputError("node_id must name the frozen probe file and exact test")
    for prov in provenance:
        if prov.scenario_id != config.scenario_id:
            raise InputError("provenance scenario mismatch")
        for anchor in prov.anchors:
            if resolve(repo_path, anchor.observed_commit) != anchor.observed_commit:
                raise InputError("anchor requires resolved object ID")
            entry = git(repo_path, "ls-tree", "-z", anchor.observed_commit, "--", anchor.path)
            if not entry:
                raise InputError(f"anchor evidence absent: {anchor.path}")
            mode = entry.split(b" ", 1)[0]
            if mode in {b"120000", b"160000", b"040000"}:
                raise InputError(f"unsupported anchor evidence: {anchor.path}")
    for receipt in receipts:
        if receipt.origin_commit != parent:
            raise InputError("parent receipt revision mismatch")
        if config.dataset_kind == "real":
            claim = claim_by_id[receipt.claim_id]
            tokenizer = (claim.kind == "symbol_exists"
                         and receipt.confirmation_type == "independent_tokenizer_parent_oracle")
            if receipt.confirmation_type not in INDEPENDENT_CONFIRMATIONS and not tokenizer:
                raise InputError("real parent receipts require independent confirmation")
            if claim.kind == "behavior_test" and receipt.confirmation_type != "independent_test":
                raise InputError("real behavior parent receipts require independent frozen-probe testing")
            if claim.kind == "prose" and receipt.confirmation_type != "human_review":
                raise InputError("real prose parent receipts require human review")
        if file_hash(within(base, receipt.evidence_path)) != receipt.evidence_sha256:
            raise InputError("parent evidence hash mismatch")
    if config.graph_views_path is not None:
        for revision in (parent, *children):
            view = load(base / config.graph_views_path / f"{revision}.json", GraphView)
            if view.commit != revision:
                raise InputError("graph view revision mismatch")
    return Inputs(config, base, tuple(sorted(claims, key=lambda c: c.claim_id)), provenance, receipts)
