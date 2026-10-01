import json

from cami.artifacts import read_json, read_jsonl, write_json
from cami.cli import main
from cami.engine import run_experiment
from cami.models import Dependency, Node
from cami.scenarios import edge_fraction


def dataset_for(config):
    data = read_json(config)
    dataset = config.parent / "dataset.json"
    write_json(dataset, {"schema_version": 1, "dataset_id": "fixture", "protocol_version": "1.0",
        "dataset_kind": "synthetic", "repositories": [{"repo_id":"fixture", "url":"synthetic://fixture",
        "path":data["repo"]["path"], "source_roots":["."], "environment_restoration":"none required"}],
        "runs":[{"run_id":"pair", "config_path":config.name,"split":"development", "cluster_id":"episode"}]})
    return dataset


def test_hidden_mask_and_zero_drop(repo):
    a = repo.commit({"module.py":"def f(): return g()\ndef g(): return 1\n"})
    b = repo.commit({"module.py":"def f(): return g()\ndef g(): return 2\n"})
    config = repo.config(a, [b])
    dataset = dataset_for(config)
    edge = Dependency(source=Node(path="module.py",qualname="f"), target=Node(path="module.py",qualname="g"), relation="calls", origin="static")
    seed = next(s for s in [17,42,73] if edge_fraction("fixture", edge, s) < 0.75)
    results = {}
    for mode, drop in [("hidden_missing",0.0),("hidden_missing",0.75),("known_missing",0.75)]:
        out = config.parent / f"{mode}-{drop}"
        assert main(["prepare-scenario","--dataset",str(dataset),"--mode",mode,"--drop",str(drop),"--seed",str(seed),"--out",str(out)]) == 0
        public = read_json(out / "public" / "dataset.json")
        path = out / "public" / public["runs"][0]["config_path"]
        run = out / "run"
        run_experiment(path, run)
        results[(mode,drop)] = read_jsonl(run / "selections.jsonl")[0]
        if drop:
            graph = read_json(path.parent / "graphs" / f"{b}.json")
            assert not graph["edges"]
            assert bool(graph["known_incomplete_nodes"]) == (mode == "known_missing")
        assert json.loads((path.parent / "claims.jsonl").read_text()) == json.loads((config.parent / "claims.jsonl").read_text())
    assert results[("hidden_missing",0.0)]["selected"]
    assert not results[("hidden_missing",0.75)]["selected"]
    assert results[("known_missing",0.75)]["selected"]
