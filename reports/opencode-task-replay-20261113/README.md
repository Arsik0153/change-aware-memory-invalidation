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
