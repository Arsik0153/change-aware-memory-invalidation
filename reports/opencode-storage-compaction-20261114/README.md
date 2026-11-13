# Removing duplicated SQLite state values

The full 80-attempt experiment identified about 42 MB of source memory per block.
The 36.8 MB SQLite file contains the same generation states in memory_generation.value
and record_state.value. The second value is never read by the product; record_state
only indexes generation/record/revision for history. Schema 2 keeps that index and
the authoritative complete generation once.

New databases use schema 2. A normal writable session upgrades an exact schema 1 DB
inside the already captured private copy. Before removing duplicates, every old
state index/revision and decoded value must match its authoritative generation.
Divergence fails closed without publishing. The rewrite is transactional, VACUUM
runs only on the private copy, and existing atomic publication/recovery remains in
charge. Read-only observation accepts both versions and never upgrades in place.
Historical records, checks, sources, receipts and generation identities are retained.
Old software refuses schema 2; downgrade is not supported. Backups of original v1
experiment data remain immutable.

Validation before measurements: 256 memory tests, 186 adapter tests and 40 watch tests
passed (one watch test skipped). They include actual legacy-reader compatibility,
read-only observation, interrupted upgrade, divergent-copy rejection, concurrent
readers and publication recovery. The obsolete source-projection test explicitly
uses schema 1 so that it still tests payload compatibility independently of schema 2.

protocol.json fixes ten source databases (five CAMI and five CAMI+replay), code
hashes, a first operation including migration, and five alternating warm operations
per copied store. The baseline implementation is preserved in baseline_store.py.
Operations include validated open, head/revisions/view, source-byte checks and
serialization. Logical rows, sampled histories and public outputs must remain equal;
original files must remain unchanged. Primary target: at least 35% smaller database
in every case. Warm timing reports median/range; overlapping ranges do not establish
speedup. This is a local store measurement, with no model calls or new whole-agent
speed claim. The completed full-model result continues to describe the prior code.

## Results

The storage target passed in all ten cases. Median database size fell from
36,755,456 to 20,533,248 bytes (44.13%); every authoritative SQL row, public output
and sampled record history remained equal. The copied store directory median fell
from 41,454,727 to 25,232,519 bytes; this directory excludes the outer seed/catalog.
An independent audit rechecked physical hashes, SQL contents, output projections,
original-file preservation and measurement arithmetic ([audit.json](audit.json)).

The first operation, including schema conversion, took a median 0.500 s versus
0.187 s for the baseline (ranges 0.449–0.671 s and 0.181–0.270 s). Five alternating
subsequent operations per case gave median-of-case-medians 0.161 s versus 0.184 s.
All ten case medians improved, but five case ranges overlap: **the warm latency
result is inconclusive**, not a proven speedup. See [summary.json](summary.json)
for all samples. No model requests were made.

Six real Linux MCP checks on fresh schema 2 stores and one real MCP operation
upgrading a copy of the prior run's schema 1 database passed. The original database
hash remained unchanged. Two additional SIGKILL tests, before and after main-file
publication during upgrade, recovered the identical history. These complement
256 memory, 186 adapter and 40 watch tests (one watch skip).

Production source is commit `3075b76`; Linux admission used immutable runtime-v10.
[protocol.json](protocol.json) pins measurement inputs and code, and
[admission.tar.xz](admission.tar.xz) preserves Linux evidence. Local measured copies
remain under `runs/local-resume-20261113/store-compaction/measured-v1`; originals
are reconstructible from the preceding full experiment's evidence archive.

A separate CPU profile ([cpu-profile.json](cpu-profile.json)) is not part of the
timing samples. It found 6,856 repeated lexical path validations per operation;
validation and JSON parsing now dominate the smaller database's local read path.
That finding motivates a separate optimization and measurement, not a revised
claim for this experiment.
