from cami.artifacts import read_json, read_jsonl
from cami.pilot import parent_candidates, prepare_pilot


def test_independent_parent_tokenizer():
    assert parent_candidates("def good(x):\n    return x\nif True:\n    def conditional(): pass\ndef rebound(): pass\nrebound = other\nclass C:\n    def method(self): pass\n") == (("good",1),)
    assert parent_candidates("def repeated(): pass\ndef repeated(): pass\n") == ()


def test_pilot_generator_leaves_labels_pending(repo):
    a = repo.commit({"src/click/utils.py":"def stable(): return 1\n", "LICENSE.txt":"fixture license"})
    b = repo.commit({"src/click/utils.py":"def changed(): return 2\n"})
    output = repo.root.parent / "pilot"
    dataset = prepare_pilot(repo.root, output, end_ref=b, count=1, claims_per_pair=1, dataset_kind="synthetic")
    assert read_json(dataset)["dataset_kind"] == "synthetic"
    claim = read_jsonl(output / "pairs/00/claims.jsonl")[0]
    assert claim["origin_commit"] == a
    assert claim["subject"]["qualname"] == "stable"
    assert not (output / "labels.jsonl").exists()
