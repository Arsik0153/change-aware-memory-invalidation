"""Read-only preparation audit. This script does not parse or label authentic code."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


BASE = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: str):
    return json.loads((BASE / path).read_bytes())


def main() -> None:
    cases = read("packet/cases.json")
    private = read("private/case_map.json")
    fields = {"id", "kind", "subject", "predicate", "text", "scope", "source_path", "source_sha256"}
    assert len(cases) == 36 and len({case["id"] for case in cases}) == 36
    assert all(set(case) == fields for case in cases)
    assert all(set(case["subject"]) == {"path", "qualname", "node_kind"} for case in cases)
    assert {case["id"] for case in cases} == {case["id"] for case in private}
    assert all(sha(BASE / "packet" / case["source_path"]) == case["source_sha256"] for case in cases)
    assert all((BASE / "packet" / case["source_path"]).resolve().is_relative_to(
        (BASE / "packet/source").resolve()) for case in cases)
    by_id = {case["id"]: case for case in cases}
    for case in private:
        assert case["source_origin"]["repo_id"] == "click"
        assert case["source_origin"]["split"] == "development"
        assert case["authentic_reference_answer_computed"] is False
        origin = case["source_origin"]
        original_source = BASE / "packet/source" / (origin["source_sha256"] + ".py")
        original_data = original_source.read_bytes()
        blob = f"blob {len(original_data)}\0".encode() + original_data
        object_hash = (hashlib.sha1(blob).hexdigest() if len(origin["git_blob_object_id"]) == 40
                       else hashlib.sha256(blob).hexdigest())
        assert object_hash == origin["git_blob_object_id"]
        original_claim_bytes = json.dumps(case["original_claim"], ensure_ascii=False,
                                         sort_keys=True, separators=(",", ":")).encode()
        assert hashlib.sha256(original_claim_bytes).hexdigest() == case["original_claim_sha256"]
        public = by_id[case["id"]]
        data = (BASE / "packet" / public["source_path"]).read_bytes()
        transformation = case["transformation"]
        if transformation is None:
            assert case["origin_class"] == "authentic_parent_claim"
            assert case["public_source_sha256"] == case["source_origin"]["source_sha256"]
            assert all(public[field] == case["original_claim"][field]
                       for field in ("kind", "subject", "predicate", "text", "scope"))
        elif transformation["type"] == "nonexistent_name":
            assert transformation["new_qualname"].encode() not in data
            assert public["subject"]["qualname"] == transformation["new_qualname"]
            assert public["predicate"] == {"type": "symbol_exists", "expected": True}
            assert public["subject"]["qualname"] in public["text"]
        elif transformation["type"] == "signature_mismatch":
            assert transformation["new_parameter_name"].encode() not in data
            parameters = public["predicate"]["expected_signature"]["parameters"]
            assert parameters[0]["name"] == transformation["new_parameter_name"]
            assert parameters[0]["name"] in public["text"]
        elif transformation["type"] == "duplicate_definition_source_variant":
            appended = transformation["appended_utf8"].encode()
            assert data.endswith(appended)
            assert hashlib.sha256(data[:-len(appended)]).hexdigest() == case["source_origin"]["source_sha256"]
            target = public["subject"]["qualname"]
            assert appended.count(f"def {target}(".encode()) == 2
        else:
            raise AssertionError("Unknown control transformation")
    controls = Counter(case["transformation"]["type"] for case in private if case["transformation"])
    assert controls == {"nonexistent_name": 3, "signature_mismatch": 6,
                        "duplicate_definition_source_variant": 3}
    authentic = [case for case in private if case["transformation"] is None]
    assert len(authentic) == 24
    per_group = Counter(case["source_origin"]["group_id"] for case in authentic)
    assert len(per_group) == 3 and set(per_group.values()) == {8}
    assert all(sha(BASE / path) == expected for path, expected in read("sealed_hashes.json").items())
    print(json.dumps({"status": "sealed_packet_verified", "authentic_cases": len(authentic),
                      "private_controls": dict(controls), "public_cases": len(cases),
                      "authentic_reference_answers_computed": False,
                      "protocol_sha256": sha(BASE / "protocol.json")}, sort_keys=True))


if __name__ == "__main__":
    main()
