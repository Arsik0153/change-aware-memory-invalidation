"""Run the frozen synthetic behavior/provenance history with real Docker probes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from cami.artifacts import file_hash, read_json, read_jsonl, reserve, write_json, write_jsonl
from cami.scenarios import prepare_scenario
from scripts.finite_behavior_oracle import value_of
from scripts.verify_cami import source_snapshot

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "examples/behavior_dependency/protocol.json"


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_DATE": "2026-10-29T00:00:00Z",
           "GIT_COMMITTER_DATE": "2026-10-29T00:00:00Z"}
    return subprocess.check_output(["git", "--no-replace-objects", "-C", str(repo), *args],
                                   env=env, stderr=subprocess.PIPE).decode().strip()


def create_fixture(out: Path, plan: dict) -> tuple[str, list[str], list[dict]]:
    repo = out / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "CAMI synthetic fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    observations, revisions = [], []
    sources = [("parent", plan["parent_source"], plan["parent_unrelated"], 1)]
    for step in plan["steps"]:
        source = f"def f():\n    return {step['f']}\n\ndef g():\n    return {step['g']}\n"
        sources.append((step["id"], source, f"VALUE = {step['unrelated']}\n", step["oracle_value"]))
    for name, source, unrelated, expected in sources:
        (repo / "module.py").write_text(source)
        (repo / "unrelated.py").write_text(unrelated)
        git(repo, "add", ".")
        git(repo, "commit", "-qm", name)
        revision = git(repo, "rev-parse", "HEAD")
        actual_source = git(repo, "show", f"{revision}:module.py") + "\n"
        assert actual_source == source
        value = value_of(actual_source)
        assert value == expected, (name, value, expected)
        observations.append({"step": name, "commit": revision, "value": value,
                             "label": "supported" if value == 1 else "contradicted",
                             "source_blob": git(repo, "rev-parse", f"{revision}:module.py")})
        revisions.append(revision)
    return revisions[0], revisions[1:], observations


def prepare_inputs(out: Path, plan: dict, parent: str, children: list[str],
                   observations: list[dict]) -> dict[str, Path]:
    probe = out / "test_behavior.py"
    probe.write_text(plan["probe"])
    write_json(out / "oracle.json", {"synthetic": True, "human_annotation": False,
        "cami_validator_used": False, "implementation_sha256": file_hash(Path(__file__).with_name("finite_behavior_oracle.py")),
        "observations": observations})
    claim = {"schema_version": 1, "claim_id": "f-returns-one", "repo_id": "behavior-fixture",
        "origin_commit": parent, "kind": "behavior_test", "text": "The finite frozen probe f() == 1 passes.",
        "subject": {"path": "module.py", "qualname": "f", "node_kind": "function"},
        "predicate": {"type": "behavior_test", "probe_path": probe.name,
            "probe_sha256": file_hash(probe), "node_id": "test_behavior.py::test_f", "environment_id": "fixture"},
        "scope": "Only this authored zero-argument finite predicate, not general behavior correctness."}
    write_jsonl(out / "claims.jsonl", [claim])
    parent_bytes = subprocess.check_output(["git", "-C", str(out / "repo"), "show", f"{parent}:module.py"])
    write_jsonl(out / "provenance.jsonl", [{"schema_version": 1, "claim_id": claim["claim_id"],
        "scenario_id": "intact", "anchors": [{"path": "module.py", "qualname": "f", "scope": "symbol",
            "observed_commit": parent, "content_hash": hashlib.sha256(parent_bytes).hexdigest(), "origin": "manual"}],
        "dependencies": [], "known_incomplete": False, "unresolved_reasons": []}])
    write_json(out / "parent_oracle.json", {"synthetic": True, "human_annotation": False,
        "observation": observations[0], "grammar": plan["oracle"]})
    write_jsonl(out / "parent_receipts.jsonl", [{"schema_version": 1, "claim_id": claim["claim_id"],
        "origin_commit": parent, "status": "supported", "confirmation_type": "synthetic_authored_finite_oracle",
        "evidence_path": "parent_oracle.json", "evidence_sha256": file_hash(out / "parent_oracle.json")}])
    write_jsonl(out / "labels.jsonl", [{"schema_version": 1, "claim_id": claim["claim_id"],
        "commit": row["commit"], "label": row["label"], "annotator_id": "synthetic-authored-finite-oracle",
        "confirmation_type": "synthetic_authored_finite_oracle", "adjudication_status": "not_required",
        "evidence": [f"oracle.json: {row['step']}; f() = {row['value']}; blob {row['source_blob']}"]}
        for row in observations[1:]])
    configs = {}
    for variant in plan["variants"]:
        config = {"schema_version": 1, "protocol_version": plan["protocol_version"],
            "repo": {"repo_id": "behavior-fixture", "path": str(out / "repo"), "source_roots": ["."]},
            "parent_commit": parent, "child_commits": children, "claims_path": "claims.jsonl",
            "provenance_path": "provenance.jsonl", "parent_receipts_path": "parent_receipts.jsonl",
            "scenario_id": "intact", "dataset_kind": "synthetic", "split": "development", "stratum": "fixture",
            "policy": {"id": variant["policy"], "dependency_depth": 1}, "cache_dir": None,
            "validation": {"execution": "docker", "llm": "disabled"},
            "environment_profiles": {"fixture": plan["environment"]}, "seed": 17}
        path = out / f"{variant['id']}.json"
        write_json(path, config)
        if variant["mask"]:
            dataset = out / f"{variant['id']}-dataset.json"
            write_json(dataset, {"schema_version": 1, "dataset_id": "behavior-fixture",
                "protocol_version": "1.0", "dataset_kind": "synthetic",
                "repositories": [{"repo_id": "behavior-fixture", "url": "synthetic://behavior-fixture",
                    "path": str(out / "repo"), "source_roots": ["."], "environment_restoration": "Pinned local probe image"}],
                "runs": [{"run_id": "history", "config_path": path.name, "split": "development",
                          "cluster_id": "single-authored-history", "sequence_id": "behavior-history"}]})
            public = prepare_scenario(dataset, variant["mask"], plan["mask"]["drop"],
                                      plan["mask"]["seed"], out / "scenarios" / variant["id"])
            path = public.parent / read_json(public)["runs"][0]["config_path"]
            masked = read_json(path)
            provenance = read_jsonl(path.parent / masked["provenance_path"])[0]
            assert provenance["known_incomplete"] == (variant["mask"] == "known_missing")
            for revision in [parent, *children]:
                graph = read_json(path.parent / "graphs" / f"{revision}.json")
                assert not graph["edges"]
            mask = read_json(public.parent.parent / "research" / "mask_report.json")
            assert (mask["unique_edges"], mask["removed_edges"]) == (1, 1)
        configs[variant["id"]] = path
    return configs


def verify_run(run: Path, variant: dict, children: list[str], observations: list[dict],
               parent: str, plan: dict) -> dict:
    manifest = read_json(run / "manifest.json")
    assert manifest["status"] == "complete" and manifest["cohort"] == ["f-returns-one"]
    assert manifest["config"]["cache_dir"] is None
    assert all(file_hash(run / name) == expected for name, expected in manifest["artifact_hashes"].items())
    selection_rows = read_jsonl(run / "selections.jsonl")
    state_rows = read_jsonl(run / "states.jsonl")
    validation_rows = read_jsonl(run / "validations.jsonl")
    assert len(selection_rows) == len(state_rows) == len(children)
    selections = {row["commit"]: row for row in selection_rows}
    states = {row["revision"]: row for row in state_rows}
    validations = {row["commit"]: row for row in validation_rows}
    assert set(selections) == set(states) == set(children)
    wanted = {c for c, selected in zip(children, variant["selected_steps"], strict=True) if selected}
    assert set(validations) == wanted and len(validation_rows) == len(wanted)
    checked = supported = parent
    available = True
    last_verdict = "supported"
    mismatches, rows = 0, []
    for commit, expected in zip(children, observations[1:], strict=True):
        selection, state = selections[commit], states[commit]
        selected = commit in wanted
        assert selection["selected"] == selected
        reasons = plan.get("expected_selection_reasons", {}).get(variant["id"], {})
        if expected["step"] in reasons:
            assert selection["reasons"] == reasons[expected["step"]], selection
        if selected:
            result = validations[commit]
            assert result["verdict"] == expected["label"] and not result["cache_hit"]
            assert result["test_executions"] == 3
            assert result["reason"] == ("test_passed" if expected["label"] == "supported" else "predicate_mismatch")
            checked, last_verdict = commit, expected["label"]
            available = last_verdict == "supported"
            if available:
                supported = commit
        assert state["available"] == available
        assert state["state"] == ("valid" if available else "stale")
        assert state["last_checked_commit"] == checked and state["last_supported_commit"] == supported
        assert state["last_verdict"] == last_verdict
        assert state["basis"] == ("validated" if selected else "carried_forward")
        mismatch = available != (expected["label"] == "supported")
        mismatches += mismatch
        rows.append({"step": expected["step"], "commit": commit, "truth": expected["label"],
                     "selected": selected, "available": available, "mismatch": mismatch,
                     "selection_reasons": selection["reasons"], "last_checked_commit": checked})
    assert mismatches == plan["expected_mismatches"][variant["id"]]
    preflight = read_jsonl(run / "preflight_validations.jsonl")
    assert len(preflight) == 1 and preflight[0]["verdict"] == "supported"
    costs = read_jsonl(run / "costs.jsonl")
    maintenance = [row for row in costs if row["phase"] == "maintenance"]
    assert sum(row["actual_validations"] for row in maintenance) == len(wanted)
    assert sum(row["test_executions"] for row in maintenance) == 3 * len(wanted)
    assert sum(row["test_executions"] for row in costs) == 3 * (1 + len(wanted))
    assert len(wanted) == plan["expected_maintenance_validations"][variant["id"]]
    return {"variant": variant["id"], "maintenance_validations": len(wanted),
            "maintenance_test_executions": 3 * len(wanted), "preflight_test_executions": 3,
            "availability_mismatches": mismatches, "states": rows}


def run(out: Path, protocol: Path = PLAN) -> None:
    out = out.resolve()
    before = source_snapshot(ROOT)
    assert not before["source_status"], "Commit source before the experiment"
    reserve(out)
    plan = read_json(protocol)
    write_json(out / "protocol.json", plan)
    manifest = {"status": "running", "source_before": before, "protocol_sha256": file_hash(protocol),
                "completed_runs": [], "synthetic": True, "independent_human_labels": False}
    write_json(out / "manifest.json", manifest)
    try:
        parent, children, observations = create_fixture(out, plan)
        configs = prepare_inputs(out, plan, parent, children, observations)
        input_hashes = {str(p.relative_to(out)): file_hash(p) for p in out.rglob("*")
                        if p.is_file() and "repo" not in p.relative_to(out).parts and p.name != "manifest.json"}
        manifest["input_hashes"] = input_hashes
        write_json(out / "manifest.json", manifest)
        variants = {row["id"]: row for row in plan["variants"]}
        results = []
        for name in plan["schedule"]:
            target = out / "runs" / name
            command = [sys.executable, "-m", "cami.cli", "run", "--config", str(configs[name]), "--out", str(target)]
            write_json(out / f"{name}.command.json", command)
            try:
                process = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=600)
            except subprocess.TimeoutExpired as exc:
                (out / f"{name}.stdout.log").write_bytes(exc.stdout or b"")
                (out / f"{name}.stderr.log").write_bytes(exc.stderr or b"")
                raise
            (out / f"{name}.stdout.log").write_bytes(process.stdout)
            (out / f"{name}.stderr.log").write_bytes(process.stderr)
            assert process.returncode == 0, name
            verified = verify_run(target, variants[name], children, observations, parent, plan)
            score_dir = out / "scores" / name
            score_command = [sys.executable, "-m", "cami.cli", "score", "--run", str(target),
                             "--labels", str(out / "labels.jsonl"), "--out", str(score_dir)]
            write_json(out / f"{name}.score-command.json", score_command)
            score = subprocess.run(score_command, cwd=ROOT, capture_output=True, timeout=60)
            (out / f"{name}.score.stdout.log").write_bytes(score.stdout)
            (out / f"{name}.score.stderr.log").write_bytes(score.stderr)
            assert score.returncode == 0, name
            metrics = read_json(score_dir / "metrics.json")["overall"]["metrics"]
            for metric, truth in (("stale_exposure", "contradicted"), ("valid_retention", "supported")):
                cohort = [row for row in verified["states"] if row["truth"] == truth]
                numerator = sum(row["available"] for row in cohort)
                assert (metrics[metric]["numerator"], metrics[metric]["denominator"]) == (numerator, len(cohort))
                assert metrics[metric]["value"] == numerator / len(cohort)
            verified["descriptive_metrics"] = {name: metrics[name] for name in ("stale_exposure", "valid_retention")}
            results.append(verified)
            manifest["completed_runs"].append(name)
            write_json(out / "results.json", results)
            write_json(out / "manifest.json", manifest)
        assert all(file_hash(out / name) == expected for name, expected in input_hashes.items())
        assert file_hash(protocol) == manifest["protocol_sha256"]
        assert git(out / "repo", "status", "--porcelain") == ""
        manifest["source_after"] = source_snapshot(ROOT)
        assert manifest["source_after"] == before
        manifest["status"] = "complete"
    except (Exception, KeyboardInterrupt) as exc:
        manifest.update(status="failed", failure={"type": type(exc).__name__, "message": str(exc)})
        raise
    finally:
        manifest["artifact_hashes"] = {p.relative_to(out).as_posix(): file_hash(p) for p in sorted(out.rglob("*"))
            if p.is_file() and "repo" not in p.relative_to(out).parts and p != out / "manifest.json"}
        write_json(out / "manifest.json", manifest)
    print(json.dumps({"status": "complete", "runs": len(results),
                      "maintenance_validations": sum(row["maintenance_validations"] for row in results)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=PLAN)
    args = parser.parse_args()
    run(args.out, args.protocol)
