import json

import pytest

from cami.artifacts import read_json, read_jsonl
from cami.demo import POLICIES, create_fixture
from cami.engine import run_experiment
from cami.errors import InputError


def test_policies_replay_and_cache(tmp_path):
    config = create_fixture(tmp_path / "fixture")
    outputs = {}
    for policy in POLICIES:
        output = tmp_path / policy
        run_experiment(config.parent / f"{policy}.json", output)
        outputs[policy] = read_jsonl(output / "states.jsonl")
    for policy in ("all_validate", "file_validate", "symbol_validate"):
        states = outputs[policy]
        removed = [s for s in states if s["claim_id"] == "removed-exists"]
        assert [s["state"] for s in removed] == ["valid", "retired", "valid"]
        signature = [s for s in states if s["claim_id"] == "add-signature"]
        assert [s["state"] for s in signature] == ["valid", "stale", "valid"]
    assert all(s["available"] for s in outputs["keep_all"])
    assert all(not s["available"] for s in outputs["clear_all"])
    assert all(s["state"] == "valid" for s in outputs["clear_all"])
    assert all(not s["available"] for s in outputs["file_invalidate"])
    stable = [s for s in outputs["symbol_validate"] if s["claim_id"] == "stable-exists"]
    assert all(s["basis"] == "carried_forward" for s in stable)
    assert len({s["last_checked_commit"] for s in stable}) == 1
    for policy in ("keep_all", "clear_all"):
        assert all(c["index_seconds"] == 0 for c in read_jsonl(tmp_path / policy / "costs.jsonl"))
    with pytest.raises(InputError):
        run_experiment(config, tmp_path / "keep_all")
    data = read_json(config)
    data["cache_dir"] = "cache"
    data["policy"]["id"] = "all_validate"
    config.write_text(json.dumps(data))
    run_experiment(config, tmp_path / "cold")
    run_experiment(config, tmp_path / "warm")
    cold, warm = (read_jsonl(tmp_path / p / "costs.jsonl")[1:] for p in ("cold", "warm"))
    assert sum(c["actual_validations"] for c in cold) == 15
    assert sum(c["actual_validations"] for c in warm) == 0
    assert sum(c["logical_validations"] for c in warm) == 15
    assert sum(c["reconstructed_validation_seconds"] for c in warm) > 0


def test_labels_do_not_affect_run(tmp_path):
    config = create_fixture(tmp_path / "fixture")
    run_experiment(config, tmp_path / "first")
    (config.parent / "labels.jsonl").unlink()
    run_experiment(config, tmp_path / "second")
    for artifact in ("claims", "provenance", "states", "selections"):
        assert read_jsonl(tmp_path / "first" / f"{artifact}.jsonl") == read_jsonl(tmp_path / "second" / f"{artifact}.jsonl")


def test_uncertainty_rechecked(repo):
    a = repo.commit({"module.py": "def f(): pass\n"})
    b = repo.commit({"module.py": "def f(\n"})
    c = repo.commit({})
    config = repo.config(a, [b, c])
    out = config.parent / "out"
    run_experiment(config, out)
    states = read_jsonl(out / "states.jsonl")
    assert all(s["state"] == "needs_validation" and not s["available"] for s in states)
    assert len(read_jsonl(out / "validations.jsonl")) == 2


def test_depth_and_independent_change(repo):
    a = repo.commit({"module.py": "def f(): return g()\ndef g(): return 1\ndef independent(): return 1\n"})
    b = repo.commit({"module.py": "def f(): return g()\ndef g(): return 2\ndef independent(): return 1\n"})
    config = repo.config(a, [b])
    data = read_json(config)
    for depth, expected in [(0, 0), (1, 1), (2, 1)]:
        data["policy"]["dependency_depth"] = depth
        config.write_text(json.dumps(data))
        out = config.parent / f"depth{depth}"
        run_experiment(config, out)
        assert len(read_jsonl(out / "validations.jsonl")) == expected
    c = repo.commit({"module.py": "def f(): return g()\ndef g(): return 2\ndef independent(): return 3\n"})
    config = repo.config(b, [c])
    out = config.parent / "independent"
    run_experiment(config, out)
    assert not read_jsonl(out / "validations.jsonl")


def test_exact_subject_selected_even_with_other_anchor(repo):
    a = repo.commit({"module.py": "def f(): pass\ndef g(): pass\n"})
    b = repo.commit({"module.py": "def g(): pass\n"})
    config = repo.config(a, [b])
    path = config.parent / "provenance.jsonl"
    row = json.loads(path.read_text())
    row["anchors"][0]["qualname"] = "g"
    path.write_text(json.dumps(row) + "\n")
    out = config.parent / "out"
    run_experiment(config, out)
    assert read_jsonl(out / "states.jsonl")[0]["state"] == "retired"


def test_import_rebinding_selects_unchanged_caller(repo):
    a = repo.commit({"module.py":"from a import g\ndef f(): return g()\n", "a.py":"def g(): return 1\n", "b.py":"def g(): return 2\n"})
    b = repo.commit({"module.py":"from b import g\ndef f(): return g()\n"})
    config = repo.config(a,[b])
    out = config.parent / "out"
    run_experiment(config,out)
    assert read_jsonl(out / "selections.jsonl")[0]["selected"]


@pytest.mark.parametrize('cross_module', [False, True])
def test_file_policy_conservatively_checks_unresolved_transitive_support(repo, cross_module):
    files = {"module.py": "def f(): return g()\ndef g(): return missing()\n"}
    if cross_module:
        files = {"module.py": "from dependency import g\ndef f(): return g()\n",
                 "dependency.py": "def g(): return missing()\n"}
    parent = repo.commit(files)
    child = repo.commit({})
    config = repo.config(parent, [child], policy="file_validate")
    out = config.parent / "out"
    run_experiment(config, out)
    selection = read_jsonl(out / "selections.jsonl")[0]
    assert selection["selected"]
    assert "graph_free_unresolved_fallback" in selection["reasons"]
    assert len(read_jsonl(out / "validations.jsonl")) == 1
