from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path
from typing import Literal

from cami.product.models import digest
from cami.product.memory.models import (
    AbsenceWitness, AvailableRecord, CarriedClaim, CheckedClaim, CheckRef, CodeView,
    DefinitionFact, DependencyStamp, Equivalence, NotePayload, NoteState, RecordRevision, RecordState,
    SignaturePayload, SourceRef, SymbolKey, WithheldRecord,
)

VALIDATOR_FINGERPRINT = digest([
    "product-memory-structural/2",
    {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
     for name in ("models.py", "adapters.py", "validation.py", "_ecma_syntax.cjs")},
])


def matches(view: CodeView, subject: SymbolKey) -> tuple[DefinitionFact, ...]:
    return tuple(d for d in view.definitions if d.subject == subject)


def identity_uncertainty(view: CodeView, subject: SymbolKey) -> bool:
    return subject.language in ("js", "jsx", "ts", "tsx") and any(
        g.covers(subject.path, subject.qualname, subject.node_kind)
        for g in view.identity_gaps)


def dependencies(record: RecordRevision, view: CodeView) -> DependencyStamp:
    payload = record.payload
    subject = payload.subject
    found = matches(view, subject)
    coverage = next((c.status for c in view.coverage if c.path == subject.path), "unavailable")
    errors = tuple(error for path, error in view.path_errors if path == subject.path)
    if identity_uncertainty(view, subject):
        errors += ("binding_unresolved",)
    scopes = (f"{subject.language}:{subject.path}:{subject.qualname}:{subject.node_kind}",
              subject.path)
    if isinstance(payload, NotePayload):
        paths = {s.path for s in payload.sources}
        source_values = [(s.path, s.sha256) for s in view.sources if s.path in paths]
        return DependencyStamp(
            fingerprint=digest(["note-inputs/1", source_values,
                                [d.subject.model_dump(mode="json") for d in found], errors]),
            scopes=tuple(sorted(set(scopes) | paths)), certain=not errors and bool(found)
            and all(not d.ambiguous and not d.identity_uncertain for d in found))
    values = [{"key": d.subject.model_dump(mode="json"), "ambiguous": d.ambiguous,
               "uncertain": d.identity_uncertain,
               "signature": d.signature.model_dump(mode="json")
               if isinstance(payload, SignaturePayload) and d.signature else None} for d in found]
    certain = (not errors and coverage in ("present", "absent")
               and all(not d.ambiguous and not d.identity_uncertain for d in found))
    return DependencyStamp(fingerprint=digest([
        "structural-inputs/1", VALIDATOR_FINGERPRINT,
        view.index.policy_fingerprint, view.index.analyzer_fingerprint,
        values, coverage, errors]), scopes=scopes, certain=certain)


def transition(record: RecordRevision, view: CodeView, previous: RecordState | None,
               previous_index: CodeView | None, transition_id: str) -> RecordState:
    stamp = dependencies(record, view)
    scopes = set(stamp.scopes)
    if previous:
        scopes.update(previous.dependencies.scopes)
    # Keep both edge sets available for invalidation explanations, including deleted edges.
    if previous_index:
        scopes.update("edge:" + edge for edge in previous_index.relation_scopes)
    scopes.update("edge:" + edge for edge in view.relation_scopes)
    payload = record.payload
    if isinstance(payload, NotePayload):
        current = {s.path: s for s in view.sources}
        coverage = {c.path: c.status for c in view.coverage}
        source_state: Literal["unchanged", "changed", "missing", "uncertain"] = "unchanged"
        if any(coverage.get(s.path) == "absent" for s in payload.sources):
            source_state = "missing"
        elif any(s.path not in current for s in payload.sources) or not stamp.certain:
            source_state = "uncertain"
        elif any(current[s.path].sha256 != s.sha256 for s in payload.sources):
            source_state = "changed"
        sticky = (previous is not None and previous.record.revision == record.revision
                  and isinstance(previous.state, NoteState)
                  and previous.state.review_state == "needs_review")
        state = NoteState(
            source_state=source_state,
            review_state="needs_review" if sticky or source_state != "unchanged"
            else "not_requested", origin=record.origin)
        return RecordState(record=record, state=state, dependencies=stamp,
                           invalidation_scopes=tuple(sorted(scopes)))
    if (previous is not None and previous.record.revision == record.revision
            and isinstance(previous.state, (CheckedClaim, CarriedClaim))
            and stamp.certain and previous.dependencies.certain
            and stamp.fingerprint == previous.dependencies.fingerprint):
        state_claim: CheckedClaim | CarriedClaim = CarriedClaim(
            check=previous.state.check, equivalence=Equivalence(
                from_index=previous.state.check.index, to_index=view.index,
                dependency_fingerprint=stamp.fingerprint))
    else:
        state_claim = CheckedClaim(check=check(record, view, transition_id))
    return RecordState(record=record, state=state_claim, dependencies=stamp,
                       invalidation_scopes=tuple(sorted(scopes)))


