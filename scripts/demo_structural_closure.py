"""Reproduce a synthetic protocol 1.1 closure comparison without held-out data."""
from __future__ import annotations

import argparse
import io
import os
import statistics
import subprocess
import sys
import time
import tokenize
from pathlib import Path
from typing import Any

from cami.artifacts import (
    canonical, digest, file_hash, load_jsonl, read_json, read_jsonl, reserve, write_bytes, write_json,
    write_jsonl,
)
from cami.models import Claim, Equals, Parameter, Provenance, Signature

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "examples/structural_closure/scenario.json"
VARIANTS = ("all_validate", "original_incomplete", "closed_structural")


def lexical_observation(source: str, name: str, kind: str) -> str:
    """Independent oracle for the deliberately small fixture grammar, never CAMI AST code."""
    compile(source, "<synthetic-oracle>", "exec", dont_inherit=True)
    indent = 0
    statements: list[list[str]] = []
    statement: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.INDENT:
            indent += 1
        elif token.type == tokenize.DEDENT:
            indent -= 1
        elif token.type == tokenize.NEWLINE:
            if statement:
                statements.append(statement)
                statement = []
        elif indent == 0 and token.type not in {
            tokenize.NL, tokenize.COMMENT, tokenize.ENDMARKER,
        }:
            statement.append(token.string)
    definitions = [row for row in statements if row[:2] == ["def", name]]
    rebound = any(row[:2] == [name, "="] for row in statements)
    if len(definitions) > 1 or rebound:
        return "insufficient_evidence"
    if not definitions:
        return "contradicted"
    if kind == "signature_equals" and definitions[0][2:] != ["(", "x", ")", ":"]:
        return "contradicted"
    return "supported"


def expected_verdict(step: dict[str, Any], claim: Claim) -> str:
    if claim.subject.qualname == "stable":
        return "supported"
    return str(step["f_exists" if claim.kind == "symbol_exists" else "f_signature"])


def fixture(base: Path) -> tuple[dict[str, Any], list[Claim], str]:
    spec = read_json(SCENARIO)
    reserve(base)
    repo = base / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_DATE": "2026-10-23T00:00:00Z",
           "GIT_COMMITTER_DATE": "2026-10-23T00:00:00Z"}

    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(repo), *args], env=env,
                                       stderr=subprocess.PIPE).decode().strip()

    git("init", "-q")
    git("config", "user.name", "CAMI structural fixture")
    git("config", "user.email", "fixture@example.invalid")

    def commit(source: str, unrelated: str, name: str) -> str:
        (repo / "module.py").write_text(source)
        (repo / "unrelated.py").write_text(unrelated)
        git("add", ".")
        git("commit", "-qm", name)
        return git("rev-parse", "HEAD")

    parent = commit(spec["parent_source"], spec["parent_unrelated"], "parent")
    claims = []
    expected_signature = Signature(parameters=(Parameter(name="x", kind="positional_or_keyword"),))
    for row in spec["claims"]:
        predicate = ({"type": "symbol_exists", "expected": True}
                     if row["kind"] == "symbol_exists" else
                     Equals(type="signature_equals", expected_signature=expected_signature).model_dump(mode="json"))
        claims.append(Claim.model_validate_json(canonical({
            "claim_id": row["id"], "repo_id": "structural-fixture", "origin_commit": parent,
            "kind": row["kind"], "text": f"Exact {row['kind']} predicate for module.py::{row['name']}.",
            "subject": {"path": "module.py", "qualname": row["name"], "node_kind": "function"},
            "predicate": predicate, "scope": "Exact syntactic definition, no runtime semantics.",
        })))
    write_jsonl(base / "claims.jsonl", claims)
    write_jsonl(base / "provenance.jsonl", [{
        "schema_version": 1, "claim_id": claim.claim_id, "scenario_id": "intact",
        "anchors": [{"path": "module.py", "qualname": claim.subject.qualname, "scope": "symbol",
                     "observed_commit": parent, "content_hash": file_hash(repo / "module.py"),
                     "origin": "static"}],
        "dependencies": [], "known_incomplete": True,
        "unresolved_reasons": ["Draft parent-only anchors; dependency extraction and review pending."],
    } for claim in claims])
    return spec, claims, parent


