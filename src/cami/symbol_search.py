from __future__ import annotations

import ast
import platform
from dataclasses import replace
from pathlib import Path
from typing import Literal

from cami.ecma_models import EcmaRelation
from cami.errors import InputError, ResourceError
from cami.index import INDEX_VERSION, CodeIndex, IndexConfig, Module, bound_names, build_index, scope_nodes
from cami.models import Dependency, Node, safe_path
from cami.product.models import (
    EcmaMatch, EcmaNotPresent, EcmaReady, EcmaUnavailable, FindResult, GitSnapshot, Observation,
    SearchLimitation, SearchMatch, SymbolMatch, WorktreeSnapshot,
)
from cami.product.ecma import analyze_snapshot, find_matches
from cami.product.git_snapshot import read_product_snapshot
from cami.repository import Snapshot, git


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
            bindings: dict[str, set[tuple[str | None, str]]] = {}
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
                target_module, target_name = next(iter(imports))
                if target_module is None:
                    continue
                candidates = targets.get((target_module, target_name), [])
                if len(candidates) == 1:
                    edges.add(Dependency(source=definition.node, target=candidates[0],
                                         relation="calls", origin="static"))
    return edges


def _import_module(module: Module, node: ast.ImportFrom) -> str | None:
    if not node.level:
        return node.module
    package = module.module_name.split(".") if module.module_name else []
    if not module.path.endswith("/__init__.py") and module.path != "__init__.py":
        package = package[:-1]
    if node.level > len(package):
        return None
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


def _search_index(snapshot: Snapshot, config: IndexConfig) -> CodeIndex:
    index = build_index(snapshot, config)
    edges = tuple(sorted(set(index.edges) | _local_import_edges(index), key=_edge_key))
    return replace(index, edges=edges)


def find_symbols(repo: Path, query: str, revision: str | None = None,
                 source_roots: tuple[str, ...] | None = None,
                 excluded_paths: tuple[str, ...] = ()) -> FindResult:
    if not query.strip() or "\x00" in query:
        raise InputError("symbol must be nonempty and contain no NUL characters")
    for path in (*(source_roots or ()), *excluded_paths):
        safe_path(path)
    if not repo.is_dir():
        raise InputError(f"repository directory does not exist: {repo}")
    observation: Observation | None = None
    source: GitSnapshot | WorktreeSnapshot
    if revision is not None:
        if excluded_paths:
            raise InputError("--exclude applies only to worktree search")
        snapshot = read_product_snapshot(repo, revision, source_roots)
        if source_roots is None:
            source_roots = (("src", ".") if any(blob.path.startswith("src/")
                                                  and blob.path.endswith(".py")
                                                  for blob in snapshot.blobs) else (".",))
        index = _search_index(snapshot, IndexConfig(source_roots))
        typescript = analyze_snapshot(snapshot)
        source = GitSnapshot(
            revision=snapshot.revision,
            tree=git(repo, "rev-parse", snapshot.revision + "^{tree}").decode().strip(),
            source_roots=source_roots, index_version=INDEX_VERSION,
            python_version=platform.python_version())
    else:
        from cami.product.store import refresh
        from cami.product.worktree import repository_root

        indexed = refresh(repository_root(repo), source_roots, excluded_paths, _search_index)
        snapshot = indexed.capture.as_snapshot()
        index = indexed.generation.index
        typescript = indexed.generation.typescript
        observation = indexed.observation
        source = WorktreeSnapshot(
            snapshot_id=indexed.capture.snapshot_id,
            generation_id=indexed.generation.manifest.generation_id,
            base_commit=indexed.capture.base_commit, source_roots=indexed.capture.policy.source_roots,
            policy=indexed.capture.policy, fingerprint=indexed.generation.manifest.fingerprint,
            index_version=INDEX_VERSION, python_version=platform.python_version())
    edges = index.edges
    matches: list[SearchMatch] = []
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
    if isinstance(typescript, EcmaReady):
        matches.extend(find_matches(typescript.analysis, query))
    if isinstance(typescript, EcmaUnavailable) and not matches:
        raise ResourceError(typescript.message)
    matches.sort(key=lambda match: (match.path, match.qualname, match.start_line, match.end_line,
                                    match.occurrence_id if isinstance(match, EcmaMatch) else ""))
    status: Literal["found", "not_found", "ambiguous"] = "not_found"
    if matches:
        status = "ambiguous" if len(matches) > 1 or any(m.ambiguous for m in matches) else "found"
    limitations = [SearchLimitation(code=code) for code in (
        "python_functions_and_methods_only" if isinstance(typescript, EcmaNotPresent)
        else "functions_and_methods_only", "static_graph_is_partial",
        "calls_may_include_nested_scopes", "unresolved_is_conservative",
        "runtime_binding_not_evaluated")]
    limitations.extend(SearchLimitation(code=code, path=path)
                       for path, code in sorted(index.limitations().items()))
    limitations.extend(SearchLimitation(code=blob.limitation, path=blob.path)
                       for blob in snapshot.blobs if blob.limitation
                       and blob.path not in index.limitations())
    ecma_limited = isinstance(typescript, EcmaUnavailable)
    if isinstance(typescript, EcmaUnavailable):
        limitations.append(SearchLimitation(code="typescript_unavailable"))
    if isinstance(typescript, EcmaReady):
        analysis = typescript.analysis
        limitations.extend(SearchLimitation(code=item.reason, path=item.path)
                           for item in analysis.excluded_files)
        limitations.extend(SearchLimitation(code="typescript_" + item.code,
                                           path=item.site.path if item.site else None)
                           for item in analysis.diagnostics if item.severity != "info")
        ecma_limited = (not analysis.configuration.valid
                        or any(item.reason != "declaration_file" for item in analysis.excluded_files)
                        or any(item.severity != "info" for item in analysis.diagnostics))
    limitations = sorted(set(limitations), key=lambda item: (item.path or "", item.code))
    limited = ecma_limited or bool(index.limitations()) or any(blob.limitation for blob in snapshot.blobs)
    return FindResult(
        query=query, requested_revision=revision, snapshot=source, observation=observation,
        status=status, coverage="partial" if limited else "complete",
        absence_confirmed=status == "not_found" and not limited,
        matches=tuple(matches), typescript=typescript, limitations=tuple(limitations),
        unresolved=tuple(sorted(index.unresolved, key=lambda node: (node.path, node.qualname or ""))),
        global_unresolved=index.global_unresolved or isinstance(typescript, EcmaUnavailable)
        or (isinstance(typescript, EcmaReady)
            and any(item.scope.endswith(":module") for item in typescript.analysis.unresolved)))


