from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import TypeAdapter, ValidationError

from cami.ecma_models import EcmaAnalysis, EcmaDefinition, EcmaIdentityGap
from cami.errors import IncompleteError
from cami.product.memory.models import (
    CodeView, DefinitionFact, EcmaSignatureSyntax, IndexRef,
    PathCoverage, PythonParameter, PythonSignature, SourceRef, SymbolKey,
)
from cami.product.memory.python_excerpt import (
    prepare_python_excerpt_source, project_python_excerpt,
)
from cami.product.models import EcmaReady, EcmaUnavailable, IndexedWorktree, Observation, digest
from cami.product.store import GenerationStore, refresh_locked, state_base
from cami.product.worktree import CaptureChanged, capture
from cami.typescript_analyzer import TypeScriptAnalyzerError, TypeScriptAnalyzerUnavailable
from cami.typescript_runtime import clean_environment, compiler_path
from cami.typescript_runtime import trusted_compiler as compiler_is_trusted


def python_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> PythonSignature:
    def syntax(value: ast.AST | None) -> str | None:
        return ast.dump(value, include_attributes=False) if value is not None else None

    args = node.args
    positional = args.posonlyargs + args.args
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults))
    defaults.extend(args.defaults)
    parameters = [PythonParameter(
        name=arg.arg, kind="positional_only" if i < len(args.posonlyargs)
        else "positional_or_keyword", annotation=syntax(arg.annotation), default=syntax(default))
        for i, (arg, default) in enumerate(zip(positional, defaults, strict=True))]
    if args.vararg:
        parameters.append(PythonParameter(name=args.vararg.arg, kind="var_positional",
                                          annotation=syntax(args.vararg.annotation), default=None))
    parameters.extend(PythonParameter(name=arg.arg, kind="keyword_only",
                                      annotation=syntax(arg.annotation), default=syntax(default))
                      for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True))
    if args.kwarg:
        parameters.append(PythonParameter(name=args.kwarg.arg, kind="var_keyword",
                                          annotation=syntax(args.kwarg.annotation), default=None))
    return PythonSignature(parameters=tuple(parameters), returns=syntax(node.returns),
                           decorators=tuple(ast.dump(d, include_attributes=False)
                                            for d in node.decorator_list),
                           type_parameters=tuple(ast.dump(t, include_attributes=False)
                                                 for t in node.type_params),
                           is_async=isinstance(node, ast.AsyncFunctionDef))


