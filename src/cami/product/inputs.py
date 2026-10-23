"""Select product inputs without reading unrelated JSON or executing target code."""

import json
import posixpath
import re
from collections.abc import Callable, Iterable
from pathlib import PurePosixPath

from cami.ecma_models import captured_path

CODE_SUFFIXES = (".py", ".js", ".jsx", ".ts", ".tsx")
ECMA_SUFFIXES = CODE_SUFFIXES[1:]
EXCLUDED_DIRS = (".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
                 ".mypy_cache", ".ruff_cache", ".cache", ".tox", ".nox", ".next", "dist",
                 "build", "out", "coverage", ".cami")
ROOT_OUTPUTS = ("runs", "reports", "output", "cache", "state")


def within(path: str, prefix: str) -> bool:
    return prefix == "." or path == prefix or path.startswith(prefix + "/")


def code_input(path: str, roots: tuple[str, ...]) -> bool:
    return path.endswith(CODE_SUFFIXES) and any(within(path, root) for root in roots)


def excluded(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return any(part in EXCLUDED_DIRS for part in parts) or parts[0] in ROOT_OUTPUTS


def _extends(raw: bytes) -> tuple[str, ...]:
    # Preserve quoted text while discarding JSONC comments and trailing commas.
    try:
        text = raw.decode("utf-8-sig")
        text = re.sub(r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/',
                      lambda m: m[0] if m[0].startswith('"') else " ", text)
        text = re.sub(r'"(?:\\.|[^"\\])*"|,\s*(?=[}\]])',
                      lambda m: m[0] if m[0].startswith('"') else "", text)
        config = json.loads(text)
    except (UnicodeError, ValueError):
        return ()
    if not isinstance(config, dict):
        return ()
    bases = config.get("extends", [])
    if isinstance(bases, str):
        return (bases,)
    return tuple(item for item in bases if isinstance(item, str)) if isinstance(bases, list) else ()


def configuration_inputs(sources: Iterable[str], exists: Callable[[str], bool],
                         read: Callable[[str], bytes | None]) -> None:
    """Read the selected root config, relative extends, and source ancestor packages.

    Missing or invalid configs remain compiler diagnostics. A callback records each
    selected input in the same verified capture as sources.
    """
    ecma_sources = [path for path in sources if path.endswith(ECMA_SUFFIXES)]
    if not ecma_sources:
        return
    packages = {str(parent / "package.json") for path in ecma_sources
                for parent in PurePosixPath(path).parents}
    contents: dict[str, bytes | None] = {}

    def selected(path: str) -> bytes | None:
        if path not in contents:
            contents[path] = read(path)
        return contents[path]

    for path in sorted(packages):
        if exists(path):
            selected(path)
    root = next((name for name in ("tsconfig.json", "jsconfig.json") if exists(name)), None)
    seen: set[str] = set()

    def config(path: str, depth: int) -> None:
        if path in seen or not exists(path) or depth >= 17:
            return
        seen.add(path)
        raw = selected(path)
        if raw is None:
            return
        for base in _extends(raw):
            if not base.startswith(".") or "\\" in base:
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(path), base))
            if not target.endswith(".json"):
                target += ".json"
            if target.startswith(("../", "/")):
                continue
            try:
                captured_path(target)
            except ValueError:
                continue
            config(target, depth + 1)

    if root:
        config(root, 0)
