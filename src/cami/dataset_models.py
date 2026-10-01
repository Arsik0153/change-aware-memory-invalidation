from __future__ import annotations

from typing import Literal

from pydantic import Field

from cami.models import Record, Value


class DatasetRepository(Value):
    repo_id: str
    url: str
    path: str
    source_roots: tuple[str, ...] = (".",)
    environment_restoration: str


class DatasetRun(Value):
    run_id: str
    config_path: str
    split: Literal["development", "heldout"]
    cluster_id: str
    sequence_id: str | None = None


class DatasetManifest(Record):
    dataset_id: str = Field(min_length=1)
    protocol_version: str
    dataset_kind: Literal["synthetic", "real"]
    repositories: tuple[DatasetRepository, ...]
    runs: tuple[DatasetRun, ...] = Field(min_length=1)
    labels_path: str | None = None
    raw_annotations_path: str | None = None
    extra_environment_paths: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
