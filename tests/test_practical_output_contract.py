import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.practical.output_contract import semantic_payload


def fixture():
    root = Path(__file__).resolve().parents[1]
    return json.loads(
        (root / "reports/practical-20261115/benchmark/found-0-baseline.json").read_text()
    )


def test_all_historical_pairs_follow_contract():
    root = Path(__file__).resolve().parents[1] / "reports/practical-20261115/benchmark"
    for case in ["found", "missing"]:
        for pair in range(5):
            left = json.loads((root / f"{case}-{pair}-baseline.json").read_text())
            right = json.loads((root / f"{case}-{pair}-candidate.json").read_text())
            assert semantic_payload(left) == semantic_payload(right)


def test_changed_source_and_changed_result_remain_different():
    left = fixture()
    right = copy.deepcopy(left)
    right["snapshot"]["snapshot_id"] = "a" * 64
    right["snapshot"]["generation_id"] = hashlib.sha256(
        json.dumps(
            [right["snapshot"]["snapshot_id"], right["snapshot"]["fingerprint"]],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert semantic_payload(left) != semantic_payload(right)
    right = copy.deepcopy(left)
    right["matches"][0]["signature_text"] = "wrong"
    assert semantic_payload(left) != semantic_payload(right)


def test_identity_tampering_rejected():
    value = fixture()
    value["snapshot"]["generation_id"] = "0" * 64
    with pytest.raises(ValueError, match="generation identity"):
        semantic_payload(value)
