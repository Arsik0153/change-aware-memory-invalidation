"""Compare line reuse to exact CPython3.12.12 source from the pinned runtime image."""
from __future__ import annotations

import ast
import gc
import hashlib
from pathlib import Path
import weakref

import pytest

import cami.index as index
from cami.repository import MAX_FILE_BYTES, Blob, Snapshot


@pytest.fixture
def stdlib_reference():
    raw = (Path(__file__).with_name("fixtures") / "python312_ast_source_segment.py.txt").read_bytes()
    block = raw[raw.index(b"_line_pattern = re.compile"):]
    assert hashlib.sha256(block).hexdigest() == "dd0c188c1eca1042a30e85d85cbc1749b1d541b93caee8e3c5cdd109f2222e6a"
    namespace = {}
    exec(compile(raw, "CPython3.12.12/Lib/ast.py:source_segment", "exec"), namespace)
    return namespace


def blob(source, path="module.py", limitation=None):
    raw = source.encode("utf-8") if isinstance(source, str) else source
    return Blob(path, hashlib.sha256(raw).hexdigest(), "100644", raw, limitation)


SOURCES = (
    "def simple(): return 'café 🙂'",
    "class C:\n    def method(self):\n        return 'π' # outside\n",
    "class C:\n\t\f\tdef method(self):\n\t\treturn 'tab/formfeed'\n",
    "def symbols():\n    return 'a\fb\vc\x1cd\x1de\x1ef\x85g\u2028h\u2029i'\n",
    "def café(π: str = 'λ') -> str:\n    return '🙂 café'\n",
    "@decorator\ndef decorated():\n    return '@ inside string'\n",
    "@(  # opening line\n    decorator\n)\nasync def wrapped():\n    return '🙂'\n",
    "class C:\n    @(\n        (left @ right) # matrix @\n    )\n    async def method(self):\n        return 'multiline @ string'\n",
    "@decorate(\n    '@ text',\n)\nasync def outer(\n    x: tuple[str, int] = ('λ', 1),\n    *, flag=True,\n) -> str:\n    def inner(): return x[0]\n    return inner()\n",
    "def continued(a=(\n    'λ'\n)):\n    return (\n        a\n    ) # outside\n",
)


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_every_valid_definition_span_matches_pinned_stdlib(source, newline, stdlib_reference):
    source = source.replace("\n", newline)
    tree = ast.parse(source)
    lines = tuple(index._source_lines(source))
    definitions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert definitions
    for node in definitions:
        expected = stdlib_reference["get_source_segment"](source, node)
        assert index._source_segment(lines, node) == expected
        assert expected.startswith(("def ", "async def "))
    module = index.parse_module(blob(source), "module")
    by_line = {node.lineno: node for node in definitions}
    for definition in module.definitions:
        assert definition.source == stdlib_reference["get_source_segment"](source, by_line[definition.start_line])


@pytest.mark.parametrize("source", ["", "\n", "\r\n", "\r", "text", "text\n", "a\fb\vc\x85d\u2028e\u2029f\r\ng\rh\ni"])
def test_split_boundaries_and_final_empty_match_equal_pinned_stdlib(source, stdlib_reference):
    lines = tuple(index._source_lines(source))
    assert lines == tuple(stdlib_reference["_splitlines_no_ff"](source))
    assert "".join(lines) == source


def test_lines_are_built_once_per_module_and_never_reused_across_copies(monkeypatch):
    original = index._source_lines
    inputs = []

    def counted(source):
        inputs.append(source)
        return original(source)

    monkeypatch.setattr(index, "_source_lines", counted)
    source = "def f():\n    def nested(): return 1\n    return nested()\nclass C:\n    def method(self): return f()\ndef g(): return f()\n"
    first = index.parse_module(blob(source), "module")
    assert len(first.definitions) == 4 and inputs == [source]
    changed = source.replace("return 1", "return 2")
    second = index.parse_module(blob(changed), "module")
    assert inputs == [source, changed]
    assert first.definitions[0].source != second.definitions[0].source
    assert "return 1" in first.definitions[1].source and "return 2" in second.definitions[1].source


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("tail", ["", "#"])
def test_near_limit_trailing_lines_are_not_materialized(newline, tail, monkeypatch, stdlib_reference):
    head = newline.join(("def early():", "    return 'λ'", ""))
    trailing = tail + newline
    count = (MAX_FILE_BYTES - len(head.encode("utf-8"))) // len(trailing.encode("utf-8"))
    source = head + trailing * count
    assert len(source.encode("utf-8")) <= MAX_FILE_BYTES
    original = index._SOURCE_LINE_PATTERN
    consumed = []

    class GuardedPattern:
        def finditer(self, value):
            for line_number, match in enumerate(original.finditer(value), 1):
                assert line_number <= 2, "unused trailing line materialized"
                consumed.append(line_number)
                yield match

    monkeypatch.setattr(index, "_SOURCE_LINE_PATTERN", GuardedPattern())
    module = index.parse_module(blob(source), "module")
    node = ast.parse(source).body[0]
    assert module.definitions[0].source == stdlib_reference["get_source_segment"](source, node)
    assert consumed == [1, 2]


