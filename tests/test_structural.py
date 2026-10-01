from cami.artifacts import load_jsonl
from cami.index import build_index
from cami.models import Claim, Provenance
from cami.validation import ValidationContext, validate_claim
from test_index import snapshot


def test_structural_outcomes(repo):
    parent = repo.commit({"module.py": "def f(x): return x\n"})
    states = [
        ("def f(x, y=1): return x\n", "supported", "predicate_matches"),
        ("def renamed(x): return x\n", "contradicted", "subject_absent"),
        ("def f(\n", "insufficient_evidence", "parse_error"),
        ("def f(): pass\ndef f(): pass\n", "insufficient_evidence", "ambiguous_subject"),
        ("f = factory()\n", "insufficient_evidence", "ambiguous_subject"),
    ]
    for source, expected, reason in states:
        child = repo.commit({"module.py": source})
        path = repo.config(parent, [child])
        claim = load_jsonl(path.parent / "claims.jsonl", Claim)[0]
        provenance = load_jsonl(path.parent / "provenance.jsonl", Provenance)[0]
        snap = snapshot(repo, child)
        result = validate_claim(claim, ValidationContext(snap, build_index(snap), provenance, path.parent, path.parent))
        assert (result.verdict, result.reason) == (expected, reason)
