# Lossless generation JSON compression

The offline screening target passed on all ten schema 2 databases. Encoding only
`memory_generation.value` with zlib level 1 and canonical base64 reduced SQLite
size by more than 62%, beyond the earlier duplicate-removal change. Every SQL row
reconstructed exactly, including the original UTF-8 generation JSON bytes.
Original files remained unchanged. The independent auditor uses only stdlib SQL,
base64 and zlib, without importing the prototype codec.

This result currently describes **experimental schema 1003 copies**, not a
production migration or a speed improvement. `prototype-protocol.json` records
the predeclared algorithm and at-least-50% size target; `prototype-summary.json`
retains every case and `prototype-audit.json` verifies reconstruction. The
screening implementation was committed as `89cf34d` before execution. Its bounded
decoder also rejected eleven malformed/truncated/oversized/concatenated encodings.

## Production design and acceptance

Schema 3 will keep the existing SQL table layout and explicitly change the
interpretation of generation values. A versioned prefix, canonical decoded byte
length and canonical base64 identify the compressed text. Decode must enforce the
length before expansion, require exactly one complete zlib stream with no trailing
data, validate exact output length and UTF-8, then run the same Pydantic model
validation. No malformed compressed value may fall back to plain JSON.

The physical database remains bounded at 256 MiB. The sum of declared decoded
generation lengths also remains bounded at 256 MiB, checked before loading the
head and before publishing changes. A small compressed file must not bypass the
previous bound on aggregate generation JSON. These are separate physical and
logical bounds, not a peak-RSS guarantee.

Schema 1/2 observation must remain read-only. A normal writable session upgrades
its captured private copy transactionally, verifies original generation/index
membership and any schema 1 duplicate values, compresses the exact original JSON,
then vacuums only that copy. Existing atomic publication and crash recovery remain
responsible for making the complete new database visible. Older binaries reject
schema 3; no implicit downgrade is planned. Model outputs, IDs, histories, source
references, checks and mutation receipts must remain unchanged.

Before a production claim: exercise both legacy versions, read-only observation,
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
