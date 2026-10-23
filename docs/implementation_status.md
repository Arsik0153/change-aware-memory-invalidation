# CAMI implementation status

The implementation follows docs/IMPLEMENTATION_SPEC.md version 1.0. Research documents and the existing submission builder remain unchanged.

## 2026-10-23: relative import overflow correction

The product adapter represented an impossible relative import with an empty
module name, which also identifies the indexed root `__init__.py`. The original
review fixture at revision `09cac2b704daf3becfad85200fc651d04174036d` produced
two false incoming calls to `__init__.py:target`, from `cli.py:main` and
`pkg/cli.py:nested`. The research index contributed no edges on that fixture.

Module resolution now returns `None` for an impossible import. An empty module
name has zero package depth. Unresolvable imports remain among competing
bindings, so the adapter still rejects ambiguous call targets. The same explicit
revision CLI query now returns no incoming calls. Its unresolved nodes and
limitations are unchanged, and `graph_complete` remains false.

The new CLI regressions ran before the production edit, with 12 failures and
15 passes. After the fix, all 27 pass. They cover the original fixture, overflow
from modules and package initializers, named imports such as `from ...name`,
valid sibling and parent imports, aliases, and competing unresolved bindings.
These are implementation checks. Fresh independent acceptance remains pending.

Verification used `PYTHONDONTWRITEBYTECODE=1` and disabled the pytest cache:

```bash
.venv/bin/pytest -q -p no:cacheprovider tests/test_symbol_search.py tests/test_index.py
.venv/bin/pytest -q -p no:cacheprovider -m 'not docker'
.venv/bin/ruff check .
.venv/bin/mypy --cache-dir /tmp/cami-relative-fix/mypy-cache src/cami scripts/demo_structural_closure.py
git diff --check
```

The targeted suite passed 59 tests. The full non-Docker suite passed 372 tests,
with 4 deselected. Ruff passed, strict mypy passed for 28 source files, and the
diff check passed. No held-out experiment, freeze, or Docker run was performed.

## 2026-10-23: first product stage, Git symbol search

`cami find SYMBOL --repo PATH --revision HEAD --format json` now searches the
existing Python AST index. Text output is the default. JSON schema version 1
records the resolved commit and Git tree, source roots, analyzer versions,
definition locations, structured and readable signatures, incoming and outgoing
static relations, all matches, limitations, and conservative unresolved nodes.
Statuses are `found`, `not_found`, and `ambiguous`. Invalid inputs produce stderr
and exit code 2. The [Russian contract](symbol_search_ru.md) specifies matching,
exit codes, graph limits, and the next stage's snapshot and cache requirements.

The product adapter owns local from-import call resolution, including the call
from `cli.main` to `engine.run_experiment`. Existing research index, selector,
validator, and `run` contracts are unchanged. Graph completeness is always false.
The inherited graph can miss calls and attribute extra calls across nested scopes
or approximate bindings. Working tree search, TypeScript, and persistent storage
remain outside this stage. No new dependencies were added.

Real CLI acceptance used a temporary Git repository with spaces in its path.
It verified exact and qualified matches, missing symbols, duplicates, revisions
before and after rename and delete, invalid repo and ref, JSON parsing, and text
output. Separate process regressions also verify staged and unstaged preservation,
signatures, relative local imports, name shadowing, module collisions, and byte
determinism across Python hash seeds. On CAMI at baseline
`dcd67fab2b1b282e1f10578e3832bedfccb48a3c`, `run_experiment` was found at
`src/cami/engine.py:38-99` with a static incoming call from `src/cami/cli.py:main`.

Verified commands for the final implementation:

```bash
uv run pytest -q tests/test_symbol_search.py tests/test_index.py
uv run pytest -q -m 'not docker'
uv run ruff check .
uv run mypy src/cami scripts/demo_structural_closure.py
git diff --check
```

The targeted suite passed 32 tests. The complete non-Docker suite passed 345 tests
with 4 deselected. Ruff and strict mypy passed, with mypy checking 28 source files.
The diff check passed. Deslop review checked the complete product diff before
commit. No real held-out datasets, protocol freeze, paid API calls, or performance
experiments were run for this stage.