def format_text(result: FindResult) -> str:
    lines = [f"{result.status}: {result.query}"]
    if isinstance(result.snapshot, GitSnapshot):
        lines.extend((f"Git revision: {result.snapshot.revision}",
                      f"Snapshot tree: {result.snapshot.tree}"))
    else:
        lines.extend((f"Worktree snapshot: {result.snapshot.snapshot_id}",
                      f"Generation: {result.snapshot.generation_id}",
                      "Consistency: verified_readset (verified reads, not an atomic filesystem snapshot)"))
    lines.append(f"Coverage: {result.coverage}")
    if result.status == "not_found" and not result.absence_confirmed:
        lines.append("Absence is not confirmed because some inputs could not be indexed.")
    for match in result.matches:
        lines.append(f"{match.path}:{match.start_line}-{match.end_line} {match.qualname}"
                     + (" [ambiguous binding]" if match.ambiguous else ""))
        lines.append(f"  {match.signature_text}")
        for label, edges in (("incoming", match.incoming), ("outgoing", match.outgoing)):
            lines.append(f"  {label}: {len(edges)} static relations")
            for edge in edges:
                if isinstance(edge, EcmaRelation):
                    lines.append(f"    {edge.source or '<module>'} --{edge.kind}--> {edge.target}"
                                 f" at {edge.site.path}:{edge.site.line}:{edge.site.column}")
                else:
                    lines.append(f"    {edge.source.path}:{edge.source.qualname or '<module>'}"
                             f" --{edge.relation}--> "
                             f"{edge.target.path}:{edge.target.qualname or '<module>'}")
    if isinstance(result.typescript, EcmaReady):
        analysis = result.typescript.analysis
        lines.append(f"TypeScript compiler: {analysis.compiler_version}; offsets: {analysis.offset_unit}")
        lines.append(f"TypeScript unresolved: {len(analysis.unresolved)}")
        lines.extend(f"Diagnostic: {item.code}: {item.message}" for item in analysis.diagnostics)
    elif isinstance(result.typescript, EcmaUnavailable):
        lines.append(result.typescript.message)
    lines.append("Graph is partial; relations are static candidates, not runtime guarantees.")
    lines.append(f"Unresolved nodes: {len(result.unresolved)}; "
                 f"global unresolved: {str(result.global_unresolved).lower()}")
    lines.extend(f"Limitation: {item.code}" + (f" ({item.path})" if item.path else "")
                 for item in result.limitations)
    return "\n".join(lines)
