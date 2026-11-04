from __future__ import annotations

import json
import subprocess

import pytest

from cami.errors import IncompleteError, InputError
from cami.product.memory.adapters import HybridIndexAdapter, HybridIndexPort
from cami.product.memory.models import AgentContext, RememberInput
from cami.product.memory.validation import availability
from cami.product.service import ProductMemory

A = "a.py:alpha"
B = "b.py:beta"


@pytest.fixture
def service(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "a.py").write_text("def alpha(x: str): return x\n")
    (repo / "b.py").write_text("def beta(y: int): return y\n")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return ProductMemory(repo)


def items(contexts, *, prefix="batch", kind="note"):
    return tuple(RememberInput(kind=kind, query=query, context=context,
                               request_id=f"{prefix}-{i}", note_key=f"key-{i}" if kind == "note" else None,
                               text=f"Origin note {query}" if kind == "note" else None)
                 for i, (query, context) in enumerate(zip((A, B), contexts, strict=True)))


def knowledge(service):
    with service._session() as db:
        head = service.store.head(db)
        count = {name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                 for name in ("record", "record_revision", "operation_receipt", "memory_generation")}
        return head, count


def projection(service):
    generation = service.refresh()
    result = {}
    for state in generation.states:
        payload = state.record.payload.model_dump(mode="json")
        if payload["type"] == "note":
            payload["sources"] = [(s["path"], s["sha256"], s["size"]) for s in payload["sources"]]
        available = availability(state)
        result[(payload["subject"]["path"], payload["type"])] = (payload, getattr(available, "reason", None))
    return result


def test_batch_contexts_share_union_and_batch_receipts_are_atomic(service):
    contexts = service.context_many((A, B))
    assert contexts[0].index == contexts[1].index
    assert contexts[0].memory_generation_id == contexts[1].memory_generation_id
    assert {c.path for c in contexts[0].coverage} >= {"a.py", "b.py"}
    receipts = service.remember_batch(items(contexts))
    assert len({r.memory_generation_id for r in receipts}) == 1
    assert all(r.changed and r.revision == 1 for r in receipts)
    head, counts = knowledge(service)
    assert head.catalog_epoch == 2 and counts["record_revision"] == counts["operation_receipt"] == 2
    assert head.sequence == 2  # Empty shared origin then one atomic publication.
    assert len(service.refresh().states) == 2


def test_payload_and_availability_match_sequential(service, tmp_path, monkeypatch):
    contexts = service.context_many((A, B))
    service.remember_batch(items(contexts))
    bulk = projection(service)
    repo = tmp_path / "sequential"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for name in ("a.py", "b.py"):
        (repo / name).write_bytes((service.root / name).read_bytes())
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "sequential-state"))
    sequential = ProductMemory(repo)
    for i, query in enumerate((A, B)):
        context = sequential.context(query)
        sequential.remember("note", query, context, f"single-{i}", note_key=f"key-{i}", text=f"Origin note {query}")
    assert projection(sequential) == bulk
    assert knowledge(sequential)[0].sequence > 2  # Sequential intermediate history is intentionally retained.


def test_batch_retries_per_request_and_conflicting_reuse(service):
    request = items(service.context_many((A, B)))
    receipts = service.remember_batch(request)
    before = knowledge(service)
    assert service.remember_batch(request) == receipts
    assert knowledge(service) == before
    bad = (request[0].model_copy(update={"text": "different"}), request[1])
    with pytest.raises(InputError, match="request_id_conflict"):
        service.remember_batch(bad)
    assert knowledge(service) == before


def test_conflict_rolls_back_earlier_item_and_receipts(service):
    contexts = service.context_many((A, B))
    service.remember("note", B, contexts[1], "existing", note_key="taken", text="old")
    before = knowledge(service)
    request = items(contexts)
    request = (request[0], request[1].model_copy(update={"note_key": "taken", "text": "conflict"}))
    with pytest.raises(InputError, match="semantic_identity_conflict"):
        service.remember_batch(request)
    assert knowledge(service) == before


def test_forged_context_rejects_whole_batch(service):
    contexts = service.context_many((A, B))
    raw = contexts[1].model_dump(mode="json")
    raw["code"][0]["signature"]["parameters"][0]["name"] = "forged"
    forged = AgentContext.model_validate_json(json.dumps(raw))
    request = items((contexts[0], forged))
    before = knowledge(service)
    with pytest.raises(InputError, match="context_mismatch"):
        service.remember_batch(request)
    assert knowledge(service) == before