Safe local Codex quota telemetry used only `event_msg` `token_count` records for
`limit_id=codex`, `window_minutes=10080`. Before implementation, the latest event
was `2026-10-23T11:09:52.984Z`, with 86% remaining. After implementation and final
tests, the latest observed event was `2026-10-23T11:19:58.623Z`, with 85% remaining.
Both report reset at `2026-10-29 18:36:49 UTC`.

## Workflow

- Read the Principles section of poteto-mode. Done.
- Phase A: Frame. No CAMI implementation existed. Acceptance is M0–M5 with actual CLI, Git and Docker evidence.
- Phase B: Design the workflow. Follow the already specified modules and milestones. No second architecture design is needed.
- Phase C: Run the loop. Verify M0, M1, M2 offline demo, M3, M4, then M5 in that order.
- Phase D: Keep the audit trail. Record decisions in docs/decisions.tsv.
- Phase E: Verify and hand back. Run the complete checks and report external limitations.

Throughput checkpoint: implement the fixed data contracts first, then Git and AST, then the first complete demo. Keep dataset preparation outside the policy process. Delegate read-only contract review while the primary agent owns code. No existing implementation needs migration.

## Current stage

M0–M5 implementation and acceptance checks are complete. Independent annotation and the main scientific experiment remain external work. M6 is optional and not implemented. Final evidence and limitations are recorded below.

## Clarifications recorded before experiments

- Parent receipts use confirmation_type, evidence_path and evidence_sha256. The evidence file must exist and match its hash. This checks integrity, not scientific independence.
- Anchor ranges use start_line and end_line. They are display metadata.
- Immutable Pydantic records use tuples for sequences and strict JSON parsing at file boundaries.
- No AGENTS.md exists on disk. The user-supplied AGENTS.md instructions apply.

## M0 verified

Installed Python 3.12.14 and dependencies from uv.lock. `uv run --locked pytest -q` passed 12 tests. `ruff check .` and `mypy src/cami` passed. The installed `cami check-inputs` command validated a real Git chain with a space in its path. Negative cases rejected unknown config fields, duplicate keys and claim IDs, unsafe paths and a skipped parent transition. JSON schemas are exported under schemas/.

## M1 verified

Real Git fixtures verify comment-only changes, exact syntactic signatures, dependency union and cycles, explicit imports, parse errors, conditional and repeated definitions, dynamic assignment ambiguity, and exact-name disappearance. The checkout, HEAD and uncommitted source remain unchanged. AST modules are cached by blob ID, Python and indexer version, plus path/module identity. Baselines can request graph-free indexes. M1 verification passed 17 tests, Ruff and mypy.

## M2 verified

`cami demo --out runs/demo` completed all seven policies and independent scoring. The synthetic replay has five claims and three transitions. `all_validate` made 15 logical validations; `symbol_validate` made 8. Both produced zero stale exposure and retention 1.0 on this fixture. This is not evidence of general superiority. 38 tests, Ruff and strict mypy passed. Reports are in runs/demo/report/.

The review found and corrected exact-subject selection without a matching anchor, shadowed call bindings, ambiguity inherited from enclosing definitions, and missing parent anchor evidence. Regression tests cover the cases. Score rejects incomplete coverage and incomplete runs; a single independent cluster gets no confidence interval.

## M3 verified

Built docker/Dockerfile.probes from a pinned Python 3.12.12 base. The prepared image is docker.io/library/cami-probes@sha256:120054cdb5169f81dce7ecf88b644f6879911981a2b5e1df750752d095e0d636 on this host. Three behavior tests passed, including actual parent/child Docker execution, import collection failure and actual timeout. Mixed repetitions are tested in the deterministic aggregation unit test. No external repository code ran on the host. Per-repetition logs are preserved under /private/tmp/cami-m3-final/ and will be copied into the reproducibility outputs.

Probe execution uses a standalone frozen probe and disables repository conftest/plugin autoload. Required fixtures must be included in the probe or prepared image. This is a deliberate environment boundary, not a claim to run arbitrary repository test suites unchanged.

## M4 verified

