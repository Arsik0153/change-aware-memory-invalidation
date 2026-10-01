import json
import subprocess
import sys
from pathlib import Path

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
