# Terminal-only development memory exposure summary

This read-only wrapper uses the existing `scripts/analyze_opencode_staleness.py` literal-source analyzer. It does not modify/import the controller, harness or CAMI, call models, use Docker, inspect heldout data, or traverse active trial contents/private state. Its authored tests finish in about0.02 seconds; the current actual snapshot ran in under1 second.

```sh
.venv/bin/python runs/opencode-terminal-staleness-development-20261104/summarize_terminal_staleness.py \
  --run runs/opencode-development-v3-20261104 \
  --analyzer scripts/analyze_opencode_staleness.py \
  --catalog runs/opencode-development-v3-20261104/namespaces/r1-static/memory/prepared/catalog.json \
  --origin runs/opencode-development-v3-staleness-20261104/origin-and-stage1 \
  --stage1 runs/opencode-development-v3-staleness-20261104/origin-and-stage1 \
  --stage3 runs/opencode-development-v3-staleness-20261104/stage3 \
  --out runs/opencode-terminal-staleness-development-20261104/NEW_SNAPSHOT
```

Outputs must be new and separate. Copy `summarize_terminal_staleness.py` and `classify_memory_calls.py` together. The analyzer remains an explicit, hash-recorded input. The catalog is an explicitly selected immutable input, not an automatic scan of mutable memory state. Its raw file hash must match each terminal's immutable catalog hash and its hashed `memory-before.json`; its canonical JSON hash must match every response/backend trace. Plain has an explicit empty external-memory result and no catalog exposure; this says nothing about whether model knowledge is current.

The script snapshots only the36 registered terminal filenames. It then reads payloads only for trials that already have `terminal.json`; active paths are never inventoried. All completed trial artifact hashes and exact file coverage are verified, with private/nonregular entries refused without reading. The canonical extracted full-file inventories/modes must equal each terminal's hashed source reset. Their hashes are checked again after memoized analysis. Study/plan/catalog/analyzer/source-tree/message/terminal provenance is retained.

Returned and withheld IDs are independently checked for uniqueness, catalog membership, disjointness and selected-count coverage. Returned payload/source bindings must match the frozen catalog; withheld kinds/subjects must match it. Returned-ID coverage is crosschecked against the existing analyzer. Backend trace query hashes bind canonical full tool arguments (including limit), rather than just query text; returned/withheld counts and catalog/backend identities must reconcile. Unsupported calls, reported IDs, classifications and backend joins remain explicit.

Each observation retains its trial, call ID, record ID, channel (`returned` or `withheld`), kind, literal assessment and source fingerprints. Typed records are labeled separately and are not interpreted as literal notes. Source-note assessments distinguish obsolete literal prefixes, unchanged literal prefixes, absent definitions, unknown after a possible/overlapping write, unavailable source and unsupported bindings. Shell/unknown tools conservatively count as possible mutation. No later lookup is upgraded by substituting the canonical base for edited source. Withheld comparisons describe records that were not returned as note content; unchanged withheld text does not establish incorrect withholding under sticky manual-review policy.

**Literal boundary:** the existing extractor uses `str.splitlines(keepends=True)`, the earliest decorator line, and prefix `[:2400]` characters. This wrapper preserves those semantics. It does not use `ast.get_source_segment`, infer complete-body equivalence, compare truncation-marker equality, or establish semantic/behavioral truth. The canonical Python sources are separately screened for VT, FF, FS/GS/RS, NEL, U+2028/U+2029 and bare CR. Any affected module is explicitly flagged unsupported for line boundaries; there is no silent extractor fix. Current canonical sources have none of those risks.

Causal reliance is always `not_inferred`. The source classification does not establish that a model used a note to make a decision, that an obsolete excerpt caused a failure, or that withholding caused success. Those questions need separate evidence-backed action review.

## Current snapshot and limits

`terminal-snapshot-final/report.json` includes17/36 terminal trials and3813 verified artifact hashes. All assessed evidence, calls and backend joins are supported. These are repeated observation counts, not independent claims or causal events:

- Static returned4 obsolete prefixes,21 unchanged prefixes and2 unknown observations after possible writes.
- CAMI returned20 unchanged prefixes; withheld4 obsolete prefixes,6 unchanged prefixes and2 unknown observations after possible writes.
- No typed-record observations occurred in this snapshot. Plain records explicitly report no external memory.

This is a partial snapshot. Rerun the same CLI into a **new** directory after all36 terminals exist. `complete_36`, snapshot IDs, unsupported lists and `all_assessed_evidence_supported` make coverage explicit; unsupported observations are never silently included as known literal results.

Earlier snapshots remain unchanged. `terminal-snapshot-v1` preserved an analysis-side query-hash mismatch: the backend field hashes canonical full arguments, not the query string. That check was corrected, covered by an authored regression test, and reconciles in v2/final. Classifications were not changed to fit model outcomes.

```sh
.venv/bin/python -m unittest discover -s runs/opencode-terminal-staleness-development-20261104 -p test_staleness.py -v
.venv/bin/ruff check runs/opencode-terminal-staleness-development-20261104/*.py
```

Nine fast authored controls cover both channels, after-write unknowns, typed records, invalid/duplicate IDs, withheld-subject mismatch, full-argument backend hashing, exotic separator flags and terminal artifact tampering. CLI results and final dependency hashes are in `handoff-manifest.json`.