Replay, graph depth 0/1/2, cycle termination, old/new edge union and deterministic dependency masks work. The CLI prepares public graph views separately from research-only full graphs and removal logs. Tests prove that hidden missingness is not repaired by the selector, known missingness triggers fallback, and zero masking preserves selection. The complete offline suite passed 45 tests with two Docker tests skipped in that invocation; those two were executed separately in M3.

## M5 protocol decisions before pilot

- Real pilot sampling is the 12 first-parent transitions ending at Click tag 8.1.8, resolved to 934813e4d421071a1b3db3973c02fe2721359a6e. This is a development chronological pilot, not held-out evaluation.
- Pilot claims are up to ten exact top-level function-existence claims per parent, selected with seed 42 from that parent alone. An independent tokenizer checks parent syntactic definitions; the production AST validator does not create receipts or child labels.
- The 12 adjacent pilot transitions share one episode cluster. Their results cannot support a precise population confidence interval.
- Child labels remain pending independent annotation. The pilot may report operational costs and validation outcomes, but no truth-quality rates without labels.
- Dataset manifests use explicit repository URLs, run config paths, split and cluster IDs. A scenario exposes only its public files to engine. Full graphs and deletion logs remain in research/.

Pilot preflight rejected the initial consecutive-history list because fdc6b020465751d26f9e74a707f2c058b0dd251f is a merge. No pilot dataset or outcomes had been created. The frozen sampling rule is now the last 12 non-merge first-parent transitions ending at the same 8.1.8 commit, each paired with its actual sole parent. This enforces the existing protocol prohibition on merges; it does not choose pairs by labels. The original wording above is superseded by this clarification.

Runtime accounting clarification: wall time includes waited subprocess work. cpu_seconds is analyzer-process CPU. Container and child-process CPU are not measured and this limitation is recorded in run manifests. Initial and incremental index times are separate fields in addition to index_seconds. Human annotation minutes and provenance preparation time remain null unless actually measured.

## Real pilot executed

The structural pilot completed 84 runs: 12 Click transitions, ten parent-only claims per pair, seven policies. Actual costs are in reports/click-pilot/. Conservative unresolved-dependency fallback selected all 120 claims for file_validate and symbol_validate, matching all_validate's 120 calls. This pilot demonstrates no validation-call saving. Its single fixed policy order is not a final timing experiment.

A separate environment smoke pilot completed 72 actual Docker test executions: three repeats on each parent and child of 12 real pairs. All 24 combined results were supported for the one frozen CliRunner echo case. This verifies that finite probe in the prepared environment, not the complete historical test suites. reports/click-environments/summary.json contains the measured outcomes. These validator outcomes are not child labels and are not used for scientific accuracy metrics.

Serialization clarification: extra_environment_paths are repository-relative paths to watch for changes, not files relative to the dataset directory. Dataset watch paths must be present in every run config. Freeze preserves their committed contents through source snapshots and seals the watch list in the expanded config. It does not read similarly named host files.

Dataset validation also detects overlapping object IDs across repository IDs, because cloned histories must not count as independent or cross splits. Explicit episode clusters may span repositories but never development/heldout splits. The initial aggregate fixture accidentally generated identical Git histories for two nominal populations; its commit identity now distinguishes the independent synthetic histories. This changes the fixture, not the bootstrap rule.


## M5 verified and final handoff

Implemented dataset manifests, blind annotation export, original-answer/adjudication import, agreement accounting, sealed protocol inputs, held-out execution gating, paired cluster bootstrap, separate strata/replay reports, cost plots and observed-only break-even. The real pilot export contains 120 annotation packets. `runs/click-protocol/protocol.json` is sealed with annotations explicitly pending. No validator result was converted into a real child label.

Actual CLI checks completed:

- `cami demo --out runs/demo-verified`: seven policies and independent synthetic scoring; reports in `runs/demo-verified/report/`.
- `cami check-inputs --config examples/demo/run.json`, `cami run --config examples/demo/run.json --out runs/example`, and `cami score --run runs/example --labels examples/demo/labels.jsonl --out reports/example`.
- `cami analyze` on four paired demo policies: `reports/demo-analysis/` (synthetic, no population inference).
- `cami prepare-scenario --dataset examples/demo/dataset.json --mode hidden_missing --drop 0.50 --seed 42 --out runs/scenario-final`.
- `cami annotate-import --input examples/demo/annotations.json --out reports/demo-annotation-import` (explicit synthetic expectations, no human annotation claim).
- Real Click preparation, 84 policy runs, operational report, 72 Docker probe executions, blind annotation export and protocol freeze; reproduction commands in README.md.
- A CLI regression checks that held-out execution requires the matching seal, runs without labels and rejects modified inputs before creating an output directory.

