"""Stdlib-only oracle for the frozen structural stress grammar; never executes source."""
from __future__ import annotations

import io
import re
import tokenize


def observe(source: str | None, name: str, kind: str) -> str:
    if kind not in ('symbol_exists', 'signature_equals') or not re.fullmatch(r'f\d+', name):
        raise ValueError('Oracle accepts only frozen fixture subjects and predicates')
    if source is None:
        return 'contradicted'
    try:
        compile(source, '<fixture-oracle>', 'exec', dont_inherit=True)
    except SyntaxError:
        return 'insufficient_evidence'
    depth = 0
    statements = []
    current = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.INDENT:
            depth += 1
        elif token.type == tokenize.DEDENT:
            depth -= 1
        elif token.type == tokenize.NEWLINE:
            if current:
                statements.append(current)
                current = []
        elif depth == 0 and token.type not in (tokenize.NL, tokenize.COMMENT, tokenize.ENDMARKER):
            current.append(token.string)
    for row in statements:
        if (len(row) < 3 or row[0] != 'def' or not re.fullmatch(r'f\d+', row[1])
                or row[2:] not in (['(', 'x', ')', ':'],
                                  ['(', 'x', ',', 'extra', '=', 'None', ')', ':'])):
            raise ValueError('Source outside the frozen oracle grammar')
    definitions = [row for row in statements if row[1] == name]
    if len(definitions) > 1:
        return 'insufficient_evidence'
    if not definitions:
        return 'contradicted'
    if kind == 'signature_equals' and definitions[0][2:] != ['(', 'x', ')', ':']:
        return 'contradicted'
    return 'supported'
