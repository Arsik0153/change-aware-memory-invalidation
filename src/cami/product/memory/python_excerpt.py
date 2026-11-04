"""Exact Python source prefixes from trusted indexed nodes and authenticated bytes."""
from __future__ import annotations

import ast
import codecs
from collections.abc import Mapping
import hashlib
from dataclasses import dataclass
import re
import sys
import tokenize
from types import MappingProxyType

from cami.product.memory.models import (
    PythonDefinitionSpan, PythonExcerptExpected, PythonExcerptProjection,
    PythonExcerptReady, PythonExcerptUnavailable,
)


class ExcerptUnavailable(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class PythonExcerptSource:
    lines: tuple[str, ...]
    definition_decorators: Mapping[int, tuple[int, ...]]
    retained_bytes: int


def _definition_decorators(lines: tuple[str, ...]) -> dict[int, tuple[int, ...]]:
    # Only the lexer sees normalized endings. Physical line numbers are unchanged
    # and the literal lines below retain every original character.
    normalized = iter(line[:-2] + "\n" if line.endswith("\r\n")
                      else line[:-1] + "\n" if line.endswith("\r") else line
                      for line in lines)
    statements: list[tokenize.TokenInfo] = []
    pending: dict[int, list[int]] = {}
    definitions: dict[int, tuple[int, ...]] = {}
    depth = 0
    for token in tokenize.generate_tokens(lambda: next(normalized, "")):
        if token.type == tokenize.INDENT:
            depth += 1
            pending.pop(depth, None)
        elif token.type == tokenize.DEDENT:
            pending.pop(depth, None)
            depth -= 1
        elif token.type == tokenize.NEWLINE:
            if not statements:
                continue
            first = statements[0]
            if first.type == tokenize.OP and first.string == "@":
                pending.setdefault(depth, []).append(first.start[0])
            else:
                is_def = first.type == tokenize.NAME and first.string == "def"
                is_async_def = (first.type == tokenize.NAME and first.string == "async"
                                and len(statements) > 1 and statements[1].type == tokenize.NAME
                                and statements[1].string == "def")
                if is_def or is_async_def:
                    definitions[first.start[0]] = tuple(pending.get(depth, ()))
                pending.pop(depth, None)
            statements.clear()
        elif token.type not in (tokenize.NL, tokenize.COMMENT, tokenize.ENDMARKER):
            statements.append(token)
    if statements or any(pending.values()):
        raise tokenize.TokenError("unassociated decorator statement", (0, 0))
    return definitions


def prepare_python_excerpt_source(raw: bytes, *, expected_source: str | None = None) -> PythonExcerptSource | PythonExcerptUnavailable:
    # The tokenizer receives only the first two Python physical byte lines. A
    # BytesIO.readline callback would treat an entire bare-CR file as one line.
    header = []
    for match in re.finditer(rb"[^\r\n]*(?:\r\n|\r|\n|$)", raw):
        if not match.group():
            break
        header.append(match.group())
        if len(header) == 2:
            break
    physical = iter(header)
    try:
        encoding, _ = tokenize.detect_encoding(lambda: next(physical, b""))
        if raw.startswith(codecs.BOM_UTF8) or codecs.lookup(encoding).name != "utf-8":
            return PythonExcerptUnavailable(reason="unsupported_encoding")
        text = raw.decode("utf-8")
    except (SyntaxError, UnicodeError, LookupError):
        return PythonExcerptUnavailable(reason="unsupported_encoding")
    if expected_source is not None and text != expected_source:
        return PythonExcerptUnavailable(reason="invalid_source_span")
    # Python physical lines only. str.splitlines also splits form feed and U+2028.
    lines = re.findall(r"[^\r\n]*(?:\r\n|\r|\n|$)", text)
    if lines and lines[-1] == "":
        lines.pop()
    physical_lines = tuple(lines)
    try:
        definitions = _definition_decorators(physical_lines)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return PythonExcerptUnavailable(reason="invalid_source_span")
    retained_bytes = (sys.getsizeof(physical_lines) + sum(map(sys.getsizeof, physical_lines))
                      + sys.getsizeof(definitions)
                      + sum(sys.getsizeof(line) + sys.getsizeof(starts)
                            + sum(map(sys.getsizeof, starts)) for line, starts in definitions.items()))
    return PythonExcerptSource(physical_lines, MappingProxyType(definitions), retained_bytes)


def _literal(source: PythonExcerptSource, span: PythonDefinitionSpan) -> PythonExcerptExpected:
    if span.last_line > len(source.lines):
        raise ExcerptUnavailable("invalid_source_span")
    region = "".join(source.lines[span.first_line - 1:span.last_line])
    if not region:
        raise ExcerptUnavailable("invalid_source_span")
    return PythonExcerptExpected(text=region[:2400], truncated=len(region) > 2400)


def project_python_excerpt(source: PythonExcerptSource | PythonExcerptUnavailable,
                           node: ast.FunctionDef | ast.AsyncFunctionDef) -> PythonExcerptProjection:
    if isinstance(source, PythonExcerptUnavailable):
        return source
    try:
        starts = source.definition_decorators.get(node.lineno)
        if starts is None or len(starts) != len(node.decorator_list):
            raise ExcerptUnavailable("invalid_source_span")
        if any(start > decorator.lineno for start, decorator in zip(starts, node.decorator_list)):
            raise ExcerptUnavailable("invalid_source_span")
        first = starts[0] if starts else node.lineno
        if node.end_lineno is None or not 1 <= first <= node.lineno <= node.end_lineno:
            raise ExcerptUnavailable("invalid_source_span")
        span = PythonDefinitionSpan(first_line=first, last_line=node.end_lineno)
        literal = _literal(source, span)
    except ExcerptUnavailable as exc:
        return PythonExcerptUnavailable(reason="unsupported_encoding" if exc.reason == "unsupported_encoding"
                                        else "invalid_source_span")
    return PythonExcerptReady(span=span, prefix_characters=len(literal.text),
                              prefix_sha256=hashlib.sha256(literal.text.encode("utf-8")).hexdigest(),
                              truncated=literal.truncated)


def origin_literal_from_certificate(source: PythonExcerptSource, certificate: PythonExcerptReady) -> PythonExcerptExpected:
    literal = _literal(source, certificate.span)
    if (certificate.prefix_characters != len(literal.text)
            or certificate.prefix_sha256 != hashlib.sha256(literal.text.encode("utf-8")).hexdigest()
            or certificate.truncated != literal.truncated):
        raise ExcerptUnavailable("invalid_source_span")
    return literal


def verify_origin_literal(source: PythonExcerptSource, span: PythonDefinitionSpan, expected: PythonExcerptExpected) -> None:
    if _literal(source, span) != expected:
        raise ExcerptUnavailable("invalid_source_span")
