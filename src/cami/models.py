from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


INDEPENDENT_CONFIRMATIONS = frozenset({"human_review", "independent_oracle", "independent_test"})


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)
    schema_version: Literal[1] = 1

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("schema_version must be integer 1")
        return value


class Value(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False,
                              populate_by_name=True)


def safe_path(value: str) -> str:
    p = PurePosixPath(value)
    if not value or p.is_absolute() or ".." in p.parts or "\\" in value or "\x00" in value:
        raise ValueError(f"unsafe repository path: {value!r}")
    if value != p.as_posix():
        raise ValueError(f"noncanonical repository path: {value!r}")
    return value


class Node(Value):
    path: str
    qualname: str | None = None
    _path = field_validator("path")(safe_path)


class Subject(Node):
    qualname: str
    node_kind: Literal["function", "method"]


class Parameter(Value):
    name: str
    kind: Literal["positional_only", "positional_or_keyword", "var_positional", "keyword_only", "var_keyword"]
    default_ast: str | None = None
    annotation_ast: str | None = None


class Signature(Value):
    parameters: tuple[Parameter, ...]
    returns_ast: str | None = None
    decorators_ast: tuple[str, ...] = ()
    is_async: bool = False


class Exists(Value):
    type: Literal["symbol_exists"]
    expected: Literal[True]

    @field_validator("expected", mode="before")
    @classmethod
    def exact_true(cls, value: object) -> object:
        if value is not True:
            raise ValueError("expected must be JSON true")
        return value


class Equals(Value):
    type: Literal["signature_equals"]
    expected_signature: Signature


class Behavior(Value):
    type: Literal["behavior_test"]
    probe_path: str
    probe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    node_id: str
    environment_id: str
    _path = field_validator("probe_path")(safe_path)


class Prose(Value):
    type: Literal["prose"]


Predicate = Annotated[Exists | Equals | Behavior | Prose, Field(discriminator="type")]


class Claim(Record):
    claim_id: str = Field(min_length=1)
    repo_id: str
    origin_commit: str
    kind: Literal["symbol_exists", "signature_equals", "behavior_test", "prose"]
    text: str = Field(min_length=1)
    subject: Subject
    predicate: Predicate
    scope: str = Field(min_length=1)

    @model_validator(mode="after")
    def match_kind(self) -> Self:
        if self.kind != self.predicate.type:
            raise ValueError("kind and predicate.type differ")
        return self


class Anchor(Node):
    scope: Literal["symbol", "file"]
    observed_commit: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    origin: Literal["manual", "static", "runtime"]
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.scope == "symbol" and not self.qualname:
            raise ValueError("symbol anchor requires qualname")
        if self.start_line and self.end_line and self.end_line < self.start_line:
            raise ValueError("reversed line range")
        return self


class Dependency(Value):
    source: Node = Field(alias="from")
    target: Node = Field(alias="to")
    relation: Literal["calls", "imports", "evidence_dependency"]
    origin: Literal["manual", "static", "runtime"]


class Provenance(Record):
    claim_id: str
    scenario_id: str
    anchors: tuple[Anchor, ...] = ()
    dependencies: tuple[Dependency, ...] = ()
    known_incomplete: bool = False
    unresolved_reasons: tuple[str, ...] = ()


class ParentReceipt(Record):
    claim_id: str
    origin_commit: str
    status: Literal["supported"]
    confirmation_type: str
    evidence_path: str
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    annotation_minutes: float | None = Field(default=None, ge=0)
    _path = field_validator("evidence_path")(safe_path)


PolicyID = Literal["keep_all", "clear_all", "file_invalidate", "symbol_invalidate",
                   "all_validate", "file_validate", "symbol_validate"]


class PolicyConfig(Value):
    id: PolicyID
    dependency_depth: Literal[0, 1, 2] = 1


class RepoLocation(Value):
    repo_id: str
    path: str
    source_roots: tuple[str, ...] = (".",)

    @field_validator("source_roots")
    @classmethod
    def paths(cls, roots: tuple[str, ...]) -> tuple[str, ...]:
        for root in roots:
            safe_path(root)
        return roots


