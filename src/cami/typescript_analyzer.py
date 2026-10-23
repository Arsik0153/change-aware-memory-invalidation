"""Run the packaged trusted compiler on caller-captured contents only."""

import bisect
import json
import subprocess
import tempfile
from collections.abc import Mapping

from pydantic import ValidationError

from cami.typescript_runtime import (
    clean_environment, compiler_path, sidecar_directory, trusted_compiler,
)

from cami.ecma_models import (
    EcmaAnalysis,
    EcmaRelation,
    EcmaUnresolved,
    EvidenceSite,
    captured_path,
)

MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_FILES = 10000


class TypeScriptAnalyzerError(RuntimeError):
    """Analysis failed; the caller must not treat this as an empty successful index."""


class TypeScriptAnalyzerUnavailable(TypeScriptAnalyzerError):
    """Node or the exact packaged compiler dependency is unavailable."""


def _positions(source: str) -> tuple[list[int], int]:
    starts = [0]
    offset = 0
    previous = ""
    for char in source:
        offset += 2 if ord(char) > 0xFFFF else 1
        if char == "\n" and previous == "\r":
            starts[-1] = offset
        elif char in "\r\n\u2028\u2029":
            starts.append(offset)
        previous = char
    return starts, offset


def _validate_analysis(result: EcmaAnalysis, files: dict[str, str], request_id: str) -> None:
    if result.request_id != request_id:
        raise ValueError("Analyzer returned a different request ID")
    positions = {name: _positions(source) for name, source in files.items()}

    def check_site(site: EvidenceSite) -> None:
        if site.path not in positions:
            raise ValueError("Evidence refers to an uncaptured file")
        starts, length = positions[site.path]
        if site.end > length:
            raise ValueError("Evidence exceeds captured source")
        for offset, line, column in (
            (site.start, site.line, site.column),
            (site.end, site.end_line, site.end_column),
        ):
            index = bisect.bisect_right(starts, offset) - 1
            if (line, column) != (index + 1, offset - starts[index] + 1):
                raise ValueError("Evidence coordinates do not match UTF-16 source offsets")

    definition_paths = {definition.id: definition.site.path for definition in result.definitions}
    ids = set(definition_paths)
    if len(ids) != len(result.definitions):
        raise ValueError("Duplicate declaration occurrence IDs")
    analyzed = set(result.analyzed_files)
    excluded = {item.path for item in result.excluded_files}
    expected = {name for name in files if name.endswith((".js", ".jsx", ".ts", ".tsx"))}
    if analyzed | excluded != expected or len(excluded) != len(result.excluded_files):
        raise ValueError("Incomplete or duplicate analyzed/excluded file coverage")
    if len(analyzed) != len(result.analyzed_files) or analyzed & excluded:
        raise ValueError("Conflicting analyzed/excluded files")
    for name in (*analyzed, *excluded):
        captured_path(name)
        if name not in files:
            raise ValueError("Analyzer returned an uncaptured path")
    if result.configuration.root_config is not None:
        captured_path(result.configuration.root_config)
    for definition in result.definitions:
        check_site(definition.site)
        if definition.key.path != definition.site.path or definition.key.path not in analyzed:
            raise ValueError("Definition path does not match analyzed evidence")
        expected_id = f"{definition.site.path}:{definition.site.start}:{definition.key.kind}"
        if definition.id != expected_id:
            raise ValueError("Invalid declaration occurrence ID")
    references: tuple[EcmaRelation | EcmaUnresolved, ...] = (*result.relations, *result.unresolved)
    for item in references:
        check_site(item.site)
        if item.site.path not in analyzed or (item.source is not None and item.source not in ids):
            raise ValueError("Invalid relation owner or file")
        if item.source is not None and definition_paths[item.source] != item.site.path:
            raise ValueError("Relation owner belongs to another file")
        if not item.scope.startswith(f"{item.site.path}:"):
            raise ValueError("Relation scope belongs to another file")
        targets = (item.target,) if isinstance(item, EcmaRelation) else item.candidates
        if any(target not in ids for target in targets):
            raise ValueError("Reference to an unknown declaration")
    for export in result.exports:
        captured_path(export.path)
        check_site(export.site)
        if export.path != export.site.path or export.path not in analyzed:
            raise ValueError("Invalid export path")
        if any(target not in ids for target in export.candidates):
            raise ValueError("Export candidate is unknown")
        if (export.reason is None) != (export.target is not None):
            raise ValueError("Export resolution state is inconsistent")
        if export.target is not None and export.target not in ids:
            raise ValueError("Export target is unknown")
    for gap in result.identity_gaps:
        captured_path(gap.path)
        if gap.path not in analyzed:
            raise ValueError("Identity gap refers to an unanalyzed file")
    for diagnostic in result.diagnostics:
        if diagnostic.site is not None:
            check_site(diagnostic.site)


