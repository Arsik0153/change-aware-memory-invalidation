#!/usr/bin/env python3
"""Independent development reference checker; no repository imports or execution."""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import sys


IDENTITY = "authored-structural-reference"
VERSION = "1.0.0-development"
LIMITATION = (
    "Shares CPython ast parsing and ast.dump(include_attributes=False) with the "
    "predicate contract; this is not parser-independent. Source is never executed. "
    "Checks exact syntactic top-level definitions, not runtime binding or behavior."
)
CASE_FIELDS = {"id", "kind", "subject", "predicate", "text", "scope", "source_path", "source_sha256"}
SIGNATURE_FIELDS = {"parameters", "returns_ast", "decorators_ast", "is_async"}
PARAMETER_FIELDS = {"name", "kind", "default_ast", "annotation_ast"}
KINDS = {"positional_only", "positional_or_keyword", "var_positional", "keyword_only", "var_keyword"}


class Uncertain(Exception):
    pass


def exact_fields(value, fields, label):
    if not isinstance(value, dict) or set(value) != fields:
        raise Uncertain(f"{label} requires exactly these fields: {', '.join(sorted(fields))}")


def nullable_string(value, label):
    if value is not None and not isinstance(value, str):
        raise Uncertain(f"{label} must be a string or null")


def validate_signature(value):
    # Explicit complete signatures prevent an absent field from hiding a mismatch.
    exact_fields(value, SIGNATURE_FIELDS, "expected_signature")
    if not isinstance(value["parameters"], list):
        raise Uncertain("expected_signature.parameters must be a list")
    names = set()
    for item in value["parameters"]:
        exact_fields(item, PARAMETER_FIELDS, "parameter")
        if not isinstance(item["name"], str) or not item["name"].isidentifier():
            raise Uncertain("parameter name must be an identifier")
        if item["name"] in names:
            raise Uncertain("duplicate expected parameter name")
        names.add(item["name"])
        if not isinstance(item["kind"], str) or item["kind"] not in KINDS:
            raise Uncertain("unsupported expected parameter kind")
        nullable_string(item["default_ast"], "default_ast")
        nullable_string(item["annotation_ast"], "annotation_ast")
    nullable_string(value["returns_ast"], "returns_ast")
    if not isinstance(value["decorators_ast"], list) or any(
        not isinstance(item, str) for item in value["decorators_ast"]
    ):
        raise Uncertain("decorators_ast must be a list of strings")
    if type(value["is_async"]) is not bool:
        raise Uncertain("is_async must be a boolean")


def validate_case(case):
    exact_fields(case, CASE_FIELDS, "case")
    for key in ("id", "kind", "text", "scope", "source_path", "source_sha256"):
        if not isinstance(case[key], str) or not case[key]:
            raise Uncertain(f"{key} must be a nonempty string")
    exact_fields(case["subject"], {"path", "qualname", "node_kind"}, "subject")
    subject = case["subject"]
    if any(not isinstance(subject[key], str) or not subject[key] for key in subject):
        raise Uncertain("subject fields must be nonempty strings")
    if subject["node_kind"] != "function":
        raise Uncertain("only node_kind=function is supported")
    if not subject["qualname"].isidentifier():
        raise Uncertain("only a simple top-level function qualname is supported")
    predicate = case["predicate"]
    if not isinstance(predicate, dict):
        raise Uncertain("predicate must be an object")
    if case["kind"] == "symbol_exists":
        exact_fields(predicate, {"type", "expected"}, "symbol_exists predicate")
        if predicate["expected"] is not True:
            raise Uncertain("symbol_exists requires expected=true")
    elif case["kind"] == "signature_equals":
        exact_fields(predicate, {"type", "expected_signature"}, "signature_equals predicate")
        validate_signature(predicate["expected_signature"])
    else:
        raise Uncertain("unsupported case kind")
    if predicate["type"] != case["kind"]:
        raise Uncertain("kind and predicate.type disagree")
    if re.fullmatch(r"[0-9a-f]{64}", case["source_sha256"]) is None:
        raise Uncertain("source_sha256 must contain 64 lowercase hexadecimal characters")


def dump(expression):
    return None if expression is None else ast.dump(expression, include_attributes=False)


