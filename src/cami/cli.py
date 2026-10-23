from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from cami.errors import IncompleteError, InputError, ResourceError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cami")
    sub = parser.add_subparsers(dest="command", required=True)
    find = sub.add_parser("find", help="find Python definitions in a committed Git snapshot")
    find.add_argument("symbol")
    find.add_argument("--repo", type=Path, required=True)
    find.add_argument("--revision", default="HEAD")
    find.add_argument("--format", choices=("text", "json"), default="text")
    find.add_argument("--source-root", action="append", dest="source_roots",
                      help="repository-relative Python source root; repeat for multiple roots")
    check = sub.add_parser("check-inputs")
    check.add_argument("--config", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    demonstration = sub.add_parser("demo")
    demonstration.add_argument("--out", type=Path, required=True)
    score = sub.add_parser("score")
    score.add_argument("--run", type=Path, required=True)
    score.add_argument("--labels", type=Path, required=True)
    score.add_argument("--out", type=Path, required=True)
    compare = sub.add_parser("compare")
    compare.add_argument("--runs", type=Path, nargs="+", required=True)
    compare.add_argument("--labels", type=Path, required=True)
    compare.add_argument("--out", type=Path, required=True)
    scenario = sub.add_parser("prepare-scenario")
    scenario.add_argument("--dataset", type=Path, required=True)
    scenario.add_argument("--mode", choices=("known_missing", "hidden_missing"), required=True)
    scenario.add_argument("--drop", type=float, required=True)
    scenario.add_argument("--seed", type=int, required=True)
    scenario.add_argument("--out", type=Path, required=True)
    pilot = sub.add_parser("prepare-pilot")
    pilot.add_argument("--repo", type=Path, required=True)
    pilot.add_argument("--out", type=Path, required=True)
    pilot_run = sub.add_parser("pilot-run")
    pilot_run.add_argument("--dataset", type=Path, required=True)
    pilot_run.add_argument("--out", type=Path, required=True)
    pilot_report_parser = sub.add_parser("pilot-report")
    pilot_report_parser.add_argument("--runs", type=Path, required=True)
    pilot_report_parser.add_argument("--out", type=Path, required=True)
    environments = sub.add_parser("pilot-environments")
    environments.add_argument("--dataset", type=Path, required=True)
    environments.add_argument("--image", required=True)
    environments.add_argument("--out", type=Path, required=True)
    for command in ("annotate-export", "freeze"):
        command_parser = sub.add_parser(command)
        command_parser.add_argument("--dataset", type=Path, required=True)
        command_parser.add_argument("--out", type=Path, required=True)
    importer = sub.add_parser("annotate-import")
    importer.add_argument("--input", type=Path, required=True)
    importer.add_argument("--out", type=Path, required=True)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--dataset", type=Path, required=True)
    analyze.add_argument("--runs", type=Path, nargs="+", required=True)
    analyze.add_argument("--labels", type=Path, required=True)
    analyze.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "find":
            from cami.symbol_search import find_symbols, format_text
            result = find_symbols(args.repo, args.symbol, args.revision,
                                  tuple(args.source_roots) if args.source_roots else None)
            print(json.dumps(result.model_dump(mode="json"), ensure_ascii=True, sort_keys=True)
                  if args.format == "json" else format_text(result))
        elif args.command == "check-inputs":
            from cami.inputs import check_inputs
            inputs = check_inputs(args.config)
            print(f"valid: {len(inputs.claims)} claims, {len(inputs.config.child_commits)} transitions")
        elif args.command == "annotate-export":
            from cami.dataset import annotate_export
            annotate_export(args.dataset, args.out)
        elif args.command == "annotate-import":
            from cami.dataset import annotate_import
            annotate_import(args.input, args.out)
        elif args.command == "freeze":
            from cami.dataset import freeze_dataset
            freeze_dataset(args.dataset, args.out)
        elif args.command == "analyze":
            from cami.aggregate import analyze_dataset
            analyze_dataset(args.dataset, args.runs, args.labels, args.out)
        elif args.command == "pilot-environments":
            from cami.environment_pilot import pilot_environments
            pilot_environments(args.dataset, args.image, args.out)
        elif args.command == "pilot-report":
            from cami.operational import pilot_report
            pilot_report(args.runs, args.out)
        elif args.command == "prepare-pilot":
            from cami.pilot import prepare_pilot
            prepare_pilot(args.repo, args.out)
        elif args.command == "pilot-run":
            from cami.pilot import run_pilot
            run_pilot(args.dataset, args.out)
        elif args.command == "prepare-scenario":
            from cami.scenarios import prepare_scenario
            prepare_scenario(args.dataset, args.mode, args.drop, args.seed, args.out)
        elif args.command == "run":
            from cami.engine import run_experiment
            run_experiment(args.config, args.out)
        elif args.command == "demo":
            from cami.demo import demo
            demo(args.out)
        elif args.command == "score":
            from cami.evaluation import score_run
            score_run(args.run, args.labels, args.out)
        elif args.command == "compare":
            from cami.evaluation import compare_runs
            compare_runs(args.runs, args.labels, args.out)
        return 0
    except (InputError, ValidationError, ValueError, OSError) as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 2
    except ResourceError as exc:
        print(f"resource unavailable: {exc}", file=sys.stderr)
        return 3
    except (IncompleteError, KeyboardInterrupt) as exc:
        print(f"incomplete: {exc}", file=sys.stderr)
        return 4
    except Exception as exc:
        print(f"incomplete: unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
