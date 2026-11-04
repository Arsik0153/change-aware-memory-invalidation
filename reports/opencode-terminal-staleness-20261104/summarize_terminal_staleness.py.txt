"""Read-only terminal snapshot: authenticated returned/withheld literal-source records."""

from __future__ import annotations

import argparse
from collections import Counter
from functools import lru_cache
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import stat

from classify_memory_calls import canonical, classify

PRIVATE = {"private-state", "server-private", "private-export-client"}


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            value.update(chunk)
    return value.hexdigest()


def read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular public artifact required")
    return json.loads(path.read_bytes())


def inventory(root):
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        if any(n in PRIVATE for n in dirs + files):
            raise ValueError("private state refused without reading")
        for name in dirs + files:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ValueError("nonregular public artifact refused")
            result[path.relative_to(root).as_posix()] = {
                "sha256": sha(path),
                "bytes": path.stat().st_size,
                "mode": stat.S_IMODE(mode),
            }
    return result


def verify_terminal(directory):
    if directory.is_symlink():
        raise ValueError("trial-directory symlink refused")
    record = read(directory / "terminal.json")
    expected = record["artifact_hashes"]
    for name in expected:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or any(p in PRIVATE for p in path.parts):
            raise ValueError("unsafe/private terminal hash reference")
    actual = {
        name: row["sha256"] for name, row in inventory(directory).items() if name != "terminal.json"
    }
    if actual != expected:
        raise ValueError("terminal artifact hashes/coverage differ")
    return record


def line_boundary_risks(root, files):
    output = []
    separators = {
        "VT": "\v",
        "FF": "\f",
        "FS": "\x1c",
        "GS": "\x1d",
        "RS": "\x1e",
        "NEL": "\x85",
        "LS": "\u2028",
        "PS": "\u2029",
    }
    for relative in sorted(files):
        if not relative.endswith(".py"):
            continue
        try:
            text = (root / relative).read_bytes().decode("utf-8")
        except UnicodeError:
            output.append({"path": relative, "risk": "unsupported_non_utf8"})
            continue
        found = {name: text.count(char) for name, char in separators.items() if char in text}
        bare_cr = len(re.findall(r"\r(?!\n)", text))
        if found or bare_cr:
            output.append(
                {
                    "path": relative,
                    "risk": "unsupported_splitlines_boundaries",
                    "exotic_separators": found,
                    "bare_cr_count": bare_cr,
                }
            )
    return output


