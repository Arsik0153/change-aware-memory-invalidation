"""Opt-in identifier ranking preserves source budgets and CAMI withholding."""
from pathlib import Path
import json
import os
import subprocess
import sys

import pytest

STAGE = Path(__file__).resolve().parents[1] / "integrations/opencode"
sys.path.insert(0, str(STAGE))
from memory_backend import (  # noqa: E402
    Backend, IDENTIFIER_RANKING, LEXICAL_RANKING, canonical, load, prepare, rank, save,
)
from seed_source_literals_v2 import build  # noqa: E402


def record(identity, name, text=""):
    return {"id": identity, "payload": {"type": "note", "text": text,
            "subject": {"qualname": name, "path": "src/pkg/api.py"}}}


def test_compound_query_promotes_explicit_identifier_over_shared_words():
    target = record("target", "load_value")
    noise = record("noise", "Cache.reader", "please load value source cache reader helper docs")
    catalog = {"records": [noise, target]}
    query = "please load_value source cache reader helper docs"
    legacy, _ = rank(catalog, query, 1)
    selected, _ = rank(catalog, query, 1, ranking_policy=IDENTIFIER_RANKING)
    assert legacy == [noise] and selected == [target]
    assert rank(catalog, query, 1) == rank(catalog, query, 1, ranking_policy=LEXICAL_RANKING)


def test_qualified_reference_beats_other_classes_with_same_method_name():
    catalog = {"records": [record("a", "Other.load_value", "special request"),
                            record("b", "Owner.load_value")]}
    selected, _ = rank(catalog, "special request package.Owner.load_value", 1,
                       ranking_policy=IDENTIFIER_RANKING)
    assert selected[0]["id"] == "b"


@pytest.mark.parametrize("query", ["load_value_extra source", "reload_value source", "read value source"])
def test_partial_names_and_prose_preserve_lexical_order(query):
    catalog = {"records": [record("a", "load_value"), record("b", "read_value", "source")]}
    assert rank(catalog, query, 2, ranking_policy=IDENTIFIER_RANKING) == rank(catalog, query, 2)


def test_class_mention_requires_written_capitalization_in_compound_query():
    catalog = {"records": [record("a", "resolve_value", "the value option source"), record("b", "Option")]}
    assert rank(catalog, "the value option source", 1, ranking_policy=IDENTIFIER_RANKING)[0][0]["id"] == "a"
    assert rank(catalog, "the value Option source", 1, ranking_policy=IDENTIFIER_RANKING)[0][0]["id"] == "b"


def test_exact_query_ties_and_origin_byte_ceiling_are_unchanged():
    catalog = {"records": [record("b", "Thing.load_value", "x" * 17000), record("a", "load_value")]}
    assert rank(catalog, "load_value", 1, ranking_policy=IDENTIFIER_RANKING)[0][0]["id"] == "a"
    assert rank(catalog, "Thing.load_value", 1, ranking_policy=IDENTIFIER_RANKING)[0] == []
    for policy in (LEXICAL_RANKING, IDENTIFIER_RANKING):
        with pytest.raises(ValueError):
            rank(catalog, "load_value", True, ranking_policy=policy)
    with pytest.raises(ValueError, match="ranking policy"):
        rank(catalog, "load_value", 1, ranking_policy="future")


@pytest.fixture
def bindings(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src/pkg").mkdir(parents=True)
    source = repo / "src/pkg/api.py"
    source.write_text('def load_value():\n    return 1\n\ndef reader():\n    """load value source cache reader helper docs"""\n    return 2\n')
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "src"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Authored",
                    "-c", "user.email=fixture@example.invalid", "commit", "-qm", "origin"], check=True)
    seed, _ = build(repo, ["src/pkg"])
    spec = tmp_path / "seed.json"
    save(spec, seed)
    outputs = {}
    for arm in ("static", "cami"):
        out = tmp_path / arm
        prepare(arm, repo, out, spec_path=spec,
                state_home=tmp_path / "state" if arm == "cami" else None)
        outputs[arm] = out
    return source, outputs


def test_real_backends_share_ranking_and_withhold_without_backfill(bindings):
    source, outputs = bindings
    backends = {arm: Backend(out / "binding.json", ranking_policy=IDENTIFIER_RANKING)
                for arm, out in outputs.items()}
    query = "load_value source cache reader helper docs"
    for backend in backends.values():
        result, detail = backend.lookup(query, 1)
        assert result["entries"][0]["payload"]["subject"]["qualname"] == "load_value"
        assert detail["ranking_policy"] == IDENTIFIER_RANKING
        assert result["selection_budget"]["ranking_before_availability"]
    source.write_text(source.read_text().replace("return 1", "return 9"))
    current, _ = backends["cami"].lookup(query, 1)
    static, _ = backends["static"].lookup(query, 1)
    assert current["entries"] == [] and len(current["withheld"]) == 1
    assert current["withheld"][0]["subject"]["qualname"] == "load_value"
    assert static["entries"][0]["availability"] == "unchecked_current"


@pytest.mark.parametrize("arm", ["static", "cami"])
def test_real_stdio_records_opt_in_policy_without_changing_response_contract(bindings, tmp_path, arm):
    _, outputs = bindings
    trace = tmp_path / (arm + "-trace.jsonl")
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "clientInfo": {}, "capabilities": {}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "memory_lookup", "arguments": {"query": "load_value source cache reader helper docs", "limit": 1}}},
    ]
    result = subprocess.run([sys.executable, str(STAGE / "memory_adapter.py"), "serve",
        "--binding", str(outputs[arm] / "binding.json"), "--trace", str(trace),
        "--ranking-policy", IDENTIFIER_RANKING], input=b"".join(canonical(r) + b"\n" for r in requests),
        capture_output=True, timeout=30, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode == 0, result.stderr.decode()
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    body = json.loads(responses[-1]["result"]["content"][0]["text"])
    assert body["entries"][0]["payload"]["subject"]["qualname"] == "load_value"
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    assert all(e["ranking_policy"] == IDENTIFIER_RANKING for e in events)
    assert load(outputs[arm] / "binding.json")["catalog_sha256"] == body["catalog_sha256"]


def test_failed_opt_in_lookup_keeps_policy_identity_and_no_historical_result(bindings, tmp_path, monkeypatch):
    from memory_adapter import Server
    _, outputs = bindings
    trace = tmp_path / "failed.jsonl"
    server = Server(outputs["static"] / "binding.json", trace, ranking_policy=IDENTIFIER_RANKING)
    server.phase = "ready"
    def failed(*args):
        raise OSError("authored read failure")
    monkeypatch.setattr(server.backend, "lookup", failed)
    result = server.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "memory_lookup", "arguments": {"query": "load_value"}}})
    body = json.loads(result["content"][0]["text"])
    assert result["isError"] and body["entries"] == body["withheld"] == []
    assert body["freshness"] == "unavailable; no historical result substituted"
    assert json.loads(trace.read_text().splitlines()[-1])["ranking_policy"] == IDENTIFIER_RANKING
