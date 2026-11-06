"""Explicit catalog2 terminal analysis; old catalog1/v3 analysis is unchanged."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

from classify_literal_calls import READABLE_VERIFIER_PATH, canonical, classify, validate_catalog
from literal_reference import FORMAT, LIMIT, body

VERSION = "source-excerpt-tuple-staleness/3"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_controls(path):
    """Load exact existing admission functions without changing their globals/code."""
    name = "classify_memory_calls"
    previous = sys.modules.get(name)
    try:
        load_module(name, path.parent / "classify_memory_calls.py")
        return load_module("literal_analysis_legacy_terminal_controls", path)
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


def admit(path):
    path = path.absolute()
    if any("heldout" in p.lower() or p in {"private-state", "server-private", "private-export-client"} for p in path.parts):
        raise ValueError("only public development analysis inputs permitted")
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError("input/output symlink refused")


def summarize(run, catalog_path, origin, stage1, stage3, controls_path, analyzer_path):
    started, cpu = time.monotonic(), time.process_time()
    for path in [run, catalog_path, origin, stage1, stage3, controls_path, analyzer_path]:
        admit(path)
    controls = load_controls(controls_path)
    analyzer = load_module("literal_analysis_legacy_api_normalizer", analyzer_path)
    study = controls.read(run / "frozen-study.json")
    if study.get("bundle_kind") != "development" or study.get("arms") != ["plain", "static", "cami"]:
        raise ValueError("registered three-arm development study required")
    selected_format = study.get("memory_response_format", "full")
    if selected_format not in ("full", "compact", "readable"):
        raise ValueError("unsupported frozen memory response format")
    plan = controls.read(run / "plan.json")["trials"]
    legal = {f"r{rep}-{arm}-s{stage}" for rep in range(1, 4) for arm in ("plain", "static", "cami") for stage in range(1, 5)}
    if len(plan) != 36 or {p["id"] for p in plan} != legal:
        raise ValueError("expected registered 36-trial plan")
    for trial in plan:
        if trial["id"] != f"r{trial['repetition']}-{trial['arm']}-s{trial['stage']}" or trial["task"] != study["normalized"]["sequence"][trial["stage"] - 1]:
            raise ValueError("trial ID/task/stage binding differs")
    completed = [p for p in plan if (run / "trials" / p["id"] / "terminal.json").is_file()]
    catalog = validate_catalog(controls.read(catalog_path))
    catalog_sha, semantic_sha = controls.sha(catalog_path), hashlib.sha256(canonical(catalog)).hexdigest()
    trees = {path: controls.inventory(path) for path in {origin, stage1, stage3}}
    tree_hashes = {str(path): hashlib.sha256(canonical(value)).hexdigest() for path, value in trees.items()}
    trials = []
    for expected in completed:
        directory = run / "trials" / expected["id"]
        row = {"trial": expected, "causal_reliance": "not_inferred"}
        try:
            terminal = controls.verify_terminal(directory)
            if terminal["trial"] != expected:
                raise ValueError("terminal/plan identity differs")
            row.update(terminal_status=terminal["status"], terminal_sha256=controls.sha(directory / "terminal.json"), artifact_hashes_verified=len(terminal["artifact_hashes"]))
            current = stage1 if expected["stage"] in (1, 2) else stage3
            reset = directory / "canonical-reset.json"
            if controls.read(reset)["canonical_files"] != trees[current]:
                raise ValueError("canonical reset source hashes/modes differ")
            messages_path = directory / "session/evidence/messages.json"
            messages = controls.read(messages_path)
            if not isinstance(messages, list):
                raise ValueError("complete API message array required")
            rows = analyzer.message_rows(messages)
            if expected["arm"] == "plain":
                if any(analyzer.memory_tool(r["part"]["tool"]) for r in rows if r.get("type") == "tool_use"):
                    raise ValueError("plain unexpectedly has external memory")
                result = {"memory_calls": [], "records": [], "counts": [], "unsupported_calls": 0,
                          "returned_record_observations": 0, "withheld_record_observations": 0,
                          "backend_crosscheck": {"status": "plain_no_external_memory_expected"}}
            else:
                before = controls.read(directory / "memory-before.json")
                if terminal["immutable_memory"].get("prepared/catalog.json") != catalog_sha or before.get("prepared/catalog.json") != catalog_sha:
                    raise ValueError("catalog immutable/before raw hash differs")
                trace_path = directory / "session/evidence/memory-backend-trace.jsonl"
                events = [json.loads(line) for line in trace_path.read_text().splitlines() if line.strip()] if trace_path.is_file() else None
                expected_marker = None if selected_format == "full" else selected_format
                if events is not None and any(
                        isinstance(event, dict) and event.get("event") == "memory_lookup"
                        and event.get("response_format") != expected_marker for event in events):
                    raise ValueError("observed memory response format differs from frozen study")
                result = classify(analyzer, rows, catalog, origin, current, expected["arm"], events)
                result["backend_crosscheck"]["sha256"] = controls.sha(trace_path) if trace_path.is_file() else None
            row.update(status="assessed", messages_sha256=controls.sha(messages_path), canonical_reset_sha256=controls.sha(reset),
                       canonical_tree_sha256=tree_hashes[str(current)], catalog_raw_sha256=catalog_sha if expected["arm"] != "plain" else None,
                       catalog_semantic_sha256=semantic_sha if expected["arm"] != "plain" else None, **result)
        except (ValueError, KeyError, TypeError, OSError, AttributeError) as error:
            row.update(status="unsupported_or_integrity_error", reason=type(error).__name__ + ":" + str(error),
                       memory_calls=None, records=None, counts=None, unsupported_calls=None)
        trials.append(row)
    if any(controls.inventory(path) != before for path, before in trees.items()):
        raise ValueError("canonical source changed during literal analysis")
    body.cache_clear()
    totals = Counter((t["trial"]["arm"], r["channel"], r["record_kind"], r["assessment"]) for t in trials for r in t.get("records") or [])
    paths = [controls_path, controls_path.parent / "classify_memory_calls.py", analyzer_path, Path(__file__), Path(__file__).with_name("classify_literal_calls.py"), Path(__file__).with_name("literal_reference.py")]
    if selected_format == "readable":
        paths.append(READABLE_VERIFIER_PATH)
    return {"schema_version": 2, "analysis_version": VERSION, "catalog_schema_version": 2,
            "planned_trials": 36, "completed_trials": len(completed), "complete_36": len(completed) == 36,
            "coverage_status": "all_registered_trials_terminal" if len(completed) == 36 else "partial_terminal_snapshot",
            "terminal_snapshot_ids": [p["id"] for p in completed], "active_trials_inspected": False, "private_state_read": False,
            "causal_reliance": "not_inferred", "complete_body_equivalence": "not_inferred",
            "literal_tuple_boundary": {"format": FORMAT, "physical_newlines": ["CRLF", "LF", "CR"], "decorator_start": "independent lexical @ association", "prefix_unicode_characters": LIMIT, "comparison": ["exact_text", "truncated"]},
            "all_assessed_evidence_supported": bool(trials) and all(t["status"] == "assessed" and not t.get("unsupported_calls") and not t.get("backend_crosscheck", {}).get("status", "").startswith("unsupported") and not any(r["assessment"].startswith("unsupported") for r in t.get("records") or []) for t in trials),
            "unassessed_trial_ids": [t["trial"]["id"] for t in trials if t["status"] != "assessed"],
            "unsupported_call_count": sum(t.get("unsupported_calls") or 0 for t in trials),
            "unsupported_call_count_complete": all(t["status"] == "assessed" for t in trials),
            "counts": [{"arm": a, "channel": c, "record_kind": k, "assessment": v, "observations": n} for (a, c, k, v), n in sorted(totals.items())],
            "trials": trials,
            "inputs": {"run": str(run), "frozen_study_sha256": controls.sha(run / "frozen-study.json"), "plan_sha256": controls.sha(run / "plan.json"),
                       "catalog_path": str(catalog_path), "catalog_raw_sha256": catalog_sha, "catalog_semantic_sha256": semantic_sha,
                       "canonical_tree_sha256": tree_hashes, "implementation_sha256": {str(p): controls.sha(p) for p in paths}},
            "offline_evaluation_cost": {"wall_seconds": time.monotonic() - started, "cpu_seconds": time.process_time() - cpu,
                                        "timing_scope": "summarize entry through final input hashing; excludes Python/startup imports, final report serialization/write and outer storage observation"},
            "limitations": ["Explicit schema2 only; catalog1/manual-note/v3 recipe is untouched.", "Canonical current source is used only before prior/overlapping possible writes; no post-write substitution.", "Full and compact require public trace joins; compact also requires intact original audit receipts. Publication redaction can invalidate receipts; unsupported never repaired using private state.", "Hashes bind evidence, not authorship, semantic behavior or model causal reliance.", "Withheld current tuples are reviewer context, not content exposed to the trial agent.", "Plain has no external-memory observations, not proof of current internal knowledge.", "Counts are dependent repeated observations; offline analysis is not trial model/tool cost."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["run", "catalog", "origin", "stage1", "stage3", "controls", "analyzer", "out"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    out = args.out.absolute()
    admit(out)
    if out.exists() or any(out.is_relative_to(getattr(args, key).absolute()) for key in ["run", "origin", "stage1", "stage3"]):
        parser.error("new separate output required")
    out.mkdir(parents=True)
    try:
        report = summarize(*[getattr(args, key).absolute() for key in ["run", "catalog", "origin", "stage1", "stage3", "controls", "analyzer"]])
        (out / "report.json").write_bytes(canonical(report) + b"\n")
    except BaseException as error:
        (out / "failure.json").write_bytes(canonical({"status": "failed_partial_preserved", "type": type(error).__name__, "reason": str(error)}) + b"\n")
        raise
    print(json.dumps({"analysis_version": VERSION, "completed_trials": report["completed_trials"], "unsupported_call_count": report["unsupported_call_count"], "labels_generated": "literal tuples only; no reliance annotations"}))


if __name__ == "__main__":
    main()
