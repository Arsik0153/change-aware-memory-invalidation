# CAMI implementation status

The implementation follows docs/IMPLEMENTATION_SPEC.md version 1.0. Research documents and the existing submission builder remain unchanged.

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
