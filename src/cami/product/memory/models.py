from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from cami.ecma_models import EcmaIdentityGap
from cami.product.models import Digest, Observation, ProductValue
from cami.models import safe_path


class SymbolKey(ProductValue):
    language: str
    path: str
    qualname: str = Field(min_length=1)
    node_kind: str
    _path = field_validator("path")(safe_path)


class IndexRef(ProductValue):
    worktree_key: Digest
    snapshot_id: Digest
    generation_id: Digest
    policy_fingerprint: Digest
    analyzer_fingerprint: Digest


class SourceRef(ProductValue):
    index: IndexRef
    path: str
    sha256: Digest
    size: int = Field(ge=0)
    _path = field_validator("path")(safe_path)


class PythonParameter(ProductValue):
    name: str
    kind: Literal["positional_only", "positional_or_keyword", "var_positional",
                  "keyword_only", "var_keyword"]
    annotation: str | None
    default: str | None


class PythonSignature(ProductValue):
    format: Literal["python.ast-signature/1"] = "python.ast-signature/1"
    parameters: tuple[PythonParameter, ...]
    returns: str | None
    decorators: tuple[str, ...]
    type_parameters: tuple[str, ...]
    is_async: bool


class EcmaParameterSyntax(ProductValue):
    pattern: str
    optional: bool
    rest: bool
    default: str | None
    annotation: str | None


class EcmaSignatureSyntax(ProductValue):
    format: Literal["ecma.syntax-signature/1", "ecma.syntax-signature/2"] = "ecma.syntax-signature/2"
    parameters: tuple[EcmaParameterSyntax, ...]
    type_parameters: tuple[str, ...]
    return_annotation: str | None
    is_async: bool
    generator: bool


Signature = Annotated[PythonSignature | EcmaSignatureSyntax, Field(discriminator="format")]


class DefinitionFact(ProductValue):
    subject: SymbolKey
    signature: Signature | None
    source: SourceRef
    ambiguous: bool
    identity_uncertain: bool = False


class PathCoverage(ProductValue):
    path: str
    status: Literal["present", "absent", "excluded", "ignored", "unavailable"]
    _path = field_validator("path")(safe_path)


class CodeView(ProductValue):
    index: IndexRef
    definitions: tuple[DefinitionFact, ...]
    sources: tuple[SourceRef, ...]
    coverage: tuple[PathCoverage, ...]
    path_errors: tuple[tuple[str, str], ...] = ()
    identity_gaps: tuple[EcmaIdentityGap, ...] = ()
    relation_scopes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    graph_complete: Literal[False] = False


class ExistsPayload(ProductValue):
    type: Literal["symbol_exists"] = "symbol_exists"
    subject: SymbolKey
    expected: Literal[True] = True


class SignaturePayload(ProductValue):
    type: Literal["signature_equals"] = "signature_equals"
    subject: SymbolKey
    expected: Signature


class NotePayload(ProductValue):
    type: Literal["note"] = "note"
    subject: SymbolKey
    note_key: str = Field(min_length=1, max_length=1024)
    text: str = Field(min_length=1)
    sources: tuple[SourceRef, ...] = Field(min_length=1)


Payload = Annotated[ExistsPayload | SignaturePayload | NotePayload, Field(discriminator="type")]


class RecordRevision(ProductValue):
    memory_id: Digest
    revision: int = Field(ge=1)
    payload: Payload
    origin: IndexRef
    author_kind: Literal["agent", "human"] = "agent"
    author_id: str = "cli"
    created_at: str
    previous_revision: int | None


class AbsenceWitness(ProductValue):
    index: IndexRef
    path: str
    qualname: str
    scope_digest: Digest
    reason: Literal["symbol_absent_in_parsed_file", "path_absent_in_scope"]


class CheckRef(ProductValue):
    check_id: Digest
    index: IndexRef
    record_revision: int
    validator_fingerprint: Digest
    checked_at: str
    verdict: Literal["supported", "contradicted", "insufficient_evidence"]
    reason: str
    evidence: tuple[SourceRef | AbsenceWitness, ...]


class DependencyStamp(ProductValue):
    fingerprint: Digest
    scopes: tuple[str, ...]
    certain: bool


class Equivalence(ProductValue):
    from_index: IndexRef
    to_index: IndexRef
    dependency_fingerprint: Digest
    rule: Literal["product-dependency-equivalence/1"] = "product-dependency-equivalence/1"


class CheckedClaim(ProductValue):
    type: Literal["checked"] = "checked"
    check: CheckRef


class CarriedClaim(ProductValue):
    type: Literal["carried"] = "carried"
    check: CheckRef
    equivalence: Equivalence


class NoteState(ProductValue):
    type: Literal["manual_note"] = "manual_note"
    source_state: Literal["unchanged", "changed", "missing", "uncertain"]
    review_state: Literal["not_requested", "needs_review"]
    origin: IndexRef
    label: Literal["manual_assertion"] = "manual_assertion"


State = Annotated[CheckedClaim | CarriedClaim | NoteState, Field(discriminator="type")]


class RecordState(ProductValue):
    record: RecordRevision
    state: State
    dependencies: DependencyStamp
    invalidation_scopes: tuple[str, ...]


class MemoryGeneration(ProductValue):
    memory_generation_id: Digest
    parent_memory_generation_id: Digest | None
    sequence: int
    index: IndexRef
    catalog_epoch: int
    validator_fingerprint: Digest
    states: tuple[RecordState, ...]


class AvailableRecord(ProductValue):
    record: RecordRevision
    state: State


class WithheldRecord(AvailableRecord):
    reason: str
    required_action: str


class AgentContext(ProductValue):
    schema_version: Literal[1] = 1
    query: str
    index: IndexRef
    memory_generation_id: Digest
    observation: Observation
    code: tuple[DefinitionFact, ...]
    coverage: tuple[PathCoverage, ...]
    path_errors: tuple[tuple[str, str], ...]
    limitations: tuple[str, ...]
    facts: tuple[AvailableRecord, ...]
    notes: tuple[AvailableRecord, ...]
    withheld: tuple[WithheldRecord, ...]
    graph_complete: Literal[False] = False


class MutationRequest(ProductValue):
    request_id: str = Field(min_length=1, max_length=1024)
    payload: Payload
    origin: IndexRef
    memory_id: Digest | None = None
    expected_revision: int | None = Field(default=None, ge=1)


class MutationReceipt(ProductValue):
    request_id: str
    memory_id: Digest
    revision: int
    changed: bool
    memory_generation_id: Digest
    label: Literal["mutation_receipt"] = "mutation_receipt"


class RecordHistory(ProductValue):
    memory_id: Digest
    revisions: tuple[RecordRevision, ...]
    generations: tuple[MemoryGeneration, ...]
    checks: tuple[CheckRef, ...]
