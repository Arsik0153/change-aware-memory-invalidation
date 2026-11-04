# Closed v3 public evidence preservation

This package preserves one completed development study: 36 terminal attempts, all operational/quality passed. It does not pool v1/v2 failures or contain a new experiment. Those failed versions remain separate in their original reports. The original source records and outcomes are never rewritten.

`public-evidence.tar.gz` contains every exact terminal-listed file, including the authorized evaluation-workspace bodies, plus terminal records, frozen run/study/plan/host metadata, intermediate summaries, baseline public reports, common immutable catalogs and preparation evidence, frozen implementation/protocol source pins, development task bundle assets, final analysis/staleness/figures and their scripts/inputs, and the metadata-only timing caveat evidence. Namespace workspaces are excluded wholesale. No final heldout task/source/gold, OpenCode session database, private auth/export state, credentials, Docker image or OpenCode binary is admitted. The timing-preflight folder contributes exactly the referenced phase-timing metadata, not its approval/account/task/runtime payloads. The initial overbroad timing-metadata admission was refused at an authorization-valued field; its failure record is retained and no rejected body was archived.

`final-memory-state.tar.gz` is separate and optional for analysis: only the three final CAMI ProductMemory state trees. It includes their source CAS, index generations and ProductMemory SQLite databases. Schema checks require the known ProductMemory tables, reject credential/session tables, and compare all stored manual-note revisions with the frozen 329-record source-only catalog. This is not global OpenCode state, a complete dataset backup, or complete Git history.

The archive members preserve repository-relative paths and original safe file modes. UIDs/GIDs and mtimes are fixed to zero. Only regular files are admitted. Source paths are opened through no-follow directory descriptors, and linked/special/privileged files, duplicates, unsafe paths and source changes are refused. The public session sanitation guards must already be passed; an additional structured-key/JWT/auth-pattern scan refuses detected credential material. No private credential file is read to build this archive. Opaque secrets cannot be recognized from arbitrary strings alone; the published guards and frozen source-catalog origin are part of the evidence boundary. Rejected payloads are not copied into a raw quarantine.

Tracked controller/harness code changed after study closure. Where necessary, archive copies recover the exact study-pinned source bytes with read-only `git show 18188a7:path`, verify their declared hashes, and place them at the original archive paths. Current tracked files are not modified. Every fallback is recorded externally in `admission.json` and `packaging-report.json`.

Each archive has `PUBLICATION-MANIFEST.json` covering all member SHA-256/size/mode values. Verification extracts to new owned directories without accepting links, checks every member, compares a second deterministic build byte-for-byte by hash/size, and rechecks admitted originals unchanged. Packaging CPU/wall/storage are separate publication overhead, never charged back to a trial. Reproducibility of compressed bytes is checked in the recorded Python/zlib environment; portable raw file identity is independently hashed.

Build from the repository root (new/owned output directory with these three scripts/doc files present):

```sh
.venv/bin/python runs/opencode-development-v3-publication-20261104/build_publication.py --repo "$PWD" --out "$PWD/runs/opencode-development-v3-publication-20261104"
```

After extraction, offline verification uses only archived public inputs:

```sh
python path/to/reproduce_analysis.py --root /absolute/extracted/public-evidence --out /absolute/new-analysis-check
```

The existing aggregator runs unchanged with its study override. The original timing-caveat JSON is retained untouched; the helper creates a separate path-only relocation derivative and verifies the same timing-evidence SHA. Aggregate summaries, all terminal artifact hashes/coverage and final staleness counts must match the archived original outputs. No model, Docker or target-source execution occurs. Absolute analysis output paths necessarily differ.

The evidence disqualifies charged-wall superiority because of the recorded infrastructure overlap. It is development evidence with dependent repetitions and two task instances, not a final heldout, causal, population or billing claim. The original normalized-counter and missing-provider-field caveats remain in the preserved reports.
