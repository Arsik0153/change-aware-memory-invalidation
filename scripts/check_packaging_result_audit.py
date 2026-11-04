#!/usr/bin/env python3
"""Generate authored replay output and rehashed negative controls in a NEW dir."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "src/cami").is_dir())
SOURCE = "".join(f"def f{i}(x=1):\n    return x\n" for i in range(4))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def call(argv, **kwargs):
    r = subprocess.run(
        argv,
        capture_output=True,
        timeout=180,
        env={
            **os.environ,
            "GIT_NO_LAZY_FETCH": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_TERMINAL_PROMPT": "0",
        },
        **kwargs,
    )
    if r.returncode:
        raise RuntimeError(r.stderr.decode(errors="replace"))
    return r.stdout


def git(repo, *args):
    return call(["git", "--no-replace-objects", "-C", str(repo), *args])


def history(repo):
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Authored fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    path = repo / "src/packaging/module.py"
    path.parent.mkdir(parents=True)
    previous = None
    frame = []
    for i in range(72):
        if path.is_symlink():
            path.unlink()
        source = SOURCE
        if i == 2:
            source = SOURCE.replace("def f0(x=1)", "def f0(x=2)")
        if i == 4:
            source = SOURCE + "class C:\n    global f0\n    f0=1\n"
        if i == 6:
            source = "def broken(\n"
        if i == 25:
            source = SOURCE.replace("def f1(x=1)", "def f1(x: int=1)")
        if i == 30:
            source = SOURCE.replace("def f2(x=1):\n    return x\n", "")
        if i == 8:
            if path.exists():
                path.unlink()
        elif i == 9:
            path.symlink_to(SOURCE)
        else:
            path.write_text(source)
        (repo / "trajectory.txt").write_text(str(i) + "\n")
        git(repo, "add", "-A")
        tree = git(repo, "write-tree").decode().strip()
        parents = [] if previous is None else [previous]
        if i == 10:
            parents.append(
                git(repo, "commit-tree", tree, "-p", previous, "-m", "authored side metadata")
                .decode()
                .strip()
            )
        args = ["commit-tree", tree]
        for parent in parents:
            args += ["-p", parent]
        commit = git(repo, *args, "-m", f"authored snapshot {i}").decode().strip()
        frame.append({"position": i, "commit": commit, "parents": parents, "committer_epoch": 0})
        previous = commit
    git(repo, "update-ref", "refs/heads/main", previous)
    return frame


def fixture(base, root):
    work = base / "workspace"
    work.mkdir()
    (work / "AUTHORED_FIXTURE_ONLY").write_text("no real project data\n")
    git(work, "init", "-q", "-b", "main")
    git(work, "config", "user.name", "Authored fixture")
    git(work, "config", "user.email", "fixture@example.invalid")
    (work / ".gitignore").write_text("/data/\n/runs/\n__pycache__/\n")
    shutil.copytree(
        root / "src/cami", work / "src/cami", ignore=shutil.ignore_patterns("__pycache__")
    )
    (work / "scripts").mkdir()
    for name in (
        "verify_cami.py",
        "real_structural_replay_support.py",
        "validate_ai_review.py",
        "structural_checker_v2.py",
        "run_packaging_replay.py",
        "packaging_replay_support.py",
    ):
        shutil.copyfile(root / "scripts" / name, work / "scripts" / name)
    shutil.copyfile(
        root / "tests/test_packaging_replay.py", work / "scripts/test_packaging_replay.py"
    )
    for name in ("pyproject.toml", "uv.lock", ".python-version"):
        shutil.copyfile(root / name, work / name)
    frame = history(work / "data/authored-repo")
    write(work / "frame.json", frame)
    (work / "inputs").mkdir()
    bootstrap = """
