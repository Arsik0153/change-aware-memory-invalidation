from __future__ import annotations

from pathlib import Path

from cami.artifacts import canonical, file_hash, load, reserve, within, write_json
from cami.behavior import ProbeContext, check_docker, execute_probe
from cami.dataset_models import DatasetManifest
from cami.errors import InputError
from cami.models import Claim, EnvironmentProfile, RunConfig
from cami.repository import read_snapshot, resolve

PROBE = '''import click
from click.testing import CliRunner


def test_echo_invocation():
    @click.command()
    def hello():
        click.echo("cami-pilot")
    result = CliRunner().invoke(hello, [])
    assert result.exit_code == 0
    assert result.output == "cami-pilot\\n"
'''


def pilot_environments(dataset_path: Path, image: str, output: Path) -> None:
    """Observe finite Click probes on parents without asserting independent confirmation."""
    dataset = load(dataset_path, DatasetManifest)
    profile = EnvironmentProfile(image=image, python_version="3.12.12", source_paths=(".", "src"))
    prepared = []
    seen = set()
    for entry in dataset.runs:
        if entry.run_id in seen:
            raise InputError("duplicate environment diagnostic run ID")
        seen.add(entry.run_id)
        within(output / "inputs", entry.run_id)
        within(output / "observations", entry.run_id)
        config_path = within(dataset_path.resolve().parent, entry.config_path)
        original = load(config_path, RunConfig)
        if original.dataset_kind != dataset.dataset_kind:
            raise InputError("environment diagnostic dataset kind differs from run configuration")
        if original.repo.repo_id != "click":
            raise InputError("pilot-environments supports the finite Click smoke probe only")
        repo = original.repo.model_copy(update={"path": str((config_path.parent / original.repo.path).resolve())})
        parent = resolve(Path(repo.path), original.parent_commit)
        prepared.append((entry, repo, parent, config_path))
    if output.resolve().is_relative_to(dataset_path.resolve().parent):
        raise InputError("environment output must be outside the source dataset")
    check_docker(profile)
    reserve(output)
    report = {"schema_version": 2, "status": "running", "dataset_kind": dataset.dataset_kind,
              "profile": profile.model_dump(mode="json"), "dataset_sha256": file_hash(dataset_path),
              "source_config_hashes": {entry.run_id: file_hash(path) for entry, _, _, path in prepared},
              "scope": "Automated parent-only finite Click environment observations.",
              "evaluation_eligible": False, "produces_parent_receipts": False,
              "child_revisions_executed": False, "child_labels": "not produced",
              "implementation_hashes": {path.name: file_hash(path) for path in (
                  Path(__file__), Path(__file__).with_name('behavior.py'),
                  Path(__file__).with_name('repository.py'), Path(__file__).with_name('probe_runner.py'))}}
    summaries: list[dict[str, str | int]] = []
    total_executions = 0

    def save(status: str, failure: dict[str, str] | None = None) -> None:
        report.update({"status": status, "parents": summaries, "failure": failure,
            "test_executions": total_executions if status == "complete" else None,
            "completed_parent_test_executions": total_executions,
            "limitations": ["Automated observations are not independent parent confirmation.",
                            "One finite probe does not establish full historical test compatibility."],
            "artifact_hashes": {path.relative_to(output).as_posix(): file_hash(path)
                for path in sorted(output.rglob('*')) if path.is_file() and path.name != 'environment_report.json'}})
        write_json(output / "environment_report.json", report)

    save("running")
    current_run = ""
    try:
        for entry, repo, parent, _ in prepared:
            current_run = entry.run_id
            snapshot = read_snapshot(repo, parent)
            core_paths = [path for path in ("src/click/core.py", "click/core.py") if path in snapshot.by_path()]
            if len(core_paths) != 1:
                raise InputError("finite Click diagnostic requires one unambiguous core module")
            base = within(output / "inputs", entry.run_id)
            base.mkdir(parents=True)
            probe = base / "test_environment.py"
            probe.write_text(PROBE)
            claim_id = entry.run_id + "-environment"
            claim = Claim.model_validate_json(canonical({"schema_version": 1, "claim_id": claim_id,
                "repo_id": repo.repo_id, "origin_commit": parent, "kind": "behavior_test",
                "text": "The frozen CliRunner invocation of an echo command exits zero and prints cami-pilot followed by a newline.",
                "subject": {"path": core_paths[0], "qualname": "Command.main", "node_kind": "method"},
                "predicate": {"type": "behavior_test", "probe_path": probe.name, "probe_sha256": file_hash(probe),
                              "node_id": "test_environment.py::test_echo_invocation", "environment_id": "click-pilot"},
                "scope": "Only this finite probe case on Linux Python 3.12.12, without repository conftest or third-party plugins."}))
            write_json(base / "claim.json", claim)
            write_json(base / "parent_input.json", {"repo": repo.model_dump(mode="json"), "parent_commit": parent})
            target = within(output / "observations", entry.run_id)
            result = execute_probe(claim, ProbeContext(snapshot, profile, base, target,
                                                       phase="preflight"))
            write_json(target / "observation.json", result)
            total_executions += result.test_executions
            summaries.append({"run_id": entry.run_id, "parent_commit": parent,
                              "verdict": result.verdict, "reason": result.reason,
                              "test_executions": result.test_executions,
                              "observation_path": f"observations/{entry.run_id}/observation.json"})
            print(f"parent environment checked {entry.run_id}: {result.verdict}", flush=True)
            save("running")
    except Exception as exc:
        save("failed", {"run_id": current_run, "type": type(exc).__name__, "message": str(exc)})
        raise
    save("complete")
