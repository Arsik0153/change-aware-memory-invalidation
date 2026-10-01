from __future__ import annotations

from pathlib import Path

from cami.artifacts import file_hash, load, reserve, write_json, write_jsonl
from cami.dataset_models import DatasetManifest
from cami.engine import run_experiment
from cami.models import EnvironmentProfile, RunConfig

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
    dataset = load(dataset_path, DatasetManifest)
    profile = EnvironmentProfile(image=image, python_version="3.12.12", source_paths=("src",))
    reserve(output)
    summaries = []
    for entry in dataset.runs:
        original = load(dataset_path.parent / entry.config_path, RunConfig)
        base = output / "inputs" / entry.run_id
        base.mkdir(parents=True)
        probe = base / "test_environment.py"
        probe.write_text(PROBE)
        claim_id = entry.run_id + "-environment"
        claim = {"schema_version":1,"claim_id":claim_id,"repo_id":original.repo.repo_id,
            "origin_commit":original.parent_commit,"kind":"behavior_test",
            "text":"The frozen CliRunner invocation of an echo command exits zero and prints cami-pilot followed by a newline.",
            "subject":{"path":"src/click/core.py","qualname":"Command.main","node_kind":"method"},
            "predicate":{"type":"behavior_test","probe_path":probe.name,"probe_sha256":file_hash(probe),
                         "node_id":"test_environment.py::test_echo_invocation","environment_id":"click-pilot"},
            "scope":"Only this finite probe case on Linux Python 3.12.12, without repository conftest or third-party plugins."}
        write_jsonl(base / "claims.jsonl",[claim])
        write_jsonl(base / "provenance.jsonl",[{"schema_version":1,"claim_id":claim_id,"scenario_id":"intact",
            "anchors":[],"dependencies":[],"known_incomplete":True,"unresolved_reasons":["finite probe spans Click command and testing modules"]}])
        write_jsonl(base / "parent_receipts.jsonl",[{"schema_version":1,"claim_id":claim_id,"origin_commit":original.parent_commit,
            "status":"supported","confirmation_type":"independently_authored_finite_case_with_required_parent_repetitions",
            "evidence_path":probe.name,"evidence_sha256":file_hash(probe)}])
        config = original.model_copy(update={"claims_path":"claims.jsonl","provenance_path":"provenance.jsonl",
            "parent_receipts_path":"parent_receipts.jsonl", "policy":original.policy.model_copy(update={"id":"all_validate"}),
            "validation":original.validation.model_copy(update={"execution":"docker"}), "environment_profiles":{"click-pilot":profile}})
        write_json(base / "run.json",config)
        run = output / "runs" / entry.run_id
        manifest = run_experiment(base / "run.json",run)
        summaries.append({"run_id":entry.run_id,"status":manifest["status"],"excluded":manifest["excluded"],
                          "run_path":str(run.resolve())})
        print(f"environment checked {entry.run_id}",flush=True)
    write_json(output / "environment_report.json",{"schema_version":1,"dataset_kind":dataset.dataset_kind,
        "profile":profile.model_dump(mode="json"),"runs":summaries,
        "scope":"Finite environment smoke probe only; not the full historical test suite.",
        "child_labels":"not produced; validation outcomes are not ground truth"})