Installation was rechecked with `uv sync --locked --extra dev`: success. Full verification is recorded by `scripts/verify_cami.py` in `docs/verification/cami/final/checks.json` with exact commands, exit codes and logs. The Docker image digest is recorded there. M3 raw evidence is preserved in `docs/verification/cami/m3/`; original absolute fixture paths in copied manifests are historical references.

The original research documents, technical specification, submission outputs and submission builder have no Git diff. The pre-existing user image is preserved. No commit or paid API request was made.

### Remaining research work and measurement limits

- Independent child annotations, at least 20% human double review and disagreement adjudication require annotators. All 120 real pilot labels remain pending. Annotation tools preserve identity and history; they cannot verify that a person's independence declaration is truthful.
- The planned primary cohort of about 600 claims, real replay cohort and held-out repositories have not been assembled or evaluated. This prototype does not prove the research hypothesis.
- The actual pilot has one episode cluster and only function-existence claims. It showed no validation-call savings. Its fixed-order operational timings are not three randomized cold repetitions.
- Memory scaling at 10/100/1000 distinct claims was not benchmarked. No unobserved break-even or timing confidence interval is reported.
- The separate behavior pilot verifies one finite Click smoke case on 24 revisions. It does not establish compatibility with all historical tests or supply gold labels.
- CPU accounting covers the analyzer process; child/container CPU is unmeasured. Cached durations are reconstructed estimates, not fresh end-to-end measurements.
- Held-out execution needs the original local Git objects; frozen source snapshots are evidence, not a replacement Git database. Rebuild the pinned Docker image on another host and use its actual digest.
- M6 has no implementation or execution: no model/key/budget/protocol was provided.


Final audit corrections: graph-free file policies now use an explicit repository-wide `graph_free_unresolved_fallback` when unresolved dependencies exist, because they cannot establish the transitive support boundary without constructing a graph. This can cost extra validations; local and imported transitive-dependency regressions cover it. Held-out preflight now compares both cohort and exclusions with the sealed record, allowing exclusions already fixed before freeze while rejecting new changes. A CLI regression covers each case. The complete demo and real structural pilot are rerun after these corrections in `runs/demo-verified/` and `runs/click-verified/`; earlier reports retain their original measurements.

Final verification result: **99 tests passed**, including actual Docker tests; Ruff passed; strict mypy passed for 24 source files. `git diff --check` passed. Final real pilot measurements are in `reports/click-verified/`, including `selection_reasons.json`. The final rerun again selected 120/120 claims for each validating policy.

A further held-out integration regression freezes two policies for the same population, runs both against real Git, and analyzes them together. Analysis merges equivalent policy declarations into one population only when input hashes, claim hashes and cluster/sequence declarations agree, and requires all explicitly declared variants. Duplicate or conflicting declarations remain errors.

## 2026-10-01: independent audit and next experiment preparation

This section supersedes the readiness statements above where noted; historical
results and their files remain unchanged. The starting commit was
`f8e6054c1d243d464c2765ffe7117e0e4493a27e`. Full Russian findings and reproduction
commands are in [next_stage_report_ru.md](next_stage_report_ru.md).

Baseline evidence was reproduced in new directories: 99 original tests passed after
restoring Docker, static analysis passed, the synthetic demo again used 8 symbol
validations versus 15 all validations, and the unchanged Click pilot selected
120/120 for all three validating policies. A separate Click environment rerun
completed 72 finite probe executions. These are operational observations, not
independent truth labels.

