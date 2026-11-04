import json

import pytest

from scripts.analyze_opencode_staleness import analyze, canonical, sha


@pytest.fixture
def sample(tmp_path):
    origin, current = tmp_path / "origin", tmp_path / "current"
    origin.mkdir()
    current.mkdir()
    source = "def api():\n    return 7\n"
    for root in [origin, current]:
        (root / "api.py").write_text(source)
    ref = {"path": "api.py", "sha256": sha(source.encode()), "size": len(source)}
    record = {"id": "note", "payload": {"type": "note", "subject": {"path": "api.py", "qualname": "api"},
                                         "text": "Historical source:\n" + source}, "source": ref}
    catalog = {"records": [record]}
    payload = {"catalog_sha256": sha(canonical(catalog)), "entries": [{"id": "note", "payload": record["payload"], "origin_source": ref}], "withheld": []}
    call = {"type": "tool_use", "part": {"id": "call1", "tool": "research_memory_memory_lookup",
                                           "state": {"status": "completed", "time": {"start": 10, "end": 20}, "output": json.dumps(payload)}}}
    return origin, current, catalog, call


def test_changed_file_is_distinct_from_changed_excerpt(sample):
    origin, current, catalog, call = sample
    (current / "api.py").write_text("# New unrelated comment\ndef api():\n    return 7\n")
    result = analyze([call], catalog, origin, current)
    assert result["counts"]["source_file_changed"] == 1
    assert result["counts"]["obsolete_literal_excerpt"] == 0
    assert result["records"][0]["assessment"] == "same_literal_excerpt"


def test_changed_body_and_absent_path_are_different(sample):
    origin, current, catalog, call = sample
    (current / "api.py").write_text("def api():\n    return 8\n")
    assert analyze([call], catalog, origin, current)["counts"]["obsolete_literal_excerpt"] == 1
    (current / "api.py").unlink()
    result = analyze([call], catalog, origin, current)
    assert result["counts"]["origin_definition_absent"] == 1
    assert result["stale_reliance"].startswith("not inferred")


def test_overlapping_shell_makes_current_source_unknown(sample):
    origin, current, catalog, call = sample
    shell = {"type": "tool_use", "part": {"id": "writer", "tool": "bash", "state": {"status": "completed", "time": {"start": 15, "end": 30}}}}
    result = analyze([call, shell], catalog, origin, current)
    assert result["counts"]["unassessed_records"] == 1
    assert not result["memory_calls"][0]["source_assessable"]


def test_duplicate_events_do_not_double_count_and_later_write_is_safe(sample):
    origin, current, catalog, call = sample
    shell = {"type": "tool_use", "part": {"id": "later", "tool": "bash", "state": {"status": "completed", "time": {"start": 30, "end": 40}}}}
    result = analyze([call, call, shell], catalog, origin, current)
    assert result["counts"]["memory_calls"] == 1
    assert result["counts"]["returned_records"] == 1
    assert result["counts"]["unassessed_records"] == 0


def test_conditional_definition_and_parse_failure_are_unknown(sample):
    origin, current, catalog, call = sample
    for text in ["if True:\n    def api(): return 7\n", "def api(:"]:
        (current / "api.py").write_text(text)
        result = analyze([call], catalog, origin, current)
        assert result["counts"]["origin_definition_absent"] == 0
        assert result["counts"]["unassessed_records"] == 1


def test_origin_mismatch_rejects_instead_of_claiming_stale(sample):
    origin, current, catalog, call = sample
    (origin / "api.py").write_text("def api(): return 0\n")
    with pytest.raises(ValueError, match="authenticate"):
        analyze([call], catalog, origin, current)


def test_error_and_withheld_payload_do_not_count_as_exposure(sample):
    origin, current, catalog, call = sample
    call["part"]["state"]["output"] = json.dumps({"error": {"code": "memory_lookup_failed"}, "entries": [], "withheld": []})
    result = analyze([call], catalog, origin, current)
    assert result["memory_calls"][0]["reason"] == "memory_tool_error"
    assert result["counts"]["returned_records"] == 0
    call["part"]["state"]["output"] = json.dumps({"catalog_sha256": sha(canonical(catalog)), "entries": [], "withheld": [{"id": "note"}]})
    result = analyze([call], catalog, origin, current)
    assert result["memory_calls"][0]["withheld_records"] == 1
    assert result["counts"]["returned_records"] == 0