def extract_signature(node):
    args = node.args
    parameters = []
    positionals = list(args.posonlyargs) + list(args.args)
    defaults = [None] * (len(positionals) - len(args.defaults)) + list(args.defaults)

    def add(argument, kind, default=None):
        parameters.append({"name": argument.arg, "kind": kind,
                           "default_ast": dump(default), "annotation_ast": dump(argument.annotation)})

    for index, (argument, default) in enumerate(zip(positionals, defaults)):
        add(argument, "positional_only" if index < len(args.posonlyargs) else "positional_or_keyword", default)
    if args.vararg is not None:
        add(args.vararg, "var_positional")
    for argument, default in zip(args.kwonlyargs, args.kw_defaults):
        add(argument, "keyword_only", default)
    if args.kwarg is not None:
        add(args.kwarg, "var_keyword")
    return {"parameters": parameters, "returns_ast": dump(node.returns),
            "decorators_ast": [dump(item) for item in node.decorator_list],
            "is_async": isinstance(node, ast.AsyncFunctionDef)}


def location(node, role):
    start = node.lineno
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.decorator_list:
        start = min(start, *(item.lineno for item in node.decorator_list))
    return {"start_line": start, "end_line": getattr(node, "end_lineno", None) or node.lineno, "role": role}


class ModuleBindings(ast.NodeVisitor):
    """Find syntactic bindings in the module's lexical scope, ignoring local scopes."""

    def __init__(self, tree, target):
        self.target = target
        self.direct = {id(node) for node in tree.body}
        self.definitions = []
        self.other = []
        self.star_imports = []

    def bind(self, name, node, role):
        if name == self.target:
            self.other.append(location(node, role))

    def function(self, node):
        if node.name == self.target:
            self.definitions.append((node, id(node) in self.direct))
        # These expressions are in the enclosing scope; the body is local.
        for expression in node.decorator_list + list(node.args.defaults) + [
            item for item in node.args.kw_defaults if item is not None
        ]:
            self.visit(expression)
        for argument in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
            if argument.annotation is not None:
                self.visit(argument.annotation)
        for argument in (node.args.vararg, node.args.kwarg):
            if argument is not None and argument.annotation is not None:
                self.visit(argument.annotation)
        if node.returns is not None:
            self.visit(node.returns)

    visit_FunctionDef = function
    visit_AsyncFunctionDef = function

    def visit_ClassDef(self, node):
        self.bind(node.name, node, "class binding")
        for expression in node.decorator_list + node.bases + [item.value for item in node.keywords]:
            self.visit(expression)
        # Class locals are not module bindings. Explicit globals are conservatively
        # recognized because the class body itself executes at module scope.
        def declares_global(statements):
            for item in statements:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                    continue
                if isinstance(item, ast.Global) and self.target in item.names:
                    return True
                if declares_global(ast.iter_child_nodes(item)):
                    return True
            return False

        if declares_global(node.body):
            self.other.append(location(node, "class body declares target global; unsupported scope"))

    def visit_Lambda(self, node):
        for expression in node.args.defaults + [item for item in node.args.kw_defaults if item is not None]:
            self.visit(expression)

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bind(node.id, node, "module name binding or deletion")

    def visit_Import(self, node):
        for alias in node.names:
            self.bind(alias.asname or alias.name.split(".")[0], node, "import binding")

    def visit_ImportFrom(self, node):
        for alias in node.names:
            if alias.name == "*":
                self.star_imports.append(location(node, "star import ambiguity"))
            else:
                self.bind(alias.asname or alias.name, node, "import binding")

    def visit_ExceptHandler(self, node):
        self.bind(node.name, node, "exception name binding")
        self.generic_visit(node)

    def visit_MatchAs(self, node):
        self.bind(node.name, node, "match capture binding")
        self.generic_visit(node)

    def visit_MatchStar(self, node):
        self.bind(node.name, node, "match capture binding")

    def visit_MatchMapping(self, node):
        self.bind(node.rest, node, "match rest binding")
        self.generic_visit(node)

    def comprehension(self, node):
        # Iteration targets are local to comprehensions; named expressions bind in
        # the containing scope and are found by visiting all other expressions.
        for generator in node.generators:
            self.visit(generator.iter)
            for condition in generator.ifs:
                self.visit(condition)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)

    visit_ListComp = comprehension
    visit_SetComp = comprehension
    visit_DictComp = comprehension
    visit_GeneratorExp = comprehension


