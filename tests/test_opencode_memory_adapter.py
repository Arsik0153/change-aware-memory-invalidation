from __future__ import annotations

import json
import os
from pathlib import Path
import select
import subprocess
import sys

import pytest

STAGE = Path(__file__).resolve().parents[1] / "integrations" / "opencode"
sys.path.insert(0, str(STAGE))
from memory_backend import Backend, canonical, digest, load, prepare, rank, save  # noqa: E402
from memory_adapter import TOOL  # noqa: E402

SCRIPT = STAGE / "memory_adapter.py"
PYTHON = Path(sys.executable)
SOURCE = 'class Command:\n    def get_help_option(self, ctx):\n        """Original help option."""\n        return ctx\n'
SUBJECT = {"language": "python", "path": "api.py", "qualname": "Command.get_help_option", "node_kind": "method"}


@pytest.fixture
def workspace(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "api.py").write_text(SOURCE)
    spec = {"schema_version": 1, "source_roots": ["."], "excluded_paths": [], "records": [
        {"id": "help-note", "kind": "note", "selector": "api.py:Command.get_help_option", "subject": SUBJECT,
         "note_key": "help", "text": "ORIGIN_SENTINEL: help option is implemented here; original body return ctx."}]}
    spec_path = tmp_path / "seed.json"
    save(spec_path, spec)
    return tmp_path, repo, spec_path


def prepared(workspace, backend):
    root, repo, spec = workspace
    output = root / backend
    prepare(backend, repo, output, spec_path=spec,
            state_home=root / "cami-state" if backend == "cami" else None)
    return output


def test_static_seed_requires_no_cami_import_and_catalog_matches(workspace):
    root, repo, spec = workspace
    static = root / "static"
    snippet = (f"import sys;sys.path.insert(0,{str(STAGE)!r});"
               "from pathlib import Path;from memory_backend import prepare,Backend;"
               f"prepare('static',Path({str(repo)!r}),Path({str(static)!r}),spec_path=Path({str(spec)!r}));"
               f"Backend(Path({str(static / 'binding.json')!r})).lookup('help option');"
               "assert not any(x=='cami' or x.startswith('cami.') for x in sys.modules)")
    result = subprocess.run([str(PYTHON), "-c", snippet], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    cami = prepared(workspace, "cami")
    assert load(static / "catalog.json") == load(cami / "catalog.json")
    metrics = load(cami / "construction-metrics.json")
    assert metrics["status"] == "complete" and metrics["state_bytes"] > 0
    assert metrics["wall_seconds"] > 0 and len(metrics["registrations"]) == 1


def test_dirty_note_withheld_no_old_text_static_unchanged_and_sticky_review(workspace):
    root, repo, _ = workspace
    static = Backend(prepared(workspace, "static") / "binding.json")
    cami = Backend(prepared(workspace, "cami") / "binding.json")
    before, _ = cami.lookup("where is the command help option")
    assert before["entries"][0]["label"] == "manual_assertion"
    assert before["entries"][0]["availability"] == "manual_assertion_source_unchanged"
    assert "code" not in before
    (repo / "api.py").write_text(SOURCE.replace("return ctx", "return None"))
    current, _ = cami.lookup("help option")
    assert not current["entries"] and current["withheld"][0]["reason"] == "manual_review_required"
    assert "ORIGIN_SENTINEL" not in canonical(current).decode()
    stale, _ = static.lookup("help option")
    assert stale["entries"][0]["availability"] == "unchecked_current"
    assert "ORIGIN_SENTINEL" in stale["entries"][0]["payload"]["text"]
    (repo / "api.py").write_text(SOURCE)
    assert cami.lookup("help option")[0]["withheld"]
    assert not (repo / ".git/refs/heads/master").exists()  # No commit/HEAD-based source reader.
    assert root.joinpath("cami-state").is_dir()


def test_untracked_edit_and_excluded_policy_are_live(workspace):
    root, repo, _ = workspace
    output = prepared(workspace, "cami")
    backend = Backend(output / "binding.json")
    first, _ = backend.lookup("help")
    (repo / "new.py").write_text("def untracked(): return 1\n")
    changed, _ = backend.lookup("help")
    assert changed["snapshot_id"] != first["snapshot_id"]
    assert changed["entries"][0]["payload"] == first["entries"][0]["payload"]
    (repo / ".gitignore").write_text("api.py\n")
    ignored, _ = backend.lookup("help")
    assert not ignored["entries"] and ignored["withheld"]
    assert (root / "cami-state").is_dir()


def test_no_stale_fallback_after_refresh_failure(workspace, monkeypatch):
    from cami.errors import IncompleteError
    from cami.product.memory.adapters import HybridIndexPort
    from memory_adapter import Server
    root, repo, _ = workspace
    output = prepared(workspace, "cami")
    server = Server(output / "binding.json", root / "trace.jsonl")
    server.phase = "ready"
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "memory_lookup", "arguments": {"query": "help"}}}
    assert not server.dispatch(request)["isError"]
    def fail(*args):
        raise IncompleteError("authored refresh failure")
    monkeypatch.setattr(HybridIndexPort, "verify", fail)
    (repo / "api.py").write_text(SOURCE.replace("return ctx", "return 2"))
    result = server.dispatch(request)
    value = json.loads(result["content"][0]["text"])
    assert result["isError"] and not value["entries"]
    assert value["error"]["type"] == "IncompleteError"
    assert "ORIGIN_SENTINEL" not in result["content"][0]["text"]
    traces = [json.loads(line) for line in (root / "trace.jsonl").read_text().splitlines()]
    assert traces[-1]["error"] and traces[-1]["wall_seconds"] > 0
    assert "authored refresh failure" in traces[-1]["error"]["message"]
    assert "query" not in traces[-1]


