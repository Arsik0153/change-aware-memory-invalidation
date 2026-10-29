"""Evaluate the tiny authored behavior-fixture language without CAMI or execution."""
from __future__ import annotations

import ast


def value_of(source: str, subject: str = "f") -> int:
    tree = ast.parse(source)
    functions: dict[str, ast.expr] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            raise ValueError("Oracle accepts only function definitions")
        args = node.args
        if (node.name in functions or node.decorator_list or node.returns is not None
                or node.type_comment or node.type_params or args.posonlyargs or args.args
                or args.vararg or args.kwonlyargs or args.kwarg or args.defaults
                or args.kw_defaults or len(node.body) != 1
                or not isinstance(node.body[0], ast.Return)):
            raise ValueError("Outside the zero-argument, single-return fixture grammar")
        expression = node.body[0].value
        literal = isinstance(expression, ast.Constant) and type(expression.value) is int
        call = (isinstance(expression, ast.Call) and isinstance(expression.func, ast.Name)
                and not expression.args and not expression.keywords)
        if expression is None or not (literal or call):
            raise ValueError("Oracle accepts only integer literals and named zero-argument calls")
        functions[node.name] = expression

    def evaluate(name: str, active: frozenset[str]) -> int:
        if name not in functions or name in active:
            raise ValueError("Unknown or recursive fixture function")
        expression = functions[name]
        if isinstance(expression, ast.Constant):
            return int(expression.value)
        assert isinstance(expression, ast.Call) and isinstance(expression.func, ast.Name)
        return evaluate(expression.func.id, active | {name})

    return evaluate(subject, frozenset())
