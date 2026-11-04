"""Brief extractor/model/transition controls; no worktree capture or SQLite."""
import ast
import hashlib

import pytest
from pydantic import ValidationError

from cami.product.memory.models import (
    CarriedClaim, CheckedClaim, CodeView, DefinitionFact, IndexRef, NotePayload,
    PathCoverage, PythonExcerptExpected, PythonExcerptReady, PythonExcerptUnavailable,
    RecordRevision, SourceExcerptPayload, SourceRef, SymbolKey,
)
from cami.product.memory.python_excerpt import (
    ExcerptUnavailable, PythonExcerptSource, origin_literal_from_certificate as _origin_literal,
    prepare_python_excerpt_source, project_python_excerpt as _project_excerpt,
)
from cami.product.memory.validation import availability, check, dependencies, transition

def project_python_excerpt(raw, node):
    return _project_excerpt(prepare_python_excerpt_source(raw), node)


def origin_literal_from_certificate(raw, cert):
    source = prepare_python_excerpt_source(raw)
    assert isinstance(source, PythonExcerptSource)
    return _origin_literal(source, cert)


SUBJECT = SymbolKey(language='python', path='src/api.py', qualname='f', node_kind='function')
BASE = 'def f():\n    return 1\n'


def view(raw, version='a', *, ambiguous=False, policy='1', analyzer='2'):
    index = IndexRef(worktree_key='0' * 64, snapshot_id=version * 64,
                     generation_id=version * 64, policy_fingerprint=policy * 64,
                     analyzer_fingerprint=analyzer * 64)
    source = SourceRef(index=index, path=SUBJECT.path, sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))
    node = next(n for n in ast.parse(raw.decode()).body if isinstance(n, ast.FunctionDef) and n.name == 'f')
    fact = DefinitionFact(subject=SUBJECT, signature=None, source=source, ambiguous=ambiguous,
                          python_excerpt=project_python_excerpt(raw, node))
    return CodeView(index=index, definitions=(fact,), sources=(source,),
                    coverage=(PathCoverage(path=SUBJECT.path, status='present'),))


def record(origin, raw):
    fact = origin.definitions[0]
    assert isinstance(fact.python_excerpt, PythonExcerptReady)
    payload = SourceExcerptPayload(subject=SUBJECT,
        expected=origin_literal_from_certificate(raw, fact.python_excerpt),
        origin_source=fact.source, origin_span=fact.python_excerpt.span)
    return RecordRevision(memory_id='9' * 64, revision=1, payload=payload, origin=origin.index,
                          created_at='authored', previous_revision=None)


@pytest.mark.parametrize('ending', ['\n', '\r\n', '\r'])
def test_decorator_physical_span_preserves_exact_endings(ending):
    source = ending.join(['# preceding', '@decorator(', '    1,', ')', '# between',
                          'def f():', '    return 1  # tail', '# after', ''])
    node = ast.parse(source).body[0]
    cert = project_python_excerpt(source.encode(), node)
    assert isinstance(cert, PythonExcerptReady)
    expected = origin_literal_from_certificate(source.encode(), cert)
    assert expected.text == ending.join(source.split(ending)[1:7]) + ending
    assert not expected.truncated
    assert 'text' not in cert.model_dump()


@pytest.mark.parametrize('separator', ['\f', '\u2028', '\u0085'])
def test_unicode_separators_do_not_create_python_physical_lines(separator):
    source = 'def f():\n    return "a' + separator + 'b"\n'
    cert = project_python_excerpt(source.encode(), ast.parse(source).body[0])
    assert isinstance(cert, PythonExcerptReady)
    assert origin_literal_from_certificate(source.encode(), cert).text == source