def test_wrong_origin_tamper_and_state_isolation(workspace):
    root, repo, _ = workspace
    output = prepared(workspace, "cami")
    binding = load(output / "binding.json")
    wrong = dict(binding, state_home=str(root / "missing"))
    save(root / "bad-binding.json", wrong)
    with pytest.raises(ValueError, match="state directory"):
        Backend(root / "bad-binding.json")
    (repo / "api.py").write_text(SOURCE.replace("return ctx", "return 9"))
    with pytest.raises(ValueError, match="origin bytes differ"):
        prepare("cami", repo, root / "second", catalog_path=output / "catalog.json", state_home=root / "second-state")
    assert load(root / "second/construction-metrics.json")["status"] == "failed"
    catalog = load(output / "catalog.json")
    catalog["records"][0]["payload"]["text"] += " tamper"
    save(output / "catalog.json", catalog)
    with pytest.raises(ValueError, match="catalog hash"):
        Backend(output / "binding.json")


def test_matching_is_shared_stable_and_budget_precedes_availability(workspace):
    root, _, spec_path = workspace
    spec = load(spec_path)
    spec["records"] = [dict(spec["records"][0], id=f"note-{i:02}", note_key=f"key-{i}",
                            text="help option " + "x" * 6000) for i in range(6)]
    save(spec_path, spec)
    static = prepared(workspace, "static")
    catalog = load(static / "catalog.json")
    selected, total = rank(catalog, "where help option lives", 5)
    assert total == 6 and [r["id"] for r in selected] == ["note-00", "note-01"]
    assert sum(len(canonical(r)) for r in selected) <= 16384
    with pytest.raises(ValueError):
        rank(catalog, "help", True)
    with pytest.raises(ValueError):
        rank(catalog, "...", 5)
    assert root.is_dir()


