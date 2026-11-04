"""Authored failure/admission controls; no model, live credential or task data."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

import pytest

STAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(STAGE))
import container_session as host  # noqa: E402
import container_worker as worker  # noqa: E402
from evidence_safety import collect_private_values, scrub_state_evidence  # noqa: E402
from trial_guards import git_closure  # noqa: E402


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_redaction_preserves_diff_decorators_but_scrubs_email_addresses():
    patch = "-@pytest.fixture(params=[None])\n+@pytest.fixture(params=[1])\n"
    assert worker.redact(patch) == patch
    for address in ["person@example.invalid", "+tag.person@example.invalid"]:
        assert worker.redact(address) == "[REDACTED_EMAIL]"


@pytest.mark.parametrize("statuses,arm,error", [
    (["pending", "connected"], "cami", None),
    (["failed", "connected"], "static", RuntimeError),
    (["pending"], "cami", TimeoutError),
    (["connected"], "plain", AssertionError),
])
def test_mcp_readiness_waits_only_for_startup(tmp_path, monkeypatch, statuses, arm, error):
    monkeypatch.setattr(worker, "OUT", tmp_path)
    clock = [0.0]
    monkeypatch.setattr(worker.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    calls = []
    class StartupServer:
        def request(self, method, path, *, timeout):
            assert method == "GET" and path.startswith("/api/mcp")
            status = statuses[min(len(calls), len(statuses) - 1)]
            calls.append(status)
            return {"data": [{"name": "research_memory", "status": {"status": status}}]}
    if error:
        with pytest.raises(error):
            worker.await_mcp(StartupServer(), "?location=test", arm, timeout=0.2)
    else:
        assert worker.await_mcp(StartupServer(), "?location=test", arm)["data"][0]["status"]["status"] == "connected"
        assert calls == statuses
    if statuses[0] == "failed":
        assert calls == ["failed"]
    assert json.loads((tmp_path / "mcp-readiness.json").read_text())["observations"]


def repo(path):
    path.mkdir()
    git(path, "init", "-q")
    (path / "fixture.py").write_text("def authored(): return 7\n")
    git(path, "add", "fixture.py")
    git(path, "-c", "user.name=Authored", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "initial")
    return path


def test_git_guard_ignores_inherited_foreign_git_dir(tmp_path, monkeypatch):
    expected, foreign = repo(tmp_path / "expected"), repo(tmp_path / "foreign")
    (foreign / "extra.py").write_text("# authored future\n")
    git(foreign, "add", "extra.py")
    git(foreign, "-c", "user.name=Authored", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "future")
    monkeypatch.setenv("GIT_DIR", str(foreign / ".git"))
    assert git_closure(expected)["commits"] == 1


def test_failure_capture_keeps_latest_usage_if_messages_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "OUT", tmp_path)
    tokens = {"input": 9, "output": 2, "reasoning": 1, "cache": {"read": 5, "write": 0}}
    class FailedServer:
        def request(self, method, path, **kwargs):
            if "/message?" in path:
                raise TimeoutError("authored pagination timeout")
            return {"data": {"tokens": tokens, "cost": 0}}
    manifest = {}
    worker.capture_failure(FailedServer(), "authored-session", 1, manifest)
    assert json.loads((tmp_path / "usage.json").read_text())["session_tokens"] == tokens
    assert manifest["failure_usage_capture"].startswith("partial_or_unavailable")


def test_missing_failure_usage_is_null_not_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "OUT", tmp_path)
    class DeadServer:
        def request(self, *args, **kwargs):
            raise ConnectionError("authored server death")
    worker.capture_failure(DeadServer(), "authored-session", 1, {})
    assert json.loads((tmp_path / "usage.json").read_text())["session_tokens"] is None


def test_disjoint_token_threshold_components():
    assert worker.reported_tokens({"input": 3, "output": 5, "reasoning": 7, "cache": {"read": 11, "write": 13}}) == 39


def test_known_opaque_rotation_values_stay_only_in_memory(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    dbpath = tmp_path / "data/opencode/session.db"
    dbpath.parent.mkdir(parents=True)
    connection = sqlite3.connect(dbpath)
    connection.execute("CREATE TABLE credential(integration_id TEXT,value TEXT)")
    old, new = "AUTHORED_OPAQUE_OLD_123456789", "AUTHORED_OPAQUE_NEW_123456789"
    connection.execute("INSERT INTO credential VALUES('openai',?)", (json.dumps({"refresh": old}),))
    connection.commit()
    initial = collect_private_values(tmp_path, expect_credential=True)
    connection.execute("UPDATE credential SET value=?", (json.dumps({"refresh": new}),))
    connection.commit()
    connection.close()
    (evidence / "messages.json").write_text(json.dumps([old, new]))
    scrub_state_evidence(tmp_path, expect_credential=True, initial_private_values=initial)
    assert all(value not in (evidence / "messages.json").read_text() for value in [old, new])


def test_known_secret_artifact_name_denied(tmp_path):
    (tmp_path / "evidence").mkdir()
    fake = "AUTHORED_FILENAME_SECRET_123456789"
    (tmp_path / "evidence" / (fake + ".json")).write_text("{}")
    with pytest.raises(ValueError, match="artifact name"):
        scrub_state_evidence(tmp_path, expect_credential=False, initial_private_values={fake})


@pytest.mark.parametrize("selected", ["data/opencode/session.db", "server-private/server-password.private"])
def test_private_fifo_denied_without_open(tmp_path, selected):
    (tmp_path / "evidence").mkdir()
    target = tmp_path / selected
    target.parent.mkdir(parents=True)
    os.mkfifo(target)
    with pytest.raises(ValueError, match="regular file"):
        scrub_state_evidence(tmp_path, expect_credential=False)


def test_runtime_mismatch_prevents_any_auth_or_container(tmp_path, monkeypatch):
    with tempfile.TemporaryDirectory(prefix="admission-", dir=host.ROOT / "runs") as name:
        case = Path(name)
        workspace = repo(case / "workspace")
        memory = case / "memory"
        memory.mkdir()
        source = case / "src/cami"
        source.mkdir(parents=True)
        (source / "__init__.py").write_text("")
        adapter = case / "adapter"
        adapter.mkdir()
        (adapter / "memory_adapter.py").write_text("# authored trusted stub\n")
        frozen = case / "frozen.json"
        frozen.write_text("{}")
        calls = []
        def local_command(argv, **kwargs):
            calls.append(argv)
            assert "inspect" in argv and "image" in argv
            return {"returncode": 0, "stdout": host.IMAGE + "\n", "stderr": ""}
        monkeypatch.setattr(host, "command", local_command)
        monkeypatch.setattr(host, "credential_pipe", lambda *a: pytest.fail("credential export reached"))
        output, state = case / "output", case / "state"
        monkeypatch.setattr(sys, "argv", ["controller", "--workspace", str(workspace), "--memory-dir", str(memory), "--state-dir", str(state), "--out", str(output), "--arm", "plain", "--run-model", "--prompt-file", str(case / "NEVER_READ"), "--runtime-manifest", str(frozen), "--cami-source", str(source.parent), "--adapter-dir", str(adapter)])
        with pytest.raises(AssertionError, match="runtime identity"):
            host.main()
        assert len(calls) == 1 and not state.exists()
        assert "runtime identity" in json.loads((output / "manifest.json").read_text())["failure"]


@pytest.mark.parametrize("mode", ["worker-failed", "writers-unfrozen", "missing-evidence", "bad-json"])
def test_failed_publication_and_cleanup_are_durable(mode, monkeypatch):
    with tempfile.TemporaryDirectory(prefix="cleanup-", dir=host.ROOT / "runs") as name:
        case = Path(name)
        workspace = repo(case / "workspace")
        memory = case / "memory"
        memory.mkdir()
        source = case / "src/cami"
        source.mkdir(parents=True)
        (source / "__init__.py").write_text("")
        adapter = case / "adapter"
        adapter.mkdir()
        (adapter / "memory_adapter.py").write_text("# authored\n")
        output, state = case / "output", case / "state"
        order = []
        actual_scrub = host.scrub_state_evidence
        def checked_scrub(*args, **kwargs):
            assert "remove" in order and mode != "writers-unfrozen"
            order.append("publish")
            return actual_scrub(*args, **kwargs)
        monkeypatch.setattr(host, "scrub_state_evidence", checked_scrub)
        def local_command(argv, **kwargs):
            if "image" in argv:
                return {"returncode": 0, "stdout": host.IMAGE, "stderr": ""}
            if "run" in argv:
                return {"returncode": 0, "stdout": "a" * 64, "stderr": ""}
            if "rm" in argv:
                order.append("remove")
                return {"returncode": int(mode == "writers-unfrozen"), "stdout": "", "stderr": ""}
            if "/opt/harness/container_worker.py" in argv:
                if mode != "missing-evidence":
                    evidence = state / "evidence"
                    evidence.mkdir()
                    (evidence / "manifest.json").write_text(json.dumps({"status": "failed" if mode == "worker-failed" else "passed"}))
                    (evidence / "usage.json").write_text(json.dumps({"session_tokens": None, "status": "authored unavailable"}))
                    if mode == "bad-json":
                        (evidence / "bad.json").write_text('{"broken":"\\[INVALID]"}')
                return {"returncode": int(mode == "worker-failed"), "stdout": "", "stderr": ""}
            return {"returncode": 0, "stdout": "{}", "stderr": ""}
        monkeypatch.setattr(host, "command", local_command)
        monkeypatch.setattr(sys, "argv", ["controller", "--workspace", str(workspace), "--memory-dir", str(memory), "--state-dir", str(state), "--out", str(output), "--arm", "plain", "--no-model", "--cami-source", str(source.parent), "--adapter-dir", str(adapter)])
        with pytest.raises((AssertionError, SystemExit)):
            host.main()
        result = json.loads((output / "manifest.json").read_text())
        assert result["status"] == "failed" and result["state_removed"]
        if mode == "writers-unfrozen":
            assert result["publication_blocked"] and not (output / "evidence").exists()
        elif mode == "worker-failed":
            assert order.index("remove") < order.index("publish")
            assert json.loads((output / "evidence/usage.json").read_text())["session_tokens"] is None

        if mode == "bad-json":
            assert not (output / "evidence/bad.json").exists()
            assert json.loads((output / "evidence/usage.json").read_text())["session_tokens"] is None
            assert json.loads((output / "publication-guard.json").read_text())["status"] == "partial"
            assert not result.get("publication_blocked")