@pytest.mark.parametrize('characters', [2399, 2400, 2401])
def test_unicode_prefix_limit_and_truncation(characters):
    prefix, suffix = 'def f():\n    return "', '"\n'
    source = prefix + '😀' * (characters - len(prefix) - len(suffix)) + suffix
    assert len(source) == characters
    cert = project_python_excerpt(source.encode(), ast.parse(source).body[0])
    assert isinstance(cert, PythonExcerptReady)
    literal = origin_literal_from_certificate(source.encode(), cert)
    assert literal.text == source[:2400] and literal.truncated == (characters > 2400)
    assert cert.prefix_characters == min(characters, 2400)
    assert len(literal.text.encode()) > len(literal.text)


@pytest.mark.parametrize('raw', [b'\xef\xbb\xbf' + BASE.encode(), b'# coding: latin-1\n' + BASE.encode(), b'\xff'])
def test_unsupported_encoding_is_explicit(raw):
    cert = project_python_excerpt(raw, ast.parse(BASE).body[0])
    assert isinstance(cert, PythonExcerptUnavailable) and cert.reason == 'unsupported_encoding'


def test_stale_certificate_cannot_authenticate_changed_raw_source():
    raw = BASE.encode()
    cert = project_python_excerpt(raw, ast.parse(BASE).body[0])
    assert isinstance(cert, PythonExcerptReady)
    with pytest.raises(ExcerptUnavailable):
        origin_literal_from_certificate(raw.replace(b'return 1', b'return 2'), cert)


def test_literal_mismatch_does_not_fall_through_to_exists():
    raw = BASE.encode()
    origin = view(raw)
    item = record(origin, raw)
    result = check(item, view(BASE.replace('1', '2').encode(), 'b'), 'authored-transition')
    assert result.verdict == 'contradicted' and result.reason == 'source_excerpt_mismatch'


def test_unrelated_file_edit_carries_literal_but_manual_note_needs_review():
    raw = BASE.encode()
    origin = view(raw)
    item = record(origin, raw)
    first = transition(item, origin, None, None, 'first')
    moved = view(b'GLOBAL = 2\n\n' + raw, 'b')
    assert dependencies(item, origin).fingerprint == dependencies(item, moved).fingerprint
    carried = transition(item, moved, first, origin, 'second')
    assert isinstance(carried.state, CarriedClaim) and carried.state.check == first.state.check
    assert carried.state.equivalence.to_index == moved.index
    note = item.model_copy(update={'memory_id': '8' * 64,
        'payload': NotePayload(subject=SUBJECT, note_key='manual', text='Unrestricted manual assertion.', sources=origin.sources)})
    note_first = transition(note, origin, None, None, 'n1')
    note_changed = transition(note, moved, note_first, origin, 'n2')
    assert availability(note_changed).reason == 'manual_review_required'
    assert transition(note, origin, note_changed, moved, 'n3').state.review_state == 'needs_review'


def test_policy_change_checks_again_and_mismatch_recovery_has_new_actual_check():
    raw = BASE.encode()
    origin = view(raw)
    item = record(origin, raw)
    first = transition(item, origin, None, None, 'first')
    changed_policy = view(raw, 'b', policy='3')
    policy_checked = transition(item, changed_policy, first, origin, 'policy')
    assert isinstance(policy_checked.state, CheckedClaim)
    changed = view(BASE.replace('1', '2').encode(), 'c')
    mismatch = transition(item, changed, policy_checked, changed_policy, 'mismatch')
    restored = view(raw, 'd')
    recovered = transition(item, restored, mismatch, changed, 'recover')
    assert isinstance(recovered.state, CheckedClaim) and recovered.state.check.verdict == 'supported'
    assert recovered.state.check.index == restored.index


def test_truncated_suffix_change_supports_prefix_only():
    raw = ('def f():\n    return "' + 'x' * 2500 + '"\n').encode()
    origin = view(raw)
    item = record(origin, raw)
    beyond = raw[:-3] + b'y"\n'
    assert beyond[:2400] == raw[:2400] and beyond != raw
    assert check(item, view(beyond, 'b'), 'suffix').verdict == 'supported'
    included = raw[:2399] + b'y' + raw[2400:]
    assert check(item, view(included, 'c'), 'included').verdict == 'contradicted'


