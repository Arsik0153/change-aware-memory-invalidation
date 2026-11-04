"""Explicit schema2 literal comparison data and common stdlib origin reauthentication."""

from __future__ import annotations

import json
import re

from literal_source import (
    FORMAT,
    LIMIT,
    MAX_SOURCE_BYTES,
    literal,
    prepare_module,
    read_source,
    safe_relative,
    source_ref,
)

KEYS = {"schema_version", "source_roots", "excluded_paths", "records"}


def check(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode()


def validate_policy(value):
    check(
        isinstance(value, dict)
        and set(value) == KEYS
        and type(value["schema_version"]) is int
        and value["schema_version"] == 2,
        "literal policy requires explicit schema2",
    )
    for key in ["source_roots", "excluded_paths"]:
        check(
            isinstance(value[key], list) and all(isinstance(p, str) for p in value[key]),
            "invalid literal policy paths",
        )
        for path in value[key]:
            if path != ".":
                safe_relative(path)
    check(bool(value["source_roots"]), "empty literal source roots")
    check(
        isinstance(value["records"], list) and 1 <= len(value["records"]) <= 1024,
        "literal policy requires1..1024records",
    )
    check(len(canonical(value)) <= 4 * 1024 * 1024, "literal policy exceeds4MiB")


def validate_source(value, path):
    check(
        isinstance(value, dict) and set(value) == {"path", "sha256", "size"},
        "portable literal source requires path/hash/size only",
    )
    check(
        value["path"] == path
        and isinstance(value["sha256"], str)
        and re.fullmatch("[a-f0-9]{64}", value["sha256"]) is not None
        and type(value["size"]) is int
        and 0 <= value["size"] <= MAX_SOURCE_BYTES,
        "invalid literal source binding",
    )


def validate_payload(payload):
    check(
        isinstance(payload, dict)
        and set(payload) == {"type", "subject", "expected", "origin_source", "origin_span"}
        and payload["type"] == "source_excerpt_equals",
        "schema2 supports only explicit source excerpt payloads",
    )
    subject = payload["subject"]
    check(
        isinstance(subject, dict)
        and set(subject) == {"language", "path", "qualname", "node_kind"}
        and all(isinstance(v, str) and bool(v) for v in subject.values())
        and subject["language"] == "python"
        and subject["node_kind"] in {"function", "method"},
        "invalid literal Python subject",
    )
    safe_relative(subject["path"])
    expected = payload["expected"]
    check(
        isinstance(expected, dict)
        and set(expected) == {"format", "text", "truncated"}
        and expected["format"] == FORMAT
        and isinstance(expected["text"], str)
        and 1 <= len(expected["text"]) <= LIMIT
        and type(expected["truncated"]) is bool
        and (not expected["truncated"] or len(expected["text"]) == LIMIT),
        "invalid literal tuple",
    )
    expected["text"].encode("utf-8")
    span = payload["origin_span"]
    check(
        isinstance(span, dict)
        and set(span) == {"first_line", "last_line"}
        and all(type(span[k]) is int for k in span)
        and 1 <= span["first_line"] <= span["last_line"],
        "invalid literal origin span",
    )
    validate_source(payload["origin_source"], subject["path"])


def validate_catalog2(value):
    validate_policy(value)
    ids, subjects = set(), set()
    for record in value["records"]:
        check(
            isinstance(record, dict) and set(record) == {"id", "payload", "source"},
            "invalid literal catalog record",
        )
        check(
            isinstance(record["id"], str)
            and 0 < len(record["id"]) <= 200
            and record["id"] not in ids,
            "duplicate/invalid literal ID",
        )
        validate_payload(record["payload"])
        source = record["payload"]["origin_source"]
        check(
            record["source"] == source, "literal source wrapper differs from payload origin source"
        )
        identity = canonical(record["payload"]["subject"])
        check(identity not in subjects, "duplicate literal subject identity")
        ids.add(record["id"])
        subjects.add(identity)
    return value


def catalog_from_seed2(seed):
    validate_policy(seed)
    records = []
    for item in seed["records"]:
        check(
            isinstance(item, dict)
            and set(item)
            == {"id", "kind", "selector", "subject", "expected", "origin_source", "origin_span"},
            "schema2 seed forbids manual text/note_key and unrecognized fields",
        )
        check(item["kind"] == "source_excerpt_equals", "no automatic manual-note conversion")
        payload = {
            key: item[key] for key in ["subject", "expected", "origin_source", "origin_span"]
        }
        payload["type"] = item["kind"]
        validate_payload(payload)
        check(
            item["selector"] == item["subject"]["path"] + ":" + item["subject"]["qualname"],
            "literal selector/subject mismatch",
        )
        records.append({"id": item["id"], "payload": payload, "source": item["origin_source"]})
    return validate_catalog2(
        {key: seed[key] for key in ["schema_version", "source_roots", "excluded_paths"]}
        | {"records": records}
    )


def reauthenticate(repo, policy, *, seed):
    """Comparison-only expected values never become CAMI registration inputs."""
    catalog = catalog_from_seed2(policy) if seed else validate_catalog2(policy)
    grouped = {}
    for record in catalog["records"]:
        grouped.setdefault(record["source"]["path"], []).append(record)
    for path, records in grouped.items():
        check(
            any(
                root == "." or path == root or path.startswith(root + "/")
                for root in catalog["source_roots"]
            ),
            "literal subject outside declared source roots",
        )
        check(
            not any(
                excluded == "." or path == excluded or path.startswith(excluded + "/")
                for excluded in catalog["excluded_paths"]
            ),
            "literal subject is explicitly excluded",
        )
        raw = read_source(repo, path)
        actual_source, module = source_ref(path, raw), prepare_module(raw)
        for record in records:
            payload, source = record["payload"], record["source"]
            kind, expected, span = literal(module, payload["subject"]["qualname"])
            check(actual_source == source, "literal origin source bytes differ")
            check(
                kind == payload["subject"]["node_kind"]
                and expected == payload["expected"]
                and span == payload["origin_span"],
                "literal frozen tuple/span/subject differs from canonical origin",
            )
        # No cache of all module ASTs/bytes: retain only one prepared module at once.
    return catalog, {"prepared_modules": len(grouped), "records": len(catalog["records"])}


def verify_origin_sources(repo, catalog):
    sources = {record["source"]["path"]: record["source"] for record in catalog["records"]}
    for path, expected in sources.items():
        check(
            source_ref(path, read_source(repo, path)) == expected,
            "literal origin source changed during preparation",
        )
    return len(sources)
