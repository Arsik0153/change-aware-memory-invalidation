import json
import subprocess
import sys
from pathlib import Path

import pytest

from cami.cli import main


def test_cli_checks_real_git(repo):
    parent = repo.commit({"module.py": "def f(): return 1\n"})
    child = repo.commit({"module.py": "def f(): return 2\n"})
    config = repo.config(parent, [child])
    assert main(["check-inputs", "--config", str(config)]) == 0
    result = subprocess.run([str(Path(sys.executable).parent / "cami"), "check-inputs", "--config", str(config)], capture_output=True)
    assert result.returncode == 0
    data = json.loads(config.read_text())
    data["labels"] = "forbidden.jsonl"
    config.write_text(json.dumps(data))
    assert main(["check-inputs", "--config", str(config)]) == 2


def test_reject_nonlinear_and_duplicate(repo):
    a = repo.commit({"module.py": "def f(): pass\n"})
    b = repo.commit({})
    c = repo.commit({})
    config = repo.config(a, [c])
    assert main(["check-inputs", "--config", str(config)]) == 2
    config = repo.config(a, [b, c])
    claims = config.parent / "claims.jsonl"
    claims.write_text(claims.read_text() * 2)
    assert main(["check-inputs", "--config", str(config)]) == 2


def test_receipt_symlink_escape(repo, tmp_path):
    a = repo.commit({"module.py": "def f(): pass\n"})
    b = repo.commit({})
    config = repo.config(a, [b])
    evidence = config.parent / "parent-evidence.txt"
    contents = evidence.read_bytes()
    evidence.unlink()
    external = tmp_path.parent / (tmp_path.name + "-external")
    external.write_bytes(contents)
    evidence.symlink_to(external)
    assert main(["check-inputs", "--config", str(config)]) == 2


def test_missing_anchor_rejected(repo):
    a = repo.commit({"module.py":"def f(): pass\n"})
    b = repo.commit({})
    config = repo.config(a,[b])
    path = config.parent / "provenance.jsonl"
    data = json.loads(path.read_text())
    data["anchors"][0]["path"] = "absent.py"
    path.write_text(json.dumps(data)+"\n")
    assert main(["check-inputs","--config",str(config)]) == 2


def test_merge_rejected(repo):
    a = repo.commit({"module.py":"def f(): pass\n"})
    branch = repo.git("branch","--show-current")
    repo.git("checkout","-qb","side")
    repo.commit({"side.txt":"side"})
    repo.git("checkout",branch)
    b = repo.commit({"main.txt":"main"})
    repo.git("merge","--no-ff","-m","merge","side")
    c = repo.git("rev-parse","HEAD")
    config = repo.config(b,[c])
    assert a != b
    assert main(["check-inputs","--config",str(config)]) == 2


def test_real_input_rejects_synthetic_parent_confirmation(repo):
    """Synthetic fixture exercising a real-mode boundary; no real cohort is executed."""
    parent = repo.commit({'module.py': 'def f(): return 1\n'})
    child = repo.commit({'module.py': 'def f(): return 2\n'})
    config = repo.config(parent, [child])
    data = json.loads(config.read_text())
    data['dataset_kind'] = 'real'
    config.write_text(json.dumps(data))
    assert main(['check-inputs', '--config', str(config)]) == 2


@pytest.mark.parametrize('method,accepted', [
    ('human_review', True), ('independent_oracle', True), ('independent_test', True),
    ('independent_tokenizer_parent_oracle', True), ('synthetic_manual', False),
    ('production_validator', False), ('unknown_method', False),
])
def test_real_structural_parent_confirmation_methods(repo, method, accepted):
    parent = repo.commit({'module.py': 'def f(): return 1\n'})
    child = repo.commit({})
    config = repo.config(parent, [child])
    data = json.loads(config.read_text())
    data['dataset_kind'] = 'real'
    config.write_text(json.dumps(data))
    receipts = config.parent / 'parent_receipts.jsonl'
    row = json.loads(receipts.read_text())
    row['confirmation_type'] = method
    receipts.write_text(json.dumps(row) + '\n')
    assert main(['check-inputs', '--config', str(config)]) == (0 if accepted else 2)


@pytest.mark.parametrize('method,accepted', [('human_review', False), ('independent_oracle', False),
                                            ('independent_test', True), ('synthetic_manual', False)])
def test_real_behavior_receipts_require_independent_test_even_in_preview(repo, method, accepted):
    import hashlib
    parent = repo.commit({'module.py': 'def f(): return 1\n'})
    child = repo.commit({})
    probe = repo.root.parent / 'frozen_probe.py'
    probe.write_text('def test_f():\n    assert True\n')
    claim = {'schema_version': 1, 'claim_id': 'behavior', 'repo_id': 'fixture', 'origin_commit': parent,
             'kind': 'behavior_test', 'text': 'Synthetic boundary fixture, not real evidence.',
             'scope': 'Finite frozen fixture probe.',
             'subject': {'path': 'module.py', 'qualname': 'f', 'node_kind': 'function'},
             'predicate': {'type': 'behavior_test', 'probe_path': probe.name,
                           'probe_sha256': hashlib.sha256(probe.read_bytes()).hexdigest(),
                           'node_id': probe.name + '::test_f', 'environment_id': 'fixture'}}
    config = repo.config(parent, [child], claims=[claim])
    data = json.loads(config.read_text())
    data.update(dataset_kind='real', preview=True)
    config.write_text(json.dumps(data))
    path = config.parent / 'parent_receipts.jsonl'
    receipt = json.loads(path.read_text())
    receipt['confirmation_type'] = method
    path.write_text(json.dumps(receipt) + '\n')
    assert main(['check-inputs', '--config', str(config)]) == (0 if accepted else 2)


@pytest.mark.parametrize('kind,method,accepted', [
    ('prose', 'human_review', True), ('prose', 'independent_oracle', False),
    ('signature_equals', 'independent_tokenizer_parent_oracle', False),
    ('signature_equals', 'independent_oracle', True),
])
def test_real_parent_method_scope_matches_claim_kind(repo, kind, method, accepted):
    parent = repo.commit({'module.py': 'def f(): return 1\n'})
    child = repo.commit({})
    config = repo.config(parent, [child])
    data = json.loads(config.read_text())
    data['dataset_kind'] = 'real'
    config.write_text(json.dumps(data))
    path = config.parent / 'claims.jsonl'
    claim = json.loads(path.read_text())
    claim['kind'] = kind
    claim['predicate'] = ({'type': 'prose'} if kind == 'prose' else
                          {'type': 'signature_equals', 'expected_signature': {'parameters': []}})
    path.write_text(json.dumps(claim) + '\n')
    path = config.parent / 'parent_receipts.jsonl'
    receipt = json.loads(path.read_text())
    receipt['confirmation_type'] = method
    path.write_text(json.dumps(receipt) + '\n')
    assert main(['check-inputs', '--config', str(config)]) == (0 if accepted else 2)