def test_nested_backward_and_later_spans_reuse_the_prefix(monkeypatch, stdlib_reference):
    source = ("def outer():\n    def inner(): return 'λ'\n    def sibling():\n"
              "        return inner()\n    return sibling()\n\ndef later(): return '🙂'\n"
              + "# unused tail\n" * 20)
    original_lines, original_segment = index._source_lines, index._source_segment
    consumed, checkpoints = [], []

    def counted(value):
        for line_number, line in enumerate(original_lines(value), 1):
            consumed.append(line_number)
            yield line

    def observed(lines, node):
        checkpoints.append((node.name, node.end_lineno, len(lines), len(consumed)))
        result = original_segment(lines, node)
        assert result == stdlib_reference["get_source_segment"](source, node)
        return result

    monkeypatch.setattr(index, "_source_lines", counted)
    monkeypatch.setattr(index, "_source_segment", observed)
    module = index.parse_module(blob(source), "module")
    assert len(module.definitions) == 4
    assert checkpoints == [("outer", 5, 5, 5), ("inner", 2, 5, 5),
                           ("sibling", 4, 5, 5), ("later", 7, 7, 7)]
    assert consumed == list(range(1, 8))


def test_equal_parent_and_nested_end_lines_do_not_advance_twice(monkeypatch, stdlib_reference):
    source = "def outer():\n    def inner(): return '🙂'\n# unused\n"
    original = index._source_lines
    consumed = []

    def counted(value):
        for line_number, line in enumerate(original(value), 1):
            consumed.append(line_number)
            yield line

    monkeypatch.setattr(index, "_source_lines", counted)
    module = index.parse_module(blob(source), "module")
    nodes = {node.lineno: node for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.FunctionDef)}
    assert len(module.definitions) == 2 and consumed == [1, 2]
    for definition in module.definitions:
        assert definition.source == stdlib_reference["get_source_segment"](source, nodes[definition.start_line])


def test_identical_source_still_has_fresh_iterator_per_operation_and_file(monkeypatch):
    source = "def f(): return 1\n# unused\n"
    original = index._source_lines
    factories, consumed = [], []

    def counted(value):
        factories.append(value)

        def lines():
            for line in original(value):
                consumed.append(line)
                yield line

        return lines()

    monkeypatch.setattr(index, "_source_lines", counted)
    first = index.parse_module(blob(source), "module")
    again = index.parse_module(blob(source), "module")
    other = index.parse_module(blob(source, path="other.py"), "other")
    assert first == again
    assert other.definitions[0].source == first.definitions[0].source
    assert factories == [source] * 3 and consumed == ["def f(): return 1\n"] * 3


def test_prefix_iterator_is_released_on_return_without_cyclic_gc(monkeypatch):
    original = index._source_lines
    segment = index._source_segment
    references, buffers = [], []

    def tracked(source):
        iterator = original(source)
        references.append(weakref.ref(iterator))
        return iterator

    def observed(lines, node):
        buffers.append(lines)
        return segment(lines, node)

    monkeypatch.setattr(index, "_source_lines", tracked)
    monkeypatch.setattr(index, "_source_segment", observed)
    enabled = gc.isenabled()
    gc.disable()
    try:
        module = index.parse_module(blob("def f():\n    def inner(): return 1\n    return inner()\n# unused\n"), "module")
        assert len(module.definitions) == 2 and len(references) == 1
        assert references[0]() is None
        assert buffers and all(not buffer for buffer in buffers)
    finally:
        if enabled:
            gc.enable()
        else:
            gc.disable()


@pytest.mark.parametrize("source,limitation", [(b"VALUE = 'no definitions'\n", None),
    (b"def broken(", None), (b"\xff", None), (b"\xef\xbb\xbfdef f(): pass", None),
    (b"def f(): pass", "file_too_large")])
def test_unneeded_or_unavailable_modules_do_not_prepare_lines(source, limitation, monkeypatch):
    def forbidden(*args):
        raise AssertionError("source lines prepared without an indexed definition")

    monkeypatch.setattr(index, "_source_lines", forbidden)
    module = index.parse_module(blob(source, limitation=limitation), "module")
    assert not module.definitions
    assert module.limitation == (limitation or (None if source.startswith(b"VALUE") else "parse_error"))


@pytest.mark.parametrize("build_graph", [False, True])
def test_complete_authored_index_and_edges_equal_stdlib_reference(build_graph, stdlib_reference, monkeypatch):
    snapshot = Snapshot("authored", "same-snapshot", (
        blob("@decorate\ndef f():\n    return g()\ndef g(): return 'λ'\n", "a.py"),
        blob("from a import f\nclass C:\n    async def method(self): return f()\n", "b.py"),
        blob("if flag:\n    def duplicate(): return 1\ndef duplicate(): return 2\n", "c.py"),
    ))
    config = index.IndexConfig(build_graph=build_graph)
    actual = index.build_index(snapshot, config)
    monkeypatch.setattr(index, "_source_segment", lambda lines, node:
                        stdlib_reference["get_source_segment"]("".join(lines), node))
    expected = index.build_index(snapshot, config)
    assert actual == expected  # Every field, including Definition.source and graph ordering.
    assert bool(actual.edges) is build_graph
