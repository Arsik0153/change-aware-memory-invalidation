from __future__ import annotations

import ast
import platform
from pathlib import Path
from typing import Literal

from cami.errors import InputError
from cami.index import INDEX_VERSION, CodeIndex, IndexConfig, Module, bound_names, build_index, scope_nodes
from cami.models import Dependency, Node, Record, RepoLocation, Signature, Value
from cami.repository import git, read_snapshot


class SearchSnapshot(Value):
    kind: Literal["git"] = "git"
    revision: str
    tree: str
    source_roots: tuple[str, ...]
    index_version: str = INDEX_VERSION
    search_version: Literal["1"] = "1"
    python_version: str


class SearchLimitation(Value):
    code: str
    path: str | None = None


class SymbolMatch(Value):
    path: str
    qualname: str
    module: str
    qualified_name: str
    node_kind: str
    start_line: int
    end_line: int
    signature: Signature
    signature_text: str
    ambiguous: bool
    incoming: tuple[Dependency, ...]
    outgoing: tuple[Dependency, ...]


class FindResult(Record):
    query: str
    requested_revision: str
    snapshot: SearchSnapshot
    status: Literal["found", "not_found", "ambiguous"]
    matches: tuple[SymbolMatch, ...]
    graph_complete: Literal[False] = False
    limitations: tuple[SearchLimitation, ...]
    unresolved: tuple[Node, ...]
    global_unresolved: bool


def _edge_key(edge: Dependency) -> tuple[str, str, str, str, str]:
    return (edge.source.path, edge.source.qualname or "", edge.target.path,
            edge.target.qualname or "", edge.relation)


