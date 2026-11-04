from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from cami.errors import IncompleteError, InputError
from cami.product.models import Observation, digest
from cami.product.observation import ProductObservation
from cami.product.store import CacheCorrupt, GenerationStore, index_fingerprint, state_base
from cami.product.worktree import CaptureChanged, capture, repository_root
from cami.product.memory.adapters import ProductIndexPort, HybridIndexPort
from cami.product.memory.models import (
    AgentContext, AvailableRecord, CodeView, DefinitionFact, ExistsPayload, MemoryGeneration,
    MutationReceipt, MutationRequest, NotePayload, NoteState, Payload, RecordHistory,
    RecordRevision, RememberInput, SignaturePayload, SourceRef, WithheldRecord,
)
from cami.product.memory.store import MemoryStore
from cami.product.memory.validation import VALIDATOR_FINGERPRINT, availability, transition


def select(view: CodeView, query: str) -> tuple[DefinitionFact, ...]:
    return tuple(d for d in view.definitions if query in (
        f"{d.subject.path}:{d.subject.qualname}", d.subject.qualname,
        d.subject.qualname.rsplit(".", 1)[-1]))


def identity(worktree_key: str, payload: Payload) -> str:
    if isinstance(payload, NotePayload):
        return digest(["note/1", worktree_key, payload.note_key])
    return digest(["claim/1", worktree_key, payload.subject.model_dump(mode="json"), payload.type])


def semantic_payload(payload: Payload) -> object:
    value = payload.model_dump(mode="json")
    if isinstance(payload, NotePayload):
        value["sources"] = [(s.path, s.sha256, s.size) for s in payload.sources]
    return value


MAX_BATCH = 1024


def _probes(records: tuple[RecordRevision, ...] | list[RecordRevision],
            query: str | tuple[str, ...] | None = None,
            requests: tuple[MutationRequest, ...] = ()) -> tuple[str, ...]:
    paths = {r.payload.subject.path for r in records}
    for record in records:
        if isinstance(record.payload, NotePayload):
            paths.update(s.path for s in record.payload.sources)
    queries = (query,) if isinstance(query, str) else query or ()
    paths.update(item.split(":", 1)[0] for item in queries if ":" in item)
    paths.update(request.payload.subject.path for request in requests)
    return tuple(sorted(paths))


def _bounded_batch(items: tuple[object, ...]) -> None:
    if type(items) is not tuple or not 1 <= len(items) <= MAX_BATCH:
        raise InputError(f"batch must be a tuple with 1..{MAX_BATCH} items")


