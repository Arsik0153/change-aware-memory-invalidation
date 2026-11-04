# Independent Packaging result audit

The seven audit Python files installed together under `scripts/` form a separate stdlib-only audit bundle. Audit decisions import neither CAMI production code nor the replay driver/support nor the reference checker. `packaging_audit_common.py` reuses independently authored JSON/hash/signature/state/aggregate primitives from the earlier Click audit (original source SHA256 `7e43e21f39a45eebcc2bb9409e8b2b3b66b8253a481d2c6cac1eea513f6fbc96`). The new lexical binding, module/index summaries, complete parent ranking, review gate, topology, trajectory checks and projections are separately implemented here. Shared CPython 3.12 `ast` and `ast.dump` remain an explicit common dependency.

Implementation and authored data/schema controls preceded the first actual project read. Root then authorized final source at `b9602184b035f0eb211526c4628e800cb4e9202c` and separately notified that acquisition/replay were complete. Actual audits access only the exact 72 authorized Packaging snapshot IDs; full side-parent lists are checked as commit metadata, and side-parent trees are never read. No Git fetch, project source execution or heldout project access occurs.

Root supplied preliminary result claims while implementation was underway. Outcome quantities are recomputed from raw records and are not acceptance constants. This is an independent reanalysis with prior awareness of those claims; no blinded-replication claim is made.

## What is verified

The real protocol and seal SHA256s are independently pinned in `packaging_audit_inputs.py`. The audit verifies all 2,378 output artifact files and exact file layout, 578 sealed inputs, 272 historical source files and matching source-before/source-after snapshots. Every sealed file and source entry is tied to historical Git bytes at the recorded implementation commit, allowing a later current HEAD or working tree. The 53 production Python files are individually compared to workspace commit `700ebf2`; the unchanged reference v2 source is bound to SHA256 `d8e6fc722e08e36b5576d6469ca6c4c6a932f4f9d085fba3600d21fb6bde0e1a`. Frozen source files are inspected as data and are never imported for audit decisions.

The metadata-informed v2 amendment, prior failed v1 bindings, exact 72-frame and three disjoint parent-plus-23-child windows are checked independently. Actual full parent lists are checked for all 72 commits. Complete snapshot trees bind blob object IDs, modes, sizes and readable raw bytes; every readable body is independently checked against its Git blob hash. Raw exact-path reference packets are compared to the authorized Git tree and bytes. Independent lexical AST decisions cover direct, absent, conditional, duplicate and rebound definitions, class-global hazards, signatures, parse failures and unsupported modes/ancestors. They reproduce the complete reference verdict, facts, reason, evidence and checker metadata, while production validation verdicts and reasons are computed separately from independently built index summaries.

All parent module and function-occurrence inventories, exclusions and full SHA256 ordering are recomputed. The selected first four eligible functions per parent must produce the exact 24 new-derived claims, predicates, full claim hashes and source/AST identities. The three inventories contain 84/85/85 tree entries and 14 eligible Python modules each, with 75/77/79 eligible direct subjects. They cover 42 parent module occurrences and 37 distinct module blob OIDs; the 12 selected path/function identities are distinct in this cohort. These counts do not make the histories or observations statistically independent.

All six declared AI contexts and 36 public parent/control cases are bound to exact packets, private maps, full derived claims, source identities and reference records. All 12 authored controls must pass the reference and both AI records, and eligibility/exclusion reasons must follow those bound decisions. Input/response token estimates and their byte bindings are checked as named estimator artifacts; the auditor does not recount tokens or claim actual context/billing measurements. Model/provider identity and context independence remain declared rather than verified.

The audit recomputes file, symbol, import/call-edge, limitation and unresolved changes; all four policies' selections, validation identities/input hashes, provenance, prior/current states and availability; exact parent/child/reference/index cost row multiplicities; all 24 parent rows and 2,208 candidate child-policy rows; all 576 runtime reference packets; all full23/prefix12/group/kind/merge projections; unique contradicted claims, first observations, repeated observations and observed consecutive runs. It checks the 146 recorded resource checkpoints and caps. Recorded costs and clocks are reconciled as raw evidence, not treated as independent observation of past physical executions.

## Verified result and limits

