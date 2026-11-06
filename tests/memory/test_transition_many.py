"""Exact-subject batching against the retained pre-index scan implementation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from types import ModuleType

import pytest

from cami.product.memory import validation
from cami.product.memory.models import (
    CodeView, DefinitionFact, ExistsPayload, IndexRef, NotePayload, PathCoverage,
    PythonDefinitionSpan, PythonExcerptExpected, PythonExcerptReady, PythonExcerptUnavailable,
    PythonSignature, RecordRevision, RememberInput, SignaturePayload, SourceExcerptPayload, SourceRef, SymbolKey,
)
from cami.product.models import digest
from cami.product.service import ProductMemory

RAW = b"def target():\n    return 1\n"


@pytest.fixture
def scan_reference():
    path = Path(__file__).with_name("fixtures") / "validation_scan_reference.py.txt"
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "16a44a5c32a91a3e57c1435441782896df2f9005c28c501f277493750e8dbdfb"
    reference = ModuleType("validation_scan_reference")
    # Only the old fingerprint's source-location context changes. The retained
    # scan/dependency/check/transition bodies execute verbatim, with today's fingerprint.
    reference.__file__ = validation.__file__
    exec(compile(raw, str(path), "exec"), reference.__dict__)
    reference.VALIDATOR_FINGERPRINT = validation.VALIDATOR_FINGERPRINT
    return reference


def view(raw=RAW, tag="origin"):
    index = IndexRef(worktree_key=digest("worktree"), snapshot_id=digest([tag, "snapshot"]),
                     generation_id=digest([tag, "generation"]),
                     policy_fingerprint=digest("policy"), analyzer_fingerprint=digest("analyzer"))
    source = SourceRef(index=index, path="api.py", sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))
    subject = SymbolKey(language="python", path=source.path, qualname="target", node_kind="function")
    signature = PythonSignature(parameters=(), returns=None, decorators=(), type_parameters=(), is_async=False)
    excerpt = PythonExcerptReady(span=PythonDefinitionSpan(first_line=1, last_line=2),
                                 prefix_characters=len(raw), prefix_sha256=hashlib.sha256(raw).hexdigest(),
                                 truncated=False)
    definition = DefinitionFact(subject=subject, signature=signature, source=source,
                                ambiguous=False, python_excerpt=excerpt)
    return CodeView(index=index, definitions=(definition,), sources=(source,),
                    coverage=(PathCoverage(path=source.path, status="present"),),
                    relation_scopes=(digest([tag, "edge"]),))


def records(origin):
    fact = origin.definitions[0]
    payloads = (
        ExistsPayload(subject=fact.subject),
        SignaturePayload(subject=fact.subject, expected=fact.signature),
        NotePayload(subject=fact.subject, note_key="manual", text="Freeform manual text.", sources=origin.sources),
        SourceExcerptPayload(subject=fact.subject, expected=PythonExcerptExpected(text=RAW.decode(), truncated=False),
                             origin_source=fact.source, origin_span=fact.python_excerpt.span),
    )
    return tuple(RecordRevision(memory_id=digest(payload.type), revision=1, payload=payload,
                                origin=origin.index, created_at="authored", previous_revision=None)
                 for payload in payloads)


def serialized(value):
    """Normalize only actual-check wall timestamps, preserving every other field."""
    if isinstance(value, tuple):
        return [serialized(item) for item in value]
    result = json.loads(value.model_dump_json())

    def normalize(item):
        if isinstance(item, dict):
            return {key: "<checked_at>" if key == "checked_at" else normalize(part)
                    for key, part in item.items()}
        if isinstance(item, list):
            return [normalize(part) for part in item]
        return item

    return normalize(result)


SCENARIOS = (
    "unique", "missing", "duplicate", "ambiguous", "uncertain", "parse_error",
    "excluded", "absent", "signature_mismatch", "signature_unavailable", "excerpt_unavailable",
    "excerpt_legacy", "excerpt_mismatch", "source_unbound", "changed_source",
)


def changed(origin, scenario):
    fact = origin.definitions[0]
    changes = {}
    if scenario == "missing":
        changes["definitions"] = ()
    elif scenario == "duplicate":
        other_source = fact.source.model_copy(update={"sha256": digest("other")})
        other = fact.model_copy(update={"source": other_source})
        changes.update(definitions=(other, fact, other), sources=(fact.source, other_source))
    elif scenario in ("ambiguous", "uncertain"):
        flag = "ambiguous" if scenario == "ambiguous" else "identity_uncertain"
        changes["definitions"] = (fact.model_copy(update={flag: True}),)
    elif scenario == "parse_error":
        changes["path_errors"] = ((fact.subject.path, "parse_error"),)
    elif scenario in ("excluded", "absent"):
        changes["coverage"] = (PathCoverage(path=fact.subject.path, status=scenario),)
        changes["definitions"] = ()
    elif scenario == "signature_mismatch":
        changes["definitions"] = (fact.model_copy(update={"signature": fact.signature.model_copy(update={"returns": "Name(id='str')"})}),)
    elif scenario == "signature_unavailable":
        changes["definitions"] = (fact.model_copy(update={"signature": None}),)
    elif scenario in ("excerpt_unavailable", "excerpt_legacy"):
        projection = PythonExcerptUnavailable(reason="unsupported_encoding") if scenario == "excerpt_unavailable" else None
        changes["definitions"] = (fact.model_copy(update={"python_excerpt": projection}),)
    elif scenario == "excerpt_mismatch":
        changes["definitions"] = (fact.model_copy(update={"python_excerpt": fact.python_excerpt.model_copy(update={"prefix_sha256": digest("different")})}),)
    elif scenario == "source_unbound":
        changes["sources"] = ()
    elif scenario == "changed_source":
        return view(RAW.replace(b"1", b"2"), "changed")
    return origin.model_copy(update=changes)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_all_payloads_match_retained_scan_for_fresh_transition_and_direct_entrypoints(scan_reference, scenario):
    origin = view()
    items = records(origin)
    current = changed(origin, scenario)
    actual = validation.transition_many(items, current, {}, origin, "transition")
    expected = tuple(scan_reference.transition(item, current, None, origin, "transition") for item in items)
    assert serialized(actual) == serialized(expected)
    assert [state.record.memory_id for state in actual] == [item.memory_id for item in items]
    for item, state in zip(items, actual, strict=True):
        assert validation.dependencies(item, current) == scan_reference.dependencies(item, current)
        assert serialized(validation.check(item, current, "check")) == serialized(scan_reference.check(item, current, "check"))
        assert serialized(validation.transition(item, current, None, origin, "transition")) == serialized(state)
        assert serialized(validation.availability(state)) == serialized(scan_reference.availability(state))


def test_carry_recheck_recovery_and_sticky_notes_match_scan_history(scan_reference):
    origin = view()
    items = records(origin)
    prior, expected_prior = {}, {}
    previous_view = None
    history = (origin, view(tag="moved"), view(RAW.replace(b"1", b"2"), "changed"),
               view(tag="restored"), changed(view(tag="duplicate"), "duplicate"),
               view(tag="recovered"))
    for step, current in enumerate(history):
        transition_id = f"transition-{step}"
        actual = validation.transition_many(items, current, prior, previous_view, transition_id)
        expected = tuple(scan_reference.transition(item, current, expected_prior.get(item.memory_id),
                                                   previous_view, transition_id) for item in items)
        assert serialized(actual) == serialized(expected)
        prior = {state.record.memory_id: state for state in actual}
        expected_prior = {state.record.memory_id: state for state in expected}
        previous_view = current


def test_ordered_duplicates_and_pydantic_key_type_equality_remain_exact(scan_reference):
    class DerivedKey(SymbolKey):
        pass

    origin = view()
    fact = origin.definitions[0]
    derived = fact.model_copy(update={"subject": DerivedKey(**fact.subject.model_dump())})
    other_source = fact.source.model_copy(update={"sha256": digest("second occurrence")})
    second = fact.model_copy(update={"source": other_source, "ambiguous": True})
    current = origin.model_copy(update={"definitions": (derived, second, fact, second)})
    base_item = records(origin)[0]
    derived_item = base_item.model_copy(update={"memory_id": digest("derived"),
        "payload": ExistsPayload(subject=derived.subject)})
    assert type(derived_item.payload.subject) is DerivedKey
    items = (base_item, derived_item)
    actual = validation.transition_many(items, current, {}, None, "keys")
    expected = tuple(scan_reference.transition(item, current, None, None, "keys") for item in items)
    assert serialized(actual) == serialized(expected)
    assert actual[0].state.check.evidence == (second.source, fact.source, second.source)
    assert actual[0].state.check.reason == "ambiguous_binding"
    assert actual[1].state.check.verdict == "supported"


@pytest.mark.parametrize("field,value", [("language", "js"), ("path", "other.py"),
                                         ("qualname", "other"), ("node_kind", "method")])
def test_all_subject_fields_participate_in_index(field, value, scan_reference):
    origin = view()
    fact = origin.definitions[0]
    changed_fact = fact.model_copy(update={"subject": fact.subject.model_copy(update={field: value})})
    current = origin.model_copy(update={"definitions": (changed_fact,)})
    item = records(origin)[0]
    actual = validation.transition_many((item,), current, {}, None, "changed-key")[0]
    assert serialized(actual) == serialized(scan_reference.transition(item, current, None, None, "changed-key"))
    assert actual.state.check.reason == "subject_absent"


def test_copied_views_with_same_index_get_fresh_lookup_without_hashing_view(monkeypatch):
    origin = view()
    items = records(origin)

    def forbidden(*args, **kwargs):
        raise AssertionError("bulk validation must not hash the whole view or fall back to scans")

    monkeypatch.setattr(CodeView, "__hash__", forbidden)
    monkeypatch.setattr(validation, "matches", forbidden)
    initial = validation.transition_many(items, origin, {}, None, "initial")
    copied = origin.model_copy(update={"definitions": ()})
    assert copied.index is origin.index
    missing = validation.transition_many(items, copied, {}, None, "missing")
    assert initial[0].state.check.verdict == "supported"
    assert missing[0].state.check.reason == "subject_absent"
    assert validation.transition_many((), origin, {}, None, "empty") == ()


def test_bulk_removes_repeated_subject_comparisons_without_dropping_records(monkeypatch, scan_reference):
    origin = view()
    fact = origin.definitions[0]
    definitions = tuple(fact.model_copy(update={"subject": fact.subject.model_copy(update={"qualname": f"f{i}"})}) for i in range(24))
    current = origin.model_copy(update={"definitions": definitions})
    items = tuple(RecordRevision(memory_id=digest(i), revision=1,
        payload=ExistsPayload(subject=SymbolKey.model_validate_json(definition.subject.model_dump_json())),
        origin=current.index, created_at="authored", previous_revision=None)
        for i, definition in enumerate(definitions))
    comparisons = 0
    original_equal = SymbolKey.__eq__

    def equal(left, right):
        nonlocal comparisons
        comparisons += 1
        return original_equal(left, right)

    monkeypatch.setattr(SymbolKey, "__eq__", equal)
    expected = tuple(scan_reference.transition(item, current, None, None, "count") for item in items)
    scan_comparisons = comparisons
    comparisons = 0
    actual = validation.transition_many(items, current, {}, None, "count")
    indexed_comparisons = comparisons
    assert serialized(actual) == serialized(expected)
    assert scan_comparisons == 2 * len(items) * len(definitions)
    assert indexed_comparisons < scan_comparisons / 4


def test_service_builds_once_per_transition_and_skips_unchanged_generation(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "api.py").write_bytes(RAW)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    service = ProductMemory(root)
    calls = []
    original = validation._definition_index

    def counted(current):
        calls.append(current)
        return original(current)

    monkeypatch.setattr(validation, "_definition_index", counted)
    context = service.context("api.py:target")
    assert not calls  # Initial empty catalog needs no subject index.
    service.remember_batch(tuple(RememberInput(
        kind=kind, query="api.py:target", context=context, request_id=kind,
        note_key="manual" if kind == "note" else None,
        text="Authored manual note." if kind == "note" else None)
        for kind in ("symbol_exists", "signature_equals", "note", "source_excerpt_equals")))
    assert len(calls) == 1
    same = service.context("api.py:target")
    again = service.context("api.py:target")
    assert same.memory_generation_id == again.memory_generation_id
    assert len(calls) == 1
    (root / "api.py").write_bytes(RAW.replace(b"1", b"2"))
    fresh = service.context("api.py:target")
    assert fresh.memory_generation_id != same.memory_generation_id
    assert len(calls) == 2
