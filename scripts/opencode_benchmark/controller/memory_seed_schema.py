"""Stdlib-only explicit memory-source policy and frozen schema2 comparison data."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
import re

FORMAT = "python.definition-prefix/1"


def check(value, message):
    if not value:
        raise ValueError(message)


def relative(value):
    check(
        isinstance(value, str) and bool(value) and "\\" not in value and "\x00" not in value,
        "invalid memory-source relative path",
    )
    path = PurePosixPath(value)
    check(
        not path.is_absolute() and ".." not in path.parts and str(path) == value,
        "unsafe memory-source relative path",
    )
    return value


def validate_policy(policy):
    check(
        isinstance(policy, dict)
        and set(policy)
        == {"schema_version", "seed", "generator", "helpers", "payload_kind", "extractor_format"}
        and type(policy["schema_version"]) is int
        and policy["schema_version"] == 2,
        "unsupported explicit memory-source policy",
    )
    relative(policy["seed"])
    relative(policy["generator"])
    check(
        PurePosixPath(policy["generator"]).name == "seed_source_literals_v2.py",
        "schema2 requires versioned literal generator",
    )
    check(
        isinstance(policy["helpers"], list) and len(policy["helpers"]) == 1,
        "schema2 requires its explicit literal_source helper",
    )
    relative(policy["helpers"][0])
    check(
        PurePosixPath(policy["helpers"][0]).name == "literal_source.py",
        "schema2 helper identity differs",
    )
    check(
        policy["payload_kind"] == "source_excerpt_equals" and policy["extractor_format"] == FORMAT,
        "schema2 literal predicate/format differs",
    )
    return policy


def policy_for(normalized):
    if "memory_source" not in normalized:
        return {
            "schema_version": 1,
            "seed": normalized["seed"],
            "generator": "seed_source_notes.py",
            "helpers": [],
        }
    policy = validate_policy(normalized["memory_source"])
    check(policy["seed"] == normalized["seed"], "frozen seed/policy path differs")
    return policy


def literal_catalog(seed):
    check(
        isinstance(seed, dict)
        and set(seed) == {"schema_version", "source_roots", "excluded_paths", "records"}
        and type(seed["schema_version"]) is int
        and seed["schema_version"] == 2,
        "explicit schema2 seed required",
    )
    for name in ["source_roots", "excluded_paths"]:
        check(
            isinstance(seed[name], list) and all(isinstance(x, str) for x in seed[name]),
            "invalid schema2 policy paths",
        )
        for path in seed[name]:
            if path != ".":
                relative(path)
    check(
        bool(seed["source_roots"])
        and isinstance(seed["records"], list)
        and 1 <= len(seed["records"]) <= 1024,
        "schema2 seed population bound violated",
    )
    check(
        len(
            json.dumps(
                seed, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
            ).encode()
        )
        <= 4 * 1024 * 1024,
        "schema2 seed exceeds4MiB",
    )
    records, ids, subjects = [], set(), set()
    for item in seed["records"]:
        check(
            isinstance(item, dict)
            and set(item)
            == {"id", "kind", "selector", "subject", "expected", "origin_source", "origin_span"},
            "invalid schema2 seed item; no manual note conversion",
        )
        check(
            isinstance(item["id"], str) and 0 < len(item["id"]) <= 200 and item["id"] not in ids,
            "duplicate/invalid schema2 ID",
        )
        check(item["kind"] == "source_excerpt_equals", "schema2 kind differs")
        subject = item["subject"]
        check(
            isinstance(subject, dict)
            and set(subject) == {"language", "path", "qualname", "node_kind"}
            and all(isinstance(v, str) and v for v in subject.values())
            and subject["language"] == "python"
            and subject["node_kind"] in ("function", "method"),
            "invalid schema2 Python subject",
        )
        relative(subject["path"])
        check(
            item["selector"] == subject["path"] + ":" + subject["qualname"],
            "schema2 selector/subject differs",
        )
        identity = json.dumps(subject, sort_keys=True)
        check(identity not in subjects, "duplicate schema2 subject")
        source, expected, span = item["origin_source"], item["expected"], item["origin_span"]
        check(
            isinstance(source, dict)
            and set(source) == {"path", "sha256", "size"}
            and source["path"] == subject["path"]
            and isinstance(source["sha256"], str)
            and re.fullmatch("[a-f0-9]{64}", source["sha256"]) is not None
            and type(source["size"]) is int
            and 0 <= source["size"] <= 2 * 1024**2,
            "schema2 portable source differs",
        )
        check(
            isinstance(expected, dict)
            and set(expected) == {"format", "text", "truncated"}
            and expected["format"] == FORMAT
            and isinstance(expected["text"], str)
            and 1 <= len(expected["text"]) <= 2400
            and type(expected["truncated"]) is bool
            and (not expected["truncated"] or len(expected["text"]) == 2400),
            "schema2 literal tuple differs",
        )
        expected["text"].encode("utf-8")
        check(
            isinstance(span, dict)
            and set(span) == {"first_line", "last_line"}
            and all(type(v) is int for v in span.values())
            and 1 <= span["first_line"] <= span["last_line"],
            "schema2 origin span differs",
        )
        payload = {
            "type": item["kind"],
            **{key: item[key] for key in ["subject", "expected", "origin_source", "origin_span"]},
        }
        records.append({"id": item["id"], "payload": payload, "source": source})
        ids.add(item["id"])
        subjects.add(identity)
    return {key: seed[key] for key in ["schema_version", "source_roots", "excluded_paths"]} | {
        "records": records
    }
