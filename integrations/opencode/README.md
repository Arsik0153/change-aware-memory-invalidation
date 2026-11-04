# Frozen memory lookup for OpenCode

Two Python runtime files implement one small stdio MCP tool, `memory_lookup`, with interchangeable `static` and `cami` backends. Keep `memory_adapter.py` and `memory_backend.py` together. They do not import or execute target source code, launch models, fetch repositories, or replace OpenCode's native coding tools. Static preparation and lookup do not import CAMI at all. CAMI preparation and lookup call the existing `ProductMemory` live-worktree service.

The primary notes-only seed catalog is the same semantic content in both arms. Static returns origin assertions marked `unchecked_current`. CAMI returns source-unchanged notes marked `manual_assertion`, and withholds changed/uncertain notes without returning their old prose. Optional supported structural facts are labeled separately. No fresh `AgentContext.code`, inferred behavior or current source enrichment is returned exclusively in the CAMI arm.

## Prepare notes independently at the same origin version

The shared source-only generator supplies this shape, including an exact subject so the static arm does not need to reimplement CAMI symbol analysis:

```json
{
  "schema_version": 1,
  "source_roots": ["src"],
  "excluded_paths": [],
  "records": [
    {
      "id": "stable-origin-note-id",
      "kind": "note",
      "selector": "src/api.py:Client.open",
      "subject": {
        "language": "python",
        "path": "src/api.py",
        "qualname": "Client.open",
        "node_kind": "method"
      },
      "note_key": "source-excerpt",
      "text": "Manual origin source assertion: <exact source-only signature/docstring/bounded body excerpt>"
    }
  ]
}
```

The input must have 1–1024 records and be at most 4 MiB. IDs and semantic identities must be unique. CAMI note keys are GLOBAL within a worktree, independent of subject; use e.g. source-excerpt:<selectorhash>. Duplicate note keys are rejected before any CAMI import, state initialization or symbol capture. Notes need nonempty text and note key. Paths are relative and canonical. Source body generation/model costs are outside this adapter and must be recorded per arm; this adapter does not create LLM summaries or select helpful task-specific notes.

Use a separate new preparation directory and, for CAMI, a new state directory outside the target repository:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/ABS/CAMI/src /ABS/CAMI/.venv/bin/python /ABS/CAMI/integrations/opencode/memory_adapter.py prepare \
  --backend static --repo /ABS/STATIC_ORIGIN_WORKTREE --seed-spec /ABS/seed-spec.json --out /ABS/static-prepared
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/ABS/CAMI/src /ABS/CAMI/.venv/bin/python /ABS/CAMI/integrations/opencode/memory_adapter.py prepare \
  --backend cami --repo /ABS/CAMI_ORIGIN_WORKTREE --seed-spec /ABS/seed-spec.json \
  --out /ABS/cami-prepared --state-home /ABS/cami-private-state
```

Both commands write:

- `catalog.json`: portable canonical payloads and origin full-file SHA-256/size; backend-specific `IndexRef` values are excluded.
- `binding.json`: frozen catalog digest/path, backend, absolute repository and private state paths, and CAMI record-ID/revision mappings.
- `construction-metrics.json`: success/failure, total wall and self+completed-child CPU, output/state bytes; CAMI also records catalog-capture and each registration span.

At the same canonical origin bytes, notes-only catalogs must compare semantically equal (the authored test proves exact JSON equality). CAMI authenticates each unique subject from immutable backend context and checks the registered payload, origin source, and initial availability. No candidate is silently dropped or substituted. Static binds the given manual subject and origin bytes; it does not independently establish symbol existence or note meaning. It reads source files only during preparation, not runtime lookup.

After preparation, advance every arm to the same independently fixed canonical task version. Do not construct old expectations against the later version or use another agent's generated solution as a start. Keep the absolute worktree path stable: CAMI IDs are worktree-scoped. Do not copy a CAMI SQLite DB between different worktrees.

An existing frozen `catalog.json` may also be passed with `--catalog` instead of `--seed-spec`. Both backends require matching origin bytes at preparation. Optional typed CAMI seeds use `kind: "symbol_exists"` or `"signature_equals"` and omit note fields; CAMI derives the expectation from the authenticated origin context. Static cannot independently derive those typed seed-spec expectations, but can consume an explicitly frozen typed catalog. The primary notes-only study avoids attributing this typed derivation to the static arm.

## Serve one backend

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/ABS/CAMI/src /ABS/CAMI/.venv/bin/python /ABS/CAMI/integrations/opencode/memory_adapter.py serve \
  --binding /ABS/cami-prepared/binding.json --trace /ABS/tool-trace.jsonl
```

The trace must be outside the target repository. The server is serial and long-lived. Stdout contains only newline-delimited MCP JSON-RPC; diagnostics go to stderr. There is one tool, with identical name/description/schema in both arms:

```json
{"name":"memory_lookup","arguments":{"query":"where is the client open method", "limit":5}}
```

`query` is required, nonempty and at most 1000 characters. `limit` defaults to 5 and must be an integer 1–20 (booleans are rejected). Matching is shared and deterministic: exact case-folded ID/name/qualname/path-qualified selector first, then token overlap (identifier/path tokens weight 4; note-text/key tokens weight 1), then stable ID. Underscore/dot/path separators split tokens. No embeddings, model ranking, task IDs or future answers are used.