def _local_import_edges(index: CodeIndex) -> set[Dependency]:
    """Add candidate calls through unshadowed function-local from-imports."""
    targets: dict[tuple[str, str], list[Node]] = {}
    module_counts: dict[str, int] = {}
    for module in index.modules:
        module_counts[module.module_name] = module_counts.get(module.module_name, 0) + 1
    for module in index.modules:
        for definition in module.definitions:
            if not definition.ambiguous and module_counts[module.module_name] == 1:
                targets.setdefault((module.module_name, definition.node.qualname or ""), []).append(
                    definition.node)
    edges: set[Dependency] = set()
    for module in index.modules:
        if not module.source:
            continue
        functions = {node.lineno: node for node in ast.walk(ast.parse(module.source))
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for definition in module.definitions:
            if definition.ambiguous:
                continue
            function = functions[definition.start_line]
            lexical = tuple(scope_nodes(function.body))
            blocked = bound_names(lexical)
            blocked.update(arg.arg for arg in ast.walk(function.args) if isinstance(arg, ast.arg))
            blocked.update(node.name for node in lexical
                           if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
            blocked.update(name for node in lexical if isinstance(node, (ast.Global, ast.Nonlocal))
                           for name in node.names)
            bindings: dict[str, set[tuple[str, str]]] = {}
            for node in lexical:
                if isinstance(node, ast.ImportFrom):
                    target_module = _import_module(module, node)
                    for alias in node.names:
                        if alias.name == "*":
                            blocked.update(definition.calls)
                        else:
                            bindings.setdefault(alias.asname or alias.name, set()).add(
                                (target_module, alias.name))
                elif isinstance(node, ast.Import):
                    blocked.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
            calls = {node.func.id for node in lexical if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name)}
            for called_name in sorted(calls & bindings.keys() - blocked):
                imports = bindings[called_name]
                if len(imports) != 1:
                    continue
                candidates = targets.get(next(iter(imports)), [])
                if len(candidates) == 1:
                    edges.add(Dependency(source=definition.node, target=candidates[0],
                                         relation="calls", origin="static"))
    return edges


def _import_module(module: Module, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = module.module_name.split(".")
    if not module.path.endswith("/__init__.py") and module.path != "__init__.py":
        package = package[:-1]
    if node.level > len(package):
        return ""
    return ".".join(package[:len(package) - node.level + 1]
                    + ([node.module] if node.module else []))


def _signature_text(source: str) -> str:
    function = ast.parse(source).body[0]
    assert isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
    prefix = "async def" if isinstance(function, ast.AsyncFunctionDef) else "def"
    type_params = ("[" + ", ".join(ast.unparse(param) for param in function.type_params) + "]"
                   if function.type_params else "")
    returns = f" -> {ast.unparse(function.returns)}" if function.returns else ""
    return f"{prefix} {function.name}{type_params}({ast.unparse(function.args)}){returns}"


def find_symbols(repo: Path, query: str, revision: str = "HEAD",
                 source_roots: tuple[str, ...] | None = None) -> FindResult:
    if not query.strip() or "\x00" in query:
        raise InputError("symbol must be nonempty and contain no NUL characters")
    if not repo.is_dir():
        raise InputError(f"repository directory does not exist: {repo}")
    snapshot = read_snapshot(RepoLocation(repo_id="symbol-search", path=str(repo)), revision)
    if source_roots is None:
        source_roots = (("src", ".") if any(blob.path.startswith("src/")
                                              and blob.path.endswith(".py")
                                              for blob in snapshot.blobs) else (".",))
    location = RepoLocation(repo_id="symbol-search", path=str(repo), source_roots=source_roots)
    index = build_index(snapshot, IndexConfig(location.source_roots))
    edges = tuple(sorted(set(index.edges) | _local_import_edges(index), key=_edge_key))
    matches: list[SymbolMatch] = []
    for module in index.modules:
        for definition in module.definitions:
            qualname = definition.node.qualname or ""
            qualified_name = ".".join(part for part in (module.module_name, qualname) if part)
            identifiers = {qualname, qualified_name, f"{module.path}:{qualname}"}
            if "." not in query and ":" not in query:
                identifiers.add(qualname.rsplit(".", 1)[-1])
            if query not in identifiers:
                continue
            matches.append(SymbolMatch(
                path=module.path, qualname=qualname, module=module.module_name,
                qualified_name=qualified_name, node_kind=definition.node_kind,
                start_line=definition.start_line, end_line=definition.end_line,
                signature=definition.signature, signature_text=_signature_text(definition.source),
                ambiguous=definition.ambiguous,
                incoming=tuple(edge for edge in edges if edge.target == definition.node),
                outgoing=tuple(edge for edge in edges if edge.source == definition.node)))
    matches.sort(key=lambda match: (match.path, match.qualname, match.start_line, match.end_line))
    status: Literal["found", "not_found", "ambiguous"] = "not_found"
    if matches:
        status = "ambiguous" if len(matches) > 1 or any(m.ambiguous for m in matches) else "found"
    limitations = [SearchLimitation(code=code) for code in (
        "python_functions_and_methods_only", "static_graph_is_partial",
        "calls_may_include_nested_scopes", "unresolved_is_conservative",
        "runtime_binding_not_evaluated")]
    limitations.extend(SearchLimitation(code=code, path=path)
                       for path, code in sorted(index.limitations().items()))
    limitations.extend(SearchLimitation(code=blob.limitation, path=blob.path)
                       for blob in snapshot.blobs if blob.limitation
                       and blob.path not in index.limitations())
    return FindResult(
        query=query, requested_revision=revision,
        snapshot=SearchSnapshot(revision=snapshot.revision,
                                tree=git(repo, "rev-parse", snapshot.revision + "^{tree}").decode().strip(),
                                source_roots=source_roots, python_version=platform.python_version()),
        status=status, matches=tuple(matches), limitations=tuple(limitations),
        unresolved=tuple(sorted(index.unresolved, key=lambda node: (node.path, node.qualname or ""))),
        global_unresolved=index.global_unresolved)


def format_text(result: FindResult) -> str:
    lines = [f"{result.status}: {result.query}",
             f"Git revision: {result.snapshot.revision}", f"Snapshot tree: {result.snapshot.tree}"]
    for match in result.matches:
        lines.append(f"{match.path}:{match.start_line}-{match.end_line} {match.qualname}"
                     + (" [ambiguous binding]" if match.ambiguous else ""))
        lines.append(f"  {match.signature_text}")
        for label, edges in (("incoming", match.incoming), ("outgoing", match.outgoing)):
            lines.append(f"  {label}: {len(edges)} static relations")
            for edge in edges:
                lines.append(f"    {edge.source.path}:{edge.source.qualname or '<module>'}"
                             f" --{edge.relation}--> "
                             f"{edge.target.path}:{edge.target.qualname or '<module>'}")
    lines.append("Graph is partial; relations are static candidates, not runtime guarantees.")
    lines.append(f"Unresolved nodes: {len(result.unresolved)}; "
                 f"global unresolved: {str(result.global_unresolved).lower()}")
    lines.extend(f"Limitation: {item.code}" + (f" ({item.path})" if item.path else "")
                 for item in result.limitations)
    return "\n".join(lines)
