from __future__ import annotations

import ast
import hashlib
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath

from cami.models import Dependency, Node, Parameter, Signature
from cami.repository import Blob, Snapshot, changed_files

INDEX_VERSION = "4"


@dataclass(frozen=True)
class Definition:
    node: Node
    node_kind: str
    signature: Signature
    ast_hash: str
    start_line: int
    end_line: int
    source: str
    ambiguous: bool
    calls: tuple[str, ...]
    local_bindings: frozenset[str]
    loaded_names: frozenset[str]


@dataclass(frozen=True)
class Module:
    path: str
    module_name: str
    definitions: tuple[Definition, ...]
    imports: tuple[tuple[str, str, str | None], ...]
    unresolved: tuple[Node, ...]
    limitation: str | None
    source: str


@dataclass(frozen=True)
class CodeIndex:
    revision: str
    modules: tuple[Module, ...]
    edges: tuple[Dependency, ...]
    unresolved: frozenset[Node]
    global_unresolved: bool

    def definitions(self) -> dict[Node, Definition]:
        return {d.node: d for m in self.modules for d in m.definitions}

    def limitations(self) -> dict[str, str]:
        return {m.path: m.limitation for m in self.modules if m.limitation}


@dataclass(frozen=True)
class IndexConfig:
    source_roots: tuple[str, ...] = (".",)
    build_graph: bool = True


@dataclass(frozen=True)
class ChangeSet:
    files: frozenset[str]
    symbols: frozenset[Node]
    edges: tuple[Dependency, ...]
    unresolved: frozenset[Node]
    limited_paths: frozenset[str]
    global_unresolved: bool


def dump(node: ast.AST | None) -> str | None:
    return ast.dump(node, include_attributes=False) if node is not None else None


def signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Signature:
    args = node.args
    positional = args.posonlyargs + args.args
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    parameters: list[Parameter] = []
    for i, (arg, default) in enumerate(zip(positional, defaults, strict=True)):
        parameters.append(Parameter(name=arg.arg,
            kind="positional_only" if i < len(args.posonlyargs) else "positional_or_keyword",
            default_ast=dump(default), annotation_ast=dump(arg.annotation)))
    if args.vararg:
        parameters.append(Parameter(name=args.vararg.arg, kind="var_positional", annotation_ast=dump(args.vararg.annotation)))
    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        parameters.append(Parameter(name=arg.arg, kind="keyword_only", default_ast=dump(default), annotation_ast=dump(arg.annotation)))
    if args.kwarg:
        parameters.append(Parameter(name=args.kwarg.arg, kind="var_keyword", annotation_ast=dump(args.kwarg.annotation)))
    return Signature(parameters=tuple(parameters), returns_ast=dump(node.returns),
                     decorators_ast=tuple(ast.dump(d, include_attributes=False) for d in node.decorator_list),
                     is_async=isinstance(node, ast.AsyncFunctionDef))


def _module_name(path: str, roots: tuple[str, ...]) -> str | None:
    for root in sorted(roots, key=len, reverse=True):
        p = PurePosixPath(path)
        try:
            relative = p if root == "." else p.relative_to(root)
        except ValueError:
            continue
        parts = list(relative.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)
    return None


def scope_nodes(nodes: Iterable[ast.AST]) -> Iterator[ast.AST]:
    for node in nodes:
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            expressions = [*node.args.defaults, *(value for value in node.args.kw_defaults if value is not None)]
            if not isinstance(node, ast.Lambda):
                expressions.extend(node.decorator_list)
                expressions.extend(arg.annotation for arg in ast.walk(node.args)
                                   if isinstance(arg, ast.arg) and arg.annotation is not None)
                if node.returns is not None:
                    expressions.append(node.returns)
            yield from scope_nodes(expressions)
            continue
        if isinstance(node, ast.ClassDef):
            yield from scope_nodes([*node.decorator_list, *node.bases, *(item.value for item in node.keywords)])
            continue
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            yield from (part for part in ast.walk(node) if isinstance(part, ast.NamedExpr))
            continue
        yield from scope_nodes(ast.iter_child_nodes(node))


def bound_names(nodes: Iterable[ast.AST]) -> set[str]:
    names: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.add(node.rest)
    return names


def module_class_globals(nodes: Iterable[ast.AST]) -> set[str]:
    """Class bodies run in the enclosing execution; function bodies are deferred."""
    pending = [node for node in scope_nodes(nodes) if isinstance(node, ast.ClassDef)]
    names: set[str] = set()
    while pending:
        lexical = tuple(scope_nodes(pending.pop().body))
        names.update(name for node in lexical if isinstance(node, ast.Global) for name in node.names)
        pending.extend(node for node in lexical if isinstance(node, ast.ClassDef))
    return names