The quantitative audit found zero changed sampled subject ASTs, five changed
subject files, module-level unresolved support for all 120 claims, and direct
subject unresolved support for 108. All symbol selections and 115 file selections
were fallback-only. File fallback expanded uncertainty across the repository;
symbol fallback reached the whole sampled cohort through module support. Full
counts, overlap sets and examples are in
`reports/next-stage-20261001/baseline-diagnostics/selection_diagnostics.json`.

Confirmed implementation fixes cover rebinding and unknown global reads, a more
conservative tokenizer parent oracle, shared-cache semantic invalidation, full-run
costs and Pareto accounting, cold-parent index timing, and rejection of historical
source collisions with preloaded probe infrastructure. Failing-before evidence is
preserved in `reports/next-stage-20261001/reproductions/`. Index version is 2;
validator version is 3. Final source verification passed **182 tests**, including
Docker, Ruff and strict mypy for 24 source files, recorded in
`reports/next-stage-20261001/frozen-code-verification/`.

The structural selection change is a separate protocol extension, not a claimed
implementation correction. [Protocol 1.1](protocol_1_1.md) narrows inferred graph
support only for exact existence/signature claims without explicit dependencies;
unknown provenance, parse limitations, explicit support, anchors and retries remain
conservative. Protocol 1.0 and its original cohort are preserved. No quality claim
is justified without independent child labels.

Actual preparation now includes 60 main pairs with 600 draft claims and three
10-transition replay sequences with 30 initial draft claims across Click,
Requests and pytest. Click is development; Requests and pytest are heldout.
Selection recipes and object IDs are in `data/manifests/main-20261001.*`.
`runs/next-stage-20261001/main-ready/` contains source evidence and blank forms for
1530 primary and 306 secondary tasks; child main and replay populations are separate.
Three generation runs produced identical claim hashes. There are **zero admitted
claims, independent receipts or child labels** so far. The final scientific seal
has deliberately not been created on empty receipts. These facts replace the older
statement that no main/replay candidate set had been assembled.

[Annotation instructions](annotation_next_stage_ru.md) give the exact packets,
answer format, parent import, child import and remaining freeze steps. Prose stays
outside the offline cohort; this leaves at most 540 main candidates, or 480 without
behavior admission. Historical behavior environments still require verification,
especially pytest, where the new runner rejects a collision with installed `_pytest`.
Human review, provenance completion and final cohort admission are outstanding.
No heldout policies, truth-quality metrics, M6 or paid API calls were run. Memory
scaling and population inference remain research work, not completed results.

The completed paired benchmark contains **1188 successful runs**: three seeded
repetitions, unchanged pilot inputs, seven uncached policies, and separate verdict
cache fill/measurement. Protocol 1.0 retains 120/120 after fixes. Protocol 1.1 uses
120 all, 5 file and 0 symbol validations, but selective policies remain slower than
all_validate in full-process medians: 11.637 s file and 12.977 s symbol versus
11.289 s all, per 12 transitions. All counts and verdicts repeat exactly. There are
no independent quality labels. Full data, source hashes, schedule, ranges and plots
are in `reports/next-stage-20261001/timing-verified/`; preliminary interrupted
series are excluded. This replaces the old limitation of a single fixed-order
timing run, but does not establish population inference or a break-even point.

After timing, the final code also reran the demo (15 all versus 8 symbol validations)
and all 72 Click smoke executions (24 combined supported verdicts, no exclusions).
Ruff, mypy and diff checks passed again. Logs and exact commands are in
`reports/next-stage-20261001/completion/`. This final smoke includes the new runner
collision guard; it does not remove the documented pytest environment limitation.

## 2026-10-23: worktree search and persistent product generations

`cami find SYMBOL --repo PATH` now reads the working tree by default, including
unstaged changes and untracked Python files. Explicit `--revision HEAD` or a SHA
still reads Git objects in a dirty checkout. Product JSON uses schema version 2;
research records, protocols, datasets, seals, and `cami run` retain their contracts.
The [worktree index contract](worktree_index_ru.md) documents coverage, excludes,
content identity, persistence, and errors.

The product captures bytes, builds a complete immutable index, and verifies the
readset before publication or reuse. Content identity includes full file hashes,
policy, and analyzer fingerprint. Per-worktree writer locks serialize refresh;
atomic generation and pointer publication supports restart and concurrent queries.
The guarantee is `verified_readset` over a reported interval. It does not claim an
atomic filesystem snapshot. Parse errors permit healthy search with partial
coverage; I/O failures do not publish a partial current generation or return an
old index as fresh. Damaged caches rebuild with stderr diagnostics.

