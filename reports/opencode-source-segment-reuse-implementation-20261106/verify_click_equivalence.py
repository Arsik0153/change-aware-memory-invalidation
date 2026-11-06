"""Compare complete indexes on the two approved Click source exports; never import target code."""
import ast
import dataclasses
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import cami.index as candidate
from cami.repository import Blob, Snapshot

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BASELINE = ROOT / "runs/opencode-indexed-transition-candidate-20261106/candidate-source/cami/index.py"
BASELINE_SHA = "08c2a18e5a5f7b386cf1ef6aa854e985ca71ab7146777ce5ba228e2a1f68c61f"
TREES = {
    "origin-and-stage1": "6707f9b10a4b1b29695e319526113894a25fdbb6c4c70ba9a364f4b2e818a6a2",
    "stage3": "b19c9160c31bfdd5c5d50937dfc423984df3cb9707e71360f3f218e1d0265d99",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()


def inventory(root):
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                continue
            assert stat.S_ISREG(mode), path
            result[path.relative_to(root).as_posix()] = {
                "sha256": sha(path.read_bytes()), "bytes": path.stat().st_size,
                "mode": stat.S_IMODE(mode),
            }
    return result


def main():
    raw = BASELINE.read_bytes()
    assert sha(raw) == BASELINE_SHA
    baseline = ModuleType("frozen_source_segment_baseline")
    sys.modules[baseline.__name__] = baseline
    exec(compile(raw, str(BASELINE), "exec"), baseline.__dict__)
    refpath = ROOT / "tests/fixtures/python312_ast_source_segment.py.txt"
    reference = {}
    exec(compile(refpath.read_bytes(), str(refpath), "exec"), reference)
    reference_calls = 0

    def segment(source, node):
        nonlocal reference_calls
        reference_calls += 1
        return reference["get_source_segment"](source, node)

    # Replace only this frozen module's ast binding, not the process-global module.
    baseline.ast = SimpleNamespace(**{**vars(ast), "get_source_segment": segment})
    cases = []
    for tree, expected in TREES.items():
        root = ROOT / "runs/opencode-development-v3-staleness-20261104" / tree
        before = inventory(root)
        assert sha(canonical(before)) == expected
        blobs = []
        for path in sorted((root / "src").rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            raw = path.read_bytes()
            assert sha(raw) == before[relative]["sha256"]
            blobs.append(Blob(relative, sha(raw), "100755" if before[relative]["mode"] & 0o111 else "100644", raw, None))
        snapshot = Snapshot("approved-click-source-export", "canonical-inventory:" + expected, tuple(blobs))
        for graph in (False, True):
            reference_calls = 0
            old = baseline.build_index(snapshot, baseline.IndexConfig(source_roots=("src",), build_graph=graph))
            preparations = []
            prepare = candidate._source_lines

            def counted(source):
                preparations.append(source)
                return prepare(source)

            candidate._source_lines = counted
            try:
                new = candidate.build_index(snapshot, candidate.IndexConfig(source_roots=("src",), build_graph=graph))
            finally:
                candidate._source_lines = prepare
            # Dataclass class namespaces differ. No fields/provenance values are excluded.
            assert dataclasses.asdict(old) == dataclasses.asdict(new)
            assert len(preparations) == sum(bool(module.definitions) for module in new.modules)
            assert reference_calls == sum(len(module.definitions) for module in old.modules)
            cases.append({"canonical_tree": tree, "canonical_inventory_sha256": expected,
                "source_roots": ["src"], "build_graph": graph, "all_fields_equal": True,
                "input_python_files": len(blobs), "modules": len(new.modules),
                "definitions": sum(len(module.definitions) for module in new.modules),
                "baseline_source_segment_calls": reference_calls,
                "candidate_source_line_preparations": len(preparations),
                "edges": len(new.edges), "unresolved": len(new.unresolved),
                "excluded_fields": [],
                "comparison": "dataclasses.asdict equality including complete module/definition/source/signature/hash/span/import/ambiguity/binding/loaded-name/edge/unresolved/revision data"})
        assert inventory(root) == before
    result = {"status": "passed", "cases": cases, "baseline_source_sha256": BASELINE_SHA,
        "candidate_index_sha256": sha(Path(candidate.__file__).read_bytes()),
        "reference_fixture_sha256": sha(refpath.read_bytes()),
        "same_provenance_inputs_to_both_implementations": True,
        "frozen_baseline_uses_exact_container31212_stdlib_source_reference": True,
        "canonical_sources_unchanged": True, "target_code_execution_or_imports": False,
        "model_calls": 0, "Docker_calls": 0, "network_calls": 0,
        "timing_or_speedup_claim": False}
    (OUT / "click-equivalence.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
