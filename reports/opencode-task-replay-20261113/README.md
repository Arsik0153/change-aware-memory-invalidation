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
the fixed graders. Both passed (6 and35 acceptance cases and each fixed regression
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

Prospective source731123b is frozen in Linux runtime-v7. Protocol SHA256:
`5dcb049c598aa232a6c46eadfa3efd610b6001ea6231fcc0309c5867a239d547`.
Eight attempts, six maximum model sessions, two expected exact-result hits,
empty cache at start. Rotating plain/replay order, the same A,A,B,B development
sequence, no retries or replacements. Require complete quality and telemetry,
uniform observed provider tier, and strictly lower total token work AND measured
pipeline wall. All cache learning/recording and fresh grading costs are charged;
shared baseline preflight is split equally. Speed applies to this measured exact
repeat workload only, without a host-quietness or population inference.
A real no-model OpenCode admission passed with private state removed.