def test_uncertain_projection_and_legacy_model_remain_unavailable():
    raw = BASE.encode()
    origin = view(raw)
    item = record(origin, raw)
    fact = origin.definitions[0]
    unavailable = fact.model_copy(update={'python_excerpt': PythonExcerptUnavailable(reason='unsupported_encoding')})
    uncertain = origin.model_copy(update={'definitions': (unavailable,)})
    assert not dependencies(item, uncertain).certain
    assert check(item, uncertain, 'unavailable').verdict == 'insufficient_evidence'
    legacy = fact.model_dump(mode='json')
    legacy.pop('python_excerpt')
    restored = DefinitionFact.model_validate_json(__import__('json').dumps(legacy))
    assert restored.python_excerpt is None


def test_invalid_expected_tuple_and_origin_index_rejected():
    with pytest.raises(ValidationError):
        PythonExcerptExpected(text='short', truncated=True)
    origin = view(BASE.encode())
    item = record(origin, BASE.encode())
    bad = item.model_dump(mode='json')
    bad['origin']['snapshot_id'] = 'f' * 64
    with pytest.raises(ValidationError, match='origin index mismatch'):
        RecordRevision.model_validate_json(__import__('json').dumps(bad))


def test_bare_cr_encoding_cookie_uses_only_two_physical_lines():
    ignored_third = b"# first\r# second\r# coding: latin-1\rdef f():\r    return 1\r"
    assert isinstance(prepare_python_excerpt_source(ignored_third), PythonExcerptSource)
    unsupported_second = b"# first\r# coding: latin-1\rdef f():\r    return 1\r"
    assert isinstance(prepare_python_excerpt_source(unsupported_second), PythonExcerptUnavailable)


def test_projection_prepares_source_once_for_many_definitions(monkeypatch):
    from types import SimpleNamespace
    import cami.product.memory.adapters as adapters
    from cami.models import Node
    source = "\n".join(f"def f{i}():\n    return {i}\n" for i in range(8))
    nodes = ast.parse(source).body
    definitions = tuple(SimpleNamespace(start_line=n.lineno,
        node=Node(path=SUBJECT.path, qualname=n.name), node_kind="function", ambiguous=False) for n in nodes)
    index = view(BASE.encode()).index
    manifest = SimpleNamespace(worktree_key=index.worktree_key, snapshot_id=index.snapshot_id,
        generation_id=index.generation_id, policy=SimpleNamespace(model_dump=lambda **kwargs: {}),
        fingerprint=index.analyzer_fingerprint)
    indexed = SimpleNamespace(generation=SimpleNamespace(manifest=manifest,
        index=SimpleNamespace(modules=(SimpleNamespace(limitation=None, source=source,
            path=SUBJECT.path, definitions=definitions),), edges=())),
        capture=SimpleNamespace(blobs=(SimpleNamespace(path=SUBJECT.path, content=source.encode()),), path_coverage=()))
    calls = []
    original = adapters.prepare_python_excerpt_source
    def counted(raw, **kwargs):
        calls.append(len(raw))
        return original(raw, **kwargs)
    monkeypatch.setattr(adapters, "prepare_python_excerpt_source", counted)
    projected = adapters.PythonIndexAdapter().project(indexed)
    assert len(projected.definitions) == 8 and len(calls) == 1
    assert all(isinstance(d.python_excerpt, PythonExcerptReady) for d in projected.definitions)