def prepare_closure(base: Path, parent: str, claims: list[Claim], output: Path) -> float:
    provenance = load_jsonl(base / "provenance.jsonl", Provenance, "claim_id")
    by_id = {record.claim_id: record for record in provenance}
    request = {
        "schema_version": 1, "protocol_version": "1.1",
        "addendum_version": "structural-provenance-closure/1",
        "addendum_sha256": file_hash(ROOT / "docs/protocol_1_1_structural_closure_v1.md"),
        "dataset_kind": "synthetic", "split": "development", "stratum": "fixture",
        "repo": {"repo_id": "structural-fixture", "path": str((base / "repo").resolve()),
                 "source_roots": ["."]},
        "parent_commit": parent, "claims_path": "claims.jsonl",
        "claims_sha256": file_hash(base / "claims.jsonl"),
        "provenance_path": "provenance.jsonl",
        "provenance_sha256": file_hash(base / "provenance.jsonl"),
        "closures": [{"claim_id": claim.claim_id, "claim_sha256": digest(claim),
                      "provenance_sha256": digest(by_id[claim.claim_id]),
                      "close_reasons": list(by_id[claim.claim_id].unresolved_reasons)}
                     for claim in claims],
        "authority": {"type": "automatic_fixture", "independent": False},
    }
    write_json(base / "parent_inputs.json", request)
    started = time.perf_counter()
    result = subprocess.run([
        sys.executable, str(ROOT / "scripts/prepare_main.py"), "close-structural-provenance",
        "--parents", str(base / "parent_inputs.json"), "--out", str(output),
    ], cwd=ROOT, capture_output=True, text=True, check=True)
    elapsed = time.perf_counter() - started
    write_bytes(output.parent / "preparation_cli.log", (result.stdout + result.stderr).encode())
    return elapsed


def create_children(base: Path, spec: dict[str, Any]) -> list[str]:
    repo = base / "repo"
    revisions = []
    for step in spec["transitions"]:
        (repo / "module.py").write_text(step["source"])
        (repo / "unrelated.py").write_text(step["unrelated"])
        env = {**os.environ, "GIT_AUTHOR_DATE": "2026-10-23T00:00:00Z",
               "GIT_COMMITTER_DATE": "2026-10-23T00:00:00Z"}
        subprocess.run(["git", "-C", str(repo), "add", "."], env=env, check=True,
                       capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", step["name"]],
                       env=env, check=True, capture_output=True)
        revisions.append(subprocess.check_output([
            "git", "-C", str(repo), "rev-parse", "HEAD",
        ]).decode().strip())
    return revisions


def verify_fixture(base: Path, spec: dict[str, Any], claims: list[Claim],
                   parent: str, children: list[str]) -> list[dict[str, str]]:
    observations = []
    for revision, step in zip([parent, *children], [None, *spec["transitions"]], strict=True):
        source = subprocess.check_output([
            "git", "--no-replace-objects", "-C", str(base / "repo"),
            "show", f"{revision}:module.py",
        ]).decode()
        expected_source = spec["parent_source"] if step is None else step["source"]
        if source != expected_source:
            raise ValueError("fixture Git source differs from authored source")
        for claim in claims:
            expected = "supported" if step is None else expected_verdict(step, claim)
            observed = lexical_observation(source, claim.subject.qualname, claim.kind)
            if observed != expected:
                raise ValueError(f"independent oracle disagrees at {revision}/{claim.claim_id}")
            observations.append({"commit": revision, "claim_id": claim.claim_id,
                                 "expected": expected, "observed": observed})
    return observations