def analyze_typescript(
    files: Mapping[str, str | bytes],
    *,
    root_config: str | None = None,
    request_id: str = "snapshot",
    timeout: float = 30.0,
    node_executable: str = "node",
) -> EcmaAnalysis:
    """Analyze one complete capture, without reading any target checkout.

    Byte sources must be UTF-8. Configs and resolver inputs belong in ``files``.
    ``None`` selects captured root tsconfig.json, then jsconfig.json, then defaults.
    Every invocation starts one bounded Node process. It never runs npm.
    """
    if not isinstance(request_id, str) or not request_id or len(request_id) > 1024:
        raise ValueError("request_id must contain 1..1024 characters")
    if not 0 < timeout <= 300:
        raise ValueError("timeout must be in (0, 300] seconds")
    if len(files) > MAX_FILES:
        raise ValueError(f"Capture exceeds {MAX_FILES} files")
    if root_config is not None:
        captured_path(root_config)
    sources = {}
    source_bytes = 0
    for name, source in sorted(files.items()):
        captured_path(name)
        if not isinstance(source, (str, bytes)):
            raise ValueError("Captured source must be text or UTF-8 bytes")
        text = source.decode("utf-8") if isinstance(source, bytes) else source
        source_bytes += len(text.encode("utf-8"))
        if source_bytes > MAX_INPUT_BYTES:
            raise ValueError("Capture exceeds 16 MiB")
        sources[name] = text
    payload = json.dumps(
        dict(schema_version=1, request_id=request_id, files=sources, root_config=root_config),
        ensure_ascii=False,
    ).encode("utf-8")
    if len(payload) > MAX_INPUT_BYTES:
        raise ValueError("Serialized capture exceeds 16 MiB")
    directory = sidecar_directory()
    compiler = compiler_path()
    if not trusted_compiler(compiler):
        raise TypeScriptAnalyzerUnavailable(
            "Trusted TypeScript 6.0.3 dependency is missing. Install Node.js 24 and npm 11, "
            "then run cami setup-typescript (trusted npm ci --ignore-scripts)."
        )
    environment = clean_environment()
    # Temporary streams bound Python memory even if the child fails before its output limit.
    with (
        tempfile.TemporaryFile() as stdin,
        tempfile.TemporaryFile() as stdout,
        tempfile.TemporaryFile() as stderr,
    ):
        stdin.write(payload)
        stdin.seek(0)
        try:
            process = subprocess.Popen(
                [
                    node_executable,
                    "--no-addons",
                    "--no-global-search-paths",
                    str(directory / "analyze.cjs"),
                    str(compiler),
                ],
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                cwd=directory,
                env=environment,
            )
        except FileNotFoundError as error:
            raise TypeScriptAnalyzerUnavailable("Node.js 24 executable is unavailable") from error
        except OSError as error:
            raise TypeScriptAnalyzerError("Cannot start trusted TypeScript sidecar") from error
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.wait()
            raise TypeScriptAnalyzerError("TypeScript analysis exceeded timeout") from error
        except BaseException:
            process.kill()
            process.wait()
            raise
        stdout.seek(0)
        raw = stdout.read(MAX_OUTPUT_BYTES + 1)
        stderr.seek(0)
        error_text = stderr.read(8192).decode("utf-8", errors="replace")
        if len(raw) > MAX_OUTPUT_BYTES:
            raise TypeScriptAnalyzerError("Analyzer response exceeds 32 MiB")
        if process.returncode:
            raise TypeScriptAnalyzerError(f"TypeScript sidecar failed: {error_text.strip()}")
    try:
        result = EcmaAnalysis.model_validate_json(raw)
        _validate_analysis(result, sources, request_id)
    except (ValidationError, ValueError) as error:
        raise TypeScriptAnalyzerError(f"Invalid TypeScript analyzer response: {error}") from error
    return result