def test_verification_cache_is_unique_full_ref_and_operation_local(monkeypatch):
    from types import SimpleNamespace
    import cami.product.service as service
    raw = "\n".join(f"def f{i}():\n    return {i}\n" for i in range(8)).encode()
    index = view(BASE.encode()).index
    source_ref = SourceRef(index=index, path=SUBJECT.path,
                           sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))
    prepared = prepare_python_excerpt_source(raw)
    assert isinstance(prepared, PythonExcerptSource)
    facts, records = [], []
    for i, node in enumerate(ast.parse(raw.decode()).body):
        subject = SUBJECT.model_copy(update={"qualname": node.name})
        cert = _project_excerpt(prepared, node)
        assert isinstance(cert, PythonExcerptReady)
        facts.append(DefinitionFact(subject=subject, signature=None, source=source_ref,
                                    ambiguous=False, python_excerpt=cert))
        records.append(RecordRevision(memory_id=f"{i:064x}", revision=1,
            payload=SourceExcerptPayload(subject=subject, expected=_origin_literal(prepared, cert),
                origin_source=source_ref, origin_span=cert.span),
            origin=index, created_at="authored", previous_revision=None))
    origin = CodeView(index=index, definitions=tuple(facts), sources=(source_ref,),
                      coverage=(PathCoverage(path=SUBJECT.path, status="present"),))
    states = [transition(r, origin, None, None, "first") for r in records]
    owner = object.__new__(service.ProductMemory)
    reads, prepares = [], []
    owner.store = SimpleNamespace(read_source=lambda ref: reads.append(ref) or raw)
    original = service.prepare_python_excerpt_source
    def counted(value):
        prepares.append(value)
        return original(value)
    monkeypatch.setattr(service, "prepare_python_excerpt_source", counted)
    source_cache, prepared_cache = {}, {}
    for state in states:
        owner._verify_sources(state, source_cache, prepared_cache)
    assert len(reads) == len(prepares) == 1
    owner._verify_sources(states[0], {}, {})
    assert len(reads) == len(prepares) == 2
    other_index = index.model_copy(update={"generation_id": "b" * 64})
    other_source = source_ref.model_copy(update={"index": other_index})
    other_payload = records[0].payload.model_copy(update={"origin_source": other_source})
    other_record = records[0].model_copy(update={"origin": other_index, "payload": other_payload})
    other_view = origin.model_copy(update={"index": other_index, "sources": (other_source,),
        "definitions": tuple(f.model_copy(update={"source": other_source}) for f in facts)})
    other_state = transition(other_record, other_view, None, None, "other")
    owner._verify_sources(other_state, source_cache, prepared_cache)
    assert len(reads) == len(prepares) == 3  # Same blob, different complete SourceRef.


def test_operation_cache_overflow_still_verifies_each_source(monkeypatch):
    from types import SimpleNamespace
    import cami.product.service as service
    raw = BASE.encode()
    origin = view(raw)
    state = transition(record(origin, raw), origin, None, None, "first")
    owner = object.__new__(service.ProductMemory)
    reads = []
    owner.store = SimpleNamespace(read_source=lambda ref: reads.append(ref) or raw)
    monkeypatch.setattr(service, "MAX_SOURCE_CACHE_BYTES", 0)
    source_cache, prepared_cache = {}, {}
    owner._verify_sources(state, source_cache, prepared_cache)
    owner._verify_sources(state, source_cache, prepared_cache)
    assert not source_cache and not prepared_cache
    assert len(reads) == 4  # Origin and check evidence, each fully verified each time.


def test_stale_index_source_cannot_supply_current_literal_certificate():
    result = prepare_python_excerpt_source(BASE.encode(), expected_source=BASE.replace("f()", "other()"))
    assert isinstance(result, PythonExcerptUnavailable) and result.reason == "invalid_source_span"


def test_literal_certificate_cannot_escape_its_view_source_binding():
    raw = BASE.encode()
    origin = view(raw)
    item = record(origin, raw)
    source = origin.sources[0].model_copy(update={"index": view(raw, "b").index})
    unrelated_fact = origin.definitions[0].model_copy(update={"source": source})
    invalid = origin.model_copy(update={"definitions": (unrelated_fact,)})
    assert not dependencies(item, invalid).certain
    assert check(item, invalid, "wrong-source-index").verdict == "insufficient_evidence"