def verify_run(run: Path, variant: str, spec: dict[str, Any], claims: list[Claim],
               parent: str, children: list[str]) -> list[dict[str, Any]]:
    manifest = read_json(run / "manifest.json")
    ids = {claim.claim_id for claim in claims}
    if manifest["status"] != "complete" or set(manifest["cohort"]) != ids or manifest["excluded"]:
        raise ValueError("run failed or changed the fixed cohort")
    if manifest["config"]["cache_dir"] is not None:
        raise ValueError("the demonstration requires disabled verdict caching")
    for name, expected in manifest["artifact_hashes"].items():
        if file_hash(run / name) != expected:
            raise ValueError(f"run artifact hash mismatch: {name}")
    selections = read_jsonl(run / "selections.jsonl")
    validations = read_jsonl(run / "validations.jsonl")
    states = read_jsonl(run / "states.jsonl")
    costs = read_jsonl(run / "costs.jsonl")
    last_checked = dict.fromkeys(ids, parent)
    rows = []
    for commit, step in zip(children, spec["transitions"], strict=True):
        decisions = {row["claim_id"]: row for row in selections if row["commit"] == commit}
        results = {row["claim_id"]: row for row in validations if row["commit"] == commit}
        current = {row["claim_id"]: row for row in states if row["revision"] == commit}
        wanted = set(step["closed_selected"]) if variant == "closed_structural" else ids
        selected = {key for key, row in decisions.items() if row["selected"]}
        if set(decisions) != ids or set(current) != ids or selected != wanted or set(results) != wanted:
            raise ValueError(f"selection or coverage mismatch: {variant}/{step['name']}")
        if variant == "original_incomplete" and any(
            "known_incomplete" not in decision["reasons"] for decision in decisions.values()
        ):
            raise ValueError("incomplete provenance lost its conservative fallback")
        if variant == "closed_structural" and any(
            "known_incomplete" in decision["reasons"] for decision in decisions.values()
        ):
            raise ValueError("closed provenance unexpectedly retained the fallback")
        for claim in claims:
            expected = expected_verdict(step, claim)
            if claim.claim_id in results:
                result = results[claim.claim_id]
                if result["verdict"] != expected or result["cache_hit"]:
                    raise ValueError(f"validator disagrees with independent fixture oracle: {claim.claim_id}")
                expected_reason = (
                    "ambiguous_subject" if expected == "insufficient_evidence" else
                    "subject_absent" if step["name"] == "function_removed" and expected == "contradicted" else
                    "predicate_mismatch" if expected == "contradicted" else "predicate_matches"
                )
                if result["reason"] != expected_reason:
                    raise ValueError("validator returned the wrong reason")
                last_checked[claim.claim_id] = commit
            state = current[claim.claim_id]
            if state["available"] != (expected == "supported"):
                raise ValueError("memory availability disagrees with the authored expectation")
            if state["last_checked_commit"] != last_checked[claim.claim_id]:
                raise ValueError("a carried claim was falsely marked as rechecked")
            if claim.claim_id not in wanted and state["basis"] != "carried_forward":
                raise ValueError("an unselected claim lost its carried status")
        maintenance = next(row for row in costs if row["commit"] == commit and row["phase"] == "maintenance")
        if maintenance["actual_validations"] != len(wanted) or maintenance["cache_hits"]:
            raise ValueError("cost accounting disagrees with actual validations")
        rows.append({
            "transition": step["name"], "commit": commit, "selected": len(selected),
            "selected_claims": sorted(selected),
            "selection_reasons": {key: row["reasons"] for key, row in decisions.items()},
            "verdicts": {key: {"verdict": row["verdict"], "reason": row["reason"]}
                         for key, row in results.items()},
            "carried_claims": sorted(ids - wanted),
            "maintenance_seconds": maintenance["wall_seconds"],
        })
    return rows


