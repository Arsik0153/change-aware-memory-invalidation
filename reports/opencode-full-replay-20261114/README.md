# Full CAMI plus exact-result reuse experiment, version2

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
Status: admission complete; waiting for local test suites before model execution.

Final local admission: project suite1719 passed,1 skipped,4 Docker-marked deselected
in708.01s; benchmark integration suite835 passed in28.57s. Ruff passed on changed
code. Both suites finished before model timing began. The repaired freeze and all
admission artifacts were committed before model execution.
