# Read-only memory storage diagnosis

Both first-block final quiet namespaces, C2 and C4, have the same SQLite storage
layout. The dominant cost is repeated serialized state evidence, not free pages.
This diagnosis ran only stdlib inspection code, with no project imports, model,
network, Docker, migration, compression, checkpoint or VACUUM.

| Measured bytes | C2 | C4 |
| --- | ---: | ---: |
| Memory directory regular-file logical bytes | 29,046,737 | 29,046,756 |
| Memory directory regular-file allocated bytes | 29,106,176 | 29,106,176 |
| SQLite logical/allocated bytes | 24,862,720 | 24,862,720 |
| Index generation files, logical | 2,797,688 | 2,797,688 |
| Source objects, logical | 502,463 | 502,463 |
| Prepared files plus seed files, logical | 881,648 | 881,648 |
| Entire selected namespace regular-file logical bytes | 30,578,871 | 30,578,858 |

Each memory directory has34 files. Each SQLite database has6,070 pages of4,096
bytes, zero freelist pages and delete journal mode. No WAL, SHM or rollback-journal
sibling existed before or after inspection. Originals were opened with
`mode=ro&immutable=1`, query-only enabled; no database copies were necessary.
Every memory-directory file matched the published manifest before inspection and
retained its full inventory afterward, including SHA256, size and allocation.

| SQLite object | Allocated bytes | Cell payload bytes | Unused bytes |
| --- | ---: | ---: | ---: |
| record_state | 10,936,320 | 10,221,410 | 690,601 |
| memory_generation | 10,145,792 | 10,134,544 | 1,309 |
| index_view | 1,650,688 | 1,647,710 | 1,342 |
| record_revision | 962,560 | 717,147 | 239,913 |
| validation_event | 684,032 | 495,894 | 183,682 |
| operation_receipt | 176,128 | 153,314 | 20,306 |
| All remaining objects, including autoindexes/schema | 307,200 | 218,939 | 78,825 |

The two largest tables account for84.794% of the file. Full page accounting is
23,588,958 payload +1,215,978 unused +57,784 headers/pointers/other =24,862,720
bytes. Unused space is4.891% and the freelist is empty; this does not support
free-page cleanup as the main intervention. Every table/index is separately
reported by `dbstat` in `storage-report.json`; object sizes include overflow pages.

There are329 records and revisions,658 record states,331 validation events,
329 operation receipts,3 memory generations,2 index views,32 source references
and1 product head. Two generations contain329 states each; the third is empty.
The largest generation JSON is5,246,317 bytes. Each record state JSON is
14,272–17,825 bytes, median15,465 and nearest-rank p95 16,791. Record revisions
are1,551–4,000 bytes, median1,875. Two CodeView JSON values total1,647,570 bytes.

Exact raw JSON substring accounting finds7,373,628 bytes of `invalidation_scopes`
in the658 state rows: median11,223 bytes per list, with156–157 items each. Of
102,977 total items,101,661 are graph-edge hashes; only1,316 are the two local
dependency scopes per row. There are just two distinct edge lists, with154 and155
edges, each repeated329 times. Their canonical list bytes total7,320,250 across
the state rows, versus22,250 bytes for the two unique lists once each.

The **same658 complete state JSON values, totaling10,131,264 bytes**, also occur
byte for byte inside `memory_generation.value.states`. This was checked by
generation ID, record ID, exact byte length and SHA256 for every state, rather
than inferred from equal sizes. Consequently the scope JSON alone occupies
14,747,256 bytes across those two representations,59.315% of the whole database.
These nested numbers overlap; they must not be added to table sizes or to one
another.

The frozen production writer explains both repetitions:

- `cami/product/memory/validation.py:128–135` unions each record's dependency
  scopes with all previous/current relation edges. Its comment explicitly keeps
  both edge sets for invalidation explanations, including deleted edges.
- `cami/product/memory/models.py:262–276` embeds those scopes in each RecordState
  and embeds every RecordState in MemoryGeneration.
- `cami/product/memory/store.py:288–295` writes the whole generation JSON, then
  writes every full state JSON again in `record_state`. Lines306–320 show history
  consuming generation snapshots, revisions and validation events.
- `cami/product/service.py:434–436` includes full state values in the generation
  ID digest. A representation change must reconstruct those same values or use
  an explicit versioned identity/migration contract.

One evidence-backed candidate is to **store immutable transition edge sets once
and reference them from each stored state**, while retaining record-local scopes
and reconstructing exactly the existing effective sorted scope list. Both old
and new edges, source bindings, validation/check history, fail-closed behavior and
generation identities must remain available. The repeated edge-list content is
14,640,500 bytes across the two current representations, compared with22,250
bytes for the unique lists once: a14,618,250-byte representation-only upper
bound before reference/format overhead. This is not measured file savings,
and does not justify deleting history or claiming lower RAM/latency. No candidate
was implemented or benchmarked.

Source objects are verified provenance, and immutable index/CodeView generations
support prior/current interpretation. The diagnosis does not establish that
these artifacts can be discarded as caches. The demonstrated redundancy is the
multiple representation of the same edge/state evidence. The writer also uses
whole-database serialization (`store.py:112–130`); that links database size to
one explicit byte-image operation, but no process RSS or peak-memory reduction
was measured here. Full-suite overlap invalidates timing comparisons.

`storage-report.json` records exact input file inventories, publication/freeze
hashes, matched C2/C4 historical source pins, per-object pages/row counts, serialized
field distributions and unchanged-original checks. Field sizes are exact original
JSON value substring UTF8 bytes; parents overlap their children. `queries.json`
contains every analysis SELECT/metadata PRAGMA. Connection-local query-only and
2MiB cache settings are visible in the runner. `diagnose.py` reproduces the bounded
inspection without importing or executing project code. No full row or source-text
dump is included. These are two selected snapshots, not a growth/scaling model or
a basis for choosing Rust or compression.