class PythonIndexAdapter:
    def project(self, indexed: IndexedWorktree) -> CodeView:
        manifest = indexed.generation.manifest
        ref = IndexRef(worktree_key=manifest.worktree_key, snapshot_id=manifest.snapshot_id,
                       generation_id=manifest.generation_id,
                       policy_fingerprint=digest(manifest.policy.model_dump(mode="json")),
                       analyzer_fingerprint=manifest.fingerprint)
        sources = {blob.path: SourceRef(index=ref, path=blob.path,
                                        sha256=hashlib.sha256(blob.content).hexdigest(),
                                        size=len(blob.content))
                   for blob in indexed.capture.blobs if blob.content is not None}
        raw_sources = {blob.path: blob.content for blob in indexed.capture.blobs
                       if blob.content is not None}
        definitions = []
        errors = []
        for module in indexed.generation.index.modules:
            if module.limitation:
                errors.append((module.path, module.limitation))
                continue
            tree = ast.parse(module.source)
            excerpt_source = prepare_python_excerpt_source(raw_sources[module.path], expected_source=module.source)
            nodes = {n.lineno: n for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for definition in module.definitions:
                node = nodes[definition.start_line]
                definitions.append(DefinitionFact(
                    subject=SymbolKey(language="python", path=module.path,
                                      qualname=definition.node.qualname or "",
                                      node_kind=definition.node_kind),
                    signature=python_signature(node), source=sources[module.path],
                    ambiguous=definition.ambiguous,
                    python_excerpt=project_python_excerpt(excerpt_source, node)))
        coverage = {s.path: PathCoverage(path=s.path, status="present") for s in sources.values()}
        coverage.update({c.path: PathCoverage(path=c.path, status=c.status)
                         for c in indexed.capture.path_coverage})
        edges = indexed.generation.index.edges
        return CodeView(index=ref, definitions=tuple(definitions), sources=tuple(sources.values()),
                        coverage=tuple(coverage[p] for p in sorted(coverage)),
                        path_errors=tuple(errors),
                        relation_scopes=tuple(sorted({digest(e.model_dump(mode="json"))
                                                      for e in edges})),
                        limitations=("python_functions_and_methods_only", "static_graph_is_partial",
                                     "runtime_binding_not_evaluated"))


def ecma_signatures(definitions: tuple[EcmaDefinition, ...], *,
                    trusted_compiler: Path | None = None) -> tuple[EcmaSignatureSyntax | None, ...]:
    """Canonicalize the actual core fields with the same trusted syntax parser, without inference."""
    compiler = trusted_compiler if trusted_compiler is not None else compiler_path()
    if not compiler_is_trusted(compiler):
        raise TypeScriptAnalyzerUnavailable("Trusted TypeScript 6.0.3 dependency is missing")
    payload = [{"language": d.language,
                "signature": d.signature.model_dump(mode="json", by_alias=True)} for d in definitions]
    environment = clean_environment()
    try:
        result = subprocess.run(
            ["node", "--no-addons", "--no-global-search-paths",
             str(Path(__file__).with_name("_ecma_syntax.cjs")), str(compiler)],
            input=json.dumps(payload).encode(), capture_output=True, timeout=30,
            cwd=compiler.parent, env=environment)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TypeScriptAnalyzerError("Cannot normalize compiler signature syntax") from exc
    if result.returncode:
        raise TypeScriptAnalyzerError("Compiler signature normalization failed: "
                                      + result.stderr.decode(errors="replace")[:2000])
    try:
        values = TypeAdapter(tuple[EcmaSignatureSyntax | None, ...]).validate_json(result.stdout)
        if len(values) != len(definitions):
            raise ValueError("Wrong signature count")
        return values
    except (ValueError, ValidationError) as exc:
        raise TypeScriptAnalyzerError("Invalid normalized compiler signatures") from exc


def ecma_view(analysis: EcmaAnalysis, index: IndexRef, captured: Mapping[str, bytes],
              coverage: tuple[PathCoverage, ...], *, trusted_compiler: Path | None = None) -> CodeView:
    """Adapt an actual compiler result and the same immutable capture; never run target code.

    The integrator supplies capture coverage and pins compiler/configuration fingerprints in index.
    Method signature predicates remain unsupported because core v1 omits access modifiers.
    """
    sources = {path: SourceRef(index=index, path=path, sha256=hashlib.sha256(raw).hexdigest(),
                               size=len(raw)) for path, raw in sorted(captured.items())}
    if not set(analysis.analyzed_files).issubset(sources):
        raise ValueError("ECMA analysis refers to uncaptured files")
    signatures = ecma_signatures(analysis.definitions, trusted_compiler=trusted_compiler)
    gaps_by_path: dict[str, list[EcmaIdentityGap]] = {}
    for gap in analysis.identity_gaps:
        gaps_by_path.setdefault(gap.path, []).append(gap)
    definitions = tuple(DefinitionFact(
        subject=SymbolKey(language=d.language, path=d.key.path, qualname=d.key.qualname,
                          node_kind=d.key.kind),
        signature=signature if d.key.kind != "method" else None,
        source=sources[d.key.path], ambiguous=d.ambiguous,
        identity_uncertain=not d.implementation or any(
            g.covers(d.key.path, d.key.qualname, d.key.kind)
            for g in gaps_by_path.get(d.key.path, ())))
        for d, signature in zip(analysis.definitions, signatures, strict=True))
    errors = tuple((item.path, "parse_error" if item.reason == "syntax_error"
                    else "scope_uncovered") for item in analysis.excluded_files)
    if not analysis.configuration.valid:
        errors += tuple((p, "scope_uncovered") for p in analysis.analyzed_files)
    return CodeView(index=index, definitions=definitions, sources=tuple(sources.values()),
                    coverage=coverage, path_errors=errors, identity_gaps=analysis.identity_gaps,
                    relation_scopes=tuple(sorted({digest(r.model_dump(mode="json"))
                                                  for r in analysis.relations})),
                    limitations=("static_graph_is_partial", "no_inferred_types",
                                 "ecma_core_v1_method_modifiers_unavailable"))


@dataclass(frozen=True)
class PreparedIndex:
    view: CodeView
    observation: Observation
    sources: dict[str, bytes]
    base_commit: str | None


class ProductIndexPort(Protocol):
    def prepare_locked(self, store: GenerationStore, root: Path,
                       source_roots: tuple[str, ...] | None, excluded_paths: tuple[str, ...],
                       probe_paths: tuple[str, ...]) -> PreparedIndex: ...

    def verify(self, root: Path, source_roots: tuple[str, ...] | None,
               excluded_paths: tuple[str, ...], probe_paths: tuple[str, ...],
               prepared: PreparedIndex) -> None: ...


class HybridIndexAdapter:
    def project(self, indexed: IndexedWorktree) -> CodeView:
        python = PythonIndexAdapter().project(indexed)
        state = indexed.generation.typescript
        if isinstance(state, EcmaReady):
            try:
                ecma = ecma_view(state.analysis, python.index,
                                 {b.path: b.content for b in indexed.capture.blobs
                                  if b.content is not None}, python.coverage)
            except TypeScriptAnalyzerError as exc:
                raise IncompleteError(f"memory_projection_unavailable: {exc}") from exc
            return python.model_copy(update={
                "definitions": python.definitions + ecma.definitions,
                "path_errors": tuple(sorted(set(python.path_errors + ecma.path_errors))),
                "identity_gaps": ecma.identity_gaps,
                "relation_scopes": tuple(sorted(set(python.relation_scopes + ecma.relation_scopes))),
                "limitations": tuple(sorted(set(python.limitations + ecma.limitations))),
            })
        if isinstance(state, EcmaUnavailable):
            paths = {c.path for c in python.coverage if c.path.endswith((".js", ".jsx", ".ts", ".tsx"))}
            return python.model_copy(update={
                "path_errors": tuple(sorted((*python.path_errors,
                                              *((p, "compiler_unavailable") for p in paths)))),
                "limitations": python.limitations + (state.message,),
            })
        return python


class HybridIndexPort:
    def prepare_locked(self, store: GenerationStore, root: Path,
                       source_roots: tuple[str, ...] | None, excluded_paths: tuple[str, ...],
                       probe_paths: tuple[str, ...]) -> PreparedIndex:
        from cami.symbol_search import _search_index

        indexed = refresh_locked(store, root, source_roots, excluded_paths, _search_index,
                                 probe_paths)
        return PreparedIndex(
            view=HybridIndexAdapter().project(indexed), observation=indexed.observation,
            sources={b.path: b.content for b in indexed.capture.blobs if b.content is not None},
            base_commit=indexed.capture.base_commit)

    def verify(self, root: Path, source_roots: tuple[str, ...] | None,
               excluded_paths: tuple[str, ...], probe_paths: tuple[str, ...],
               prepared: PreparedIndex) -> None:
        try:
            verified = capture(root, source_roots, excluded_paths, state_base(), probe_paths)
        except CaptureChanged as exc:
            raise IncompleteError("memory_refresh_unstable: capture changed") from exc
        if (verified.snapshot_id != prepared.view.index.snapshot_id
                or verified.base_commit != prepared.base_commit):
            raise IncompleteError("memory_refresh_unstable: inputs changed before DB commit")