def load_analyzer(path):
    spec = importlib.util.spec_from_file_location("frozen_staleness_analyzer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Identical shared CPython AST logic, memoized only for immutable canonical trees.
    module.body = lru_cache(maxsize=1024)(module.body)
    return module


def crosscheck_backend(path, result, catalog_semantic_sha, backend, rows):
    if not path.is_file():
        return {"status": "unsupported_missing_backend_trace"}
    events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if any(
        e.get("catalog_sha256") != catalog_semantic_sha or e.get("backend") != backend
        for e in events
    ):
        return {"status": "unsupported_catalog_or_backend_mismatch"}
    events = [e for e in events if e.get("event") == "memory_lookup"]
    supported = {r["call_id"]: r for r in result["memory_calls"] if r["status"] == "supported"}
    payloads = []
    for row in rows:
        part = row.get("part", {})
        if part.get("id") in supported:
            payloads.append(
                (
                    supported[part["id"]],
                    json.loads(part["state"]["output"]),
                    part["state"].get("input"),
                )
            )
    if len(events) != len(payloads):
        return {
            "status": "unsupported_lookup_count_mismatch",
            "backend_events": len(events),
            "supported_model_calls": len(payloads),
        }
    for event, (call, payload, arguments) in zip(events, payloads, strict=True):
        if (
            not isinstance(arguments, dict)
            or event.get("query_sha256") != hashlib.sha256(canonical(arguments)).hexdigest()
            or event.get("returned_records") != len(call["returned_ids"])
            or event.get("withheld_records") != len(call["withheld_ids"])
        ):
            return {"status": "unsupported_lookup_count_or_query_mismatch"}
    return {"status": "matched", "lookup_events": len(events), "sha256": sha(path)}


def summarize(run, analyzer_path, catalog_path, origin, stage1, stage3):
    analyzer = load_analyzer(analyzer_path)
    study = read(run / "frozen-study.json")
    if study["bundle_kind"] != "development" or study["arms"] != ["plain", "static", "cami"]:
        raise ValueError("development-only registered three-arm study required")
    plan = read(run / "plan.json")["trials"]
    legal = {
        f"r{rep}-{arm}-s{stage}"
        for rep in range(1, 4)
        for arm in ("plain", "static", "cami")
        for stage in range(1, 5)
    }
    if len(plan) != 36 or {r["id"] for r in plan} != legal:
        raise ValueError("expected registered 36-trial plan")
    for item in plan:
        if (
            item["id"] != f"r{item['repetition']}-{item['arm']}-s{item['stage']}"
            or item["task"] != study["normalized"]["sequence"][item["stage"] - 1]
        ):
            raise ValueError("registered trial ID/task/stage binding differs")
    # Snapshot terminal filenames only: no active trial traversal, metadata, or state reads.
    completed = [row for row in plan if (run / "trials" / row["id"] / "terminal.json").is_file()]
    catalog = read(catalog_path)
    catalog_sha = sha(catalog_path)
    semantic_sha = hashlib.sha256(canonical(catalog)).hexdigest()
    trees = {p: inventory(p) for p in {origin, stage1, stage3}}
    boundary_risks = {str(p): line_boundary_risks(p, files) for p, files in trees.items()}
    tree_hashes = {str(p): hashlib.sha256(canonical(v)).hexdigest() for p, v in trees.items()}
    trials = []
    for expected in completed:
        directory = run / "trials" / expected["id"]
        try:
            terminal = verify_terminal(directory)
            if terminal["trial"] != expected:
                raise ValueError("terminal/plan identity differs")
            current = stage1 if expected["stage"] in (1, 2) else stage3
            reset_path = directory / "canonical-reset.json"
            if read(reset_path)["canonical_files"] != trees[current]:
                raise ValueError(
                    "canonical extracted tree differs from terminal reset source hashes/modes"
                )
            messages_path = directory / "session/evidence/messages.json"
            messages = read(messages_path)
            if not isinstance(messages, list):
                raise ValueError("complete aggregated message array required")
            rows = analyzer.message_rows(messages)
            if expected["arm"] == "plain":
                if any(
                    analyzer.memory_tool(r["part"]["tool"])
                    for r in rows
                    if r.get("type") == "tool_use"
                ):
                    raise ValueError("plain unexpectedly contains external memory calls")
                result = {
                    "memory_calls": [],
                    "records": [],
                    "counts": [],
                    "unsupported_calls": 0,
                    "returned_record_observations": 0,
                    "withheld_record_observations": 0,
                }
                backend_check = {"status": "plain_no_external_memory_expected"}
            else:
                before = read(directory / "memory-before.json")
                if (
                    terminal["immutable_memory"].get("prepared/catalog.json") != catalog_sha
                    or before.get("prepared/catalog.json") != catalog_sha
                ):
                    raise ValueError(
                        "catalog raw bytes differ from terminal immutable/before hashes"
                    )
                result = classify(analyzer, rows, catalog, origin, current, expected["arm"])
                backend_check = crosscheck_backend(
                    directory / "session/evidence/memory-backend-trace.jsonl",
                    result,
                    semantic_sha,
                    expected["arm"],
                    rows,
                )
            risk_paths = {
                r["path"] for r in boundary_risks[str(origin)] + boundary_risks[str(current)]
            }
            for observation in result["records"]:
                if observation["subject"]["path"] in risk_paths:
                    observation["prior_literal_assessment"] = observation["assessment"]
                    observation["assessment"] = "unsupported_source_line_boundaries"
            # Recount after conservative line-boundary flags without changing extraction.
            recount = Counter(
                (r["channel"], r["record_kind"], r["assessment"]) for r in result["records"]
            )
            result["counts"] = [
                {"channel": ch, "record_kind": kind, "assessment": assessment, "observations": n}
                for (ch, kind, assessment), n in sorted(recount.items())
            ]
            trials.append(
                {
                    "trial": expected,
                    "terminal_status": terminal["status"],
                    "status": "assessed",
                    "terminal_sha256": sha(directory / "terminal.json"),
                    "artifact_hashes_verified": len(terminal["artifact_hashes"]),
                    "messages_sha256": sha(messages_path),
                    "canonical_reset_sha256": sha(reset_path),
                    "canonical_tree_sha256": tree_hashes[str(current)],
                    "catalog_raw_sha256": catalog_sha if expected["arm"] != "plain" else None,
                    "catalog_semantic_sha256": semantic_sha if expected["arm"] != "plain" else None,
                    "backend_crosscheck": backend_check,
                    **result,
                }
            )
        except (ValueError, KeyError, TypeError, OSError) as error:
            trials.append(
                {
                    "trial": expected,
                    "status": "unsupported_or_integrity_error",
                    "reason": type(error).__name__ + ": " + str(error),
                    "counts": None,
                    "memory_calls": None,
                    "records": None,
                    "causal_reliance": "not_inferred",
                    "literal_comparison_boundary": "str.splitlines(keepends=True), earliest decorator line, prefix[:2400] characters; text only",
                    "complete_body_equivalence": "not_inferred",
                    "truncation_marker_equality": "not_assessed",
                }
            )
    if any(inventory(path) != before for path, before in trees.items()):
        raise ValueError("canonical source tree changed during cached literal analysis")
    totals = Counter()
    for trial in trials:
        for row in trial.get("records") or []:
            totals[
                trial["trial"]["arm"], row["channel"], row["record_kind"], row["assessment"]
            ] += 1
    return {
        "schema_version": 1,
        "scope": "Development terminal trials only. Repeated record observations; no causal reliance inference.",
        "planned_trials": 36,
        "completed_trials": len(completed),
        "complete_36": len(completed) == 36,
        "coverage_status": "partial_terminal_snapshot"
        if len(completed) != 36
        else "all_registered_trials_terminal",
        "all_assessed_evidence_supported": all(
            t["status"] == "assessed"
            and not t.get("unsupported_calls")
            and not t.get("backend_crosscheck", {}).get("status", "").startswith("unsupported")
            and not any(r["assessment"].startswith("unsupported") for r in t.get("records") or [])
            for t in trials
        ),
        "terminal_snapshot_ids": [r["id"] for r in completed],
        "active_trials_inspected": False,
        "private_state_read": False,
        "causal_reliance": "not_inferred",
        "literal_comparison_boundary": "str.splitlines(keepends=True), earliest decorator line, prefix[:2400] characters; text only",
        "complete_body_equivalence": "not_inferred",
        "truncation_marker_equality": "not_assessed",
        "backend_crosscheck_unsupported_trial_ids": [
            r["trial"]["id"]
            for r in trials
            if r.get("backend_crosscheck", {}).get("status", "").startswith("unsupported")
        ],
        "trials": trials,
        "unsupported_trial_ids": [r["trial"]["id"] for r in trials if r["status"] != "assessed"],
        "unsupported_call_count": sum(r.get("unsupported_calls", 0) for r in trials),
        "counts": [
            {
                "arm": arm,
                "channel": channel,
                "record_kind": kind,
                "assessment": assessment,
                "observations": n,
            }
            for (arm, channel, kind, assessment), n in sorted(totals.items())
        ],
        "inputs": {
            "run": str(run),
            "frozen_study_sha256": sha(run / "frozen-study.json"),
            "plan_sha256": sha(run / "plan.json"),
            "analyzer_path": str(analyzer_path),
            "analyzer_sha256": sha(analyzer_path),
            "catalog_path": str(catalog_path),
            "catalog_raw_sha256": catalog_sha,
            "catalog_semantic_sha256": semantic_sha,
            "canonical_tree_sha256": tree_hashes,
            "canonical_line_boundary_risks": boundary_risks,
        },
        "limitations": [
            "Only lookups ending before any possible/overlapping mutating tool are source-assessable; shell conservatively counts as possible mutation.",
            "After possible edits or missing timestamps, source classification remains unknown; no canonical-base substitution for edited source.",
            "Literal excerpt changes, unchanged excerpts, absent definitions and typed records are separate; neither behavioral truth nor semantic equivalence is inferred.",
            "Withheld literal comparisons describe origin records not exposed as returned content; they do not prove the withholding policy was incorrect.",
            "Shared existing analyzer and CPython AST logic, with immutable-tree caching; no independent semantic-binding or model reliance oracle.",
            "Plain has no external memory tool exposure, not proof that model knowledge is current.",
            "Unsupported calls/trials stay explicit; assessed-record counts exclude unclassifiable payloads and are not complete totals when unsupported evidence exists.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["run", "analyzer", "catalog", "origin", "stage1", "stage3", "out"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    out = args.out.absolute()
    if (
        out.exists()
        or out.is_relative_to(args.run.absolute())
        or any(p.is_symlink() for p in [out, *out.parents])
    ):
        parser.error("new separate nonsymlink output required")
    out.mkdir(parents=True)
    result = summarize(
        *[
            getattr(args, name).absolute()
            for name in ["run", "analyzer", "catalog", "origin", "stage1", "stage3"]
        ]
    )
    with (out / "report.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
