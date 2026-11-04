"""Research-only selection adapter. Never calls a validator or changes availability."""
from __future__ import annotations

from dataclasses import dataclass

from cami.index import CodeIndex
from cami.models import Claim, MemoryState, Provenance, Selection
from cami.repository import Snapshot
from negative_carry_witness import witness_gate


@dataclass(frozen=True)
class CarryDecision:
    original: Selection
    effective: Selection
    suppressed: bool
    reason: str


def select_negative_carry(claim: Claim, provenance: Provenance, previous: MemoryState,
                          original: Selection, before: Snapshot, after: Snapshot,
                          old_index: CodeIndex, new_index: CodeIndex, *,
                          witness, context) -> CarryDecision:
    """Requires actual-mismatch witness bound to immutable claim and full context.

    Caller first runs production symbol_validate selection with the complete genuine
    ChangeSet. Caller still runs production advance_state with the effective selection.
    This bounded prototype supports only an extant exact-function signature mismatch.
    """
    def keep(reason):
        return CarryDecision(original, original, False, reason)

    rejection = witness_gate(claim, provenance, previous, original, before, after, witness, context)
    if rejection:
        return keep(rejection)
    if context.protocol_version != "1.1" or claim.kind != "signature_equals":
        return keep("outside_exact_signature_research_scope")
    if claim.subject.node_kind != "function" or not (claim.subject.qualname or "").isidentifier():
        return keep("outside_top_level_function_scope")
    if (original.claim_id != claim.claim_id or previous.claim_id != claim.claim_id
            or provenance.claim_id != claim.claim_id or original.commit != after.revision
            or previous.revision != before.revision or old_index.revision != before.revision
            or new_index.revision != after.revision):
        return keep("identity_mismatch")
    if not original.selected or original.reasons != ("previously_unavailable",):
        return keep("production_change_or_fallback_reason_retained")
    if (previous.available or previous.state != "stale" or previous.last_verdict != "contradicted"
            or previous.withheld_reason != "predicate_mismatch"):
        return keep("no_definitive_existing_signature_mismatch")
    if (provenance.known_incomplete or provenance.unresolved_reasons or provenance.dependencies
            or not provenance.anchors or previous.current_provenance != provenance):
        return keep("provenance_not_eligible")
    path = claim.subject.path
    for snapshot in (before, after):
        blob = snapshot.by_path().get(path)
        if blob is None or blob.mode not in {"100644", "100755"} or blob.limitation or blob.content is None:
            return keep("missing_or_nonregular_subject_module")
        if any(blob.limitation and path.startswith(blob.path + "/") for blob in snapshot.blobs):
            return keep("unsupported_subject_ancestor")
    definitions = []
    for index in (old_index, new_index):
        modules = [module for module in index.modules if module.path == path]
        if len(modules) != 1 or modules[0].limitation:
            return keep("subject_module_unavailable_to_index")
        matches = [definition for definition in modules[0].definitions
                   if definition.node.path == path and definition.node.qualname == claim.subject.qualname]
        if len(matches) != 1 or matches[0].ambiguous or matches[0].node_kind != "function":
            return keep("subject_not_unique_unambiguous_function")
        definitions.append(matches[0])
    if (definitions[0].ast_hash != definitions[1].ast_hash
            or definitions[0].signature != definitions[1].signature
            or definitions[1].ast_hash != witness.subject_ast_hash or definitions[1].signature != witness.signature):
        return keep("subject_witness_changed")
    effective = original.model_copy(update={"selected": False, "reasons": ()})
    return CarryDecision(original, effective, True, "unchanged_existing_signature_mismatch_carried")
