# Full CAMI plus exact-result reuse experiment, version2

Completed and independently verified: all80 scheduled attempts passed, all70 model
sessions completed with provider-reported default tier, all10 exact-repeat hits
skipped the model and passed fresh fixed grading. All10 changed-input rejection
probes and their unchanged-input positive controls passed, including direct checks
of the physical candidate sources, changed bytes, and absent rejected outputs.
The fixed criterion passed: lower token work AND timed pipeline wall versus EACH
of plain/static/CAMI in EACH of five blocks, all15 comparisons per metric.

| Condition | Token work median (min–max) | Pipeline seconds median (min–max) |
|---|---:|---:|
| plain | 111,655 (96,803–127,477) | 429.00 (413.74–479.57) |
| static | 117,237 (107,136–125,997) | 439.33 (394.56–454.67) |
| cami | 117,191 (98,279–128,900) | 433.09 (418.23–457.90) |
| cami_replay | 54,317 (50,087–66,983) | 217.53 (197.49–248.18) |

Compared with original CAMI, reductions of the five-block medians are53.65% in
token work and49.77% in timed pipeline wall. Paired-block reductions range31.84–57.26%
and40.66–56.83%, respectively (paired medians51.44% and52.49%). These are distinct
statistics, not interchangeable estimates. Every candidate block was below every
comparator block even across the observed unpaired ranges. No population-wide
confidence claim is made from two historical tasks.

The new condition made10 model calls for20 tasks; each comparator made20. Across
all five blocks, its cache-read tokens were1,988,352 versus4,201,472 for CAMI, so
the primary uncached-token result is not hiding an increase in cached input.
Ten hits took2.03–2.18s each, median2.09s, including reset/guards/materialization and
fresh quality checks. All50 configured-memory model sessions actually called
memory, with zero lookup errors. Actual provider tier was default despite requesting
priority; this was uniform across all70 calls. This is not a measured dollar saving.

Independent artifacts: audit.json verifies exact trial hashes, schedule, quality
receipts, same-block result lineage, tier and arithmetic; binding-audit.json checks
physical graded-source identity, session hashes and pre-redaction native-read
receipts; accounting.json adds disjoint token components, actual memory calls,
storage and physical guard probes. Native read bytes rely on the pinned numeric
pre-redaction receipt: original redacted text cannot be remeasured afterward.
summary.json and guard-probes.json preserve primary results. evidence.tar.xz retains
all raw sanitized run artifacts; archive-receipt.json proves byte-identical raw tar
content to the original gzip export. results.png/results.pdf are standalone figures.

Timed pipeline includes preparation/reset, guards, source-memory construction,
model/auth/cleanup, result recording/materialization, capture and fresh grading.
It ends before terminal hash/publication and final analysis; baseline preflight
is charged equally. The launcher ran15:13:34–17:20:49 UTC on2026-11-13. Host load
was monitored (one-minute maximum4.76 on8 logical CPUs), not independently isolated.

The traced CAMI backend spans total16.21s out of2,141.61s of model-session wall
(about0.76%); this excludes some process/transport overhead and is not a complete
CPU profile. The dominant measured improvement comes from avoiding repeated model
sessions. Source-memory storage still totals211.69MB over five CAMI namespaces,
while candidate result caches total399,396bytes. That large source-memory store
is the next storage investigation; it is not retrospectively changed in this run.

The aborted v8 remains separate: two started model sessions, observed60,007 token
work and494,592 cache-read tokens, no scored quality result. Neither its answers nor
its timing are reused or pooled. Full successful v9 evidence does not erase that cost.


Frozen production/controller source: ca5f73d in immutable Linux runtime-v9.
Protocol SHA256: e0ee8573fcfe1526c62fa99848262b0b000bf35e57c479471a16d7a46aac123d.

The fixed schedule has80 attempts: plain, static, CAMI, and CAMI plus exact-result
reuse; five independent memory initializations; A,A,B,B per condition. All task
inputs reset to canonical sources, each namespace starts empty, and only prior
successful changes from the same candidate condition may teach its result cache.
There are70 maximum model calls and10 expected exact-repeat hits. No retries,
replacement, pooling, extension, or implementation changes during execution.

A positive result requires all80 quality/operational gates, complete telemetry,
uniform provider tier,10 changed-input rejections with successful exact-input
positive controls, and both lower token work AND lower total pipeline wall than
EACH comparator in EACH block (15 comparisons per metric). Timing includes model
work, cache construction, input guards, reset, materialization and fresh grading;
shared baseline verification is charged equally to all20 condition-block sequences.
Wall observations on this laptop do not establish independently isolated host load.

This is a full development replication on two historical tasks. It can establish
benefit for exact repeated tasks under these guards, not arbitrary new-task benefit
or semantic reuse after source changes. The sealed heldout remains unopened. Token
work excludes cache-read tokens and is not monetary billing; all components are
retained for separate accounting. Requested priority does not imply served priority.

This is a declared repair after v8 failed its model-contract validation. v8's two
started model calls and sanitized artifacts remain in ../opencode-full-replay-20261113;
no solutions or observations are imported into this run. The model is now frozen
and validated before a paid subprocess, with the actual session contract exercised
for all three backend arms. Additional forwarding-test fixtures were supplied with
valid model identities; this does not change the frozen production/controller files.

Linux admission: six real MCP stdio probes and three real no-model OpenCode sessions
passed, with zero model calls, exact model/config validation and private-state removal.
Status: complete; all independent audits verified.

Final local admission: project suite1719 passed,1 skipped,4 Docker-marked deselected
in708.01s; benchmark integration suite835 passed in28.57s. Ruff passed on changed
code. Both suites finished before model timing began. The repaired freeze and all
admission artifacts were committed before model execution.

Execution launched2026-11-13T15:13:34Z (2026-11-14 in Asia/Seoul), after both test
suites finished, using launch.py. The controller runs the complete schedule without
intermediate performance-based decisions. Live operational progress is in
../../runs/local-resume-20261113/full-driver-v9.jsonl; host load observations are in
../../runs/local-resume-20261113/full-host-load-v9.jsonl. The final audit and charts
were added after the complete run. render_results.py requires an80-attempt
independent audit and fixes the median/range presentation before final outcomes.

Evidence archive compressed losslessly from102,799,881 to15,021,832bytes; uncompressed tar SHA256 `5e573e0948dcadd2ad3b3ec482636a640565b4cf3877fe72f45ee352b6132bf2` is identical.