def read_source(packet, case):
    relative = Path(case["source_path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise Uncertain("source_path must stay within the packet")
    path = (packet / relative).resolve(strict=True)
    if not path.is_relative_to(packet) or not path.is_file():
        raise Uncertain("source_path must resolve to a regular file within the packet")
    return path.read_bytes()


def check_case(packet, case):
    result = {"id": case.get("id") if isinstance(case, dict) else None,
              "verdict": "uncertain", "reason": "", "facts": {}, "evidence": [],
              "source_sha256": None, "declared_source_sha256": case.get("source_sha256") if isinstance(case, dict) else None,
              "checker": {"identity": IDENTITY, "version": VERSION,
                          "python": sys.version.split()[0], "shared_primitive_limitation": LIMITATION}}
    try:
        validate_case(case)
        raw = read_source(packet, case)
        result["source_sha256"] = hashlib.sha256(raw).hexdigest()
        if result["source_sha256"] != case["source_sha256"]:
            raise Uncertain("source SHA-256 mismatch")
        source = raw.decode("utf-8", errors="strict")
        tree = ast.parse(source, filename=case["subject"]["path"], mode="exec")
        bindings = ModuleBindings(tree, case["subject"]["qualname"])
        bindings.visit(tree)
        result["facts"]["definition_count"] = len(bindings.definitions)
        result["facts"]["unconditional_definition_count"] = sum(direct for _, direct in bindings.definitions)
        result["evidence"] = [location(node, "unconditional definition" if direct else "conditional definition")
                              for node, direct in bindings.definitions] + bindings.other + bindings.star_imports
        if bindings.other or bindings.star_imports:
            raise Uncertain("target rebinding or module namespace ambiguity")
        if any(not direct for _, direct in bindings.definitions):
            raise Uncertain("conditional target definition is outside supported scope")
        if len(bindings.definitions) > 1:
            raise Uncertain("duplicate target definitions")
        if not bindings.definitions:
            result.update(verdict="contradicted", reason="no top-level syntactic function definition for target")
            result["facts"]["exists"] = False
            if tree.body:
                result["evidence"] = [{"start_line": 1, "end_line": len(source.splitlines()), "role": "complete module inspected for absence"}]
            return result
        node, _ = bindings.definitions[0]
        if getattr(node, "type_params", []):
            raise Uncertain("target type parameters are unsupported")
        signature = extract_signature(node)
        result["facts"].update(exists=True, signature=signature)
        if case["kind"] == "symbol_exists":
            result.update(verdict="supported", reason="unique unconditional top-level syntactic function definition")
        elif signature == case["predicate"]["expected_signature"]:
            result.update(verdict="supported", reason="all complete signature fields match")
        else:
            different = [key for key in sorted(SIGNATURE_FIELDS) if signature[key] != case["predicate"]["expected_signature"][key]]
            result.update(verdict="contradicted", reason="signature mismatch in: " + ", ".join(different))
    except (Uncertain, OSError, UnicodeError, SyntaxError, ValueError, TypeError, RecursionError) as error:
        result["reason"] = f"{type(error).__name__}: {error}"
    return result


def reject_duplicate_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def run(packet, out):
    packet = packet.resolve(strict=True)
    with (packet / "cases.json").open(encoding="utf-8") as stream:
        cases = json.load(stream, object_pairs_hook=reject_duplicate_json_keys)
    if not isinstance(cases, list):
        raise ValueError("cases.json must be a list")
    ids = [case.get("id") for case in cases if isinstance(case, dict) and isinstance(case.get("id"), str)]
    duplicate_ids = {value for value in ids if ids.count(value) > 1}
    records = []
    for case in cases:
        record = check_case(packet, case)
        if isinstance(record["id"], str) and record["id"] in duplicate_ids:
            record.update(verdict="uncertain", reason="duplicate case id in packet")
        records.append(record)
    # O_EXCL preserves existing review artifacts and makes publication one-shot.
    payload = json.dumps({"format": "independent-structural-reference-development-v1", "records": records}, indent=2, allow_nan=False) + "\n"
    with out.open("x", encoding="utf-8") as stream:
        stream.write(payload)
    return len(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        count = run(args.packet, args.out)
    except (OSError, ValueError, TypeError, RecursionError) as error:
        parser.exit(2, f"packet/output error: {type(error).__name__}: {error}\n")
    print(f"Wrote {count} development reference records to {args.out}")


if __name__ == "__main__":
    main()
