# Per-module source-line reuse

The parser now prepares physical source lines once per module when a function is indexed. UTF-8 column slicing and decorator exclusion match CPython 3.12.12 from the pinned OpenCode runtime. The separate decorator-inclusive literal-excerpt extractor is unchanged.

All 127 targeted tests passed. Four complete Click indexes (origin and changed source, with and without graph edges) matched the old implementation in every field, including provenance. Each indexed 512 definitions; line preparation occurred 15 times instead of 512. These are functional operation counts, not a measured speedup. Full verification and repeated actual-tool timing are separate follow-up evidence.

The local tuple lives only during one parse and is not a persistent cache. Preparing all lines can do extra work for files with one early function and a long unused tail; no universal speedup is claimed.

The manifest binds the exact implementation, tests, pinned stdlib reference, comparison checker and results. Evidence is copied byte-for-byte from the recorded runs directory; original paths are retained. No model calls, held-out tasks or historical trial changes occurred.
