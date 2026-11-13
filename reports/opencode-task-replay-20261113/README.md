# Exact-task result memory prototype

This separate experimental module remembers source changes, rather than repeatedly
showing the model source prefixes. It only hits for the identical task text, all
regular workspace file bytes/modes and caller-declared external context. Changed
inputs miss. It materializes a new candidate, never overwrites the original tree,
and always requires fresh grading. It is result memoization, not semantic reuse
across changed repositories or a demonstrated improvement to the existing CAMI
source-validation engine. First-solution and recording costs must be charged.

Post-hoc verification reused two already-completed model solutions, independently
verified their terminal artifact hashes, reproduced source bytes and freshly ran
the fixed graders. Both passed (6 and 35 acceptance cases and each fixed regression
set). Each changed-input probe missed without creating output. No model calls.
The first verification driver passed a tuple instead of the allowance dictionary
to grading; its failure is preserved alongside the corrected verification. This
was a correctness run, not a paid-session retry or timing experiment.

16 authored checks pass for exact output, changed source/configuration/task/context/
mode/untracked inputs, corrupted entries, path traversal, symlinks, output
ownership, concurrent input mutation and source-prefix overlap analysis.

The larger hypothesis is restricted to identical repeated tasks: a prospective
empty-cache experiment must include learning, storage, materialization, fresh
quality checks and failures. No claim for new tasks, cache hit rates in the wild,
or general agent superiority is made by this prototype. Existing closed studies
remain unchanged; heldout tasks remain unopened.

Prospective source 731123b is frozen in Linux runtime-v7. Protocol SHA256:
`5dcb049c598aa232a6c46eadfa3efd610b6001ea6231fcc0309c5867a239d547`.
Eight attempts, six maximum model sessions, two expected exact-result hits,
empty cache at start. Rotating plain/replay order, the same A,A,B,B development
sequence, no retries or replacements. Require complete quality and telemetry,
uniform observed provider tier, and strictly lower total token work AND measured
pipeline wall. All cache learning/recording and fresh grading costs are charged;
shared baseline preflight is split equally. Speed applies to this measured exact
repeat workload only, without a host-quietness or population inference.
A real no-model OpenCode admission passed with private state removed.

## Prospective result (closed, no retries)

All 8 attempts passed their fresh fixed acceptance/regression tests. Both expected
cache misses learned from new model runs, and both expected hits reproduced the
earlier same-condition source with zero model calls. Independent audit verified
terminal/session hashes, fixed grades, source provenance, tiers and arithmetic.

| Four-stage condition | Token work | Charged wall seconds | Quality |
| --- | ---: | ---: | --- |
| Plain | 99,672 | 395.714 | 4/4 pass |
| Exact result replay | 67,567 | 225.032 | 4/4 pass |

The predeclared two-metric direction criterion passed: 32.21% lower normalized
noncached token work and 43.13% lower measured charged wall. The cache hits took
1.741 and 1.734 seconds including fresh grading; their zero tokens are established
by absence of model invocation, not imputation for missing telemetry. The initial
solutions, recording and shared baseline preflight are included in totals. All
six provider response streams reported default despite requested priority.

This is a result for exact repeated tasks only: two dependent development tasks
and one block. New-task benefit, changed-input semantic reuse, monetary billing
and a population speedup are not established. Host quietness was not independently
verified. The runner source 731123b and its original output remain immutable.

See summary.json, audit.json, prospective-evidence.tar.gz and driver.jsonl.
The post-hoc auditor is scripts/opencode_benchmark/analysis/task_replay_audit.py.
Subsequent interface/storage changes are separate and must retain source-equivalent
outputs; they are not retroactively part of this measured block.
