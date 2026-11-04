"""Authored pure counterexample: no worktree, ProductMemory, SQLite or execution."""

import ast
import hashlib

from cami.product.memory.models import (  # noqa: E402
    CodeView, DefinitionFact, IndexRef, PathCoverage, RecordRevision,
    SourceExcerptPayload, SourceRef, SymbolKey,
)
from cami.product.memory.python_excerpt import (  # noqa: E402
    origin_literal_from_certificate, prepare_python_excerpt_source, project_python_excerpt,
)
from cami.product.memory.validation import check  # noqa: E402

OLD = "@(\n    decorator\n)\ndef f():\n    return 1\n"
NEW = "@(  # authored change on first decorator physical line\n    decorator\n)\ndef f():\n    return 1\n"
SUBJECT = SymbolKey(language="python", path="src/api.py", qualname="f", node_kind="function")


def view(text, version):
    node = ast.parse(text).body[0]
    source = prepare_python_excerpt_source(text.encode())
    certificate = project_python_excerpt(source, node)
    index = IndexRef(worktree_key="0" * 64, snapshot_id=version * 64, generation_id=version * 64,
                     policy_fingerprint="1" * 64, analyzer_fingerprint="2" * 64)
    ref = SourceRef(index=index, path=SUBJECT.path, sha256=hashlib.sha256(text.encode()).hexdigest(), size=len(text.encode()))
    fact = DefinitionFact(subject=SUBJECT, signature=None, source=ref, ambiguous=False, python_excerpt=certificate)
    code = CodeView(index=index, definitions=(fact,), sources=(ref,), coverage=(PathCoverage(path=SUBJECT.path, status="present"),))
    return code, source, certificate


def test_contract_span_starts_at_first_decorator_physical_line():
    _, _, certificate = view(OLD, "a")
    assert certificate.span.first_line == 1  # Actual2 drops the @ opening line.


def test_contract_detects_changed_decorator_opening_line():
    origin, source, certificate = view(OLD, "a")
    current, _, _ = view(NEW, "b")
    payload = SourceExcerptPayload(subject=SUBJECT, expected=origin_literal_from_certificate(source, certificate),
                                   origin_source=origin.sources[0], origin_span=certificate.span)
    record = RecordRevision(memory_id="9" * 64, revision=1, payload=payload, origin=origin.index,
                            created_at="authored", previous_revision=None)
    result = check(record, current, "authored-decorator-change")
    assert result.verdict == "contradicted"  # Actual supported despite changed promised physical region.
