# Offline lossless storage representation prototype

Both bounded encodings pass exact reconstruction. Start with **A** if this becomes
production work: it removes the second copy of each state while keeping stored
RecordState JSON unchanged. B saves more bytes, but adds digest references,
scope reconstruction and another corruption boundary. These files are experimental
encodings, not migrations or production-compatible databases.

| Database | Logical bytes | Pages of4,096 bytes | Difference from original |
| --- | ---: | ---: | ---: |
| Original frozen C4 | 24,862,720 | 6,070 | — |
| A: generation metadata + ordered state membership | 15,007,744 | 3,664 | −9,854,976 |
| B: A + shared immutable edge sets | 7,684,096 | 1,876 | −17,178,624 |

The two derived database files total22,691,840 logical bytes. Both have zero free
pages. Their allocated regular-file bytes are15,011,840 and7,688,192. These are
observed sizes of **freshly built files**; repacking is included. The two-copy bound
excluded a third fresh baseline rewrite, so do not attribute every changed page
to encoding alone. No speed, latency, RSS, model-quality or production saving was
measured. The root full suite could overlap this offline work.

A copies every original table into a fresh database and removes `states` only
from the stored generation JSON. An explicit `(generation, position, record,
revision)` membership table preserves array order, with foreign keys to the
existing state/revision rows. A separate ordinal preserves the location of the
`states` JSON field, so reconstruction restores exact original field order and
bytes. Empty generations remain empty. Existing record_state values stay intact.

B additionally replaces each stored `invalidation_scopes` field with an explicit
experimental encoding containing local scopes and a SHA256 reference to immutable
shared edge content. Whole scope lists are unique after A because each includes
record-local scopes, so sharing those lists would add overhead. The repeated edge
subset instead has two unique lists, totaling22,250 bytes, referenced by658
states. Reconstruction verifies the digest, the JSON/relational reference, token
types, uniqueness and sorted effective scope order. Both old and new relation
edges remain represented; no invalidation explanation or local scope is dropped.

Verification covered all329 record/revision rows,658 states,3 generations,
331 validation events,329 receipts,2 index views,32 source references and the
product head. For every original row, all columns reconstruct exactly. Each state
and generation matches both **original raw JSON bytes** and decoded JSON values,
including10,131,264 state bytes and10,134,130 generation bytes. Generation IDs,
parent links, record order, revision identity and history membership ordered by
sequence remain equal. Every untouched table value matches exactly. This proves
the model inputs are unchanged without executing Pydantic or project code; it
does not prove a production reader or migration has been implemented.

Original and both derived databases pass SQLite integrity and foreign-key checks.
Four deliberate corruptions were rejected: altered shared bytes, missing state
membership, noncontiguous member order, and deletion of a referenced edge set.
All were rolled back; B's final full-file hash equals its initial verified hash.
There were no failed build attempts. The successful first-run log and expected
negative-check reasons are retained.

Compatibility requires an explicit storage version and reader/migration work:

- `src/cami/product/memory/store.py:119` rejects schemas other than user_version1
  and the exact known table set. The derived files deliberately use1001/1002
  plus additional tables, so a legacy reader must reject them.
- The store's `head()` and `history()` parse full MemoryGeneration JSON directly.
  They would need one reconstruction boundary before model validation. A must not
  silently write metadata-only generations under version1.
- B also changes the stored RecordState field type. Any direct state reader needs
  verified reconstruction; missing pool objects, digest mismatch, missing member
  rows, duplicate references or order damage must fail closed. Checks here cover
  representative corruptions, not every future storage failure.
- `tests/watch/cli_driver.py:65–77` parses generation/state JSON directly and
  asserts equality between the table states and `head['states']`.
  `tests/memory/test_memory.py:300` reads raw generation JSON.
  `tests/memory/test_source_excerpt_behavior.py:198,231` fixes user_version1.
  These consumers require explicit compatibility updates, not weakened checks.
- `src/cami/product/service.py:434–436` hashes full state model values into the
  generation ID. Exact reconstruction here preserves those values; a rollout
  must retain identity rules or version them explicitly. Historical IDs and old
  evidence cannot be recomputed casually.
- Schema recognition, durable publication/recovery, read-only observation, old
  database admission, interrupted migration, source verification and concurrent
  readers all remain production design work. This prototype provides none of
  that lifecycle or crash-safety machinery.

The original was opened only with `mode=ro&immutable=1` after confirming there was
no live WAL/SHM/journal family. Its SHA256 remains
`9b2ebeaa56154c261ac9068976ef7f45603fc01f656aba1e22b1bb70c879bda1`.
Final verification rehashed all34 original memory files against the diagnosed
published inventory, including unchanged index generations and source objects.
No namespace was copied; the derived source references still point to that
unchanged external evidence. No original VACUUM, checkpoint or write occurred.

`prototype.py` is a reproducible new-only builder and verifier. `verify_final.py`
rechecks retained file hashes, original provenance inventory, pool/reference
counts and integrity. `prototype-report.json` includes per-object dbstat/page
accounting, exact source/input hashes and all row counts; `queries.json` records
the analysis/build statements used through the query helper. SQL helper schemas,
connection settings and deliberate corruption statements are explicit in the
runner. Only stdlib code was executed. No tracked source, test, HEAD, model,
network, Docker, heldout, child agent or commit was changed or invoked.