def demonstrate(output: Path, repeats: int = 5) -> dict[str, Any]:
    if repeats < 1:
        raise ValueError("repeats must be positive")
    started = time.perf_counter()
    reserve(output)
    write_bytes(output / "scenario.json", SCENARIO.read_bytes())
    spec, claims, parent = fixture(output / "parent")
    authored_hash = file_hash(SCENARIO)
    preparation_seconds = prepare_closure(output / "parent", parent, claims, output / "derived")
    source_paths = [output / "parent" / name for name in
                    ("claims.jsonl", "provenance.jsonl", "parent_inputs.json")]
    source_paths += [output / "scenario.json", ROOT / "docs/protocol_1_1.md",
                     ROOT / "docs/protocol_1_1_structural_closure_v1.md"]
    source_hashes = {str(path): file_hash(path) for path in source_paths}
    children = create_children(output / "parent", spec)
    observations = verify_fixture(output / "parent", spec, claims, parent, children)
    write_json(output / "independent_oracle.json", {
        "implementation_sha256": file_hash(Path(__file__)), "observations": observations,
        "oracle": "authored expectations plus independent tokenize traversal of actual Git blobs",
        "cami_validator_used": False,
    })
    write_json(output / "parent_oracle.json", {
        "synthetic": True, "independent_human_review": False,
        "observations": [row for row in observations if row["commit"] == parent],
    })
    write_jsonl(output / "parent_receipts.jsonl", [{
        "schema_version": 1, "claim_id": claim.claim_id, "origin_commit": parent,
        "status": "supported", "confirmation_type": "synthetic_authored_tokenizer_oracle",
        "evidence_path": "parent_oracle.json", "evidence_sha256": file_hash(output / "parent_oracle.json"),
    } for claim in claims])
    for variant in VARIANTS:
        write_json(output / f"{variant}.json", {
            "schema_version": 1, "protocol_version": "1.1",
            "repo": {"repo_id": "structural-fixture", "path": "parent/repo", "source_roots": ["."]},
            "parent_commit": parent, "child_commits": children, "claims_path": "parent/claims.jsonl",
            "provenance_path": ("derived/provenance.jsonl" if variant == "closed_structural"
                                else "parent/provenance.jsonl"),
            "parent_receipts_path": "parent_receipts.jsonl", "scenario_id": "intact",
            "dataset_kind": "synthetic", "split": "development", "stratum": "fixture",
            "policy": {"id": "all_validate" if variant == "all_validate" else "symbol_validate",
                       "dependency_depth": 1},
            "cache_dir": None, "seed": 42,
        })
    schedule = [list(VARIANTS[index % 3:] + VARIANTS[:index % 3]) for index in range(repeats)]
    write_json(output / "schedule.json", {
        "order": schedule, "repetitions": repeats, "cache": "no shared verdict cache; process-local AST cache",
        "timing": "CLI process wall time includes startup, preflight, six transitions, artifacts and exit",
        "claim": "fewer validations; timing is descriptive and establishes no speedup",
        "scenario_sha256": authored_hash,
    })
    measurements = []
    transitions: dict[str, list[dict[str, Any]]] = {}
    for replicate, order in enumerate(schedule):
        for variant in order:
            run = output / "runs" / f"{replicate:02d}-{variant}"
            command = [sys.executable, "-m", "cami.cli", "run", "--config",
                       str(output / f"{variant}.json"), "--out", str(run)]
            tick = time.perf_counter()
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
            elapsed = time.perf_counter() - tick
            transitions[variant] = verify_run(run, variant, spec, claims, parent, children)
            manifest = read_json(run / "manifest.json")
            if read_jsonl(run / "claims.jsonl") != [claim.model_dump(mode="json") for claim in claims]:
                raise ValueError("a run changed claims")
            measurements.append({
                "replicate": replicate, "variant": variant, "cli_wall_seconds": elapsed,
                "engine_end_to_end_seconds": manifest["end_to_end_seconds"],
                "validations": sum(row["selected"] for row in transitions[variant]),
                "run": str(run.relative_to(output)), "exit_code": result.returncode,
            })
    for path in source_paths:
        if file_hash(path) != source_hashes[str(path)]:
            raise ValueError("source artifact changed during the demonstration")
    summaries = {}
    for variant in VARIANTS:
        values = [row["cli_wall_seconds"] for row in measurements if row["variant"] == variant]
        summaries[variant] = {
            "actual_validations": sum(row["selected"] for row in transitions[variant]),
            "cli_wall_seconds_median": statistics.median(values),
            "cli_wall_seconds_min": min(values), "cli_wall_seconds_max": max(values),
            "transitions": transitions[variant],
        }
    summary = {
        "status": "passed", "dataset_kind": "synthetic", "split": "development",
        "protocol_version": "1.1", "addendum_version": "structural-provenance-closure/1",
        "claims": len(claims), "transitions": len(children), "repetitions": repeats,
        "parent_commit": parent, "scenario_sha256": authored_hash,
        "closure_manifest_sha256": file_hash(output / "derived/closure_manifest.json"),
        "environment": {"python": sys.version, "cpu_count": os.cpu_count(),
                        "load_average": list(os.getloadavg())},
        "variants": summaries, "measurements": measurements,
        "preparation_cli_wall_seconds": preparation_seconds,
        "total_demo_wall_seconds": time.perf_counter() - started,
        "source_preservation": {"verified": True, "sha256": source_hashes},
        "oracle_checks": len(observations), "timing_conclusion": "no speedup claim",
        "limitations": [
            "Synthetic fixtures do not establish quality on real projects.",
            "Automatic fixture authority is not independent human review.",
            "Real experiment still requires independent parent/provenance review, labels, environments and freeze.",
            "Protocol 1.1 selects whole AST changes, including function body changes; selection is not minimal.",
            "CLI timing includes Python startup and Git/artifact I/O; OS caches are not reset.",
        ],
    }
    write_json(output / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    result = demonstrate(args.out.resolve(), args.repeats)
    for name, row in result["variants"].items():
        print(f"{name}: {row['actual_validations']} checks; "
              f"CLI median {row['cli_wall_seconds_median']:.6f}s "
              f"[{row['cli_wall_seconds_min']:.6f}, {row['cli_wall_seconds_max']:.6f}]")
    for index, closed in enumerate(result["variants"]["closed_structural"]["transitions"]):
        counts = [result["variants"][name]["transitions"][index]["selected"] for name in VARIANTS]
        verdicts = ", ".join(f"{key}={value['verdict']}:{value['reason']}"
                             for key, value in closed["verdicts"].items()) or "all claims carried"
        print(f"{closed['transition']}: all={counts[0]}, incomplete={counts[1]}, closed={counts[2]}; {verdicts}")
    print(f"Independent fixture checks: {result['oracle_checks']}; status: {result['status']}")
    print(f"Summary: {args.out.resolve() / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
