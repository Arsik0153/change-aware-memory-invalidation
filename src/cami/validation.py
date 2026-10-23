from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from cami.artifacts import digest
from cami.index import CodeIndex
from cami.models import Claim, Equals, Node, Provenance, ValidationResult, Verdict
from cami.repository import Snapshot

VALIDATOR_VERSION = "3"


@dataclass(frozen=True)
class ValidationContext:
    snapshot: Snapshot
    index: CodeIndex | None
    provenance: Provenance
    base_dir: Path
    output_dir: Path


def validate_claim(claim: Claim, context: ValidationContext) -> ValidationResult:
    started, cpu = time.perf_counter(), time.process_time()
    verdict: Verdict = "insufficient_evidence"
    reason = "validator_unavailable"
    evidence = (f"{context.snapshot.revision}:{claim.subject.path}:{claim.subject.qualname}",)
    if claim.kind in {"symbol_exists", "signature_equals"}:
        assert context.index is not None
        index = context.index
        node = Node(path=claim.subject.path, qualname=claim.subject.qualname)
        blob = context.snapshot.by_path().get(node.path)
        definitions = [d for m in index.modules for d in m.definitions if d.node == node]
        module_paths = {m.path for m in index.modules}
        ancestor_limitations = [b.limitation for b in context.snapshot.blobs
                                if b.limitation and (node.path == b.path or node.path.startswith(b.path + "/"))]
        if ancestor_limitations:
            reason = ancestor_limitations[0] or "analysis_limitation"
        elif node.path in index.limitations():
            reason = index.limitations()[node.path]
        elif blob and node.path not in module_paths:
            reason = "outside_source_roots"
        elif any(d.ambiguous for d in definitions) or len(definitions) > 1:
            reason = "ambiguous_subject"
        elif not definitions and node in index.unresolved:
            reason = "ambiguous_subject"
        elif not definitions or definitions[0].node_kind != claim.subject.node_kind:
            verdict, reason = "contradicted", "subject_absent"
        elif isinstance(claim.predicate, Equals) and definitions[0].signature != claim.predicate.expected_signature:
            verdict, reason = "contradicted", "predicate_mismatch"
        else:
            verdict, reason = "supported", "predicate_matches"
    input_hash = digest({"claim": claim.model_dump(mode="json"), "commit": context.snapshot.revision,
                         "evidence": evidence, "validator_version": VALIDATOR_VERSION,
                         "provenance": context.provenance.model_dump(mode="json", by_alias=True)})
    return ValidationResult(claim_id=claim.claim_id, commit=context.snapshot.revision,
        validator="structural" if claim.kind in {"symbol_exists", "signature_equals"} else claim.kind,
        verdict=verdict, reason=reason, evidence=evidence, input_hash=input_hash,
        duration_seconds=time.perf_counter() - started, cpu_seconds=time.process_time() - cpu)