class Client:
    def __init__(self, output, trace):
        self.process = subprocess.Popen([str(PYTHON), str(SCRIPT), "serve", "--binding", str(output / "binding.json"),
                                         "--trace", str(trace)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})

    def send(self, value, response=True):
        raw = value if isinstance(value, bytes) else canonical(value) + b"\n"
        self.process.stdin.write(raw)
        self.process.stdin.flush()
        if response:
            readable, _, _ = select.select([self.process.stdout], [], [], 30)
            assert readable, "MCP response timed out"
            return json.loads(self.process.stdout.readline())

    def close(self):
        self.process.stdin.close()
        assert self.process.wait(timeout=30) == 0, self.process.stderr.read().decode()
        assert self.process.stdout.read() == b""


def initialize(client):
    result = client.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "authored-test", "version": "1"}}})
    assert result["result"]["protocolVersion"] == "2025-06-18"
    client.send({"jsonrpc": "2.0", "method": "notifications/initialized"}, response=False)


@pytest.mark.parametrize("backend", ["static", "cami"])
def test_transport_lifecycle_same_tool_and_jsonrpc_only(workspace, backend):
    root, _, _ = workspace
    output = prepared(workspace, backend)
    client = Client(output, root / "transport-trace.jsonl")
    assert client.send(b"{invalid}\n")["error"]["code"] == -32700
    assert client.send({"jsonrpc": "2.0", "id": 0, "method": "tools/list"})["error"]["code"] == -32600
    initialize(client)
    assert client.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"] == [TOOL]
    result = client.send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "memory_lookup", "arguments": {"query": "help option"}}})["result"]
    assert not result["isError"] and json.loads(result["content"][0]["text"])["entries"]
    assert client.send({"jsonrpc": "2.0", "id": 4, "method": "ping"})["result"] == {}
    assert client.send({"jsonrpc": "2.0", "id": 5, "method": "no-such-method"})["error"]["code"] == -32601
    client.close()


def test_catalog_static_arm_no_index_or_state_created(workspace):
    root, _, _ = workspace
    output = prepared(workspace, "static")
    result, _ = Backend(output / "binding.json").lookup("api.py:Command.get_help_option")
    assert result["selected_records"] == 1 and not (root / "cami-state").exists()
    assert load(output / "construction-metrics.json")["state_bytes"] == 0
    assert digest(load(output / "catalog.json")) == result["catalog_sha256"]


def test_optional_typed_facts_body_carry_signature_mismatch_absence(workspace):
    _, repo, spec_path = workspace
    spec = load(spec_path)
    base = spec["records"][0]
    spec["records"] = [{key: value for key, value in dict(base, id=kind, kind=kind).items()
                        if key not in ("note_key", "text")} for kind in ("symbol_exists", "signature_equals")]
    save(spec_path, spec)
    backend = Backend(prepared(workspace, "cami") / "binding.json")
    initial, _ = backend.lookup("get help option")
    assert len(initial["entries"]) == 2 and not initial["withheld"]
    (repo / "api.py").write_text(SOURCE.replace("return ctx", "return None"))
    body, _ = backend.lookup("get help option")
    assert all(e["availability"] == "supported" and e["state_type"] == "carried" for e in body["entries"])
    (repo / "api.py").write_text(SOURCE.replace("self, ctx", "self, ctx, enabled=True"))
    changed, _ = backend.lookup("get help option")
    assert [e["id"] for e in changed["entries"]] == ["symbol_exists"]
    assert changed["withheld"][0]["reason"] == "signature_mismatch"
    (repo / "api.py").unlink()
    absent, _ = backend.lookup("get help option")
    assert not absent["entries"] and {e["reason"] for e in absent["withheld"]} == {"subject_absent"}


