#!/usr/bin/env python3
"""Audit declared AI review records; never judge verdict truth or create labels."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any


DISCLOSURE = "Model weights and training independence are unverified."
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
CASE_KEYS = {"id", "kind", "subject", "predicate", "text", "scope", "source_path", "source_sha256"}
HEADER_KEYS = {"schema_version", "reviewer_kind", "human", "provider", "model", "reasoning_effort",
               "agent_task", "packet_sha256", "independence_disclosure", "identity_basis", "items"}
ITEM_KEYS = {"id", "source_sha256", "verdict", "extracted_facts", "evidence", "reasoning", "scope_notes"}


class ReviewError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReviewError(message)


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (UnicodeError, ValueError) as error:
        raise ReviewError("packet identity is not valid canonical UTF-8 JSON") from error


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> tuple[Any, bytes]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                           parse_constant=lambda value: (_ for _ in ()).throw(
                               ReviewError(f"non-finite JSON value: {value}")))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ReviewError(f"invalid UTF-8 JSON: {path.name}") from error
    return value, raw


def exact_keys(value: Any, keys: set[str], context: str) -> None:
    require(isinstance(value, dict), f"{context} must be an object")
    require(set(value) == keys, f"{context} keys differ: missing={sorted(keys - set(value))}, "
            f"unexpected={sorted(set(value) - keys)}")


def nonblank(value: Any, context: str) -> None:
    require(isinstance(value, str) and bool(value.strip()), f"{context} must be nonempty text")


def digest_field(value: Any, context: str) -> None:
    require(isinstance(value, str) and SHA256.fullmatch(value) is not None,
            f"{context} must be a lowercase SHA-256")


def safe_relative(value: Any) -> None:
    nonblank(value, "source_path")
    require(not value.startswith("/") and "\\" not in value and "\x00" not in value
            and all(part not in ("", ".", "..") for part in value.split("/")),
            "source_path must be a contained POSIX relative path")


def contained_file(root: Path, relative: str) -> Path:
    safe_relative(relative)
    resolved = (root / relative).resolve(strict=True)
    require(resolved.is_relative_to(root) and resolved.is_file(), "source path escapes packet or is not a file")
    return resolved


def load_packet(packet: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], str, str]:
    root = packet.resolve(strict=True)
    require(root.is_dir(), "packet must be a directory")
    cases, raw = read_json(contained_file(root, "cases.json"))
    require(isinstance(cases, list) and bool(cases), "cases.json must be a nonempty list")
    by_id: dict[str, dict[str, Any]] = {}
    sources: dict[str, dict[str, Any]] = {}
    for case in cases:
        exact_keys(case, CASE_KEYS, "packet case")
        for key in ("id", "kind", "text", "scope"):
            nonblank(case[key], f"case {key}")
        require(isinstance(case["subject"], (str, dict)) and bool(case["subject"]), "subject must be text or object")
        require(isinstance(case["predicate"], (str, dict)) and bool(case["predicate"]), "predicate must be text or object")
        require(case["id"] not in by_id, "duplicate packet case ID")
        digest_field(case["source_sha256"], "case source_sha256")
        path = contained_file(root, case["source_path"])
        content = path.read_bytes()
        require(sha256(content) == case["source_sha256"], "packet source hash mismatch")
        try:
            source = content.decode("utf-8")
        except UnicodeError as error:
            raise ReviewError("packet source is not UTF-8") from error
        # Newline-delimited source lines; the empty source has no evidence lines.
        lines = len(source.split("\n")) - int(source.endswith("\n")) if source else 0
        sources[case["source_path"]] = {"source_sha256": case["source_sha256"], "line_count": lines}
        by_id[case["id"]] = case
    cases_digest = sha256(raw)
    identity = {"cases_sha256": cases_digest, "sources": [
        {"source_path": path, "source_sha256": sources[path]["source_sha256"]} for path in sorted(sources)]}
    return by_id, sources, sha256(canonical(identity)), cases_digest


def compute_packet_identity(packet: Path) -> str:
    """Hash exact cases.json bytes plus canonical sorted declared source inventory."""
    return load_packet(packet)[2]


def audit_review(packet: Path, review_path: Path) -> dict[str, Any]:
    cases, sources, packet_digest, cases_digest = load_packet(packet)
    review, review_bytes = read_json(review_path)
    exact_keys(review, HEADER_KEYS, "review")
    require(type(review["schema_version"]) is int and review["schema_version"] == 1, "schema_version must be 1")
    require(review["reviewer_kind"] == "ai_reviewer" and review["human"] is False,
            "AI provenance requires reviewer_kind=ai_reviewer and human=false")
    for key in ("provider", "model", "reasoning_effort", "agent_task"):
        nonblank(review[key], key)
    require(review["identity_basis"] == "declared_invocation", "identity is a declared invocation, not a weight fingerprint")
    require(review["independence_disclosure"] == DISCLOSURE, "required independence disclosure missing")
    digest_field(review["packet_sha256"], "packet_sha256")
    require(review["packet_sha256"] == packet_digest, "packet identity mismatch")
    require(isinstance(review["items"], list), "items must be a list")
    seen: set[str] = set()
    counts = {"supported": 0, "contradicted": 0, "uncertain": 0}
    available_count = unavailable_count = 0
    for item in review["items"]:
        exact_keys(item, ITEM_KEYS, "review item")
        nonblank(item["id"], "item id")
        require(item["id"] in cases and item["id"] not in seen, "unknown or duplicate review case ID")
        seen.add(item["id"])
        case = cases[item["id"]]
        require(item["source_sha256"] == case["source_sha256"], "review source hash mismatch")
        require(isinstance(item["verdict"], str) and item["verdict"] in counts, "invalid verdict")
        counts[item["verdict"]] += 1
        nonblank(item["reasoning"], "reasoning")
        nonblank(item["scope_notes"], "scope_notes")
        facts = item["extracted_facts"]
        require(isinstance(facts, (str, list, dict)) and bool(facts), "extracted_facts must be nonempty text, array, or object")
        if isinstance(facts, str):
            nonblank(facts, "extracted_facts")
        require(isinstance(item["evidence"], list), "evidence must be a list")
        positive = item["verdict"] != "uncertain"
        require(not positive or bool(item["evidence"]), "supported/contradicted requires source evidence")
        for evidence in item["evidence"]:
            require(isinstance(evidence, dict) and type(evidence.get("available")) is bool,
                    "evidence available must be a boolean")
            require(evidence.get("source_path") == case["source_path"], "evidence must reference this case's sealed source")
            if evidence["available"]:
                exact_keys(evidence, {"source_path", "available", "line_start", "line_end"}, "available evidence")
                start, end = evidence["line_start"], evidence["line_end"]
                require(type(start) is int and type(end) is int, "evidence line bounds must be integers")
                require(1 <= start <= end <= sources[case["source_path"]]["line_count"], "evidence line range is outside source")
                available_count += 1
            else:
                exact_keys(evidence, {"source_path", "available", "explanation"}, "unavailable evidence")
                require(not positive, "unavailable evidence is only allowed for uncertain verdicts")
                nonblank(evidence["explanation"], "unavailable evidence explanation")
                unavailable_count += 1
    require(seen == set(cases), f"review coverage mismatch: missing={sorted(set(cases) - seen)}")
    return {"schema_version": 1, "artifact_kind": "ai_review_format_audit", "status": "passed",
            "checks": {"ai_provenance_explicit": True, "packet_identity_matches": True,
                       "source_hashes_and_containment_valid": True, "exact_case_coverage": True,
                       "reasoning_present": True, "evidence_shape_and_line_ranges_valid": True},
            "counts": {"packet_cases": len(cases), "review_items": len(seen), "source_files": len(sources),
                       "declared_verdicts": counts, "available_evidence_entries": available_count,
                       "unavailable_evidence_entries": unavailable_count},
            "input_hashes": {"packet_sha256": packet_digest, "cases_sha256": cases_digest,
                             "review_sha256": sha256(review_bytes),
                             "sources": {path: value["source_sha256"] for path, value in sorted(sources.items())}},
            "limitations": ["Only declared invocation identity is checked; actual model identity is unverified.",
                            DISCLOSURE, "Verdict truth and evidentiary relevance were not checked.",
                            "This audit is not a label, parent receipt, admission decision, human review, or protocol compliance certificate."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        require(not args.out.exists() and not args.out.is_symlink(), "output must be a new file")
        audit = audit_review(args.packet, args.review)
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(audit, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except (ReviewError, OSError) as error:
        parser.exit(2, f"Review audit failed: {error}\n")
    print(f"AI review format audit passed: {audit['counts']['review_items']} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