Selection is a fixed prefix of the ranked origin catalog, capped by the requested limit and **16 KiB of canonical origin record bytes**. This selection occurs before availability filtering. A withheld CAMI hit consumes the same budget slot/bytes as its static counterpart; lower-ranked records do not backfill. Returned envelope metadata is additional, and `selection_budget` explicitly describes this as an origin-record budget, not an exact provider-token or final-response-byte cap. Input/output context/token limits must still be frozen and enforced by the outer harness.

The tool's text content is one JSON object with catalog digest, query, selected/matched counts, truncation/budget, `entries`, `withheld`, backend and freshness. Available entries contain the original frozen payload/source, not fresh code. Withheld entries contain only ID, subject, kind, machine reason and required action. CAMI includes current snapshot/memory-generation IDs. Note labels remain `manual_assertion`; a source-unchanged note is not behaviorally verified. Optional structural predicates cover exact syntax/existence only.

On a CAMI failure, the MCP result has `isError:true`, empty entries, and explicit unavailable freshness. No previous successful result, old prose, historical head or empty-success substitute is returned. Model-visible exception text is generic; local trace diagnostics are bounded. Treat the transport breaking as an error too. Frozen catalog modification or unexpected CAMI catalog/revision changes fail rather than silently updating content.

## OpenCode 2.2.5 local configuration

`opencode.config.template.json` uses the installed v2 local MCP shape verified by the peer agent. Replace absolute placeholders and choose one prepared binding. Both memory arms use the same MCP server name and tool schema. Plain OpenCode has no memory MCP server. Preserve native grep/glob/read/edit tools. No v1 plugin hook assumptions or direct grep override are used.

The installed runtime has accepted JSONL initialization fallback from requested `2025-11-25` to `2025-06-18` in a separate no-model smoke. This adapter supports `2024-11-05`, `2025-03-26`, `2025-06-18`, tools/list, tools/call and ping; it negotiates a supported fallback. It is a deliberately narrow synchronous stdio server, not a full general-purpose MCP SDK/HTTP server. The local environment has no MCP SDK installed; runtime protocol code uses only Python's standard library. CAMI/Pydantic are needed only for the CAMI backend. Official protocol references: [stdio](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports), [lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle), [tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools).

## Cost accounting and boundaries

Preparation spans include adapter entry, CAMI import/backend work, source capture/authentication, per-entry registration, final refresh/equality checks, durable storage and the final storage observation. They exclude interpreter/CLI startup and the final metrics-file write; measure whole process wall/CPU externally. `catalog_capture` and per-registration spans are nested components of the total, not additional independent costs to sum again. The generator's extraction work must also be charged per arm. Failed preparation retains metrics.

Each lookup trace contains chosen limit, a query/arguments hash (not plaintext query or note text), backend/catalog identity, backend/import/retrieval/serialization/storage-observation wall and self+completed-child CPU, state bytes, serialized response bytes, selected/returned/withheld counts and error diagnostics. JSON-RPC input/output and trace append are outside that inner span; measure total server/session overhead externally. Backend import is lazy and charged to the first CAMI lookup, so cold and warm calls must be identified separately.

Trace `states_checked_type` and `states_carried_type` describe persisted state representations, **not actual validator-call counts in that lookup**. Reusing an unchanged memory generation can retain a `checked` representation without running a new check. Use actual cProfile call counts/explicit backend instrumentation for that metric; do not infer optimization from these state counts. Source hashing, repeated captures, signature projection, index/source cache I/O, full private SQLite validation/serialization and durable publication are real costs even with a reused index. A long-lived server removes repeated Python startup but does not skip these steps or promise persistent Node analysis.

CAMI uses `verified_readset`, not an atomic filesystem snapshot. Its lock does not block outside editors/shells. Query again after edits; prior conversation text is historical and cannot be erased retroactively. The static arm deliberately continues returning origin assertions. Use single-owner workspaces and isolated OpenCode/CAMI state. The synchronous server does not process cancellation during a lookup; the outer harness must enforce timeout/process-group cleanup. It does not handle dynamic memory creation/update through MCP, rank natural language semantically, or run tests for behavioral truth.

Profile representative operations before optimizing. For example, use `python -m cProfile -o PROFILE memory_adapter.py prepare ...` or profile a separate scripted server lifecycle, and inspect parent/child CPU plus end-to-end session cost. Do not rewrite in Rust without a measured CPU hotspot and equivalent correctness boundaries.

## Verification and current status

```sh
.venv/bin/python -m pytest -q tests/test_opencode_memory_adapter.py
.venv/bin/ruff check integrations/opencode tests/test_opencode_memory_adapter.py
```

15 authored tests pass (including duplicate global note-key rejection before capture and distinct-key cross-subject registration). They cover independent static preparation with zero CAMI imports, exact semantic catalog equality, method notes, dirty/untracked edits, sticky note review, failed refresh without old-text fallback, origin mismatch, frozen-catalog tampering, two-worktree state isolation, optional existence/signature carry/mismatch/deletion, shared ranking/budget, 1024-entry cap before capture, JSON-only stdio lifecycle, protocol fallback, invalid arguments, and oversized-message recovery. Tests use newly authored temporary repositories, not benchmark tasks or future oracles.

This integration has passed authored transport/backend tests. Real OpenCode smoke results and task benchmark results are recorded separately. A full-catalog preflight exposed a duplicate note-key error in the first source-note generator; the failed run is preserved and catalog validation now rejects duplicate global note keys before CAMI imports or source capture. No end-to-end efficiency advantage is claimed.