Implementation-worktree validation passed 68 targeted tests and the complete
non-Docker suite, **381 passed, 4 Docker tests deselected**. Ruff, strict mypy for
31 source files, and `git diff --check` passed. Separate-process CLI fixtures
cover staged/unstaged bytes, untracked files, rename, delete, revert, comment-line
identity, HEAD isolation, parse recovery, and persistent reuse. Controlled tests
cover unstable capture, permission failure, symlink replacement, crash boundaries,
corrupt state, and two concurrent processes. These are correctness and reuse
checks; no speedup is claimed. Integration must preserve the independent stage1
resolver fix and repeat key acceptance before committing to main.

JavaScript/TypeScript, product memory, watch, and automatic generation GC remain
future work. No heldout Requests/pytest execution or scientific freeze was run
for this product stage.

### Main integration verification

The Stage2 full-index patch was applied three-way to main `14572ebd470d7c246c52d860b6957635a32a0a64`
without conflicts. The accepted stage1 resolver helpers are AST-identical, and all
27 P2 regression cases remain. Main validation passed **95 targeted tests** and
**408 non-Docker tests, 4 deselected**, Ruff, and strict mypy for `src/cami` and
`scripts/demo_structural_closure.py`. The increase over the implementation
worktree is the preserved 27 P2 cases, not replacement tests.

Separate-process acceptance passed 15 lifecycle scenarios and 13 additional
checks for reuse without a builder, capture instability, input changes during
cache loading, corrupt/incompatible cache rebuild, crash recovery, unsupported
files, and the original P2 fixture in worktree, HEAD, and explicit SHA modes.
P2 has zero false incoming edges. Unresolved signals and limitation contents
match the accepted fix. JSON v2 sorts limitations by path and code.
The external acceptance driver initially compared the old limitation order and
incorrectly required a rebuild when a valid generation already existed. Those
assertions were corrected; product source did not change during verification.

Integration evidence, reproducible drivers, command logs, exact commit and tree
IDs, and postcommit CLI results are in
`/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/stage2-main-integration/run-20261023T1210/`.
The receipt is `integration-receipt.json`. These are implementation checks.
Stage2 acceptance remains `under_review` until the parent's fresh independent
review of the committed SHA. Historical stage1 FAIL and exact-499 PASS remain.

### Stage2 review r1 and storage repair

Independent review r1 returned **FAIL** for exact main SHA
`1adf399f38e38b98b16b405359287e8a28884d8e`. Four P2 defects were reproduced.
Valid external ignore sources caused false capture instability. A FIFO cache
index blocked while holding the writer lock. A file replacing a generation
directory prevented persistent repair. Excluding `.gitignore` from sources hid
active ignore rules from policy identity. The original report is retained at
`/tmp/cami-stage2-review-2p90pzt2/review-report.json`.

The fix separates Git configuration reads from source capture, validates cache
types through nonblocking descriptors, and quarantines malformed cache artifacts
before atomic publication. Active `.gitignore` metadata is captured before source
path filtering. Source symlinks remain unsupported. The existing product-code
fingerprint invalidates older generations automatically; research schemas and
index semantics are unchanged.

Before changes, the baseline passed 95 targeted and 408 non-Docker tests.
New regression tests then produced **16 failures and 8 passes**. After changes,
**133 targeted and 446 non-Docker tests passed, 4 Docker tests deselected**.
The increase is 38 focused regression cases; all previous 27 relative-import
regressions remain. Ruff, strict mypy for 32 files, and diff checks passed.
The same CLI repros now succeed, with persistent repair and next-process reuse.
Separate-process acceptance also passed 15 lifecycle scenarios and 10 calls
covering the original P2, valid relative imports, and own-source worktree/Git queries.
No benchmark or independent acceptance is claimed.

