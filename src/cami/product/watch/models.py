from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from cami.product.memory.models import IndexRef
from cami.product.models import Digest
from cami.product.observation import ProductObservation

Token = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SessionId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


class Value(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class WatchSettings(Value):
    canonical_repo: str
    state_base: str
    source_roots: tuple[str, ...] | None = None
    excluded_paths: tuple[str, ...] = ()
    poll_seconds: float = Field(default=0.5, gt=0, le=60)
    debounce_seconds: float = Field(default=0.25, ge=0, le=60)
    max_deferral_seconds: float = Field(default=2.0, gt=0, le=60)
    operation_seconds: float = Field(default=30.0, gt=0, le=300)


class Session(Value):
    schema_version: Literal[1] = 1
    session_id: SessionId
    capability: Token
    endpoint: str
    endpoint_device: int
    endpoint_inode: int
    worktree_key: Digest
    settings: WatchSettings
    pid_hint: int = Field(gt=0)


class Request(Value):
    schema_version: Literal[1] = 1
    session_id: SessionId
    capability: Token
    nonce: SessionId
    action: Literal["status", "stop"]


class Success(Value):
    completed_at: str
    memory_generation_id: Digest
    index: IndexRef
    sequence: int
    catalog_epoch: int


class WatchError(Value):
    code: str
    message: str = Field(max_length=2000)
    occurred_at: str
    retry_at: str | None = None


class WatchStatus(Value):
    schema_version: Literal[1] = 1
    lifecycle: Literal["starting", "running", "stopping", "stopped", "unknown"]
    reason: str
    ownership: Literal["lease_and_session_verified", "lease_free", "unknown"]
    retrieved_at: str
    session_id: SessionId | None = None
    pid_hint: int | None = None
    worktree_key: Digest
    settings: WatchSettings | None = None
    phase: Literal["starting", "observing", "idle", "pending", "refreshing", "retry_wait",
                   "stopping", "stopped", "unknown"] = "unknown"
    current_observation: ProductObservation | None = None
    data_freshness: Literal["matching_at_observation", "changed", "unknown"] = "unknown"
    latest_successful: Success | None = None
    pending_since: str | None = None
    last_error: WatchError | None = None
    polls: int = 0
    refreshes: int = 0


class Response(Value):
    schema_version: Literal[1] = 1
    session_id: SessionId
    nonce: SessionId
    status: WatchStatus


class OperationResult(Value):
    schema_version: Literal[1] = 1
    action: Literal["observe", "refresh"]
    observation: ProductObservation | None = None
    success: Success | None = None
    error: WatchError | None = None


class WatchEvent(Value):
    schema_version: Literal[1] = 1
    event: Literal["started", "refresh_started", "refreshed", "pending", "error", "stopping", "stopped"]
    timestamp: str
    session_id: SessionId
    reason: str
    success: Success | None = None
    error: WatchError | None = None