Child validation calls are 28 for symbol anchors, 71 for file anchors and 552 each for known-incomplete and all-validate. Per variant, 528 reference observations are supported, 24 contradicted and zero uncertain; false availability, available-unknown and withheld-supported are all zero. The 24 contradicted rows come from two signature claims: two first observations plus 22 repeated observations, in runs of 21 and three ranks. Prefix12 has 10 contradicted rows and 13/38/288/288 validation calls. The 43 additional file-only validations are supported observations. The symbol variant's 28 calls include 24 contradicted and four supported results; all four variants select 22 repeated checks because the prior state is unavailable.

The audit separates phase3 reference records (36) from runtime parent (24) and child (552) reference records, totaling 612 across those phases. Parent initialization contributes 96 production calls separately from the 1,203 child production calls; 72 shared indexes are recorded separately. These heterogeneous units are not a speed estimate.

All 69 actual transitions are nonmerge. The empty merge projection retains null rates and supplies no empirical merge evidence. These are paired syntactic predicates on 12 function occurrences in one new derived development cohort, with repeated observations and overlapping descriptive projections. There is no causal merge claim, population-level safety bound, wall-time speedup, broader-project generalization, behavioral API-break/equivalence conclusion, main admission, human label credit or change to the original 630 claims. V2 remains a disclosed metadata-informed amendment after the original 24-successor plan failed feasibility.

The trusted protocol/seal and local Git ODB are integrity roots, not signatures or an independent record of all past actions. Raw record reconciliation does not prove past physical call execution, information-flow isolation or actual model independence. The syntax/index implementation is bounded to the frozen CPython contract; it is not an executable runtime-binding oracle.

## Install and rerun

Copy all seven `.py` files beside one another, normally into `scripts/`. The auditor requires the historical workspace Git objects, recorded frozen inputs and authorized project object database. It never fetches missing objects. Both entrypoints require a fresh output directory and preserve prior outputs.

```sh
.venv/bin/python scripts/audit_packaging_replay.py \
  --root /path/to/workspace \
  --result reports/research-20261104/packaging-replay-v2 \
  --out runs/packaging-independent-audit-NEW
```

Use `--repo /absolute/path/to/offline/git/repository` to read an equivalent extracted project ODB while retaining the frozen workspace inputs and exact 72-ID allowlist. `--authored-fixture` is exclusively for generated test workspaces carrying the explicit `AUTHORED_FIXTURE_ONLY` marker; normal real auditing always enforces the pinned real protocol/seal.

```sh
.venv/bin/python scripts/check_packaging_result_audit.py \
  --root /path/to/workspace \
  --result reports/research-20261104/packaging-replay-v2 \
  --out runs/packaging-independent-real-controls-NEW
```

Omit `--result` to generate a self-contained authored Git history and complete production replay, then audit it independently. That fixture generation needs the existing research environment and installed authored driver tests; audit decisions themselves remain stdlib-only. The checker can reuse an existing authored fixture with `--fixture-root PATH --fixture-result PATH`. Every tamper copy is rehashed before auditing; originals remain untouched. Reports record the original and altered manifest SHA256s, rejection messages, stdout/stderr and the exact seven-file audit bundle hashes.

## Preserved evidence

`initial-audit-report.json` is the unchanged first actual audit. Its auxiliary population key `modules` originally counted tree-inventory entries; `report.json` corrects that label to `tree_entries`, adds actual Python-module counts and audit runtime source hashes. Decisions, coverage, states and aggregate findings are unchanged. The original and corrected reports are both preserved.

`authored-controls-report.json` and `authored-tamper-controls.json` exercises all nine rehashed dimensions, including unknown-as-contradicted on actual uncertain fixture rows. `installed-controls-report.json` and `installed-tamper-controls.json` exercises eight applicable dimensions: missing observation, forged source, reference, state, cost, aggregate, topology and parent gate. Unknown-as-contradicted is explicitly not applicable to the real result because it contains no uncertain reference rows. Earlier failed fixture iterations and earlier successful audit/control iterations remain preserved; they are not silently overwritten or substituted for the final evidence.

The installed positive audit used the extracted offline corpus and is byte-identical to `corrected-stage-report.json`; `installed-verification.json` binds that comparison. Compact installed-control stdout/stderr logs are retained under `installed-control-logs/`. `manifest.json` hashes every published audit file, while raw tampered copies remain preserved in the ignored run directory.