Before/after logs, drivers, quota, exact committed SHA, and receipt are under
`/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/stage2-storage-fix/run-20261023T123409Z/`.
The repair is `under_review` pending the parent's fresh independent review r2.
The historical r1 FAIL remains attached to `1adf399f38e38b98b16b405359287e8a28884d8e`.

### Stage2 review r2 and socket cache repair

Independent r2 returned **FAIL** for exact main SHA
`26d9188ab75784ca1c2a9d4a55b1381ab07bbdde`. It confirmed all four original P2
fixes with 133 targeted tests and 224 CLI calls. One new P2 remained. A UNIX
socket replacing `current.json`, `manifest.json`, or `index.json` caused repeated
exit 4 with `ENXIO`, leaving the invalid inode in place. The report remains at
`/tmp/cami-stage2-review-r2-461q7d91/review-report.json`.

The cache data reader now checks regular-file type before opening, compares the
descriptor with the pre-open inode before reading, and rechecks actual type when
opening fails. Regular-file permission and I/O errors remain explicit. Invalid
pointer nodes join generation artifacts in quarantine before atomic publication.
Existing bounded reads, no-follow descriptors, source coverage and ignore policy
remain. No schema or index version changes are needed.

Before the fix, nine actual CLI calls confirmed persistent failure for all three
roles. Socket regressions gave 3 failures and 2 passes; corrected boundary tests
gave 2 failures and 9 passes. After the fix, 34 focused, **148 targeted** and
**461 non-Docker tests passed, 4 Docker tests deselected**. Ruff, strict mypy for
32 files and diff checks passed. All previous 38 cache/ignore and 27 relative-import
cases remain covered. Fifteen CLI calls verified quarantine, valid JSON files,
builder-free next-process reuse and real kernel `EACCES` for each JSON role.
Ten further CLI calls checked the original relative-import P2, valid local calls
and own-source queries in worktree, HEAD and explicit SHA modes.

Evidence, drivers, hashes, command logs and the committed SHA are in
`/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/stage2-socket-fix/run-20261023T1318Z/implementation-receipt.json`.
This is implementation verification. The new commit is `under_review` pending
the parent's fresh independent R3. Both exact-SHA historical FAIL verdicts remain.
No real block or character devices were created or exercised. Controlled races
and regular-file I/O errors supplement actual socket, FIFO, directory and symlink
cases. No Docker, heldout execution, freeze or TS/memory integration was performed.
### Stage2 independent R3 acceptance

Independent R3 accepted exact MAIN
`6037294831fc0cde5525986cab043ea21af27dd3`. It passed 148 targeted tests and
76 actual CLI checks. The report is
`/tmp/cami-stage2-review-r3-ncph5p29/review-report.json`.
This verdict supersedes the pending R3 status above. Both earlier FAIL verdicts
remain bound to their original commits. Combined TypeScript integration requires
fresh checks and independent acceptance at its own MAIN commit.

## 2026-10-23: JS and TypeScript product search

`cami find createUser --repo PATH` searches JS, JSX, TS, and TSX in working trees
and explicit Git revisions. Product schema v3 adds language-discriminated matches
and a typed compiler state. Python signatures and dependency fields retain their
previous meaning. Research records and the research index schema remain separate.

`cami setup-typescript` installs TypeScript 6.0.3 from the packaged exact lockfile
into a versioned user cache. Node 24 and npm 11 are required. Query execution
never runs npm or target scripts. Capture includes the selected root JSONC config,
relative extends, and source ancestor package manifests. Compiler availability,
parser changes, configs, barrels, and source inventory invalidate generations.

The [TypeScript contract](typescript_analyzer_ru.md) records supported syntax,
static resolution, diagnostics, exclusions, and unresolved references. Signatures
are syntax evidence without type inference or consumer typechecking. One root
config, named reexports, and captured-only resolution are supported. Export-star,
general runtime alias/member/dynamic/CommonJS resolution, project references,
watch, memory maintenance, and generation GC remain outside this implementation.

Validation commands are `cami setup-typescript`, the search/compiler/setup test
modules, `pytest -q -m 'not docker'`, Ruff, mypy, Node syntax checking, and
`git diff --check`. The implementation handoff carries exact outputs and wheel
acceptance evidence; main integration must repeat the relevant checks.

### Combined MAIN implementation verification

