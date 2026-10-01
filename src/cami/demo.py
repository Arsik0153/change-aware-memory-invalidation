from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any

from cami.artifacts import file_hash, reserve, write_json, write_jsonl
from cami.engine import run_experiment

POLICIES = ("keep_all", "clear_all", "file_invalidate", "symbol_invalidate", "all_validate", "file_validate", "symbol_validate")
PARENT_SOURCE = "def add(a, b):\n    return a + b\n\ndef stable(x):\n    return x\n\ndef removable():\n    return 7\n\ndef caller():\n    return add(1, 2)\n"
CHILD_SOURCE = "def add(a, b, scale=1):\n    return (a + b) * scale\n\ndef stable(x):\n    return x\n\ndef caller():\n    return add(1, 2)\n"


def create_fixture(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    repo = base / "repo"
    repo.mkdir()
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE,
            env={**os.environ, "GIT_AUTHOR_DATE":"2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE":"2026-01-01T00:00:00Z"}).decode().strip()
    git("init", "-q")
    git("config", "user.name", "CAMI synthetic fixture")
    git("config", "user.email", "fixture@example.invalid")
    revisions = []
    for source in (PARENT_SOURCE, "# comment only\n" + PARENT_SOURCE, CHILD_SOURCE, PARENT_SOURCE):
        (repo / "math_ops.py").write_text(source)
        git("add", "math_ops.py")
        git("commit", "-qm", "synthetic scenario")
        revisions.append(git("rev-parse", "HEAD"))
    parent = revisions[0]
    claims: list[dict[str, Any]] = []
    for claim_id, name, kind in (("add-exists", "add", "symbol_exists"),
                                 ("add-signature", "add", "signature_equals"),
                                 ("stable-exists", "stable", "symbol_exists"),
                                 ("removed-exists", "removable", "symbol_exists"),
                                 ("caller-exists", "caller", "symbol_exists")):
        predicate: dict[str, Any] = {"type": kind, "expected": True}
        if kind == "signature_equals":
            predicate = {"type": kind, "expected_signature": {
                "parameters": [{"name": n, "kind": "positional_or_keyword", "default_ast": None, "annotation_ast": None} for n in ("a", "b")],
                "returns_ast": None, "decorators_ast": [], "is_async": False}}
        claims.append({"schema_version": 1, "claim_id": claim_id, "repo_id": "demo", "origin_commit": parent,
                       "kind": kind, "text": f"Exact {kind} predicate for math_ops.py::{name}.",
                       "subject": {"path": "math_ops.py", "qualname": name, "node_kind": "function"},
                       "predicate": predicate, "scope": "Exact syntactic definition, no runtime semantics."})
    write_jsonl(base / "claims.jsonl", claims)
    write_jsonl(base / "provenance.jsonl", [{"schema_version": 1, "claim_id": c["claim_id"], "scenario_id": "intact",
        "anchors": [{"path": "math_ops.py", "qualname": c["subject"]["qualname"], "scope": "symbol", "observed_commit": parent,
                     "content_hash": hashlib.sha256(PARENT_SOURCE.encode()).hexdigest(), "origin": "manual"}],
        "dependencies": [], "known_incomplete": False, "unresolved_reasons": []} for c in claims])
    (base / "parent_evidence.txt").write_text("Synthetic manually authored oracle: parent defines add(a,b), stable(x), removable(), caller().\nChild 1 changes only a comment. Child 2 adds scale=1 to add and removes removable. Child 3 restores the exact parent text.\nNo production validator produced these labels.\n")
    write_jsonl(base / "parent_receipts.jsonl", [{"schema_version": 1, "claim_id": c["claim_id"], "origin_commit": parent,
        "status": "supported", "confirmation_type": "synthetic_manual", "evidence_path": "parent_evidence.txt",
        "evidence_sha256": file_hash(base / "parent_evidence.txt")} for c in claims])
    write_jsonl(base / "labels.jsonl", [{"schema_version": 1, "claim_id": c["claim_id"], "commit": revision,
        "label": "contradicted" if i == 1 and c["claim_id"] in {"add-signature", "removed-exists"} else "supported",
        "annotator_id": "synthetic-scenario-author", "evidence": ["parent_evidence.txt"],
        "confirmation_type": "synthetic_manual", "adjudication_status": "not_required"}
        for i, revision in enumerate(revisions[1:]) for c in claims])
    config = {"schema_version": 1, "protocol_version": "1.0", "repo": {"repo_id": "demo", "path": "repo", "source_roots": ["."]},
        "parent_commit": parent, "child_commits": revisions[1:], "claims_path": "claims.jsonl", "provenance_path": "provenance.jsonl",
        "parent_receipts_path": "parent_receipts.jsonl", "scenario_id": "intact", "dataset_kind": "synthetic", "split": "development",
        "stratum": "fixture", "policy": {"id": "symbol_validate", "dependency_depth": 1},
        "validation": {"execution": "disabled", "llm": "disabled"}, "allow_network": False, "max_calls": 0, "seed": 42}
    write_json(base / "run.json", config)
    for policy in POLICIES:
        write_json(base / f"{policy}.json", config | {"policy": {"id": policy, "dependency_depth": 1}})
    return base / "run.json"


def demo(output: Path) -> None:
    reserve(output)
    create_fixture(output / "dataset")
    runs = []
    for policy in POLICIES:
        run = output / policy
        run_experiment(output / "dataset" / f"{policy}.json", run)
        runs.append(run)
    from cami.evaluation import compare_runs
    compare_runs(runs, output / "dataset" / "labels.jsonl", output / "report")
