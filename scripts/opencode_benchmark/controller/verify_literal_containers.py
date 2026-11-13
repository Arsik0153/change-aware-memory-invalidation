"""Verify schema2 preparation/catalog parity and configured MCP stdio; default plan only."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "src/cami").is_dir())


def execute(study_path, controller, output, *, ranking_policy="lexical-overlap/1"):
    # Explicit run only: pinned installed helpers, no auth import/model session invocation.
    sys.path.insert(0, str(controller))
    schema = importlib.import_module("study_schema")
    common = importlib.import_module("study_common")
    workspaces = importlib.import_module("study_workspace")
    runtime = importlib.import_module("study_runtime")
    seed_schema = importlib.import_module("memory_seed_schema")
    for module in (schema, common, workspaces, runtime, seed_schema):
        if Path(module.__file__).resolve().parent != controller:
            raise ValueError("loaded helper is not the supplied installed controller")
    study = common.read(study_path)
    schema.validate(study, execute=False)
    if Path(study["pins"]["controller"]["root"]).resolve() != controller:
        raise ValueError("supplied controller differs from pinned controller")
    if seed_schema.policy_for(study["normalized"])["schema_version"] != 2:
        raise ValueError("explicit schema2 study required")
    sys.path.insert(0, str(Path(study["harness"]).parent))
    harness = importlib.import_module("container_session")
    if Path(harness.__file__).resolve() != Path(study["harness"]).resolve():
        raise ValueError("loaded harness is not the frozen harness")
    study_sha = common.digest(study_path)
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "status": "started",
        "study_sha256": study_sha,
        "model_calls": 0,
        "ranking_policy": ranking_policy,
        "scope": "correctness only; no OpenCode model/API/auth/session; no task gold/evaluator execution",
        "timing_interpretation": "overlapping correctness work; not performance evidence",
        "preparation": {},
        "observations": [],
    }
    try:
        normalized = study["normalized"]
        task = normalized["tasks"][0]
        bundle = Path(study["bundle_path"])
        expected_catalog = seed_schema.literal_catalog(common.read(bundle / normalized["seed"]))
        expected = next(
            row
            for row in expected_catalog["records"]
            if len(
                json.dumps(row, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
            )
            <= 16384
        )
        catalogs = {}
        for backend in ("static", "cami"):
            arm = output / backend
            workspaces.create_namespace(arm, study_sha)
            common.write(
                arm / "canonical-reset.json",
                workspaces.reset(arm, bundle / task["archive"], task["archive_sha256"], study_sha),
            )
            workspace, memory = arm / "workspace", arm / "memory"
            report["preparation"][backend] = runtime.origin_memory(
                study, workspace, memory, arm / "preparation", backend
            )
            catalogs[backend] = (memory / "prepared/catalog.json").read_bytes()
            for response_format in ("full", "compact", "readable"):
                case = arm / response_format
                case.mkdir()
                evidence = case / "evidence"
                evidence.mkdir()
                server = harness.configuration(backend, "prepared/binding.json", response_format, ranking_policy=ranking_policy)[
                    "mcp"
                ]["servers"]["research_memory"]
                common.write(
                    case / "config.json",
                    {
                        "server": server,
                        "backend": backend,
                        "format": response_format,
                        "expected": expected,
                    },
                )
                common.chown(case)
                result = runtime.container(
                    study,
                    [
                        (workspace, "/workspace", False),
                        (memory, "/memory", False),
                        (Path(study["cami_source"]), "/opt/cami-src", True),
                        (Path(study["adapter"]), "/opt/memory-adapter", True),
                        (controller / "literal_stdio_worker.py", "/opt/literal_stdio_worker.py", True),
                        (controller / "readable_receipts.py", "/opt/readable_receipts.py", True),
                        (case, "/check", False),
                        (evidence, "/state/evidence", False),
                    ],
                    [
                        "python",
                        "-I",
                        "/opt/literal_stdio_worker.py",
                        "--config",
                        "/check/config.json",
                        "--out",
                        "/check/result.json",
                    ],
                    case / "container",
                    timeout=180,
                )
                if (
                    result["status"] != "passed"
                    or common.read(case / "result.json")["status"] != "passed"
                ):
                    raise ValueError("configured stdio correctness failed; evidence retained")
                events = [json.loads(line) for line in (evidence / "memory-backend-trace.jsonl").read_text().splitlines()]
                runtime.validate_ranking_trace(events, backend, ranking_policy)
                report["observations"].append(common.read(case / "result.json"))
        if catalogs["static"] != catalogs["cami"]:
            raise ValueError("global static/CAMI catalog bytes differ")
        report.update(
            status="passed",
            literal_records=len(expected_catalog["records"]),
            catalog_sha256=hashlib.sha256(catalogs["static"]).hexdigest(),
            global_catalog_byte_parity=True,
            actual_configured_stdio_cases=len(report["observations"]),
        )
        schema.validate(study, execute=False)
    except BaseException as error:
        report.update(status="failed", error=type(error).__name__ + ": " + str(error))
        raise
    finally:
        report["artifact_hashes"] = common.file_hashes(output)
        common.write(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", action="store_true", help="Explicit correctness containers; never models"
    )
    parser.add_argument("--study", type=Path)
    parser.add_argument(
        "--controller-dir", type=Path, default=ROOT / "scripts/opencode_benchmark/controller"
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--ranking-policy", choices=["lexical-overlap/1", "identifier-mentions/1"], default="lexical-overlap/1")
    args = parser.parse_args()
    if not args.run:
        print(
            json.dumps(
                {
                    "status": "plan_only",
                    "model_calls": 0,
                    "cases": [backend + "/" + mode for backend in ("static", "cami")
                              for mode in ("full", "compact", "readable")],
                    "requires": "installed schema2 controller and pinned schema2 study",
                    "writes": False,
                }
            )
        )
        return
    if args.study is None or args.out is None:
        parser.error("--run requires --study and NEW --out")
    output = args.out.resolve()
    if not output.is_relative_to(ROOT / "runs") or output.exists():
        parser.error("--out must be a new path under runs; prior attempts are preserved")
    execute(args.study.resolve(), args.controller_dir.resolve(), output, ranking_policy=args.ranking_policy)


if __name__ == "__main__":
    main()
