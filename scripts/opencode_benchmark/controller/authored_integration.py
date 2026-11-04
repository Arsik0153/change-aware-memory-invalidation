"""Explicit authored no-model Docker integration; never admits prompts or credentials."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
import tarfile

from study_common import command, digest, file_hashes, read, require_success, write
from study_runtime import grade, origin_memory, regression_allowance, verify_memory
from study_schema import make_study
from study_workspace import capture, create_namespace, reset

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "src/cami").is_dir())


def archive(source, destination):
    with tarfile.open(destination, "w:gz") as stream:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                stream.add(path, arcname=path.relative_to(source), recursive=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--runtime-manifest", type=Path)
    parser.add_argument("--cami-source", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    out = args.out.absolute()
    if not out.is_relative_to(ROOT / "runs") or out.exists():
        parser.error("new output under the owned runs directory required")
    out.mkdir(parents=True)
    bundle, source = out / "bundle", out / "authored-source"
    (bundle / "oracles").mkdir(parents=True)
    (bundle / "fixtures").mkdir()
    (source / "src/authored").mkdir(parents=True)
    (source / "tests").mkdir()
    (source / "src/pytest.py").write_text(
        "raise RuntimeError('authored candidate must not replace trusted pytest')\n"
    )
    (source / "src/authored/__init__.py").write_text("def value():\n    return 1\n")
    (source / "tests/test_value.py").write_text(
        "import pytest\nfrom authored import value\ndef test_regression():\n    assert value() > 0\n@pytest.mark.skip(reason='known synthetic platform allowance')\ndef test_known_skip():\n    assert False\n"
    )
    (bundle / "oracles/test_value.py").write_text(
        "from authored import value\ndef test_acceptance():\n    assert value() in (1, 2)\n"
    )
    shutil.copyfile(
        ROOT / "examples/opencode_benchmark_development_v1/seed_source_notes.py",
        bundle / "seed_source_notes.py",
    )
    # Build the exact origin expectation before even the authored successor is written.
    result = command(
        [
            sys.executable,
            bundle / "seed_source_notes.py",
            "--repo",
            source,
            "--source-root",
            "src/authored",
            "--out",
            bundle / "memory-origin",
        ]
    )
    write(out / "expected-seed-generation.json", result)
    require_success(result)
    fixtures = []
    for number in (1, 2):
        (source / "src/authored/__init__.py").write_text(f"def value():\n    return {number}\n")
        target = bundle / f"fixtures/task{number}.tar.gz"
        archive(source, target)
        fixtures.append(
            {
                "task": f"task{number}",
                "role": "base",
                "archive": target.relative_to(bundle).as_posix(),
                "sha256": digest(target),
            }
        )
    write(bundle / "fixture-manifest.json", {"fixtures": fixtures})
    write(
        bundle / "task-prompts.json",
        {"task1": "Authored no-model task one.", "task2": "Authored no-model task two."},
    )
    write(
        bundle / "task-evaluation.json",
        {"tasks": [{"id": f"task{i}", "acceptance": ["oracles/test_value.py"]} for i in (1, 2)]},
    )
    study = make_study(
        bundle,
        "development",
        args.harness.resolve(),
        args.image,
        args.cami_source.resolve(),
        args.adapter.resolve(),
        HERE,
        args.runtime_manifest.resolve() if args.runtime_manifest else None,
    )
    write(out / "study.json", study)
    study_sha = digest(out / "study.json")
    report = {
        "status": "started",
        "model_calls": 0,
        "auth_imports": 0,
        "cases": [],
        "source_pins_before": {name: pin["files"] for name, pin in study["pins"].items()},
    }
    try:
        for arm in ("plain", "static", "cami"):
            ns = out / "namespaces" / f"r1-{arm}"
            create_namespace(ns, study_sha)
            workspace, memory = ns / "workspace", ns / "memory"
            immutable = None
            for stage in (1, 2):
                trial_out = out / f"{arm}-stage{stage}"
                trial_out.mkdir()
                task = study["normalized"]["tasks"][stage - 1]
                canonical = reset(ns, bundle / task["archive"], task["archive_sha256"], study_sha)
                write(trial_out / "canonical.json", canonical)
                if stage == 1 and arm != "plain":
                    immutable = origin_memory(
                        study, workspace, memory, trial_out / "construction", arm
                    )
                else:
                    immutable = verify_memory(study, memory, arm, immutable)
                allowance, allowance_sha = regression_allowance(study, task, workspace, out)
                session_out = trial_out / "session"
                argv = [
                    sys.executable,
                    args.harness,
                    "--workspace",
                    workspace,
                    "--memory-dir",
                    memory,
                    "--state-dir",
                    trial_out / "private-state",
                    "--out",
                    session_out,
                    "--arm",
                    arm,
                    "--no-model",
                    "--image",
                    args.image,
                    "--cami-source",
                    args.cami_source,
                    "--adapter-dir",
                    args.adapter,
                ]
                if arm != "plain":
                    argv += ["--binding-relative", "prepared/binding.json"]
                if args.runtime_manifest:
                    argv += ["--runtime-manifest", args.runtime_manifest]
                result = command(argv, timeout=180)
                write(trial_out / "session-process.json", result)
                require_success(result)
                manifest = read(session_out / "manifest.json")
                if manifest["status"] != "passed" or manifest["model_requested"]:
                    raise ValueError("authored session requested model or failed")
                usage = read(session_out / "evidence/usage.json")
                if (
                    usage["assistant_message_count"]
                    or usage["session_tokens"]["input"]
                    or usage["session_tokens"]["output"]
                ):
                    raise ValueError("unexpected model activity")
                verify_memory(study, memory, arm, immutable)
                capture(workspace, canonical["canonical_files"], trial_out / "candidate")
                quality = grade(
                    study, task, trial_out / "candidate", trial_out / "grading", allowance=allowance
                )
                if quality["status"] != "pass":
                    raise ValueError("authored fixed grading failed")
                report["cases"].append(
                    {
                        "arm": arm,
                        "canonical_stage": stage,
                        "session": "passed",
                        "grading": "passed",
                        "canonical_sha256": task["archive_sha256"],
                        "memory_identity": str(memory),
                        "immutable_memory": immutable,
                        "model_calls": 0,
                        "regression_allowance_sha256": allowance_sha,
                    }
                )
        skip_bundle = out / "skip-control-bundle"
        shutil.copytree(bundle, skip_bundle)
        (skip_bundle / "oracles/test_value.py").write_text(
            "import pytest\n@pytest.mark.skip(reason='authored skip control')\ndef test_acceptance():\n    assert False\n"
        )
        skip_study = dict(study, bundle_path=str(skip_bundle))
        skipped = grade(
            skip_study,
            study["normalized"]["tasks"][1],
            out / "cami-stage2/candidate",
            out / "skip-control",
            checks=("acceptance",),
        )
        if (
            skipped["status"] != "fail"
            or skipped["outcomes"]["acceptance"]["counts"]["skipped"] != 1
        ):
            raise ValueError("all-skipped acceptance incorrectly counted as success")
        report["all_skipped_control"] = {"rejected": True, "outcomes": skipped["outcomes"]}
        report["status"] = "passed"
    except BaseException as error:
        report.update(status="failed", failure=type(error).__name__ + ": " + str(error))
        raise
    finally:
        report["artifact_hashes"] = file_hashes(out)
        write(out / "report.json", report)


if __name__ == "__main__":
    main()