def test_two_worktrees_same_catalog_separate_states(workspace):
    root, repo, _ = workspace
    first_out = prepared(workspace, "cami")
    other_repo = root / "other-repo"
    other_repo.mkdir()
    subprocess.run(["git", "init", "-q", str(other_repo)], check=True)
    (other_repo / "api.py").write_text(SOURCE)
    prepare("cami", other_repo, root / "other-prepared", catalog_path=first_out / "catalog.json", state_home=root / "other-state")
    first = Backend(first_out / "binding.json")
    second = Backend(root / "other-prepared/binding.json")
    first_before, _ = first.lookup("help")
    second_before, _ = second.lookup("help")
    assert first_before["entries"][0]["payload"] == second_before["entries"][0]["payload"]
    assert first.binding["mapping"] != second.binding["mapping"]
    (repo / "api.py").unlink()
    assert first.lookup("help")[0]["withheld"]
    assert second.lookup("help")[0]["entries"]
    assert (other_repo / "api.py").read_text() == SOURCE


def test_protocol_fallback_bad_arguments_and_large_message(workspace):
    root, _, _ = workspace
    client = Client(prepared(workspace, "static"), root / "edge-trace.jsonl")
    result = client.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}})
    assert result["result"]["protocolVersion"] == "2025-06-18"
    client.send({"jsonrpc": "2.0", "method": "notifications/initialized"}, response=False)
    result = client.send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "memory_lookup", "arguments": {"query": "help", "limit": True}}})
    assert result["result"]["isError"]
    assert client.send(b"x" * (1024 * 1024 + 1) + b"\n")["error"]["code"] == -32700
    assert client.send({"jsonrpc": "2.0", "id": 3, "method": "ping"})["result"] == {}
    client.close()


def test_oversized_seed_rejected_before_any_symbol_capture():
    from memory_backend import freeze_spec
    class Forbidden:
        def context(self, query):
            raise AssertionError("must not capture oversized seed")
    with pytest.raises(ValueError, match="invalid seed spec"):
        freeze_spec(Forbidden(), {"schema_version": 1, "source_roots": ["."], "excluded_paths": [],
                                 "records": [{}] * 1025})


def test_global_note_key_collision_rejected_before_capture(workspace):
    from memory_backend import freeze_spec, validate_catalog
    root, repo, spec_path = workspace
    spec = load(spec_path)
    other = dict(spec["records"][0], id="other-note", selector="api.py:Other.method",
                 subject={**SUBJECT, "qualname": "Other.method"})
    spec["records"].append(other)
    class Forbidden:
        def context(self, query):
            raise AssertionError("must reject all duplicate global note keys before capture")
    with pytest.raises(ValueError, match="duplicate global note_key"):
        freeze_spec(Forbidden(), spec)
    save(spec_path, spec)
    with pytest.raises(ValueError, match="duplicate global note_key"):
        prepare("cami", repo, root / "collision", spec_path=spec_path, state_home=root / "collision-state")
    assert not (root / "collision-state").exists()
    spec["records"] = spec["records"][:1]
    save(spec_path, spec)
    catalog = load(prepared(workspace, "static") / "catalog.json")
    record = catalog["records"][0]
    changed_subject = {**record["payload"]["subject"], "qualname": "Other.method"}
    catalog["records"].append({**record, "id": "other-note", "payload": {**record["payload"], "subject": changed_subject}})
    with pytest.raises(ValueError, match="duplicate semantic record identity"):
        validate_catalog(catalog)


def test_distinct_global_keys_on_different_subjects_prepare(workspace):
    _, repo, spec_path = workspace
    (repo / "api.py").write_text(SOURCE + "\ndef other(): return None\n")
    spec = load(spec_path)
    spec["records"].append({**spec["records"][0], "id": "other-note", "selector": "api.py:other",
                            "note_key": "source-excerpt:other", "subject": {**SUBJECT, "qualname": "other", "node_kind": "function"}})
    save(spec_path, spec)
    static = prepared(workspace, "static")
    cami = prepared(workspace, "cami")
    assert load(static / "catalog.json") == load(cami / "catalog.json")
    assert len(Backend(cami / "binding.json").lookup("ORIGIN_SENTINEL")[0]["entries"]) == 2
