"""Independent authored controls for harness publication/metadata guards only."""
import base64
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

SOURCE = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE))


def module(name):
    spec = importlib.util.spec_from_file_location(name, SOURCE / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.mark.parametrize("kind", ["root-link", "leaf-link", "hardlink", "binary"])
def test_publication_rejects_nonordinary_or_private_artifact(tmp_path, kind):
    helper = module("evidence_safety")
    state = tmp_path / "state"
    state.mkdir()
    private = tmp_path / "authored-private"
    private.mkdir()
    target = private / "dummy.json"
    target.write_text('{"authored":"PRIVATE_SENTINEL_NOT_A_CREDENTIAL"}')
    evidence = state / "evidence"
    if kind == "root-link":
        evidence.symlink_to(private, target_is_directory=True)
    else:
        evidence.mkdir()
        if kind == "leaf-link":
            (evidence / "leak.json").symlink_to(target)
        elif kind == "hardlink":
            (evidence / "leak.json").hardlink_to(target)
        else:
            (evidence / "private.sqlite3").write_bytes(b"AUTHORED_NOT_A_REAL_DATABASE")
    with pytest.raises(ValueError):
        helper.scrub_state_evidence(state, expect_credential=False)


def test_publication_scrubs_authorized_fake_credentials_and_private_password(tmp_path):
    helper = module("evidence_safety")
    state = tmp_path / "state"
    evidence = state / "evidence"
    evidence.mkdir(parents=True)
    dbpath = state / "data/opencode/session.db"
    dbpath.parent.mkdir(parents=True)
    connection = sqlite3.connect(dbpath)
    connection.execute("CREATE TABLE credential(integration_id TEXT,value TEXT)")
    fake_oauth = "AUTHORED_DUMMY_OAUTH_VALUE_1234567890"
    connection.execute("INSERT INTO credential VALUES(?,?)", ("openai", json.dumps({"access_token": fake_oauth})))
    connection.commit()
    connection.close()
    password = "AUTHORED_DUMMY_SERVER_PASSWORD_1234567890"
    private = state / "server-private"
    private.mkdir()
    (private / "server-password.private").write_text(password)
    encoded = base64.b64encode(("opencode:" + password).encode()).decode()
    (evidence / "messages.json").write_text(json.dumps({"tool_output": fake_oauth + " " + password + " " + encoded}))
    result = helper.scrub_state_evidence(state, expect_credential=True)
    text = (evidence / "messages.json").read_text()
    assert result["status"] == "passed"
    assert all(value not in text for value in (fake_oauth, password, encoded))
    assert json.loads(text)


def test_missing_private_credential_blocks_real_model_publication(tmp_path):
    helper = module("evidence_safety")
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence/messages.json").write_text("[]")
    with pytest.raises(ValueError, match="credential"):
        helper.scrub_state_evidence(tmp_path, expect_credential=True)


def git(repo, *args, data=None):
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "protocol.allow=never", "-C", str(repo), *args],
                          input=data, capture_output=True, check=True).stdout


@pytest.mark.parametrize("extra", ["none", "future-commit", "unreachable-object"])
def test_fresh_git_closure_rejects_future_history_or_unreachable_objects(tmp_path, extra):
    guard = module("trial_guards")
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "source.py").write_text("# AUTHORED_CANONICAL_SOURCE\n")
    git(repo, "add", "source.py")
    git(repo, "-c", "user.name=Authored", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "canonical")
    if extra == "none":
        assert guard.git_closure(repo)["commits"] == 1
    else:
        if extra == "future-commit":
            (repo / "source.py").write_text("# AUTHORED_FUTURE_SENTINEL\n")
            git(repo, "add", "source.py")
            git(repo, "-c", "user.name=Authored", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "future")
        else:
            git(repo, "hash-object", "-w", "--stdin", data=b"AUTHORED_UNREACHABLE_SENTINEL")
        with pytest.raises(ValueError):
            guard.git_closure(repo)


def test_arm_configuration_diff_is_only_memory_mcp():
    controller = module("container_session")
    plain = controller.configuration("plain", None)
    static = controller.configuration("static", "prepared/binding.json")
    cami = controller.configuration("cami", "prepared/binding.json")
    assert static == cami
    assert {k: v for k, v in static.items() if k != "mcp"} == plain
    environment = cami["mcp"]["servers"]["research_memory"]["environment"]
    assert "/workspace" not in environment["PYTHONPATH"]
