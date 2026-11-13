"""Exercise the shipped zipapp in an empty venv, with fresh behavioral checks."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import venv
import zipfile


def verify(artifact, out):
    out.mkdir(parents=True, exist_ok=False)
    venv.EnvBuilder(with_pip=False).create(out / "venv")
    python = out / "venv/bin/python"
    subprocess.run(
        [
            python,
            "-I",
            "-c",
            "import importlib.util; assert importlib.util.find_spec('cami') is None; assert importlib.util.find_spec('pydantic') is None",
        ],
        check=True,
        cwd=out,
    )
    with zipfile.ZipFile(artifact) as archive:
        assert sorted(archive.namelist()) == ["__main__.py", "task_replay.py"]
        source_sha = hashlib.sha256(archive.read("task_replay.py")).hexdigest()
    before, after = out / "before", out / "after"
    (before / "src").mkdir(parents=True)
    (before / "tests").mkdir()
    (before / "src/app.py").write_text("def answer():\n    return 6\n")
    (before / "src/obsolete.py").write_text("old = True\n")
    (before / "settings.json").write_text('{"mode":"original"}\n')
    (before / "tests/fixed.txt").write_text("original fixed test\n")
    shutil.copytree(before, after)
    (after / "src/app.py").write_text("def answer():\n    return 42\n")
    (after / "src/obsolete.py").unlink()
    (after / "src/added.py").write_text("ready = True\n")
    (after / "src/added.py").chmod(0o755)
    (after / "settings.json").write_text('{"mode":"must not replay"}\n')
    (after / "tests/fixed.txt").write_text("must not replay changed tests\n")
    task = out / "task.txt"
    task.write_text("Return the answer, add readiness, remove obsolete source.\n")
    cache = out / "cache"
    common = ["--task-file", str(task), "--context-id", "fixed-runtime-v1", "--cache", str(cache)]

    def command(args, ok=True):
        result = subprocess.run(
            [python, "-I", artifact, *args], capture_output=True, text=True, cwd=out
        )
        if ok:
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)
        assert result.returncode != 0
        return {"returncode": result.returncode}

    recorded = command(["record", "--before", str(before), "--after", str(after), *common])
    assert command(["record", "--before", str(before), "--after", str(after), *common]) == recorded
    target = out / "candidate"
    hit = command(["materialize", "--workspace", str(before), "--out", str(target), *common])
    assert hit["status"] == "candidate_requires_grading" and hit["model_calls"] == 0
    assert (target / "settings.json").read_bytes() == (before / "settings.json").read_bytes()
    assert (target / "tests/fixed.txt").read_bytes() == (before / "tests/fixed.txt").read_bytes()
    assert not (target / "src/obsolete.py").exists()
    assert (target / "src/added.py").stat().st_mode & 0o777 == 0o755
    subprocess.run(
        [
            python,
            "-I",
            "-c",
            "import runpy,sys;from pathlib import Path;p=Path(sys.argv[1]);assert runpy.run_path(p/'src/app.py')['answer']()==42;assert runpy.run_path(p/'src/added.py')['ready'] is True",
            target,
        ],
        check=True,
        cwd=out,
    )
    assert (before / "src/app.py").read_text() == "def answer():\n    return 6\n"
    assert (before / "src/obsolete.py").exists()
    for name, new_task, context, mutate in [
        ("task", "Different task", "fixed-runtime-v1", False),
        ("context", task.read_text(), "changed-runtime", False),
        ("input", task.read_text(), "fixed-runtime-v1", True),
    ]:
        text = out / (name + "-task.txt")
        text.write_text(new_task)
        source = out / (name + "-workspace")
        shutil.copytree(before, source)
        if mutate:
            (source / "settings.json").write_text('{"mode":"changed"}\n')
        output = out / (name + "-output")
        result = command(
            [
                "materialize",
                "--workspace",
                str(source),
                "--out",
                str(output),
                "--task-file",
                str(text),
                "--context-id",
                context,
                "--cache",
                str(cache),
            ]
        )
        assert result["status"] == "miss" and not output.exists()
    command(["materialize", "--workspace", str(before), "--out", str(target), *common], ok=False)
    entry = cache / (recorded["key"] + ".json")
    data = json.loads(entry.read_text())
    data["changes"]["src/app.py"]["sha256"] = "0" * 64
    entry.write_text(json.dumps(data))
    bad = out / "corrupt-output"
    command(["materialize", "--workspace", str(before), "--out", str(bad), *common], ok=False)
    assert not bad.exists()
    return {
        "status": "passed",
        "artifact_bytes": artifact.stat().st_size,
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "source_sha256": source_sha,
        "checks": [
            "empty_venv_without_cami_or_pydantic",
            "archive_contains_only_entrypoint_and_original_module",
            "idempotent_record",
            "exact_hit",
            "fresh_behavioral_grade",
            "source_add_change_delete_and_mode",
            "input_unchanged",
            "non_source_edits_not_replayed",
            "changed_task_miss",
            "changed_context_miss",
            "changed_input_miss",
            "existing_output_preserved",
            "corrupt_cache_rejected_before_output",
        ],
        "python": sys.version,
        "model_calls": 0,
        "scope": "Artifact delivery correctness, not a new performance measurement.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.artifact.resolve(), args.out.resolve())
    with args.report.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result))
