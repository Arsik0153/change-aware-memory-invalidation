"""Bound research witnesses for a previous actual structural signature mismatch."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import sys

from cami.artifacts import digest, file_hash
from cami.index import INDEX_VERSION, CodeIndex, IndexConfig
from cami.models import Claim, MemoryState, Provenance, Selection, Signature
from cami.repository import MAX_FILE_BYTES, RepoLocation, Snapshot
from cami.validation import VALIDATOR_VERSION, ValidationResult

SCOPE = "Exact normalized syntax, including defaults, annotations, decorators, and async status."
SCOPES = {SCOPE, "Exact syntactic definition, no runtime semantics."}


@dataclass(frozen=True)
class ResearchContext:
    repo_id: str
    source_roots: tuple[str, ...]
    build_graph: bool
    max_file_bytes: int
    implementation_hashes: tuple[tuple[str, str], ...]
    run_binding: str
    python: str = sys.version
    index_version: str = INDEX_VERSION
    validator_version: str = VALIDATOR_VERSION
    protocol_version: str = "1.1"
    scope_contract: str = "exact_normalized_python_function_signature_v1"


def bind_context(repo: RepoLocation, index_config: IndexConfig, *, run_binding: str, max_file_bytes=MAX_FILE_BYTES):
    import cami.index
    import cami.models
    import cami.policies
    import cami.repository
    import cami.validation
    modules = (cami.index, cami.models, cami.policies, cami.repository, cami.validation)
    hashes = tuple((module.__name__, file_hash(Path(module.__file__))) for module in modules)
    if len(run_binding) != 64 or any(character not in "0123456789abcdef" for character in run_binding):
        raise ValueError("context requires canonical enclosing run/input SHA-256 binding")
    return ResearchContext(repo.repo_id, index_config.source_roots, index_config.build_graph, max_file_bytes, hashes, run_binding)


@dataclass(frozen=True)
class NegativeWitness:
    claim_sha256: str
    provenance_sha256: str
    context_sha256: str
    checked_commit: str
    validation_input_hash: str
    module_oid: str
    module_sha256: str
    subject_ast_hash: str
    signature: Signature


def context_hash(context):
    return digest(asdict(context))


def input_hash(claim, provenance, commit, context):
    evidence = (f"{commit}:{claim.subject.path}:{claim.subject.qualname}",)
    return digest({"claim": claim.model_dump(mode="json"), "commit": commit, "evidence": evidence,
                   "validator_version": context.validator_version,
                   "provenance": provenance.model_dump(mode="json", by_alias=True)})


def exact_scope(claim, provenance, context):
    return (context.protocol_version == "1.1" and context.scope_contract == "exact_normalized_python_function_signature_v1"
            and claim.repo_id == context.repo_id and provenance.claim_id == claim.claim_id
            and claim.kind == "signature_equals" and claim.scope in SCOPES
            and claim.subject.node_kind == "function" and (claim.subject.qualname or "").isidentifier()
            and not provenance.known_incomplete and not provenance.unresolved_reasons
            and not provenance.dependencies and bool(provenance.anchors))


def mint_witness(claim: Claim, provenance: Provenance, result: ValidationResult,
                 snapshot: Snapshot, index: CodeIndex, context: ResearchContext):
    """Called only on an actual validate_claim result; never on a carried state.

    Matching input identity checks provenance/claim/context consistency; it is not a
    signature proving execution by an untrusted caller. The sealed runner owns minting.
    """
    if not exact_scope(claim, provenance, context):
        return None
    if (result.verdict != "contradicted" or result.reason != "predicate_mismatch"
            or result.validator != "structural" or result.claim_id != claim.claim_id
            or result.commit != snapshot.revision or snapshot.repo_id != context.repo_id or index.revision != snapshot.revision
            or result.input_hash != input_hash(claim, provenance, snapshot.revision, context)):
        return None
    blob = snapshot.by_path().get(claim.subject.path)
    if blob is None or blob.mode not in {"100644", "100755"} or blob.limitation or blob.content is None:
        return None
    modules = [module for module in index.modules if module.path == claim.subject.path]
    if len(modules) != 1 or modules[0].limitation:
        return None
    definitions = [definition for definition in modules[0].definitions
                   if definition.node.path == claim.subject.path and definition.node.qualname == claim.subject.qualname]
    if (len(definitions) != 1 or definitions[0].ambiguous or definitions[0].node_kind != "function"
            or definitions[0].signature == claim.predicate.expected_signature):
        return None
    return NegativeWitness(digest(claim), digest(provenance), context_hash(context), snapshot.revision,
                           result.input_hash, blob.object_id, blob.content_hash,
                           definitions[0].ast_hash, definitions[0].signature)


def witness_gate(claim: Claim, provenance: Provenance, previous: MemoryState, selection: Selection,
                 before: Snapshot, after: Snapshot, witness: NegativeWitness | None, context: ResearchContext):
    if witness is None:
        return "missing_actual_negative_witness"
    if not exact_scope(claim, provenance, context):
        return "outside_exact_scope_or_incomplete_provenance"
    if (digest(claim) != witness.claim_sha256 or digest(provenance) != witness.provenance_sha256
            or context_hash(context) != witness.context_sha256):
        return "bound_claim_provenance_or_context_changed"
    if (previous.claim_id != claim.claim_id or selection.claim_id != claim.claim_id
            or previous.revision != before.revision or selection.commit != after.revision
            or before.repo_id != context.repo_id or after.repo_id != context.repo_id
            or previous.last_checked_commit != witness.checked_commit
            or input_hash(claim, provenance, witness.checked_commit, context) != witness.validation_input_hash):
        return "negative_validation_identity_or_lineage_mismatch"
    if (not selection.selected or selection.reasons != ("previously_unavailable",)
            or previous.available or previous.state != "stale" or previous.last_verdict != "contradicted"
            or previous.withheld_reason != "predicate_mismatch" or previous.current_provenance != provenance):
        return "production_reason_or_previous_state_requires_validation"
    return None
