# Bounded reuse of lexical path validation

The preceding CPU profile found 6,856 lexical path validations in one validated
store operation. Each reconstructed `PurePosixPath` even when identical text had
just passed validation. The change preserves the original predicate and error
messages; it remembers successful validation for at most 1,024 plain strings of
at most 512 characters. Long strings and string subclasses use the original
uncached predicate. Filesystem state, file content and memory availability are
never cached by this helper.

Production baseline: `7e9b377` (same source as Linux runtime-v10 `3075b76`).
Candidate: `6380b2d`. Frozen measurement harness: `1a01265`, runtime-v11.
The source change affects the analyzer fingerprint, so an existing memory store
must recertify its current source on first access; that cost belongs in the cold
MCP observation. The full 80-attempt model experiment remains evidence for its
earlier frozen implementation.

The intended claim is lower latency for a validated store read and the complete
MCP process on these copied development stores. This is not a prediction of total
model-session speedup. The earlier backend trace was under 1% of model-session
wall time, excluding some transport/startup costs. Removing a fraction of that
work cannot explain a large whole-agent improvement.

Two protocols are fixed before timings:

- `local-protocol.json`: ten schema 2 stores, five alternating fresh processes per
  side per store. Each process starts with an empty lexical cache. All file hashes
  and exact public-output hashes must remain unchanged. Both internal operation
  and process time including Python imports are reported.
- Linux `path-mcp-protocol.json`: ten original source-memory stores, one cold
  first process per side, then five alternating new processes per side per store.
  The cold process includes schema conversion and analyzer recertification.
  Every process performs MCP initialize, tools/list and one readable exact-ID
  lookup, then exits. Timing includes process startup, transport and shutdown;
  Docker lifecycle is recorded separately. The real wire response must preserve
  the expected literal, source binding and supported status, with a valid numeric
  receipt and no backend error.

OS file caches are uncontrolled, with interleaving to reduce drift. No test suite
runs concurrently with timed measurements. All attempts are retained; failures
prevent a positive verdict. A consistent speed claim requires separated observed
ranges in all ten cases. These ranges are not population confidence intervals.
No model calls are made in these storage/MCP measurements.

Behavior comparison against the frozen original validated 37,470 path strings,
including all strings of length 0–5 over eight path-relevant characters and long
boundary cases. Both repeated calls produced identical outcomes and exact error
messages: [validation-audit.json](validation-audit.json). Unit tests separately
cover preservation of identity and unhashable string subclasses.

## Completed result

The strict all-ten-ranges criterion is **not met**. Results are promising but
inconclusive under that criterion: every case median improved, and eight of ten
observed ranges separate in each measurement. Two overlap. No trials were
repeated, removed or extended after observing these results.

| Measured span | Median of ten case medians, before → after | Reduction |
|---|---:|---:|
| Validated store operation | 132.28 → 115.85 ms | 12.42% |
| Complete local Python process | 271.21 → 254.57 ms | 6.14% |
| Complete Linux MCP process | 527.79 → 499.23 ms | 5.41% |

Each case has five alternating samples per side. Complete MCP case medians range
526.01–536.82 ms before and 493.72–513.35 ms after; those are ranges of medians,
not the wider individual-sample ranges used for the strict decision. Full samples
are in `local-summary.json` and `mcp-summary.json`. First MCP processes, including
schema conversion and context recertification, had medians 1.265 s before and
1.236 s after (ranges 1.233–1.331 s and 1.189–1.403 s).

The local worker recorded 6,840 lexical-cache hits and 16 misses in its first
candidate process. All 100 local process outputs matched the frozen exact hashes;
all source files and copied databases remained byte-identical. All 120 MCP
processes returned the expected supported literal, source binding and valid wire
receipt, with zero backend failures and no model calls. Independent audits
re-read raw process/response receipts and arithmetic. They also verified exactly
one new persistent generation in each MCP namespace and an unchanged generation
identity across its five subsequent calls.

The first draft of the MCP auditor incorrectly treated the trace field
`generation_changed` as a comparison with the persisted database head. It actually
compares with a process-local last generation, initially `None`, so it is true on
every new process's first lookup. The auditor was corrected to compare actual
returned generation IDs and persisted SQL history; no measurement was rerun or
changed. Cold recertification includes the canonical reset's capture-policy
change on both sides, plus the changed analyzer fingerprint on the candidate.

The full project suite passed **1,750 tests**, with one skip and four Docker-marked
tests deselected, before measurements. Ruff passed. The real MCP measurements
provide additional Linux integration coverage. This small bounded optimization
is retained with preserved semantics; its observed 5.41% MCP median reduction is
descriptive, not an established universal or whole-agent speedup. The stronger
full-model exact-reuse and database-size results remain separate.

`local-receipts.tar.xz` preserves raw subprocess receipts. Its unchanged SQLite
inputs are the schema 2 copies from the preceding storage experiment.
`mcp-evidence.tar.xz` preserves every Linux trial, resulting stores, inputs and
container reports. `audit_local.py` and `audit_mcp.py` reproduce their respective
audits; the latter also takes the original full-model export as its third path
argument. Source snapshots can be reconstructed from the pinned commits.