class ValidationConfig(Value):
    execution: Literal["disabled", "docker"] = "disabled"
    llm: Literal["disabled", "openai"] = "disabled"


class EnvironmentProfile(Value):
    image: str = Field(pattern=r"^.+@sha256:[0-9a-f]{64}$")
    python_version: str
    source_paths: tuple[str, ...] = (".",)
    cpus: int = Field(default=2, ge=1, le=2)
    memory_mib: int = Field(default=2048, ge=64, le=2048)
    pids_limit: int = Field(default=128, ge=1, le=128)
    timeout_seconds: int = Field(default=60, ge=1, le=60)
    user: Literal["65534:65534"] = "65534:65534"
    mount_mode: Literal["read_only"] = "read_only"

    @field_validator("source_paths")
    @classmethod
    def paths(cls, roots: tuple[str, ...]) -> tuple[str, ...]:
        for root in roots:
            safe_path(root)
        return roots


class RunConfig(Record):
    protocol_version: str = "1.0"
    repo: RepoLocation
    parent_commit: str
    child_commits: tuple[str, ...] = Field(min_length=1)
    claims_path: str
    provenance_path: str
    parent_receipts_path: str
    scenario_id: str = "intact"
    dataset_kind: Literal["synthetic", "real"]
    split: Literal["development", "heldout"]
    stratum: Literal["fixture", "chronological", "enriched", "replay"]
    policy: PolicyConfig
    validation: ValidationConfig = ValidationConfig()
    allow_network: bool = False
    max_calls: int = Field(default=0, ge=0)
    seed: int = 42
    preview: bool = False
    replicate_id: int = Field(default=0, ge=0)
    cache_dir: str | None = None
    environment_profiles: dict[str, EnvironmentProfile] = Field(default_factory=dict)
    extra_environment_paths: tuple[str, ...] = ()
    graph_views_path: str | None = None
    frozen_protocol_path: str | None = None

    @model_validator(mode="after")
    def resources(self) -> Self:
        if self.validation.execution == "docker" and not self.environment_profiles:
            raise ValueError("docker requires environment_profiles")
        if self.validation.llm == "openai" and (not self.allow_network or self.max_calls <= 0):
            raise ValueError("openai requires network authorization and positive budget")
        for path in self.extra_environment_paths:
            safe_path(path)
        if self.scenario_id != "intact" and self.graph_views_path is None:
            raise ValueError("ablations require graph_views_path")
        return self


Verdict = Literal["supported", "contradicted", "insufficient_evidence"]


class ValidationResult(Record):
    claim_id: str
    commit: str
    validator: str
    verdict: Verdict
    reason: str
    evidence: tuple[str, ...] = ()
    input_hash: str
    duration_seconds: float = Field(ge=0)
    cpu_seconds: float = Field(default=0, ge=0)
    test_executions: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    logs: tuple[str, ...] = ()
    cache_hit: bool = False
    original_measurement: str | None = None


class MemoryState(Record):
    claim_id: str
    revision: str
    state: Literal["valid", "needs_validation", "stale", "retired"]
    last_checked_commit: str | None
    last_supported_commit: str | None
    last_verdict: Verdict | None
    basis: Literal["validated", "carried_forward", "heuristic"]
    current_provenance: Provenance
    available: bool
    withheld_reason: str | None = None


class Selection(Record):
    claim_id: str
    commit: str
    selected: bool
    reasons: tuple[str, ...]


class Cost(Record):
    phase: Literal["preflight", "maintenance"]
    commit: str
    wall_seconds: float = 0
    cpu_seconds: float = 0
    index_seconds: float = 0
    initial_index_seconds: float = 0
    incremental_index_seconds: float = 0
    selection_seconds: float = 0
    logical_validations: int = 0
    actual_validations: int = 0
    cache_hits: int = 0
    test_executions: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reconstructed_validation_seconds: float = 0
    actual_validation_seconds: float = 0
    provenance_seconds: float | None = None
    annotation_minutes: float | None = None


class GraphView(Record):
    commit: str
    edges: tuple[Dependency, ...]
    unresolved: tuple[Node, ...] = ()
    global_unresolved: bool = False
    known_incomplete_nodes: tuple[Node, ...] = ()
