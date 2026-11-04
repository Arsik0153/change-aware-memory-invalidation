"""Research candidate: unchanged regular full-module identity since actual mismatch."""
from __future__ import annotations

from negative_carry import CarryDecision
from negative_carry_witness import witness_gate


def select_blob_negative_carry(claim, provenance, previous, original, before, after, *, witness, context):
    rejection = witness_gate(claim, provenance, previous, original, before, after, witness, context)
    if rejection:
        return CarryDecision(original, original, False, rejection)
    # A genuine Git tree cannot have a regular exact path below a non-tree ancestor.
    # 100644 and 100755 are equivalent for the frozen syntactic predicate.
    for snapshot in (before, after):
        blob = snapshot.by_path().get(claim.subject.path)
        if blob is None or blob.mode not in {"100644", "100755"} or blob.limitation or blob.content is None:
            return CarryDecision(original, original, False, "subject_not_readable_regular_file")
        if blob.object_id != witness.module_oid:
            return CarryDecision(original, original, False, "module_changed_since_actual_negative_validation")
    effective = original.model_copy(update={"selected": False, "reasons": ()})
    return CarryDecision(original, effective, True, "same_regular_module_as_actual_signature_mismatch")