def test_duplicate_global_note_keys_and_request_ids_reject_before_prepare(service, monkeypatch):
    request = items(service.context_many((A, B)))
    before = knowledge(service)
    def forbidden(*args):
        raise AssertionError("must reject invalid batch before preparing index")
    monkeypatch.setattr(HybridIndexPort, "prepare_locked", forbidden)
    with pytest.raises(InputError, match="global note_key"):
        service.remember_batch((request[0], request[1].model_copy(update={"note_key": request[0].note_key})))
    with pytest.raises(InputError, match="request_id"):
        service.remember_batch((request[0], request[1].model_copy(update={"request_id": request[0].request_id})))
    assert knowledge(service) == before


def test_final_verify_failure_rolls_back_batch(service, monkeypatch):
    request = items(service.context_many((A, B)))
    before = knowledge(service)
    def fail(*args):
        raise IncompleteError("authored final verification failure")
    monkeypatch.setattr(HybridIndexPort, "verify", fail)
    with pytest.raises(IncompleteError, match="authored"):
        service.remember_batch(request)
    assert knowledge(service) == before


def test_changed_source_between_projection_and_verify_not_published(service, monkeypatch):
    before = knowledge(service)
    project = HybridIndexAdapter.project
    def changing(adapter, indexed):
        view = project(adapter, indexed)
        (service.root / "a.py").write_text("def changed(): return 4\n")
        return view
    monkeypatch.setattr(HybridIndexAdapter, "project", changing)
    with pytest.raises(IncompleteError, match="unstable"):
        service.context_many((A, B))
    assert knowledge(service) == before


def test_stale_origin_kept_and_current_signature_withheld(service):
    contexts = service.context_many((A, B))
    request = items(contexts, kind="signature_equals")
    (service.root / "a.py").write_text("def alpha(x: int): return x\n")
    receipts = service.remember_batch(request)
    current = service.context_many((A, B))
    assert current[0].withheld[0].reason == "signature_mismatch"
    assert current[0].withheld[0].record.origin == contexts[0].index
    assert current[1].facts[0].state.check.verdict == "supported"
    assert service.remember_batch(request) == receipts


def test_source_cas_corruption_rejects_without_partial_batch(service):
    contexts = service.context_many((A, B))
    before = knowledge(service)
    source = contexts[1].code[0].source
    path = service.store.objects / source.sha256
    original = path.read_bytes()
    path.write_bytes(b"corrupt")
    with pytest.raises(IncompleteError, match="source_evidence_corrupt"):
        service.remember_batch(items(contexts))
    path.write_bytes(original)
    assert knowledge(service) == before


def test_single_api_receipt_update_history_compatibility(service):
    context = service.context(A)
    receipt = service.remember("note", A, context, "single", note_key="single", text="manual")
    assert service.remember("note", A, context, "single", note_key="single", text="manual") == receipt
    current = service.context(A)
    changed = service.update(receipt.memory_id, 1, current, "update", text="reviewed")
    assert changed.revision == 2
    assert service.update(receipt.memory_id, 1, current, "update", text="reviewed") == changed
    with pytest.raises(InputError, match="revision_conflict"):
        service.update(receipt.memory_id, 1, current, "conflict", text="another")
    assert len(service.history(receipt.memory_id).revisions) == 2


def test_batch_boundaries(service):
    for queries in ((), [A], (A,) * 1025):
        with pytest.raises(InputError, match="batch"):
            service.context_many(queries)
    with pytest.raises(InputError, match="symbol"):
        service.context_many((A, ""))
    with pytest.raises(InputError, match="batch"):
        service.remember_batch(())


def test_mixed_retry_and_new_request_keep_old_receipt_generation(service):
    contexts = service.context_many((A, B))
    request = items(contexts)
    original = service.remember_batch((request[0],))[0]
    old_history = service.history(original.memory_id)
    receipts = service.remember_batch(request)
    assert receipts[0] == original
    assert receipts[0].memory_generation_id != receipts[1].memory_generation_id
    assert receipts[1].memory_generation_id == service.refresh().memory_generation_id
    assert len(service.history(original.memory_id).revisions) == len(old_history.revisions) == 1
    assert len(service.history(receipts[1].memory_id).revisions) == 1
    assert knowledge(service)[1]["operation_receipt"] == 2
    before = knowledge(service)
    assert service.remember_batch(request) == receipts
    assert knowledge(service) == before
