from __future__ import annotations

from typing import Literal

from cami.product.memory.models import IndexRef
from cami.product.models import Digest, ProductValue


class ProductObservation(ProductValue):
    comparison_key: Digest
    relation: Literal["matching", "changed"]
    reason: Literal["inputs_changed", "head_matches", "index_artifact_unavailable", "no_head"]
    capture_started_at: str
    verified_at: str
    memory_generation_id: Digest | None
    index: IndexRef | None