def check(record: RecordRevision, view: CodeView, transition_id: str) -> CheckRef:
    payload = record.payload
    subject = payload.subject
    found = matches(view, subject)
    errors = dict(view.path_errors)
    coverage = {c.path: c.status for c in view.coverage}
    verdict: Literal["supported", "contradicted", "insufficient_evidence"] = "insufficient_evidence"
    reason = "scope_uncovered"
    evidence: tuple[SourceRef | AbsenceWitness, ...] = tuple(d.source for d in found)
    if subject.language not in ("python", "js", "jsx", "ts", "tsx"):
        reason = "unsupported_language"
    elif subject.node_kind not in (("function", "method") if subject.language == "python"
                                   else ("function", "method", "arrow", "function_expression")):
        reason = "unsupported_symbol_kind"
    elif subject.path in errors:
        reason = errors[subject.path] if errors[subject.path] in ("parse_error", "scope_uncovered", "compiler_unavailable") \
            else "source_unavailable"
    elif len(found) > 1 or any(d.ambiguous for d in found):
        reason = "ambiguous_binding"
    elif any(d.identity_uncertain for d in found) or identity_uncertainty(view, subject):
        reason = "binding_unresolved"
    elif coverage.get(subject.path) not in ("present", "absent"):
        reason = "scope_uncovered"
    elif not found:
        verdict, reason = "contradicted", "subject_absent"
        evidence = (AbsenceWitness(
            index=view.index, path=subject.path, qualname=subject.qualname,
            scope_digest=digest([view.index.snapshot_id, subject.model_dump(mode="json")]),
            reason="path_absent_in_scope" if coverage[subject.path] == "absent"
            else "symbol_absent_in_parsed_file"),)
    elif isinstance(payload, SignaturePayload):
        actual = found[0].signature
        if actual is None:
            reason = "unsupported_symbol_kind"
        elif actual.format != payload.expected.format:
            reason = "signature_schema_mismatch"
        elif actual == payload.expected:
            verdict, reason = "supported", "predicate_matches"
        else:
            verdict, reason = "contradicted", "signature_mismatch"
    else:
        verdict, reason = "supported", "predicate_matches"
    return CheckRef(
        check_id=digest(["check/1", transition_id, record.memory_id, record.revision,
                         view.index.generation_id, VALIDATOR_FINGERPRINT]),
        index=view.index, record_revision=record.revision,
        validator_fingerprint=VALIDATOR_FINGERPRINT, checked_at=datetime.now(UTC).isoformat(),
        verdict=verdict, reason=reason, evidence=evidence)


def availability(item: RecordState) -> AvailableRecord | WithheldRecord:
    state = item.state
    if isinstance(state, NoteState):
        reason = "manual_review_required" if state.review_state == "needs_review" else None
        action = "review_and_update_note"
    else:
        reason = None if state.check.verdict == "supported" else state.check.reason
        action = "inspect_source_and_refresh" if state.check.verdict == "insufficient_evidence" \
            else "review_and_update_expectation"
    if reason:
        return WithheldRecord(record=item.record, state=state, reason=reason,
                              required_action=action)
    return AvailableRecord(record=item.record, state=state)
