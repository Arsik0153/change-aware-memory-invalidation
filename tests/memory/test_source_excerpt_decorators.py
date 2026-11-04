"""Decorator opening lines are lexical; AST expression lineno is insufficient."""
import ast
from dataclasses import replace
from types import MappingProxyType

import pytest

from cami.product.memory.models import PythonExcerptReady, PythonExcerptUnavailable
import cami.product.memory.python_excerpt as excerpt


CASES = [
    '@(\n    decorator\n)\ndef f():\n    return 1\n',
    '@(  # opening comment\n    decorator  # expression comment\n)\ndef f():\n    return 1\n',
    '@(\n    (((decorator)))\n)\ndef f():\n    return 1\n',
    '@(\n    left @ right\n)\ndef f():\n    return 1\n',
    '@wrapper("""text\n@not_a_decorator\n def fake():\n""")\ndef f():\n    return 1\n',
    '@simple\n# between decorators\n@(\n    decorator\n)\n# before def\ndef f():\n    return 1\n',
    '@(\n    decorator\n)\nasync def f():\n    return 1\n',
    'class C:\n    @(\n        decorator\n    )\n    async def f(self):\n        return 1\n',
    '@class_decorator\nclass C:\n    def untouched(self): pass\n\n    @(\n        decorator\n    )\n    def f(self):\n        return 1\n',
    '@(\n    lambda value: value\n)\ndef f():\n    return 1\n',
]


@pytest.mark.parametrize('ending', ['\n', '\r\n', '\r'])
@pytest.mark.parametrize('source', CASES)
def test_lexical_opening_included_exactly(source, ending):
    source = source.replace('\n', ending)
    node = next(n for n in ast.walk(ast.parse(source))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 'f')
    prepared = excerpt.prepare_python_excerpt_source(source.encode())
    assert isinstance(prepared, excerpt.PythonExcerptSource)
    cert = excerpt.project_python_excerpt(prepared, node)
    assert isinstance(cert, PythonExcerptReady)
    lines = source.split(ending)
    first = next(i for i, line in enumerate(lines, 1)
                 if line.lstrip().startswith('@') and not line.lstrip().startswith('@class_decorator'))
    assert cert.span.first_line == first
    literal = excerpt.origin_literal_from_certificate(prepared, cert)
    expected = ending.join(lines[first - 1:node.end_lineno]) + ending
    assert literal.text == expected


def test_matrix_and_multiline_string_do_not_leak_to_later_definition():
    source = ('value = left @ right\ntext = """\n@looks_like_a_decorator\n"""\n'
              'def plain(): pass\n@decorator\ndef wrapped(): return left @ right\n')
    prepared = excerpt.prepare_python_excerpt_source(source.encode())
    assert isinstance(prepared, excerpt.PythonExcerptSource)
    plain, wrapped = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)]
    assert prepared.definition_decorators[plain.lineno] == ()
    assert prepared.definition_decorators[wrapped.lineno] == (plain.lineno + 1,)
    assert excerpt.project_python_excerpt(prepared, plain).span.first_line == plain.lineno


def test_decorator_count_or_missing_index_association_is_unavailable():
    source = '@(\n decorator\n)\ndef f(): pass\n'
    node = ast.parse(source).body[0]
    prepared = excerpt.prepare_python_excerpt_source(source.encode())
    assert isinstance(prepared, excerpt.PythonExcerptSource)
    for mapping in ({}, {node.lineno: ()}, {node.lineno: (node.lineno,)}):
        bad = replace(prepared, definition_decorators=MappingProxyType(mapping))
        assert isinstance(excerpt.project_python_excerpt(bad, node), PythonExcerptUnavailable)


def test_module_is_tokenized_once_for_many_indexed_definitions(monkeypatch):
    source = '\n'.join(f'@(\n decorator\n)\ndef f{i}(): return {i}\n' for i in range(12))
    calls = []
    original = excerpt.tokenize.generate_tokens
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(excerpt.tokenize, 'generate_tokens', counted)
    prepared = excerpt.prepare_python_excerpt_source(source.encode())
    assert isinstance(prepared, excerpt.PythonExcerptSource)
    for node in ast.parse(source).body:
        assert isinstance(excerpt.project_python_excerpt(prepared, node), PythonExcerptReady)
    assert len(calls) == 1
    with pytest.raises(TypeError):
        prepared.definition_decorators[1] = ()
