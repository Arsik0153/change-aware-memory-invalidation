"""Compare line reuse to exact CPython3.12.12 source from the pinned runtime image."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

import cami.index as index
from cami.repository import Blob, Snapshot


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
    lines = index._source_lines(source)
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
    lines = index._source_lines(source)
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
