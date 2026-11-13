"""Frozen semantic catalog plus static or existing ProductMemory lookup backend."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import resource
import re
import stat
import time

from literal_catalog import (
    catalog_from_seed2,
    reauthenticate,
    validate_catalog2,
    verify_origin_sources,
)

MAX_JSON_BYTES = 4 * 1024 * 1024


def check(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def load(path):
    with path.open("rb") as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    check(len(raw) <= MAX_JSON_BYTES, "JSON file too large")
    return json.loads(raw)


def save(path, value):
    path.write_bytes(canonical(value) + b"\n")


def storage(path):
    return (
        sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())
        if path.exists()
        else 0
    )


def cpu():
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time() + children.ru_utime + children.ru_stime


def source_record(path):
    subject_path = PurePosixPath(path)
    check(
        not subject_path.is_absolute()
        and ".." not in subject_path.parts
        and str(subject_path) == path
        and "\\" not in path
        and "\x00" not in path
        and path != ".",
        "unsafe source path",
    )


def plain_payload(payload):
    value = payload.model_dump(mode="json")
    if value["type"] == "source_excerpt_equals":
        value["origin_source"] = dict(value["origin_source"])
        value["origin_source"].pop("index")
    if value["type"] == "note":
        value["sources"] = [
            {key: s[key] for key in ("path", "sha256", "size")} for s in value["sources"]
        ]
    return value


def validate_catalog(value):
    if isinstance(value, dict) and value.get("schema_version") == 2:
        return validate_catalog2(value)
    check(
        isinstance(value, dict)
        and set(value) == {"schema_version", "source_roots", "excluded_paths", "records"}
        and type(value["schema_version"]) is int
        and value["schema_version"] == 1,
        "invalid catalog schema",
    )
    for key in ("source_roots", "excluded_paths"):
        check(
            isinstance(value[key], list) and all(isinstance(p, str) for p in value[key]),
            "invalid catalog policy",
        )
        for path in value[key]:
            if path != ".":
                source_record(path)
    check(bool(value["source_roots"]), "empty source roots")
    check(
        isinstance(value["records"], list) and 1 <= len(value["records"]) <= 1024,
        "catalog requires 1..1024 records",
    )
    ids, identities = set(), set()
    for record in value["records"]:
        check(
            isinstance(record, dict) and set(record) == {"id", "payload", "source"},
            "invalid catalog record",
        )
        check(
            isinstance(record["id"], str)
            and 0 < len(record["id"]) <= 200
            and record["id"] not in ids,
            "invalid/duplicate record ID",
        )
        ids.add(record["id"])
        payload = record["payload"]
        check(
            isinstance(payload, dict)
            and payload.get("type") in ("symbol_exists", "signature_equals", "note"),
            "unsupported payload",
        )
        subject = payload.get("subject")
        check(
            isinstance(subject, dict)
            and set(subject) == {"language", "path", "qualname", "node_kind"}
            and all(isinstance(v, str) and v for v in subject.values()),
            "invalid subject",
        )
        source_record(subject["path"])
        source = record["source"]
        check(
            isinstance(source, dict)
            and set(source) == {"path", "sha256", "size"}
            and source["path"] == subject["path"]
            and isinstance(source["sha256"], str)
            and len(source["sha256"]) == 64
            and all(c in "0123456789abcdef" for c in source["sha256"])
            and type(source["size"]) is int
            and 0 <= source["size"] <= 2 * 1024**2,
            "invalid source binding",
        )
        kind = payload["type"]
        common = {"type", "subject"}
        if kind == "symbol_exists":
            check(
                set(payload) == common | {"expected"} and payload["expected"] is True,
                "invalid exists payload",
            )
        elif kind == "signature_equals":
            check(
                set(payload) == common | {"expected"}
                and isinstance(payload["expected"], dict)
                and payload["expected"].get("format")
                in ("python.ast-signature/1", "ecma.syntax-signature/2"),
                "invalid signature payload",
            )
        else:
            check(
                set(payload) == common | {"note_key", "text", "sources"}
                and all(isinstance(payload[k], str) and payload[k] for k in ("note_key", "text"))
                and payload["sources"] == [source],
                "invalid manual note payload",
            )
        identity = digest(["note", payload["note_key"]] if kind == "note" else [subject, kind])
        check(identity not in identities, "duplicate semantic record identity")
        identities.add(identity)
    check(len(canonical(value)) <= MAX_JSON_BYTES, "catalog too large")
    return value


def validate_seed_spec(spec):
    if isinstance(spec, dict) and spec.get("schema_version") == 2:
        catalog_from_seed2(spec)
        return spec
    check(
        isinstance(spec, dict)
        and set(spec) == {"schema_version", "source_roots", "excluded_paths", "records"}
        and type(spec["schema_version"]) is int
        and spec["schema_version"] == 1
        and isinstance(spec["records"], list)
        and 1 <= len(spec["records"]) <= 1024,
        "invalid seed spec",
    )
    ids, note_keys = set(), set()
    for item in spec["records"]:
        check(
            isinstance(item, dict)
            and set(item) <= {"id", "kind", "selector", "subject", "note_key", "text"}
            and {"id", "kind", "selector"} <= set(item),
            "invalid seed item",
        )
        check(
            isinstance(item["id"], str) and item["id"] and item["id"] not in ids,
            "duplicate/invalid seed ID",
        )
        ids.add(item["id"])
        check(
            item["kind"] in ("note", "symbol_exists", "signature_equals")
            and isinstance(item["selector"], str)
            and item["selector"],
            "invalid seed selector/kind",
        )
        if item["kind"] == "note":
            key = item.get("note_key")
            check(
                isinstance(key, str) and key and isinstance(item.get("text"), str) and item["text"],
                "note needs key and text",
            )
            check(key not in note_keys, "duplicate global note_key")
            note_keys.add(key)
    return spec


def freeze_spec(service, spec):
    validate_seed_spec(spec)
    records = []
    contexts = {}
    batch_contexts = service.context_many(tuple(item["selector"] for item in spec["records"]))
    for item, context in zip(spec["records"], batch_contexts, strict=True):
        check(
            set(item) <= {"id", "kind", "selector", "subject", "note_key", "text"}
            and {"id", "kind", "selector"} <= set(item),
            "invalid seed item",
        )
        check(
            len(context.code) == 1
            and not context.code[0].ambiguous
            and not context.code[0].identity_uncertain,
            "seed requires unique supported symbol",
        )
        fact = context.code[0]
        check(
            "subject" not in item or fact.subject.model_dump(mode="json") == item["subject"],
            "seed subject differs from authenticated symbol",
        )
        source = {
            key: fact.source.model_dump(mode="json")[key] for key in ("path", "sha256", "size")
        }
        payload = {"type": item["kind"], "subject": fact.subject.model_dump(mode="json")}
        if item["kind"] == "symbol_exists":
            payload["expected"] = True
        elif item["kind"] == "signature_equals":
            check(fact.signature is not None, "unsupported signature")
            payload["expected"] = fact.signature.model_dump(mode="json")
        elif item["kind"] == "note":
            payload.update(note_key=item.get("note_key"), text=item.get("text"), sources=[source])
        else:
            raise ValueError("unsupported seed kind")
        records.append({"id": item["id"], "payload": payload, "source": source})
        contexts[item["id"]] = context
    catalog = validate_catalog(
        {key: spec[key] for key in ("schema_version", "source_roots", "excluded_paths")}
        | {"records": records}
    )
    return catalog, contexts


LEXICAL_RANKING = "lexical-overlap/1"
IDENTIFIER_RANKING = "identifier-mentions/1"
RANKING_POLICIES = (LEXICAL_RANKING, IDENTIFIER_RANKING)


def identifier_mentions(query):
    names = set(re.findall(r"[^\W\d]\w*(?:\.[^\W\d]\w*)*", query))
    qualified = {".".join(name.split(".")[offset:]).casefold()
                 for name in names for offset in range(len(name.split(".")))}
    return names, qualified


def mention_priority(subject, mentions):
    names, folded = mentions
    qualname = subject["qualname"]
    if "." in qualname and qualname.casefold() in folded:
        return 0
    basename = qualname.rsplit(".", 1)[-1]
    if ("_" in basename and basename.casefold() in folded
            or any(c.isupper() for c in basename) and basename in names):
        return 1
    return 2


def rank(catalog, query, limit, *, ranking_policy=LEXICAL_RANKING):
    check(ranking_policy in RANKING_POLICIES, "unsupported ranking policy")
    check(
        isinstance(query, str) and 0 < len(query.strip()) <= 1000 and "\x00" not in query,
        "query must be 1..1000 non-NUL characters",
    )
    check(type(limit) is int and 1 <= limit <= 20, "limit must be integer 1..20")
    mentions = identifier_mentions(query) if ranking_policy == IDENTIFIER_RANKING else None
    query = query.strip().casefold()
    tokens = set(re.findall(r"[^\W_]+", query))
    check(bool(tokens), "query requires a name, path or text token")
    results = []
    for record in catalog["records"]:
        payload, subject = record["payload"], record["payload"]["subject"]
        exact = [
            record["id"],
            subject["qualname"],
            subject["qualname"].rsplit(".", 1)[-1],
            subject["path"] + ":" + subject["qualname"],
        ]
        identity_tokens = set(re.findall(r"[^\W_]+", " ".join(exact).casefold()))
        literal_text = (
            payload["expected"]["text"]
            if payload["type"] == "source_excerpt_equals"
            else payload.get("text", "")
        )
        text_tokens = set(
            re.findall(r"[^\W_]+", (literal_text + " " + payload.get("note_key", "")).casefold())
        )
        overlap = len(tokens & identity_tokens) * 4 + len(tokens & text_tokens)
        is_exact = query in [item.casefold() for item in exact]
        if is_exact or overlap:
            priority = mention_priority(subject, mentions) if mentions is not None else 2
            results.append((0 if is_exact else 1, priority, -overlap, record["id"], record))
    results.sort(key=lambda item: item[:4])
    selected, used = [], 0
    for _, _, _, _, record in results[:limit]:
        cost = len(canonical(record))
        if used + cost > 16384:
            break
        used += cost
        selected.append(record)
    return selected, len(results)


def origin_source(repo, path):
    source_record(path)
    location = repo / path
    check(
        not any(
            parent.is_symlink()
            for parent in [location, *location.parents]
            if parent.is_relative_to(repo)
        ),
        "origin symlink unsupported",
    )
    fd = os.open(location, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        check(
            stat.S_ISREG(info.st_mode) and info.st_size <= 2 * 1024**2,
            "unsupported origin source size/type",
        )
        with os.fdopen(fd, "rb", closefd=False) as stream:
            content = stream.read(info.st_size + 1)
        check(len(content) == info.st_size, "origin source changed during read")
        return {"path": path, "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}
    finally:
        os.close(fd)


def static_spec(repo, spec):
    validate_seed_spec(spec)
    records = []
    for item in spec["records"]:
        check(
            set(item) == {"id", "kind", "selector", "subject", "note_key", "text"}
            and item["kind"] == "note",
            "static seed spec supports source-asserted notes with explicit subject only",
        )
        subject = item["subject"]
        check(
            item["selector"] == subject["path"] + ":" + subject["qualname"],
            "selector/subject mismatch",
        )
        source = origin_source(repo, subject["path"])
        records.append(
            {
                "id": item["id"],
                "payload": {
                    "type": "note",
                    "subject": subject,
                    "note_key": item["note_key"],
                    "text": item["text"],
                    "sources": [source],
                },
                "source": source,
            }
        )
    return validate_catalog(
        {key: spec[key] for key in ("schema_version", "source_roots", "excluded_paths")}
        | {"records": records}
    )


@contextmanager
def isolated_state(state_home):
    previous = os.environ.get("XDG_STATE_HOME")
    os.environ["XDG_STATE_HOME"] = str(state_home)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = previous


def prepare(backend, repo, output, catalog_path=None, spec_path=None, state_home=None):
    started, started_cpu = time.perf_counter(), cpu()
    check(repo.is_dir(), "repo directory required")
    check(backend in ("static", "cami"), "unknown backend")
    check((catalog_path is None) != (spec_path is None), "one catalog or seed spec required")
    check(not output.is_relative_to(repo), "prepare output must be outside target repo")
    output.mkdir(parents=True, exist_ok=False)
    metrics = {
        "status": "preparing",
        "backend": backend,
        "timing_scope": "prepare function entry through final metrics observation; excludes Python/CLI startup and final metrics write",
    }
    try:
        policy = load(spec_path or catalog_path)
        validate_seed_spec(policy) if spec_path else validate_catalog(policy)
        literal_catalog = None
        if policy["schema_version"] == 2:
            capture_started, capture_cpu = time.perf_counter(), cpu()
            literal_catalog, authentication = reauthenticate(
                repo, policy, seed=spec_path is not None
            )
            metrics["literal_origin_reauthentication"] = {
                **authentication,
                "wall_seconds": time.perf_counter() - capture_started,
                "cpu_seconds_self_and_completed_children": cpu() - capture_cpu,
                "before_backend_construction": True,
            }
        if backend == "cami":
            check(
                state_home is not None
                and not state_home.exists()
                and not state_home.is_relative_to(repo),
                "CAMI state must be a new directory outside repo",
            )
            state_home.mkdir(parents=True)
            with isolated_state(state_home):
                from cami.product.service import ProductMemory
                from cami.product.memory.validation import availability
                from cami.product.memory.models import RememberInput

                service = ProductMemory(
                    repo, tuple(policy["source_roots"]), tuple(policy["excluded_paths"])
                )
                capture_started, capture_cpu = time.perf_counter(), cpu()
                if literal_catalog is not None:
                    catalog = literal_catalog
                    selectors = tuple(
                        r["payload"]["subject"]["path"] + ":" + r["payload"]["subject"]["qualname"]
                        for r in catalog["records"]
                    )
                    contexts = {
                        r["id"]: context
                        for r, context in zip(
                            catalog["records"], service.context_many(selectors), strict=True
                        )
                    }
                elif spec_path:
                    catalog, contexts = freeze_spec(service, policy)
                else:
                    catalog = validate_catalog(policy)
                    selectors = tuple(
                        r["payload"]["subject"]["path"] + ":" + r["payload"]["subject"]["qualname"]
                        for r in catalog["records"]
                    )
                    contexts = {
                        r["id"]: context
                        for r, context in zip(
                            catalog["records"], service.context_many(selectors), strict=True
                        )
                    }
                metrics["catalog_capture"] = {
                    "wall_seconds": time.perf_counter() - capture_started,
                    "cpu_seconds_self_and_completed_children": cpu() - capture_cpu,
                    "created_from_spec": spec_path is not None,
                }
                mapping = {}
                requests = []
                entry_started, entry_cpu = time.perf_counter(), cpu()
                for record in catalog["records"]:
                    payload = record["payload"]
                    subject = payload["subject"]
                    selector = subject["path"] + ":" + subject["qualname"]
                    context = contexts[record["id"]]
                    check(
                        len(context.code) == 1
                        and context.code[0].subject.model_dump(mode="json") == subject,
                        "catalog subject differs from current source",
                    )
                    source = context.code[0].source.model_dump(mode="json")
                    check(
                        all(source[k] == v for k, v in record["source"].items()),
                        "catalog origin bytes differ; prepare at seed version first",
                    )
                    if payload["type"] == "signature_equals":
                        check(
                            context.code[0].signature is not None
                            and context.code[0].signature.model_dump(mode="json")
                            == payload["expected"],
                            "catalog signature differs from backend",
                        )
                    if payload["type"] == "source_excerpt_equals":
                        fact = context.code[0]
                        check(
                            not fact.ambiguous and not fact.identity_uncertain,
                            "literal seed requires one certain source subject",
                        )
                        certificate = getattr(fact, "python_excerpt", None)
                        certificate = (
                            certificate.model_dump(mode="json") if certificate is not None else None
                        )
                        check(
                            certificate is not None
                            and certificate.get("status") == "ready"
                            and certificate.get("format") == payload["expected"]["format"]
                            and certificate.get("span") == payload["origin_span"]
                            and certificate.get("prefix_characters")
                            == len(payload["expected"]["text"])
                            and certificate.get("prefix_sha256")
                            == hashlib.sha256(payload["expected"]["text"].encode()).hexdigest()
                            and certificate.get("truncated") == payload["expected"]["truncated"],
                            "literal context certificate differs from frozen comparison",
                        )
                        requests.append(
                            RememberInput(
                                kind=payload["type"],
                                query=selector,
                                context=context,
                                request_id="adapter-seed-" + digest(record),
                            )
                        )
                    else:
                        requests.append(
                            RememberInput(
                                kind=payload["type"],
                                query=selector,
                                context=context,
                                request_id="adapter-seed-" + digest(record),
                                note_key=payload.get("note_key"),
                                text=payload.get("text"),
                            )
                        )
                receipts = service.remember_batch(tuple(requests))
                for record, receipt in zip(catalog["records"], receipts, strict=True):
                    mapping[record["id"]] = {
                        "memory_id": receipt.memory_id,
                        "revision": receipt.revision,
                    }
                metrics["registration_batch"] = {
                    "items": len(requests),
                    "wall_seconds": time.perf_counter() - entry_started,
                    "cpu_seconds_self_and_completed_children": cpu() - entry_cpu,
                    "publication": "one atomic post-batch generation; individual intermediate generations are not created",
                }
                generation = service.refresh()
                live = {r.record.memory_id: r.record for r in generation.states}
                check(len(live) == len(mapping), "unexpected prepared memory catalog")
                check(
                    all(not hasattr(availability(item), "reason") for item in generation.states),
                    "seed registration is not initially available",
                )
                for record in catalog["records"]:
                    if literal_catalog is None:
                        check(
                            origin_source(repo, record["source"]["path"]) == record["source"],
                            "seed source changed during preparation",
                        )
                    check(
                        plain_payload(live[mapping[record["id"]]["memory_id"]].payload)
                        == record["payload"],
                        "registered semantic payload mismatch",
                    )
                binding = {
                    "schema_version": 1,
                    "backend": backend,
                    "repo": str(repo),
                    "state_home": str(state_home),
                    "mapping": mapping,
                }
        else:
            check(state_home is None, "static backend has no CAMI state")
            catalog = (
                literal_catalog
                if literal_catalog is not None
                else static_spec(repo, load(spec_path))
                if spec_path
                else validate_catalog(load(catalog_path))
            )
            if literal_catalog is None:
                for record in catalog["records"]:
                    check(
                        origin_source(repo, record["source"]["path"]) == record["source"],
                        "static seed origin bytes differ",
                    )
            binding = {
                "schema_version": 1,
                "backend": backend,
                "repo": str(repo),
                "state_home": None,
                "mapping": {},
            }
        if literal_catalog is not None:
            metrics["literal_origin_reauthentication"]["final_source_reads"] = (
                verify_origin_sources(repo, catalog)
            )
        save(output / "catalog.json", catalog)
        binding.update(catalog_sha256=digest(catalog), catalog_path=str(output / "catalog.json"))
        save(output / "binding.json", binding)
        metrics.update(
            status="complete", catalog_sha256=digest(catalog), records=len(catalog["records"])
        )
        return binding
    except Exception as exc:
        metrics.update(status="failed", error_type=type(exc).__name__, error=str(exc)[:500])
        raise
    finally:
        metrics.update(
            wall_seconds=time.perf_counter() - started,
            cpu_seconds_self_and_completed_children=cpu() - started_cpu,
            state_bytes=storage(state_home) if state_home else 0,
            output_bytes=storage(output),
        )
        save(output / "construction-metrics.json", metrics)


class Backend:
    def __init__(self, binding_path, *, ranking_policy=LEXICAL_RANKING):
        check(ranking_policy in RANKING_POLICIES, "unsupported ranking policy")
        self.ranking_policy = ranking_policy
        self.binding = load(binding_path)
        check(
            set(self.binding)
            == {
                "schema_version",
                "backend",
                "repo",
                "state_home",
                "mapping",
                "catalog_sha256",
                "catalog_path",
            }
            and type(self.binding["schema_version"]) is int
            and self.binding["schema_version"] == 1
            and self.binding["backend"] in ("static", "cami"),
            "invalid binding",
        )
        self.catalog = validate_catalog(load(Path(self.binding["catalog_path"])))
        check(
            digest(self.catalog) == self.binding["catalog_sha256"], "frozen catalog hash mismatch"
        )
        self.service = None
        self.last_generation = None
        if self.binding["backend"] == "cami":
            check(
                set(self.binding["mapping"]) == {r["id"] for r in self.catalog["records"]},
                "binding catalog mismatch",
            )
            state = Path(self.binding["state_home"])
            check(
                state.is_dir() and not state.is_relative_to(Path(self.binding["repo"])),
                "missing/invalid CAMI state directory",
            )

    def lookup(self, query, limit=5):
        selected, total = rank(self.catalog, query, limit, ranking_policy=self.ranking_policy)
        states, generation = {}, None
        if self.binding["backend"] == "cami":
            with isolated_state(Path(self.binding["state_home"])):
                if self.service is None:
                    from cami.product.service import ProductMemory

                    self.service = ProductMemory(
                        Path(self.binding["repo"]),
                        tuple(self.catalog["source_roots"]),
                        tuple(self.catalog["excluded_paths"]),
                    )
                from cami.product.memory.validation import availability

                generation = self.service.refresh()
                by_id = {item.record.memory_id: item for item in generation.states}
                check(
                    len(by_id) == len(self.binding["mapping"]),
                    "current memory catalog membership changed",
                )
                for record in self.catalog["records"]:
                    bound = self.binding["mapping"][record["id"]]
                    item = by_id.get(bound["memory_id"])
                    check(
                        item is not None
                        and item.record.revision == bound["revision"]
                        and plain_payload(item.record.payload) == record["payload"],
                        "current memory differs from frozen catalog",
                    )
                    status = availability(item)
                    states[record["id"]] = (item, status)
        entries, withheld = [], []
        for record in selected:
            entry = {
                "id": record["id"],
                "payload": record["payload"],
                "origin_source": record["source"],
            }
            if generation is None:
                entry.update(
                    availability="unchecked_current",
                    label="origin_literal_source_assertion"
                    if record["payload"]["type"] == "source_excerpt_equals"
                    else "manual_assertion"
                    if record["payload"]["type"] == "note"
                    else "origin_structural_assertion",
                )
                entries.append(entry)
            else:
                item, status = states[record["id"]]
                if hasattr(status, "reason"):
                    withheld.append(
                        {
                            "id": record["id"],
                            "subject": record["payload"]["subject"],
                            "kind": record["payload"]["type"],
                            "reason": status.reason,
                            "required_action": status.required_action,
                        }
                    )
                else:
                    entry.update(
                        availability="manual_assertion_source_unchanged"
                        if item.state.type == "manual_note"
                        else "supported",
                        label="manual_assertion"
                        if item.state.type == "manual_note"
                        else "validated_literal_source"
                        if record["payload"]["type"] == "source_excerpt_equals"
                        else "validated_structural_fact",
                        state_type=item.state.type,
                    )
                    entries.append(entry)
        result = {
            "schema_version": 1,
            "backend": self.binding["backend"],
            "query": query,
            "catalog_sha256": self.binding["catalog_sha256"],
            "matched_records": total,
            "selected_records": len(selected),
            "truncated": total > len(selected),
            "selection_budget": {
                "origin_record_bytes": 16384,
                "used_bytes": sum(len(canonical(r)) for r in selected),
                "ranking_before_availability": True,
            },
            "entries": entries,
            "withheld": withheld,
            "freshness": "origin only; current validity unchecked"
            if generation is None
            else "verified_readset; may change after verification; refresh after edits",
        }
        detail = {
            "selected_records": len(selected),
            "returned_records": len(entries),
            "withheld_records": len(withheld),
        }
        if self.ranking_policy != LEXICAL_RANKING:
            detail["ranking_policy"] = self.ranking_policy
        if generation is not None:
            result["snapshot_id"] = generation.index.snapshot_id
            result["memory_generation_id"] = generation.memory_generation_id
            detail.update(
                generation_changed=generation.memory_generation_id != self.last_generation,
                states_checked_type=sum(s.state.type == "checked" for s in generation.states),
                states_carried_type=sum(s.state.type == "carried" for s in generation.states),
                note_states=sum(s.state.type == "manual_note" for s in generation.states),
                counter_note="State types are not counts of actual validator calls in this lookup.",
            )
            self.last_generation = generation.memory_generation_id
        return result, detail
