# Removing duplicated SQLite state values

The full80-attempt experiment identified about42MB of source memory per block.
The36.8MB SQLite file contains the same generation states in memory_generation.value
and record_state.value. The second value is never read by the product; record_state
only indexes generation/record/revision for history. Schema2 keeps that index and
the authoritative complete generation once.

New databases use schema2. A normal writable session upgrades an exact schema1 DB
inside the already captured private copy. Before removing duplicates, every old
state index/revision and decoded value must match its authoritative generation.
Divergence fails closed without publishing. The rewrite is transactional, VACUUM
runs only on the private copy, and existing atomic publication/recovery remains in
charge. Read-only observation accepts both versions and never upgrades in place.
Historical records, checks, sources, receipts and generation identities are retained.
Old software refuses schema2; downgrade is not supported. Backups of original v1
experiment data remain immutable.

Validation before measurements:256 memory tests,186 adapter tests and40 watch tests
passed (one watch test skipped). They include actual legacy-reader compatibility,
read-only observation, interrupted upgrade, divergent-copy rejection, concurrent
readers and publication recovery. The obsolete source-projection test explicitly
uses schema1 so that it still tests payload compatibility independently of schema2.

protocol.json fixes ten source databases (five CAMI and five CAMI+replay), code
hashes, a first operation including migration, and five alternating warm operations
per copied store. The baseline implementation is preserved in baseline_store.py.
Operations include validated open, head/revisions/view, source-byte checks and
serialization. Logical rows, sampled histories and public outputs must remain equal;
original files must remain unchanged. Primary target: at least35% smaller database
in every case. Warm timing reports median/range; overlapping ranges do not establish
speedup. This is a local store measurement, with no model calls or new whole-agent
speed claim. The completed full-model result continues to describe the prior code.