def parse_module(blob: Blob, name: str) -> Module:
    if blob.limitation:
        return Module(blob.path, name, (), (), (), blob.limitation, "")
    try:
        source = (blob.content or b"").decode("utf-8")
        tree = ast.parse(source, filename=blob.path)
    except (UnicodeDecodeError, SyntaxError, ValueError, RecursionError):
        return Module(blob.path, name, (), (), (), "parse_error", "")
    definitions: list[Definition] = []
    imports: list[tuple[str, str, str | None]] = []
    unresolved: set[Node] = set()
    assignments = module_class_globals(tree.body)
    scope_counts: dict[str, int] = {}

    def visit(body: list[ast.stmt], prefix: str, in_class: bool, conditional: bool) -> None:
        for statement in body:
            assignments.update(prefix + name for name in bound_names(scope_nodes((statement,))))
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = prefix + statement.name
                scope_counts[qualname] = scope_counts.get(qualname, 0) + 1
                node = Node(path=blob.path, qualname=qualname)
                calls: list[str] = []
                outer_expressions = [*statement.decorator_list, *statement.args.defaults,
                                     *(value for value in statement.args.kw_defaults if value is not None)]
                if any(isinstance(part, ast.Name) for expression in outer_expressions
                       for part in ast.walk(expression)):
                    unresolved.add(node)
                bindings = {arg.arg for arg in ast.walk(statement.args) if isinstance(arg, ast.arg)}
                lexical = tuple(scope_nodes(statement.body))
                bindings.update(bound_names(lexical))
                bindings.update(n.name for n in lexical
                                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
                bindings.difference_update(name for n in lexical
                                           if isinstance(n, (ast.Global, ast.Nonlocal)) for name in n.names)
                for part in ast.walk(statement):
                    if isinstance(part, ast.Call):
                        if isinstance(part.func, ast.Name):
                            calls.append(part.func.id)
                        else:
                            unresolved.add(node)
                    if isinstance(part, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
                        unresolved.add(node)
                definitions.append(Definition(node, "method" if in_class else "function", signature(statement),
                    hashlib.sha256(ast.dump(statement, include_attributes=False).encode()).hexdigest(),
                    statement.lineno, statement.end_lineno or statement.lineno,
                    ast.get_source_segment(source, statement) or "", conditional, tuple(calls), frozenset(bindings),
                    frozenset(n.id for n in ast.walk(statement)
                              if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load))))
                visit(statement.body, qualname + ".<locals>.", False, conditional)
            elif isinstance(statement, ast.ClassDef):
                scope_name = prefix + statement.name
                scope_counts[scope_name] = scope_counts.get(scope_name, 0) + 1
                visit(statement.body, prefix + statement.name + ".", True, conditional)
            elif isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                for target in targets:
                    assignments.update(prefix + n.id for n in ast.walk(target) if isinstance(n, ast.Name))
            elif isinstance(statement, ast.Delete):
                for target in statement.targets:
                    assignments.update(prefix + n.id for n in ast.walk(target)
                                       if isinstance(n, ast.Name))
            elif isinstance(statement, (ast.Import, ast.ImportFrom)):
                for alias in statement.names:
                    bound = alias.asname or (alias.name.split(".")[0]
                                             if isinstance(statement, ast.Import) else alias.name)
                    scope = prefix + bound
                    scope_counts[scope] = scope_counts.get(scope, 0) + 1
                if prefix:
                    continue
                if isinstance(statement, ast.ImportFrom):
                    module = statement.module or ""
                    if statement.level:
                        package = name.split(".") if blob.path.endswith("/__init__.py") else name.split(".")[:-1]
                        module = ".".join(package[:len(package) - statement.level + 1] + ([module] if module else []))
                    for alias in statement.names:
                        imports.append((alias.asname or alias.name, module, alias.name))
                        if alias.name == "*":
                            unresolved.add(Node(path=blob.path))
                else:
                    for alias in statement.names:
                        imports.append((alias.asname or alias.name, alias.name, None))
            else:
                for field, value in ast.iter_fields(statement):
                    if field in {"body", "orelse", "finalbody"} and isinstance(value, list):
                        visit(value, prefix, in_class, True)
                    elif field == "handlers" and isinstance(value, list):
                        for handler in value:
                            visit(handler.body, prefix, in_class, True)
                    elif field == "cases" and isinstance(value, list):
                        for case in value:
                            visit(case.body, prefix, in_class, True)

    visit(tree.body, "", False, False)
    counts: dict[Node, int] = {}
    for definition in definitions:
        counts[definition.node] = counts.get(definition.node, 0) + 1
    from dataclasses import replace
    ambiguous_scopes = {name for name, count in scope_counts.items() if count > 1} | assignments
    definitions = [replace(d, ambiguous=d.ambiguous or counts[d.node] > 1
                          or any(symbol == "*" for _, _, symbol in imports) or any(
        d.node.qualname == scope or (d.node.qualname or "").startswith(scope + ".") for scope in ambiguous_scopes))
                   for d in definitions]
    for name_assigned in assignments:
        unresolved.add(Node(path=blob.path, qualname=name_assigned))
    return Module(blob.path, name, tuple(definitions), tuple(imports), tuple(unresolved), None, source)


def build_index(snapshot: Snapshot, config: IndexConfig = IndexConfig(),
                cache: dict[tuple[str, str, str, str, str], Module] | None = None) -> CodeIndex:
    modules: list[Module] = []
    for blob in snapshot.blobs:
        if not blob.path.endswith(".py"):
            continue
        name = _module_name(blob.path, config.source_roots)
        if name is None:
            continue
        if blob.limitation:
            modules.append(parse_module(blob, name))
            continue
        key = (blob.object_id, sys.version, INDEX_VERSION, blob.path, name)
        if cache is not None and key in cache:
            module = cache[key]
        else:
            module = parse_module(blob, name)
            if cache is not None:
                cache[key] = module
        modules.append(module)
    by_name: dict[str, list[Module]] = {}
    for module in modules:
        by_name.setdefault(module.module_name, []).append(module)
    edges: set[Dependency] = set()
    unresolved = {node for module in modules for node in module.unresolved}
    for module in modules:
        module_unresolved = frozenset(module.unresolved)
        local = {d.node.qualname: d for d in module.definitions}
        imported: dict[str, Node] = {}
        for alias, target_module, symbol in module.imports:
            targets = by_name.get(target_module, [])
            if len(targets) == 1 and symbol and symbol != "*":
                candidates = [d for d in targets[0].definitions if d.node.qualname == symbol and not d.ambiguous]
                if len(candidates) == 1:
                    imported[alias] = candidates[0].node
                    if config.build_graph:
                        edges.add(Dependency(source=Node(path=module.path), target=candidates[0].node, relation="imports", origin="static"))
                else:
                    unresolved.add(Node(path=module.path))
            else:
                unresolved.add(Node(path=module.path))
        for definition in module.definitions:
            if definition.loaded_names - definition.local_bindings - set(definition.calls):
                unresolved.add(definition.node)
            for call in definition.calls:
                if call in definition.local_bindings or Node(path=module.path, qualname=call) in module_unresolved:
                    unresolved.add(definition.node)
                    continue
                candidate = local.get(call)
                target = candidate.node if candidate and not candidate.ambiguous else imported.get(call)
                if target is None:
                    unresolved.add(definition.node)
                elif config.build_graph:
                    edges.add(Dependency(source=definition.node, target=target, relation="calls", origin="static"))
    return CodeIndex(snapshot.revision, tuple(modules), tuple(sorted(edges, key=lambda e: (e.source.path, e.source.qualname or "", e.target.path, e.target.qualname or "", e.relation))),
                     frozenset(unresolved), any(n.qualname is None for n in unresolved))


def compare_indexes(before: CodeIndex, after: CodeIndex, old: Snapshot, new: Snapshot) -> ChangeSet:
    left, right = before.definitions(), after.definitions()
    symbols = frozenset(node for node in left.keys() | right.keys()
                       if node not in left or node not in right or left[node].ast_hash != right[node].ast_hash
                       or left[node].ambiguous or right[node].ambiguous)
    changed_consumers = {edge.source for edge in set(before.edges) ^ set(after.edges)}
    symbols = symbols | frozenset(changed_consumers)
    return ChangeSet(changed_files(old, new), symbols, tuple(set(before.edges) | set(after.edges)),
                     before.unresolved | after.unresolved,
                     frozenset(before.limitations().keys() | after.limitations().keys()),
                     before.global_unresolved or after.global_unresolved)


def impacted(changes: ChangeSet, depth: int) -> frozenset[Node]:
    seen = set(changes.symbols)
    seen.update(Node(path=path) for path in changes.files)
    frontier = set(seen)
    for _ in range(depth):
        consumers = {edge.source for edge in changes.edges if edge.target in frontier}
        frontier = consumers - seen
        seen.update(frontier)
    return frozenset(seen)
