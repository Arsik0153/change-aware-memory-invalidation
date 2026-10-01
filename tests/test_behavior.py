import json
import os

import pytest

from cami.artifacts import file_hash, read_json, read_jsonl
from cami.behavior import ProbeOutcome, ProbePayload, classify, combine
from cami.engine import run_experiment


def test_classification_requires_collected_target_and_assertion():
    def payload(outcome, assertion=False, code=1):
        return ProbePayload.model_validate_json(json.dumps({"collected": ["probe.py::test_it"], "exit_code": code,
            "reports": [{"nodeid": "probe.py::test_it", "when": phase, "outcome": outcome if phase == "call" else "passed",
                         "assertion": assertion if phase == "call" else False, "fingerprint": "same" if assertion else None}
                        for phase in ("setup", "call", "teardown")]}))
    assert classify(payload("failed", True), "probe.py::test_it")[:2] == ("assertion_failure", "predicate_mismatch")
    assert classify(payload("failed"), "probe.py::test_it")[0] == "technical_error"
    assert classify(payload("passed", code=0), "other.py::test_it")[1] == "collection_error"
    success = ProbeOutcome(outcome="passed", reason="test_passed", duration_seconds=0.0, log_path="log")
    failure = ProbeOutcome(outcome="assertion_failure", reason="predicate_mismatch", fingerprint="same", duration_seconds=0.0, log_path="log")
    assert combine((success, failure, success)) == ("insufficient_evidence", "flaky")
    assert combine((failure,) * 3) == ("contradicted", "predicate_mismatch")
    error = ProbeOutcome(outcome="technical_error", reason="timeout", duration_seconds=0.0, log_path="log")
    assert combine((error,) * 3) == ("insufficient_evidence", "timeout")


@pytest.mark.docker
@pytest.mark.skipif(not os.environ.get("CAMI_TEST_IMAGE"), reason="set CAMI_TEST_IMAGE to prepared image digest")
def test_docker_real_git_parent_child_and_environment(repo):
    a = repo.commit({"module.py": "def f(): return 1\n"})
    b = repo.commit({"module.py": "def f(): return 2\n"})
    c = repo.commit({"module.py": "import nonexistent_dependency\ndef f(): return 1\n"})
    config = repo.config(a, [b, c], policy="all_validate")
    probe = config.parent / "test_probe.py"
    probe.write_text("from module import f\ndef test_f():\n    assert f() == 1\n")
    claims_path = config.parent / "claims.jsonl"
    claim = json.loads(claims_path.read_text())
    claim.update(kind="behavior_test", predicate={"type": "behavior_test", "probe_path": probe.name,
                 "probe_sha256": file_hash(probe), "node_id": "test_probe.py::test_f", "environment_id": "test"})
    claims_path.write_text(json.dumps(claim) + "\n")
    data = read_json(config)
    data["validation"]["execution"] = "docker"
    data["environment_profiles"] = {"test": {"image": os.environ["CAMI_TEST_IMAGE"], "python_version": "3.12.12"}}
    config.write_text(json.dumps(data))
    out = config.parent / "out"
    run_experiment(config, out)
    preflight = read_jsonl(out / "preflight_validations.jsonl")
    assert preflight[0]["verdict"] == "supported"
    results = read_jsonl(out / "validations.jsonl")
    assert [r["verdict"] for r in results] == ["contradicted", "insufficient_evidence"]
    assert results[1]["reason"] == "collection_error"
    assert sum(row["test_executions"] for row in read_jsonl(out / "costs.jsonl")) == 9


@pytest.mark.docker
@pytest.mark.skipif(not os.environ.get("CAMI_TEST_IMAGE"), reason="set CAMI_TEST_IMAGE to prepared image digest")
def test_docker_timeout_is_uncertainty(repo):
    from cami.artifacts import load_jsonl
    from cami.behavior import ProbeContext, execute_probe
    from cami.models import Claim, EnvironmentProfile
    from test_index import snapshot
    a = repo.commit({"module.py": "def f(): pass\n"})
    b = repo.commit({})
    config = repo.config(a, [b])
    probe = config.parent / "test_slow.py"
    probe.write_text("import time\ndef test_slow():\n    time.sleep(10)\n")
    path = config.parent / "claims.jsonl"
    row = json.loads(path.read_text())
    row.update(kind="behavior_test", predicate={"type":"behavior_test", "probe_path":probe.name,
        "probe_sha256":file_hash(probe), "node_id":"test_slow.py::test_slow", "environment_id":"test"})
    path.write_text(json.dumps(row) + "\n")
    claim = load_jsonl(path, Claim)[0]
    profile = EnvironmentProfile(image=os.environ["CAMI_TEST_IMAGE"], python_version="3.12.12", timeout_seconds=1)
    result = execute_probe(claim, ProbeContext(snapshot(repo, b), profile, config.parent, config.parent / "timeout"))
    assert (result.verdict, result.reason, result.test_executions) == ("insufficient_evidence", "timeout", 3)


@pytest.mark.docker
@pytest.mark.skipif(not os.environ.get("CAMI_TEST_IMAGE"), reason="set CAMI_TEST_IMAGE to prepared image digest")
def test_behavior_hidden_dependency_masks_real_contradiction(repo):
    from cami.artifacts import write_json
    from cami.evaluation import score_run
    from cami.models import Dependency, Node
    from cami.scenarios import edge_fraction, prepare_scenario
    from test_scenarios import dataset_for
    a = repo.commit({"module.py":"def f(): return g()\ndef g(): return 1\n"})
    b = repo.commit({"module.py":"def f(): return g()\ndef g(): return 2\n"})
    config = repo.config(a,[b])
    probe = config.parent / "test_dependency.py"
    probe.write_text("from module import f\ndef test_result():\n    assert f() == 1\n")
    path = config.parent / "claims.jsonl"
    claim = json.loads(path.read_text())
    claim.update(kind="behavior_test",predicate={"type":"behavior_test","probe_path":probe.name,
        "probe_sha256":file_hash(probe),"node_id":"test_dependency.py::test_result","environment_id":"test"})
    path.write_text(json.dumps(claim)+"\n")
    data = read_json(config)
    data["validation"]["execution"] = "docker"
    data["environment_profiles"] = {"test":{"image":os.environ["CAMI_TEST_IMAGE"],"python_version":"3.12.12"}}
    write_json(config,data)
    labels = config.parent / "independent_labels.jsonl"
    labels.write_text(json.dumps({"schema_version":1,"claim_id":"f","commit":b,"label":"contradicted",
        "annotator_id":"synthetic-scenario-author","evidence":["Manually authored scenario changes g return value from 1 to 2; f calls g."],
        "confirmation_type":"synthetic_manual","adjudication_status":"not_required"})+"\n")
    dataset = dataset_for(config)
    edge = Dependency(source=Node(path="module.py",qualname="f"),target=Node(path="module.py",qualname="g"),relation="calls",origin="static")
    seed = next(seed for seed in [17,42,73] if edge_fraction("fixture",edge,seed)<0.75)
    for mode, expected in [("known_missing",0.0),("hidden_missing",1.0)]:
        out = config.parent / mode
        public = prepare_scenario(dataset,mode,0.75,seed,out)
        manifest = read_json(public)
        run_experiment(public.parent / manifest["runs"][0]["config_path"],out / "run")
        report = score_run(out / "run",labels,out / "score")
        assert report.overall.metrics["stale_exposure"].value == expected
