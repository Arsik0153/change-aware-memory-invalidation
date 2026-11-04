"""Stdlib-only strict Python physical-line literal extraction; no CAMI imports."""

from __future__ import annotations

import ast
import codecs
from dataclasses import dataclass
import hashlib
import os
from pathlib import PurePosixPath
import re
import stat
import tokenize

FORMAT = "python.definition-prefix/1"
LIMIT = 2400
MAX_SOURCE_BYTES = 2 * 1024 * 1024


class UnsupportedSource(ValueError):
    pass


def safe_relative(value):
    if not isinstance(value, str):
        raise ValueError("unsafe source path")
    path = PurePosixPath(value)
    if (
        not isinstance(value, str)
        or not value
        or value == "."
        or path.is_absolute()
        or ".." in path.parts
        or str(path) != value
        or "\\" in value
        or "\x00" in value
    ):
        raise ValueError("unsafe source path")
    return value


def read_source(repo, relative):
    safe_relative(relative)
    path = repo / relative
    if any(p.is_symlink() for p in [path, *path.parents] if p.is_relative_to(repo)):
        raise UnsupportedSource("symlink_source")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SOURCE_BYTES:
            raise UnsupportedSource("unsupported_source_type_or_size")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(info.st_size + 1)
        after = os.fstat(descriptor)
        if len(raw) != info.st_size or (info.st_size, info.st_mtime_ns) != (
            after.st_size,
            after.st_mtime_ns,
        ):
            raise UnsupportedSource("source_changed_during_read")
        return raw
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class PreparedModule:
    raw: bytes
    lines: tuple[str, ...]
    definitions: dict
    decorator_openings: dict


def decorator_openings(lines):
    """Associate lexical leading @ with function headers, once per module."""
    normalized = []
    for line in lines:
        if line.endswith("\r\n"):
            normalized.append(line[:-2] + "\n")
        elif line.endswith(("\r", "\n")):
            normalized.append(line[:-1] + "\n")
        else:
            normalized.append(line)
    iterator = iter(normalized)
    pending, statement, openings = [], [], {}
    try:
        for token in tokenize.generate_tokens(lambda: next(iterator, "")):
            if token.type in (tokenize.INDENT, tokenize.DEDENT):
                pending.clear()
                continue
            if token.type in (tokenize.COMMENT, tokenize.NL, tokenize.ENCODING):
                continue
            if token.type in (tokenize.NEWLINE, tokenize.ENDMARKER):
                if statement:
                    first = statement[0]
                    if first.type == tokenize.OP and first.string == "@":
                        pending.append(first.start[0])
                    elif first.string == "def" or (
                        first.string == "async"
                        and len(statement) > 1
                        and statement[1].string == "def"
                    ):
                        openings[first.start[0]] = tuple(pending)
                        pending.clear()
                    else:
                        pending.clear()
                    statement.clear()
                continue
            statement.append(token)
    except (tokenize.TokenError, IndentationError, SyntaxError) as error:
        raise UnsupportedSource("invalid_lexical_definition_span") from error
    return openings


def prepare_module(raw):
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
            raise UnsupportedSource("unsupported_encoding")
        text = raw.decode("utf-8")
    except (SyntaxError, UnicodeError, LookupError) as error:
        raise UnsupportedSource("unsupported_encoding") from error
    try:
        tree = ast.parse(text)
    except SyntaxError as error:
        raise UnsupportedSource("parse_error") from error
    lines = re.findall(r"[^\r\n]*(?:\r\n|\r|\n|$)", text)
    if lines and lines[-1] == "":
        lines.pop()
    definitions = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions.setdefault(node.name, []).append(("function", node))
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    definitions.setdefault(node.name + "." + child.name, []).append(
                        ("method", child)
                    )
    return PreparedModule(raw, tuple(lines), definitions, decorator_openings(lines))


def literal(module, qualname):
    candidates = module.definitions.get(qualname, [])
    if len(candidates) != 1:
        raise UnsupportedSource("missing_or_ambiguous_direct_definition")
    kind, node = candidates[0]
    openings = module.decorator_openings.get(node.lineno)
    if (
        openings is None
        or len(openings) != len(node.decorator_list)
        or any(
            first > expression.lineno
            for first, expression in zip(openings, node.decorator_list, strict=True)
        )
    ):
        raise UnsupportedSource("invalid_lexical_definition_span")
    first = openings[0] if openings else node.lineno
    last = node.end_lineno
    if last is None or not 1 <= first <= node.lineno <= last <= len(module.lines):
        raise UnsupportedSource("invalid_source_span")
    region = "".join(module.lines[first - 1 : last])
    if not region:
        raise UnsupportedSource("invalid_source_span")
    return (
        kind,
        {"format": FORMAT, "text": region[:LIMIT], "truncated": len(region) > LIMIT},
        {"first_line": first, "last_line": last},
    )


def source_ref(relative, raw):
    return {"path": relative, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
