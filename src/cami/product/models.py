from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cami.index import CodeIndex
from cami.models import Dependency, Node, Signature, safe_path
from cami.repository import Blob, Snapshot


class ProductValue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class CapturePolicy(ProductValue):
    source_roots: tuple[str, ...]
    excluded_paths: tuple[str, ...]
    excluded_dirs: tuple[str, ...]
    root_outputs: tuple[str, ...]
    ignore_fingerprint: Digest
    language: Literal["python"] = "python"


class InputEntry(ProductValue):
    path: str
    kind: Literal["file", "symlink", "submodule", "special"]
    mode: str
    sha256: Digest | None
    size: int = Field(ge=0)
    limitation: str | None = None
    _path = field_validator("path")(safe_path)


class StoreRecord(ProductValue):
    schema_version: Literal[1] = 1

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("schema_version must be integer 1")
        return value


class Manifest(StoreRecord):
    worktree_key: Digest
    snapshot_id: Digest
    generation_id: Digest
    fingerprint: Digest
    policy: CapturePolicy
    entries: tuple[InputEntry, ...]
    index_sha256: Digest


class Pointer(StoreRecord):
    generation_id: Digest


class SearchLimitation(ProductValue):
    code: str
    path: str | None = None


class GitSnapshot(ProductValue):
    kind: Literal["git"] = "git"
    revision: str
    tree: str
    source_roots: tuple[str, ...]
    index_version: str
    search_version: Literal["2"] = "2"
    python_version: str


class WorktreeSnapshot(ProductValue):
    kind: Literal["worktree"] = "worktree"
    snapshot_id: Digest
    generation_id: Digest
    base_commit: str | None
    consistency: Literal["verified_readset"] = "verified_readset"
    source_roots: tuple[str, ...]
    policy: CapturePolicy
    fingerprint: Digest
    index_version: str
    search_version: Literal["2"] = "2"
    python_version: str


class Observation(ProductValue):
    capture_started_at: str
    verified_at: str
    cache_reused: bool


class SymbolMatch(ProductValue):
    path: str
    qualname: str
    module: str
    qualified_name: str
    node_kind: str
    start_line: int
    end_line: int
    signature: Signature
    signature_text: str
    ambiguous: bool
    incoming: tuple[Dependency, ...]
    outgoing: tuple[Dependency, ...]


class FindResult(ProductValue):
    schema_version: Literal[2] = 2
    query: str
    requested_revision: str | None
    snapshot: Annotated[GitSnapshot | WorktreeSnapshot, Field(discriminator="kind")]
    observation: Observation | None = None
    status: Literal["found", "not_found", "ambiguous"]
    coverage: Literal["complete", "partial"]
    absence_confirmed: bool
    matches: tuple[SymbolMatch, ...]
    graph_complete: Literal[False] = False
    limitations: tuple[SearchLimitation, ...]
    unresolved: tuple[Node, ...]
    global_unresolved: bool


@dataclass(frozen=True)
class Capture:
    snapshot_id: str
    base_commit: str | None
    policy: CapturePolicy
    entries: tuple[InputEntry, ...]
    blobs: tuple[Blob, ...]

    def as_snapshot(self) -> Snapshot:
        return Snapshot("product-worktree", "worktree:" + self.snapshot_id, self.blobs)


@dataclass(frozen=True)
class Generation:
    manifest: Manifest
    index: CodeIndex


@dataclass(frozen=True)
class IndexedWorktree:
    capture: Capture
    generation: Generation
    observation: Observation
