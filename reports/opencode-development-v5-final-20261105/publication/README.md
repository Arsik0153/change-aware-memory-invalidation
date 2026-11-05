# Closed v5 public evidence

This package preserves the completed development v5 exactly. All 36 original terminals are included: 36 quality passes and 35 operational passes. `r3-static-s1` remains failed after controller admission rejected an unknown API system record, while its underlying runtime manifest reports passed. No trial is excluded, retried, relabelled or pooled with an older version. The frozen primary superiority criterion is **not established**. This is development evidence, not a heldout result or a population/causal claim.

`public-evidence.tar.gz` contains every terminal-declared artifact, including explicitly declared evaluation workspace files, plus run/plan/summaries/baselines, all six immutable 329-record catalogs and preparation evidence, namespace identity metadata, frozen study/protocol/runtime sources, exact frozen source pins, study process logs/admission/completion metadata, final aggregate/resource/staleness reports and analysis source/canonical inputs. Full mutable namespace workspaces/Git and OpenCode private/auth state are excluded. Later reliance analyses remain separate; tuple exposure/staleness is not causal reliance.

`final-memory-state.tar.gz` contains only the three final CAMI ProductMemory state trees. Every database must have the expected ProductMemory table set/user version and 329 stored typed literal revisions matching its immutable catalog after removal of the runtime-only index certificate from `origin_source`. Expected text, truncation, subject, span, source path/SHA/size are retained and compared. Final state hashes must match each namespace's original stage-4 terminal. This is a usable memory snapshot, not OpenCode authentication state or a complete history/source-workspace backup; original `/workspace` identity and external runtime dependencies still matter for continuation.

Both archives contain an internal `PUBLICATION-MANIFEST.json` with every file's SHA256, size and safe mode. Tar/gzip owner/time/header metadata is deterministic. A second build must match exactly, extraction must read back every file, and all source signatures/hashes must remain unchanged. Published already-redacted bytes are copied exactly; no additional transcript redaction is performed. Private paths, nonregular entries, hardlinks, privileged files, credential-valued JSON keys and JWT/auth-shaped strings are refused. These bounded checks do not prove detection of arbitrary opaque or encoded secrets. No private credential state is inspected.

Build only into this new owned stage with source inputs still present:

```sh
.venv/bin/python runs/opencode-development-v5-publication-20261105/build_publication.py \
  --repo "$PWD" --out "$PWD/runs/opencode-development-v5-publication-20261105"
```

For offline reproduction, safely extract `public-evidence.tar.gz` into a new owned empty directory (regular-file members only), then run the included helper with a new separate output:

```sh
python /EXTRACTED/runs/opencode-development-v5-publication-20261105/reproduce_analysis.py \
  --root /EXTRACTED --out /NEW_ANALYSIS
```

The helper hashes every declared public file before executing the included unchanged aggregator. It supplies the byte-identical extracted frozen study explicitly, without editing its absolute paths. The entire aggregate must match the archived report except its relocated `run` path; all three CSVs must match byte-for-byte. The original failed trial, its diagnostic, all 36 terminal hashes and artifact coverage must remain exact. It also replays the unchanged literal staleness analyzer and compares counts/coverage/integrity-support categories. No model, Docker, target source or network is used for this replay. Python 3.12 standard library is sufficient; the OpenCode binary/image/credentials are not needed for aggregation and are not bundled.

Packaging, hashing, compression, readback and offline analysis are separately measured publication/evaluation overhead, never trial cost. See `admission.json`, `packaging-report.json`, `offline-analysis-verification/verification.json` and the final handoff manifest. Do not overwrite an existing completed archive/extraction; a failed packaging attempt is preserved under a separate failure JSON.