class ProductMemory:
    def __init__(self, repo: Path, source_roots: tuple[str, ...] | None = None,
                 excluded_paths: tuple[str, ...] = (), port: ProductIndexPort | None = None):
        self.root = repository_root(repo)
        self.roots = source_roots
        self.excludes = excluded_paths
        self.index_store = GenerationStore(self.root, state_base())
        self.store = MemoryStore(self.index_store.path)
        self.port: ProductIndexPort = port if port is not None else HybridIndexPort()

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        try:
            with self.index_store.writer(), self.store.connection() as db:
                yield db
        except (OSError, CacheCorrupt) as exc:
            raise IncompleteError(f"memory_state_io_error: {exc}") from exc

    def refresh(self) -> MemoryGeneration:
        return self._coordinate(None, None)[0]

    def observe(self) -> ProductObservation:
        """Capture canonical inputs without analysis, validation or knowledge publication."""
        started = datetime.now(UTC).isoformat()
        try:
            with self.index_store.writer(), self.store.observation_connection() as db:
                previous = self.store.head(db) if db is not None else None
                records = self.store.revisions(db) if db is not None else ()
                probes = _probes(records)
                fingerprint = index_fingerprint()
                captured = capture(self.root, self.roots, self.excludes, state_base(), probes)
                matches = (previous is not None
                           and previous.index.snapshot_id == captured.snapshot_id
                           and previous.index.analyzer_fingerprint == fingerprint
                           and previous.index.policy_fingerprint == digest(
                               captured.policy.model_dump(mode="json"))
                           and previous.validator_fingerprint == VALIDATOR_FINGERPRINT
                           and tuple(s.record for s in previous.states) == records)
                reason: Literal["inputs_changed", "head_matches",
                                "index_artifact_unavailable", "no_head"] = (
                                    "head_matches" if matches else
                                    "no_head" if previous is None else "inputs_changed")
                if previous is not None and db is not None:
                    view = self.store.view(db, previous.index.generation_id)
                    if view.index != previous.index:
                        raise IncompleteError("memory_head_index_mismatch")
                    # Unavailable compiler results deliberately have no reusable cache artifact.
                    unavailable = any(error == "compiler_unavailable"
                                      for _, error in view.path_errors)
                    if matches and not unavailable and self.index_store.load(
                            previous.index.generation_id, captured, fingerprint) is None:
                        matches, reason = False, "index_artifact_unavailable"
                    for item in previous.states:
                        sources = (item.record.payload.sources
                                   if isinstance(item.record.payload, NotePayload) else
                                   tuple(e for e in item.state.check.evidence
                                         if isinstance(e, SourceRef))
                                   if not isinstance(item.state, NoteState) else ())
                        for source in sources:
                            self.store.read_source(source)
                verified = capture(self.root, self.roots, self.excludes, state_base(), probes)
                if (captured.snapshot_id != verified.snapshot_id
                        or captured.base_commit != verified.base_commit
                        or fingerprint != index_fingerprint()):
                    raise IncompleteError("memory_observation_unstable: inputs changed")
                return ProductObservation(
                    comparison_key=digest([captured.snapshot_id, fingerprint,
                                           VALIDATOR_FINGERPRINT,
                                           [r.model_dump(mode="json") for r in records],
                                           previous.catalog_epoch if previous else 0]),
                    relation="matching" if matches else "changed", reason=reason,
                    capture_started_at=started, verified_at=datetime.now(UTC).isoformat(),
                    memory_generation_id=previous.memory_generation_id if previous else None,
                    index=previous.index if previous else None)
        except CaptureChanged as exc:
            raise IncompleteError(f"memory_observation_unstable: {exc}") from exc
        except (OSError, CacheCorrupt) as exc:
            raise IncompleteError(f"memory_state_io_error: {exc}") from exc

    def context(self, query: str) -> AgentContext:
        return self.context_many((query,))[0]

    def context_many(self, queries: tuple[str, ...]) -> tuple[AgentContext, ...]:
        """Resolve queries from one verified view with the union of all path probes."""
        _bounded_batch(queries)
        for query in queries:
            if not isinstance(query, str) or not query.strip() or "\x00" in query:
                raise InputError("symbol must be nonempty and contain no NUL characters")
        generation, view, observation, _ = self._coordinate(queries, None)
        return tuple(self._context(query, generation, view, observation) for query in queries)

    def _context(self, query: str, generation: MemoryGeneration, view: CodeView,
                 observation: Observation) -> AgentContext:
        code = select(view, query)
        # Exact selectors continue to expose withheld records when their definitions disappear.
        selected = {d.subject for d in code}
        relevant = [s for s in generation.states if s.record.payload.subject in selected
                    or query in (f"{s.record.payload.subject.path}:{s.record.payload.subject.qualname}",
                                 s.record.payload.subject.qualname,
                                 s.record.payload.subject.qualname.rsplit(".", 1)[-1])]
        facts: list[AvailableRecord] = []
        notes: list[AvailableRecord] = []
        withheld: list[WithheldRecord] = []
        for item in relevant:
            available = availability(item)
            if isinstance(available, WithheldRecord):
                withheld.append(available)
            elif isinstance(item.state, NoteState):
                notes.append(available)
            else:
                facts.append(available)
        return AgentContext(
            query=query, index=view.index, memory_generation_id=generation.memory_generation_id,
            observation=observation, code=code, limitations=view.limitations,
            coverage=view.coverage, path_errors=view.path_errors,
            facts=tuple(facts), notes=tuple(notes), withheld=tuple(withheld))

    def remember(self, kind: Literal["symbol_exists", "signature_equals", "note"], query: str,
                 context: AgentContext, request_id: str, *, note_key: str | None = None,
                 text: str | None = None) -> MutationReceipt:
        return self._mutate(kind, query, context, request_id, note_key, text, None, None)

    def update(self, memory_id: str, expected_revision: int, context: AgentContext,
               request_id: str, *, text: str | None = None) -> MutationReceipt:
        return self._mutate(None, None, context, request_id, None, text,
                            memory_id, expected_revision)

    def _request(self, db: sqlite3.Connection, kind: str | None, query: str | None,
                 context: AgentContext, request_id: str, note_key: str | None,
                 text: str | None, memory_id: str | None, expected_revision: int | None,
                 origins: dict[str, CodeView], context_indexes: dict[str, object]) -> MutationRequest:
        if context.index.generation_id not in origins:
            origins[context.index.generation_id] = self.store.view(db, context.index.generation_id)
        origin = origins[context.index.generation_id]
        if context.memory_generation_id not in context_indexes:
            row = db.execute("SELECT value FROM memory_generation WHERE id=?",
                             (context.memory_generation_id,)).fetchone()
            context_indexes[context.memory_generation_id] = (
                MemoryGeneration.model_validate_json(row[0]).index if row else None)
        if (origin.index != context.index
                or context_indexes[context.memory_generation_id] != context.index
                or select(origin, context.query) != context.code):
            raise InputError("context_mismatch: context differs from immutable backend")
        if len(context.code) != 1 or context.code[0].ambiguous \
                or context.code[0].identity_uncertain:
            raise InputError("registration requires one exact unique symbol")
        fact = context.code[0]
        if query is not None and select(origin, query) != context.code:
            raise InputError("symbol does not match pinned context")
        if memory_id is not None:
            records = self.store.revisions(db)
            old = next((r for r in records if r.memory_id == memory_id), None)
            if old is None:
                raise InputError("unknown memory ID")
            if old.payload.subject != fact.subject:
                raise InputError("update cannot retarget the record subject")
            kind = old.payload.type
            note_key = old.payload.note_key if isinstance(old.payload, NotePayload) else None
        payload: Payload
        if kind == "symbol_exists":
            payload = ExistsPayload(subject=fact.subject)
        elif kind == "signature_equals":
            if fact.signature is None:
                raise InputError("unsupported signature form")
            payload = SignaturePayload(subject=fact.subject, expected=fact.signature)
        elif kind == "note" and note_key and text:
            payload = NotePayload(subject=fact.subject, note_key=note_key, text=text,
                                  sources=(fact.source,))
        else:
            raise InputError("note requires --note-key and nonempty --text")
        return MutationRequest(request_id=request_id, payload=payload, origin=origin.index,
                               memory_id=memory_id, expected_revision=expected_revision)

    def _mutate(self, kind: str | None, query: str | None, context: AgentContext,
                request_id: str, note_key: str | None, text: str | None,
                memory_id: str | None, expected_revision: int | None) -> MutationReceipt:
        with self._session() as db:
            request = self._request(db, kind, query, context, request_id, note_key, text,
                                    memory_id, expected_revision, {}, {})
            _, _, _, receipt = self._coordinate_locked(db, None, request)
            assert receipt is not None
            return receipt

    def remember_batch(self, items: tuple[RememberInput, ...]) -> tuple[MutationReceipt, ...]:
        """Register atomically; every new receipt names the same post-batch generation."""
        _bounded_batch(items)
        if not all(isinstance(item, RememberInput) for item in items):
            raise InputError("batch items must be RememberInput values")
        request_ids: set[str] = set()
        note_keys: set[str] = set()
        for item in items:
            if item.request_id in request_ids:
                raise InputError("duplicate batch request_id")
            request_ids.add(item.request_id)
            if item.kind == "note":
                if item.note_key in note_keys:
                    raise InputError("duplicate global note_key in batch")
                if not item.note_key or not item.text:
                    raise InputError("note requires --note-key and nonempty --text")
                note_keys.add(item.note_key)
        with self._session() as db:
            origins: dict[str, CodeView] = {}
            context_indexes: dict[str, object] = {}
            requests = tuple(self._request(
                db, item.kind, item.query, item.context, item.request_id, item.note_key,
                item.text, None, None, origins, context_indexes) for item in items)
            _, _, _, receipts = self._coordinate_many_locked(db, None, requests)
            return receipts

    def history(self, memory_id: str) -> RecordHistory:
        with self._session() as db:
            return self.store.history(db, memory_id)

    def _coordinate(self, query: str | tuple[str, ...] | None, request: MutationRequest | None) -> tuple[MemoryGeneration, CodeView, Observation, MutationReceipt | None]:
        with self._session() as db:
            return self._coordinate_locked(db, query, request)

    def _coordinate_locked(self, db: sqlite3.Connection, query: str | tuple[str, ...] | None,
                           request: MutationRequest | None) -> tuple[MemoryGeneration, CodeView, Observation, MutationReceipt | None]:
        generation, view, observation, receipts = self._coordinate_many_locked(
            db, query, (request,) if request else ())
        return generation, view, observation, receipts[0] if receipts else None

    def _coordinate_many_locked(self, db: sqlite3.Connection,
                                query: str | tuple[str, ...] | None,
                                requests: tuple[MutationRequest, ...]) -> tuple[MemoryGeneration, CodeView, Observation, tuple[MutationReceipt, ...]]:
        previous = self.store.head(db)
        records = list(self.store.revisions(db))
        probes = _probes(records, query, requests)
        prepared = self.port.prepare_locked(self.index_store, self.root, self.roots,
                                            self.excludes, probes)
        view = prepared.view
        if view.index.worktree_key != self.index_store.key:
            raise IncompleteError("index_port_worktree_identity_mismatch")
        self.store.put_sources(prepared.sources, view)
        old_view = self.store.view(db, previous.index.generation_id) if previous else None
        epoch = previous.catalog_epoch if previous else 0
        hashes = tuple(digest(request.model_dump(mode="json")) for request in requests)
        receipts = [self.store.receipt(db, request.request_id, request_hash)
                    for request, request_hash in zip(requests, hashes, strict=True)]
        mutations: list[tuple[RecordRevision, bool] | None] = []
        db.execute("BEGIN IMMEDIATE")
        try:
            for request, receipt in zip(requests, receipts, strict=True):
                if receipt is not None:
                    mutations.append(None)
                    continue
                record_id = identity(view.index.worktree_key, request.payload)
                old = next((r for r in records if r.memory_id == record_id), None)
                changed = False
                if request.memory_id is not None:
                    if request.memory_id != record_id or old is None:
                        raise InputError("record_identity_conflict")
                    if request.expected_revision != old.revision:
                        raise InputError(f"revision_conflict: current revision is {old.revision}")
                    if old.payload.subject != request.payload.subject:
                        raise InputError("record_subject_conflict")
                    changed = True
                elif old is not None:
                    if semantic_payload(old.payload) != semantic_payload(request.payload):
                        raise InputError("semantic_identity_conflict: use update with --if-revision")
                else:
                    changed = True
                if changed:
                    epoch += 1
                    mutated = RecordRevision(
                        memory_id=record_id, revision=old.revision + 1 if old else 1,
                        payload=request.payload, origin=request.origin,
                        created_at=datetime.now(UTC).isoformat(),
                        previous_revision=old.revision if old else None)
                    self.store.save_revision(db, mutated)
                    records = [r for r in records if r.memory_id != record_id] + [mutated]
                else:
                    assert old is not None
                    mutated = old
                mutations.append((mutated, changed))
            needs_transition = (previous is None or previous.index != view.index
                                or epoch != previous.catalog_epoch
                                or previous.validator_fingerprint != VALIDATOR_FINGERPRINT)
            if needs_transition:
                sequence = previous.sequence + 1 if previous else 1
                transition_id = digest([previous.memory_generation_id if previous else None,
                                        view.index.model_dump(mode="json"), epoch, sequence])
                prior = {s.record.memory_id: s for s in previous.states} if previous else {}
                states = tuple(transition(r, view, prior.get(r.memory_id), old_view, transition_id)
                               for r in sorted(records, key=lambda r: r.memory_id))
                generation = MemoryGeneration(
                    memory_generation_id=digest([transition_id,
                                                [s.model_dump(mode="json") for s in states]]),
                    parent_memory_generation_id=previous.memory_generation_id if previous else None,
                    sequence=sequence, index=view.index, catalog_epoch=epoch,
                    validator_fingerprint=VALIDATOR_FINGERPRINT, states=states)
                self.store.publish(db, view, generation)
            else:
                assert previous is not None
                generation = previous
            for item in generation.states:
                sources = item.record.payload.sources if isinstance(item.record.payload, NotePayload) \
                    else tuple(e for e in item.state.check.evidence if isinstance(e, SourceRef)) \
                    if not isinstance(item.state, NoteState) else ()
                for source in sources:
                    self.store.read_source(source)
            self.port.verify(self.root, self.roots, self.excludes, probes, prepared)
            for index, (request, request_hash, mutation) in enumerate(zip(requests, hashes, mutations, strict=True)):
                if mutation is None:
                    continue
                mutated, changed = mutation
                receipt = MutationReceipt(
                    request_id=request.request_id, memory_id=mutated.memory_id,
                    revision=mutated.revision, changed=changed,
                    memory_generation_id=generation.memory_generation_id)
                db.execute("INSERT INTO operation_receipt VALUES(?,?,?)",
                           (request.request_id, request_hash, receipt.model_dump_json()))
                receipts[index] = receipt
            complete = tuple(receipt for receipt in receipts if receipt is not None)
            if len(complete) != len(requests):
                raise IncompleteError("memory_batch_receipt_incomplete")
            db.execute("COMMIT")
            return generation, view, prepared.observation, complete
        except BaseException:
            db.execute("ROLLBACK")
            raise
