# Lossless generation JSON compression

Production schema 3 is implemented and verified. On all ten real source-memory
databases, the primary storage target and exact-reconstruction gates passed.
Median SQLite size fell from 20,533,248 to 7,716,864 bytes (62.42%) relative to the
already compacted schema 2. Compared with the original schema 1 files from the
same full experiment, the reduction is 79.00% (36,755,456 → 7,716,864 bytes).
Every SQL row reconstructs exactly, including original generation JSON bytes;
all original files and non-database artifacts remain unchanged.

| Measured span, five fresh processes per side per database | Schema 2 | Schema 3 | Reduction |
|---|---:|---:|---:|
| Validated store operation | 117.08 ms | 106.11 ms | 9.37% |
| Complete local Python process | 257.31 ms | 245.21 ms | 4.70% |
| Peak local process RSS | 229,048,320 bytes | 139,304,960 bytes | 39.18% |
| Complete Linux MCP process | 502.24 ms | 488.33 ms | 2.77% |

These are medians of ten case medians. The five-sample observed ranges separate
in all ten cases for the local operation, full local process and peak RSS. They
separate in only five MCP cases: **the full MCP latency result is inconclusive**
under its strict all-ten criterion. All ten MCP case medians are lower, but that
is not a stronger success rule. Observed ranges are not confidence intervals.
RSS is the OS high-water mark of a fresh macOS read process, not retained heap,
Docker memory, or the complete model service's peak memory.

First local reads include the schema 2 → 3 migration: complete-process medians
257.28 → 442.45 ms (baseline range 253.03–264.61 ms, candidate 437.50–460.23 ms).
Cold peak RSS medians were 229,007,360 → 213,819,392 bytes. This one-off conversion
cost is separate from subsequent reads. Cold MCP reads start from schema 1 and
also recertify a reset canonical workspace; medians were 1.231 → 1.218 s with
overlapping ranges. These cold workloads are different and must not be pooled.

All 120 local process receipts and all 120 complete MCP process receipts passed.
The independent audits checked exact SQL reconstruction, physical originals,
source-import identities, public output hashes, actual wire/source/status receipts,
process/container success and cleanup, and all arithmetic. Each MCP namespace
added exactly one persistent generation during its cold call, then retained that
same identity across five subsequent calls. No model calls were made. The prior
80-attempt full-model result remains attached to its earlier frozen code; these
storage results do not establish a new whole-agent or monetary efficiency claim.

Production source: `a8c34cd`; measurement/admission harness: `f601596` in immutable
runtime-v12; comparator production is `6380b2d` in runtime-v11. `local-protocol.json`
and `mcp-protocol.json` were frozen before timing. Measurements started only after
the project suite passed **1,781 tests** (one skipped, four Docker-marked deselected),
the real Linux admission passed, and the live schema 3 watcher passed 24 phases
with 39 commands and six owned processes, all reaped. Ruff passed.

Linux admission independently exercised six fresh MCP configurations, schema 1
and schema 2 upgrades through actual MCP, preservation of every old generation,
and the real prior schema 2 reader's refusal to read schema 3. Original files were
unchanged. The focused 72-test suite includes both legacy formats, read-only
observation, later writes, failed publication, SIGKILL recovery on both sides of
publication, malformed encodings and aggregate decompression bounds. An initial
implementation test run found a direct service-layer JSON read that bypassed the
store; that read now goes through `MemoryStore.generation`. The repaired code
passed all admissions before either timed comparison began.

`local-evidence.tar.xz` and `mcp-evidence.tar.xz` retain complete copied stores and
raw process receipts. `local-audit.json` / `mcp-audit.json` and their scripts recheck
them. `admission.tar.xz` retains actual Linux admission. Watcher archives exclude
only the copied compiler cache. Standalone PNG/PDF figures and `chart.html` are
reproduced by `render_results.py`; it verifies the schema 2 hash/size link to the
previous duplicate-removal experiment before showing cumulative size reduction.

## Earlier offline screening

The predeclared prototype also passed its at-least-50% size target on all ten
schema 2 copies, with exact reconstruction independently verified. Its schema 1003
files are experimental, not product databases. `prototype-protocol.json`,
`prototype-summary.json`, `prototype-audit.json` and `prototype-evidence.tar.xz`
preserve that separate screening. The prototype was committed as `89cf34d` before
execution and rejected eleven malformed encodings. Its one-off encoding timings
are not pooled with the production measurements above.

## Production design and acceptance

Schema 3 keeps the existing SQL table layout and explicitly changes the
interpretation of generation values. A versioned prefix, canonical decoded byte
length and canonical base64 identify the compressed text. Decode enforces the
length before expansion, requires exactly one complete zlib stream with no trailing
data, validates exact output length and UTF-8, then runs the same Pydantic model
validation. No malformed compressed value may fall back to plain JSON.

The physical database remains bounded at 256 MiB. The sum of declared decoded
generation lengths also remains bounded at 256 MiB, checked before loading the
head and before publishing changes. A small compressed file must not bypass the
previous bound on aggregate generation JSON. These are separate physical and
logical bounds, not a peak-RSS guarantee.

Schema 1/2 observation remains read-only. A normal writable session upgrades
its captured private copy transactionally, verifies original generation/index
membership and any schema 1 duplicate values, compresses the exact original JSON,
then vacuums only that copy. Existing atomic publication and crash recovery remain
responsible for making the complete new database visible. Older binaries reject
schema 3; no implicit downgrade is planned. Model outputs, IDs, histories, source
references, checks and mutation receipts must remain unchanged.

Acceptance criteria, now completed: exercise both legacy versions, read-only observation,
subsequent writes, rollback, forced process death across publication, corruption
and decompression bounds, concurrent readers, the independent watcher oracle,
all memory/adapter checks and real Linux MCP. Then freeze a separate comparison
on the same ten real databases, reporting first-use conversion cost and five
alternating reads per side. Do not mix prototype timing with production timing or
retroactively change the completed full model experiment.

The standalone watcher oracle was found to still require schema 1's duplicate
state column. Commit `c40f22c` makes it verify schema 2 membership against the
authoritative generation, while retaining the duplicate-value check for schema 1.
Fifteen driver tests passed, including real persisted-state proof and deliberate
missing-membership rejection. The complete live watcher scenario also passed: 24 phases, 39 commands, six
owned processes, all reaped. Its persisted-state evidence is preserved separately
in `watch-schema2-evidence.tar.xz`; the compiler cache is omitted.
