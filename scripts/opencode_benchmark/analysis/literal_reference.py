"""Independent stdlib literal reference. No production/generator imports or execution."""
from __future__ import annotations

import ast
import codecs
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tokenize

FORMAT = "python.definition-prefix/1"
LIMIT = 2400


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_path(root, relative):
    rel = PurePosixPath(relative)
    if not relative or relative == "." or rel.is_absolute() or ".." in rel.parts or str(rel) != relative or "\\" in relative or "\0" in relative:
        raise ValueError("unsafe source path")
    path = root / relative
    if any(p.is_symlink() for p in [path, *path.parents] if p.is_relative_to(root)):
        raise ValueError("source symlink unavailable")
    return path


def lexical_starts(text, tree):
    """Match logical @ statements to AST expression ranges, independently of core."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    markers, active, start, depth = [], None, True, 0
    for token in tokenize.generate_tokens(io.StringIO(normalized).readline):
        if token.type == tokenize.NEWLINE:
            if active is not None:
                active["end"] = token.start[0]
                markers.append(active)
                active = None
            start = True
            continue
        if token.type in {tokenize.ENCODING, tokenize.INDENT, tokenize.DEDENT, tokenize.COMMENT, tokenize.NL, tokenize.ENDMARKER}:
            continue
        if token.type == tokenize.OP:
            if token.string == "@" and start and depth == 0:
                active = {"line": token.start[0], "column": len(lines[token.start[0] - 1][:token.start[1]].encode())}
            if token.string in {"(", "[", "{"}:
                depth += 1
            elif token.string in {")", "]", "}"}:
                depth -= 1
        start = False
    if active:
        raise ValueError("unterminated decorator")
    used, starts = set(), {}
    nodes = sorted((n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))), key=lambda n: (n.lineno, n.col_offset))
    for node in nodes:
        if not node.decorator_list:
            starts[node.lineno] = node.lineno
            continue
        candidates = [(i, m) for i, m in enumerate(markers) if i not in used and m["column"] == node.col_offset and m["end"] < node.lineno]
        chosen = candidates[-len(node.decorator_list):]
        if len(chosen) != len(node.decorator_list) or any(not m["line"] <= d.lineno <= d.end_lineno <= m["end"] for (_, m), d in zip(chosen, node.decorator_list, strict=True)):
            raise ValueError("unproved lexical decorator association")
        used.update(i for i, _ in chosen)
        starts[node.lineno] = chosen[0][1]["line"]
    if len(used) != len(markers):
        raise ValueError("unassigned decorator token")
    return starts


@dataclass(frozen=True)
class Literal:
    status: str
    source_sha256: str | None = None
    source_size: int | None = None
    kind: str | None = None
    text: str | None = None
    truncated: bool | None = None
    first_line: int | None = None
    last_line: int | None = None

    def expected(self):
        return {"format": FORMAT, "text": self.text, "truncated": self.truncated}


@lru_cache(maxsize=1024)
def body(root: Path, relative: str, qualname: str):
    """Cache only small results for externally verified immutable canonical trees."""
    try:
        path = safe_path(root, relative)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return Literal("absent_path")
    except (OSError, ValueError):
        return Literal("unavailable_source")
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 2 * 1024**2:
            return Literal("unavailable_source")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(2 * 1024**2 + 1)
        if len(raw) != info.st_size:
            return Literal("unavailable_source")
    finally:
        os.close(descriptor)
    fingerprint, size = sha(raw), len(raw)
    try:
        first_two = iter(re.findall(rb"[^\r\n]*(?:\r\n|\r|\n|$)", raw)[:2])
        encoding, _ = tokenize.detect_encoding(lambda: next(first_two, b""))
        if raw.startswith(codecs.BOM_UTF8) or codecs.lookup(encoding).name != "utf-8":
            return Literal("unsupported_encoding", fingerprint, size)
        text = raw.decode("utf-8")
        tree = ast.parse(text)
        starts = lexical_starts(text, tree)
    except (UnicodeError, SyntaxError, tokenize.TokenError, ValueError, LookupError):
        return Literal("unavailable_parse_or_lexical", fingerprint, size)
    candidates = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == qualname:
            candidates.append(("function", node))
        elif isinstance(node, ast.ClassDef):
            candidates.extend(("method", member) for member in node.body if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name + "." + member.name == qualname)
    if len(candidates) != 1:
        if not candidates and any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == qualname.rsplit(".", 1)[-1] for n in ast.walk(tree)):
            return Literal("unavailable_non_direct_definition", fingerprint, size)
        return Literal("absent_definition" if not candidates else "ambiguous_definition", fingerprint, size)
    kind, node = candidates[0]
    lines = re.findall(r"[^\r\n]*(?:\r\n|\r|\n|$)", text)
    first, last = starts[node.lineno], node.end_lineno
    if last is None or not 1 <= first <= last <= len(lines):
        return Literal("unavailable_span", fingerprint, size)
    region = "".join(lines[first - 1:last])
    return Literal("unique_definition", fingerprint, size, kind, region[:LIMIT], len(region) > LIMIT, first, last)
