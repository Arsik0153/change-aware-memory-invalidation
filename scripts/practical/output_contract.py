"""Compare find payloads across implementations, retaining source identity."""

from copy import deepcopy
import hashlib
import json
import re


def semantic_payload(value):
    result = deepcopy(value)
    observation = result.pop("observation")
    assert set(observation) == {"cache_reused", "capture_started_at", "verified_at"}
    snapshot = result["snapshot"]
    for field in ("fingerprint", "generation_id", "snapshot_id"):
        if re.fullmatch("[0-9a-f]{64}", snapshot[field]) is None:
            raise ValueError(f"invalid {field}")
    expected = hashlib.sha256(
        json.dumps(
            [snapshot["snapshot_id"], snapshot["fingerprint"]],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()
    # These Python-only benchmark inputs have no unavailable ECMAScript payload.
    if snapshot["generation_id"] != expected:
        raise ValueError("generation identity does not bind snapshot and implementation")
    del snapshot["fingerprint"]
    del snapshot["generation_id"]
    return result