import ast, hashlib, importlib.util, json, sys
from pathlib import Path
root=Path(sys.argv[1]); spec=importlib.util.spec_from_file_location('authored_driver_fixture',root/'scripts/test_packaging_replay.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
c=m.PackagingFixture; c.inputs=root/'inputs'; c.repo=root/'data/authored-repo'; c.frame=json.loads((root/'frame.json').read_bytes()); c.make_inputs()
"""
    call([sys.executable, "-c", bootstrap, str(work)])
    p = read(work / "inputs/protocol.json")
    raw = SOURCE.encode()
    source_hash = hashlib.sha256(raw).hexdigest()
    cohort = {row["claim"]["claim_id"]: row for row in read(work / p["cohort_path"])}
    functions = {fn.name: fn for fn in ast.parse(SOURCE).body}
    for name in p["provenance"].values():
        path = work / name
        provenance = [json.loads(line) for line in path.read_text().splitlines()]
        for row in provenance:
            anchor = row["anchors"][0]
            fn = functions[cohort[row["claim_id"]]["claim"]["subject"]["qualname"]]
            anchor["start_line"], anchor["end_line"] = (
                (1, len(SOURCE.splitlines()))
                if anchor["scope"] == "file"
                else (fn.lineno, fn.end_lineno)
            )
        path.write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in provenance))
    for group in p["groups"]:
        parent, gid = group["parent_commit"], group["group_id"]
        folder = work / "inputs/parents" / gid
        folder.mkdir(parents=True)
        (folder / "source").mkdir()
        (folder / "source" / f"{source_hash}.raw").write_bytes(raw)
        entries = git(work / "data/authored-repo", "ls-tree", "-rz", "--full-tree", parent)
        inventory = []
        for entry in entries.split(b"\0"):
            if not entry:
                continue
            info, path = entry.split(b"\t")
            mode, kind, oid = info.decode().split()
            path = path.decode()
            inside = path == "src/packaging/module.py"
            inventory.append(
                {
                    "path": path,
                    "git_mode": mode,
                    "git_type": kind,
                    "git_oid": oid,
                    "size_bytes": len(raw) if inside else None,
                    "exclusion_reason": None if inside else "outside_package_roots",
                    "source_sha256": source_hash if inside else None,
                    "source_evidence_path": "source/" + source_hash + ".raw" if inside else None,
                }
            )
        subjects = []
        for fn in ast.parse(SOURCE).body:
            rank = hashlib.sha256(
                (
                    "20261104-packaging-derived-development-v1\n"
                    + parent
                    + "\nsrc/packaging/module.py\n"
                    + fn.name
                ).encode()
            ).hexdigest()
            subjects.append(
                {
                    "path": "src/packaging/module.py",
                    "qualname": fn.name,
                    "scope": "direct_module",
                    "start_line": fn.lineno,
                    "end_line": fn.end_lineno,
                    "rank_sha256": rank,
                    "eligible": True,
                    "exclusion_reasons": [],
                }
            )
        for name, values in [
            ("module_inventory.jsonl", inventory),
            ("subject_inventory.jsonl", subjects),
        ]:
            (folder / name).write_text(
                "".join(json.dumps(x, sort_keys=True) + "\n" for x in values)
            )
        write(
            folder / "ranking.json",
            [
                {
                    "function_rank": i,
                    "path": x["path"],
                    "qualname": x["qualname"],
                    "rank_sha256": x["rank_sha256"],
                    "selected": True,
                }
                for i, x in enumerate(sorted(subjects, key=lambda x: x["rank_sha256"]))
            ],
        )
    generation = read(work / "inputs/parent-generation.json")
    generation["artifact_hashes"] = {
        str(path.relative_to(work / "inputs")): sha(path)
        for path in (work / "inputs/parents").rglob("*")
        if path.is_file()
    }
    generation["artifact_hashes"]["cohort.json"] = sha(work / "inputs/cohort.json")
    write(work / "inputs/parent-generation.json", generation)
    files = {
        str(path.relative_to(work)): sha(path)
        for folder in ("src", "scripts", "inputs")
        for path in (work / folder).rglob("*")
        if path.is_file() and path.name not in {"protocol.json", "seal.json"}
    }
    for name in ("pyproject.toml", "uv.lock", ".python-version"):
        files[name] = sha(work / name)
    write(
        work / "inputs/seal.json",
        {"protocol_sha256": sha(work / "inputs/protocol.json"), "files": files},
    )
    git(work, "add", "-A")
    git(work, "commit", "-qm", "authored frozen final replay")
    result = work / "runs/result"
    stdout = call(
        [
            sys.executable,
            str(work / "scripts/run_packaging_replay.py"),
            "--protocol",
            str(work / "inputs/protocol.json"),
            "--out",
            str(result),
        ]
    )
    (base / "authored-driver.stdout").write_bytes(stdout)
    return work, result


def rehash(result):
    m = read(result / "manifest.json")
    m["artifact_hashes"] = {
        str(p.relative_to(result)): sha(p)
        for p in result.rglob("*")
        if p.is_file() and p != result / "manifest.json"
    }
    write(result / "manifest.json", m)


def invoke(auditor, root, result, out, authored=True):
    r = subprocess.run(
        [
            sys.executable,
            str(auditor),
            "--root",
            str(root),
            "--result",
            str(result),
            "--out",
            str(out),
        ]
        + (["--authored-fixture"] if authored else []),
        capture_output=True,
        timeout=180,
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    (out / "stdout.log").write_bytes(r.stdout)
    (out / "stderr.log").write_bytes(r.stderr)
    return r.returncode, read(out / "report.json")


def mutate_row(result, filename, callback):
    path = result / filename
    values = [json.loads(line) for line in path.read_text().splitlines()]
    callback(values)
    path.write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in values))


def controls(base, root, result, auditor, authored=True):
    rc, original = invoke(auditor, root, result, base / "audit-original", authored)
    require = rc == 0
    if not require:
        raise RuntimeError("original failed: " + original.get("failure", ""))
    results = []

    def check(name, mutator):
        copied = base / "tampered" / name / "result"
        shutil.copytree(result, copied)
        mutator(copied)
        rehash(copied)
        rc, report = invoke(auditor, root, copied, base / "tampered" / name / "audit", authored)
        results.append(
            {
                "control": name,
                "rejected": rc != 0 and report["status"] == "fail",
                "failure": report.get("failure"),
                "manifest_sha256": sha(copied / "manifest.json"),
            }
        )

    check("missing_observation", lambda r: mutate_row(r, "observations.jsonl", lambda x: x.pop()))

    def source(r):
        path = next((r / "packets").rglob("subject.raw"))
        path.write_bytes(path.read_bytes() + b"\n# forged source\n")

    check("rehash_forged_source", source)

    def ref(r):
        path = next((r / "packets").rglob("decision.json"))
        data = read(path)
        data["verdict"] = "supported" if data["verdict"] == "contradicted" else "contradicted"
        write(path, data)

    check("rehash_reference", ref)

    def state(r):
        def change(values):
            values[0]["state"]["available"] = not values[0]["state"]["available"]

        mutate_row(r, "observations.jsonl", change)

    check("rehash_state", state)

    def cost(r):
        def change(values):
            next(x for x in values if x["phase"] == "child_production_validation")[
                "actual_calls"
            ] = 0

        mutate_row(r, "costs.jsonl", change)

    check("rehash_cost", cost)

    def aggregate(r):
        path = r / "report.json"
        data = read(path)
        data["full23"]["variants"]["symbol_anchor"]["actual_validation_calls"] += 1
        write(path, data)

    check("rehash_aggregate", aggregate)

    def topology(r):
        path = r / "topology.json"
        data = read(path)
        group = next(iter(data.values()))
        step = next(iter(group.values()))
        step["is_merge"] = not step["is_merge"]
        write(path, data)

    check("rehash_topology", topology)

    def parent(r):
        def change(values):
            values[0]["eligible"] = False
            values[0]["exclusion_reasons"] = ["fresh_AI_not_both_supported"]

        mutate_row(r, "parents.jsonl", change)

    check("rehash_parent_gate", parent)

    def unknown(r):
        def change(values):
            row = next(x for x in values if x["reference"]["verdict"] == "uncertain")
            row["reference"]["verdict"] = "contradicted"

        mutate_row(r, "observations.jsonl", change)

    has_unknown = any(
        json.loads(line)["reference"]["verdict"] == "uncertain"
        for line in (result / "observations.jsonl").read_text().splitlines()
    )
    if has_unknown:
        check("unknown_as_contradicted", unknown)
    else:
        results.append(
            {
                "control": "unknown_as_contradicted",
                "status": "not_applicable",
                "rejected": None,
                "reason": "Frozen result has no uncertain reference observations; exercised on the authored fixture.",
            }
        )
    write(
        base / "tamper-controls.json",
        {
            "status": "pass" if all(x["rejected"] is not False for x in results) else "fail",
            "controls": results,
            "original_result_manifest_sha256": sha(result / "manifest.json"),
            "original_audit_report_sha256": sha(base / "audit-original/report.json"),
        },
    )
    if not all(x["rejected"] is not False for x in results):
        raise RuntimeError("a tamper control escaped rejection")
    return original, results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--auditor", type=Path, default=HERE / "audit_packaging_replay.py")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path)
    parser.add_argument("--fixture-result", type=Path)
    parser.add_argument(
        "--result", type=Path, help="Real frozen result; rehash copies only, no measured rerun."
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    if args.result is not None:
        if args.fixture_root is not None or args.fixture_result is not None:
            parser.error("--result cannot be combined with authored fixture paths")
        root, result = args.root.resolve(), args.result.resolve()
    elif args.fixture_root is not None or args.fixture_result is not None:
        if args.fixture_root is None or args.fixture_result is None:
            parser.error("--fixture-root and --fixture-result must be supplied together")
        root, result = args.fixture_root.resolve(), args.fixture_result.resolve()
        if (root / "AUTHORED_FIXTURE_ONLY").read_text().strip() != "no real project data":
            parser.error("reused fixture must have the explicit authored marker")
    else:
        root, result = fixture(args.out.resolve(), args.root.resolve())
    original, negative = controls(
        args.out.resolve(), root, result, args.auditor.resolve(), authored=args.result is None
    )
    report = {
        "status": "pass",
        "original_audit": "audit-original/report.json",
        "tamper_controls": len(negative),
        "all_applicable_rehashed_rejected": True,
        "controls_rejected": sum(x["rejected"] is True for x in negative),
        "controls_not_applicable": sum(x.get("status") == "not_applicable" for x in negative),
        "real_project_source_access": args.result is not None,
        "external_network": False,
        "auditor_sha256": sha(args.auditor),
        "reference_packets": original["reference_packets_checked"],
        "original_result_manifest_sha256": sha(result / "manifest.json"),
        "original_audit_report_sha256": sha(args.out / "audit-original/report.json"),
        "dependency_hashes": {
            name: sha(args.auditor.resolve().parent / name)
            for name in (
                "audit_packaging_replay.py",
                "packaging_audit_common.py",
                "packaging_audit_inputs.py",
                "packaging_audit_git.py",
                "packaging_audit_syntax.py",
                "packaging_audit_metrics.py",
            )
        }
        | {"check_packaging_result_audit.py": sha(Path(__file__).resolve())},
    }
    write(args.out / "report.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