The exact R2 artifact patch SHA-256 is
`741ef6de1b68519354f73259b25731d5c37c1735d0cfeaa443786decafa9e145`.
Independent artifact R2 passed 197 focused tests and the CLI and wheel checks.
That verdict applies to the artifact, not the combined MAIN commit.

Integration started from clean MAIN
`6037294831fc0cde5525986cab043ea21af27dd3`. Three-way application preserved
the accepted pre-open regular-file check, socket quarantine, bounded reads, and
effective ignore policy. The only conflict joined two status-document additions.
No source conflict required replacement of an accepted helper.

After the final source edit, 256 targeted tests and 569 non-Docker tests passed,
with 4 Docker tests deselected. The targeted results include all 53 Stage2
cache/ignore/socket cases and all 27 Python relative-import cases. Ruff, strict
mypy for 38 source files, and Node syntax checking passed. Existing test functions
remain present. Schema v3 and the hybrid stored index require three existing
test adaptations. All other pre-existing source/test files outside the seven
integration paths remain unchanged.

Separate CLI processes passed 22 Next-like scenarios, 18 P2 commands, three
transient-failure/recovery/reuse calls, 72 Stage2 calls across 21 groups, eight
extension probes in worktree/Git modes, and three own-source probes checking
`run_experiment` caller, line range, and signature. These are implementation
checks. Cache reuse is not a speedup measurement.

The freshly built wheel passed 29 recorded setup and query commands. It ran as
uid 65534 from a foreign working directory after environment relocation, with
read-only package files. Five compiler-cache damage cases and concurrent repair
passed. All 42 packaged source and sidecar files match MAIN, including the
lockfile. The wheel contains no `node_modules`. Initial offline wheel build
could not resolve uncached hatchling; ordinary build succeeded. Both logs remain.

Commands, JSON outputs, integrity hashes, drivers, and the final commit receipt
are under
`/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/stage3-main-integration/run-20261023T140732Z/`.
The combined MAIN commit remains `under_review` until fresh independent review.
Memory component R3 is read-only and pending. Watch design is a proposal saved
outside this repository; neither Stage4 nor Stage5 is accepted here.

## 2026-10-23: combined product memory in MAIN

`cami memory context`, `remember`, `update`, `refresh`, and `history` now use the
same captured Python and JS/JSX/TS/TSX index. Structural existence and syntax
signatures have immutable provenance and checks. Carried facts retain their
check ID, time, and source evidence. Notes require explicit review after a source
change. The [memory contract](product_memory_ru.md) describes scope and CLI use.

MAIN preserves the accepted R4 private SQLite image and durable publication
intent. Quoted, escaped, numeric, and direct literal-computed member names share
one compiler identity. Unsupported fields protect nested subjects from false
absence. Method signatures and runtime dispatch remain outside the syntax contract.

Integration applied the authenticated complete patch `cb31ae6e` with three-way
indexed application to clean `9ff15cb`, without conflicts or production/test edits.
All prior test files, including the 53 cache/ignore and 27 relative-import cases,
remain byte-identical. Targeted 444 and full 766 non-Docker tests passed, with
4 Docker tests deselected. Ruff, strict mypy on 45 source files, both Node syntax
checks, and diff checks passed on this final source.

Actual MAIN verification passed 396 memory CLI commands. Storage replay passed
19 publication crash/failure cases with 118 CLI commands and both R3 hot-journal
controls. A freshly built, relocated, read-only wheel passed another 41 commands
as UID 65534. Every package asset matches MAIN, and the wheel is byte-identical
to the fixed writer's wheel. Its earlier 394 commands remain separate evidence.

Three product stages are accepted at their prior exact commits. Stage4 is
implemented and `under_review`, pending fresh independent MAIN R2. Stage5 remains
isolated after watcher R1 FAIL. Its cleanup writer is terminal with all three
fixes implemented, and fresh watcher R2 is active according to the parent transfer.
Watch code is absent from this commit. These self-checks do not accept Stage4. The exact commit, trees,
commands, outputs, limits, and postcommit checks are in
[the integration receipt](/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/stage4-main-integration/run-20261023T1540Z/integration-receipt.json).
