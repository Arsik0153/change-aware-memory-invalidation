"""Adapt one complete compiler capture into the product query contract."""

from cami.ecma_models import EcmaAnalysis, EcmaSignature
from cami.product.inputs import ECMA_SUFFIXES
from cami.product.models import EcmaMatch, EcmaNotPresent, EcmaReady, EcmaState, EcmaUnavailable
from cami.repository import Snapshot
from cami.typescript_analyzer import TypeScriptAnalyzerError, analyze_typescript


def analyze_snapshot(snapshot: Snapshot) -> EcmaState:
    if not any(blob.path.endswith(ECMA_SUFFIXES) for blob in snapshot.blobs):
        return EcmaNotPresent()
    try:
        return EcmaReady(analysis=analyze_typescript(
            {blob.path: blob.content for blob in snapshot.blobs
             if blob.content is not None and not blob.path.endswith(".py")},
            request_id=snapshot.revision))
    except (TypeScriptAnalyzerError, ValueError) as error:
        return EcmaUnavailable(message=f"TypeScript analysis unavailable: {error}")


def signature_text(name: str, kind: str, signature: EcmaSignature) -> str:
    parameters = []
    for parameter in signature.parameters:
        text = ("..." if parameter.rest else "") + parameter.pattern
        text += "?" if parameter.optional else ""
        if parameter.annotation is not None:
            text += ": " + parameter.annotation
        if parameter.default is not None:
            text += " = " + parameter.default
        parameters.append(text)
    types = "<" + ", ".join(signature.type_parameters) + ">" if signature.type_parameters else ""
    prefix = "async " if signature.async_ else ""
    if kind in ("function", "function_expression"):
        prefix += "function" + ("*" if signature.generator else "") + " "
    elif signature.generator:
        prefix += "*"
    returns = ": " + signature.return_annotation if signature.return_annotation is not None else ""
    suffix = " =>" if kind == "arrow" else ""
    return prefix + name + types + "(" + ", ".join(parameters) + ")" + returns + suffix


def find_matches(analysis: EcmaAnalysis, query: str) -> tuple[EcmaMatch, ...]:
    matches = []
    for definition in analysis.definitions:
        path, qualname = definition.key.path, definition.key.qualname
        module_name = path.rsplit(".", 1)[0].replace("/", ".")
        qualified_name = module_name + "." + qualname
        identifiers = {qualname, qualified_name, f"{path}:{qualname}"}
        if "." not in query and ":" not in query:
            identifiers.add(definition.name)
            identifiers.update(export.name for export in analysis.exports
                               if export.target == definition.id
                               or definition.id in export.candidates)
        identifiers.update(f"{export.path}:{export.name}" for export in analysis.exports
                           if export.target == definition.id
                           or definition.id in export.candidates)
        if query not in identifiers:
            continue
        matches.append(EcmaMatch(
            language=definition.language, path=path, qualname=qualname, module=module_name,
            qualified_name=qualified_name, node_kind=definition.key.kind,
            start_line=definition.site.line, end_line=definition.site.end_line,
            signature=definition.signature,
            signature_text=signature_text(definition.name, definition.key.kind, definition.signature),
            ambiguous=definition.ambiguous, occurrence_id=definition.id, key=definition.key,
            site=definition.site, syntax_hash=definition.syntax_hash, ast_hash=definition.ast_hash,
            implementation=definition.implementation,
            incoming=tuple(edge for edge in analysis.relations if edge.target == definition.id),
            outgoing=tuple(edge for edge in analysis.relations if edge.source == definition.id)))
    return tuple(matches)
