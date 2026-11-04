"""New schema2 literal seed; source-only direct enumeration, never manual-note conversion."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import time

from literal_source import (
    UnsupportedSource,
    literal,
    prepare_module,
    read_source,
    safe_relative,
    source_ref,
)


def build(repo, roots):
    started, cpu = time.monotonic(), time.process_time()
    sources, records, excluded, seen = {}, [], [], set()
    for root in roots:
        if root != ".":
            safe_relative(root)
        root_path = repo / root
        if any(p.is_symlink() for p in [root_path, *root_path.parents] if p.is_relative_to(repo)):
            excluded.append({"path": root, "reason": "symlink_source_root"})
            continue
        for directory, dirs, files in os.walk(root_path, followlinks=False):
            removed = [
                name
                for name in dirs
                if name in {"__pycache__", "_vendor", "vendor"}
                or (Path(directory) / name).is_symlink()
            ]
            for name in removed:
                excluded.append(
                    {
                        "path": (Path(directory) / name).relative_to(repo).as_posix(),
                        "reason": "symlink_or_vendor",
                    }
                )
            dirs[:] = sorted(name for name in dirs if name not in removed)
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                relative = (Path(directory) / name).relative_to(repo).as_posix()
                if relative in seen:
                    continue
                seen.add(relative)
                try:
                    raw = read_source(repo, relative)
                    sources[relative] = hashlib.sha256(raw).hexdigest()
                    module = prepare_module(raw)  # Exactly once per selected module.
                except (OSError, UnsupportedSource) as error:
                    excluded.append({"path": relative, "reason": str(error)})
                    continue
                for qualname, candidates in sorted(module.definitions.items()):
                    leaf = qualname.rsplit(".", 1)[-1]
                    if (
                        len(candidates) != 1
                        or leaf.startswith("_")
                        and leaf not in {"__init__", "__call__"}
                    ):
                        continue
                    kind, expected, span = literal(module, qualname)
                    selector = relative + ":" + qualname
                    records.append(
                        {
                            "id": "literal-" + hashlib.sha256(selector.encode()).hexdigest()[:24],
                            "kind": "source_excerpt_equals",
                            "selector": selector,
                            "subject": {
                                "language": "python",
                                "path": relative,
                                "qualname": qualname,
                                "node_kind": kind,
                            },
                            "expected": expected,
                            "origin_source": source_ref(relative, raw),
                            "origin_span": span,
                        }
                    )
    records.sort(key=lambda row: row["selector"])
    if len(records) > 1024:
        raise ValueError("literal seed exceeds1024-record bound")
    seed = {"schema_version": 2, "source_roots": roots, "excluded_paths": [], "records": records}
    if len(json.dumps(seed, ensure_ascii=True, separators=(",", ":")).encode()) > 4 * 1024 * 1024:
        raise ValueError("literal seed exceeds4MiB bound")
    metrics = {
        "schema_version": 2,
        "records": len(records),
        "source_hashes": sources,
        "excluded": excluded,
        "prepared_modules": len(sources) - sum(r["path"] in sources for r in excluded),
        "source_only": True,
        "generation_model_calls": 0,
        "future_solution_access": False,
        "selection": "same direct public functions/methods plus __init__/__call__; syntactic candidates, no behavior/binding claim",
        "wall_seconds": time.monotonic() - started,
        "cpu_seconds": time.process_time() - cpu,
        "peak_self_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    return seed, metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--source-root", action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    seed, metrics = build(args.repo.resolve(), args.source_root)
    for name, value in [("seed-spec.json", seed), ("metrics.json", metrics)]:
        (args.out / name).write_text(
            json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
        )


if __name__ == "__main__":
    main()
