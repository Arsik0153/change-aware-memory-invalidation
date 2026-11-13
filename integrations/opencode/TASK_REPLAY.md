# Exact-task result memory (experimental)

Use this when the **same source-editing task** arrives again on exactly the same
repository files and external environment. The module stores changes under
`src/`, keyed by the exact task text, all regular workspace file contents and
modes, and your external context identity. Git metadata is excluded. It does not
reuse a result after a source, configuration, test, untracked-file, mode, task or
context change. Symlinks, hardlinks and special files are rejected.

This is separate from CAMI's source-prefix lookup. It does not infer semantic
validity after changes and does not automatically edit your working directory.
It creates a **new candidate that requires fresh testing**. Non-source edits are
not replayed. Recording alone does not certify a result's quality.

From a checkout, after solving and validating a task:

```sh
python integrations/opencode/task_replay.py record \
  --before /path/to/canonical-input \
  --after /path/to/completed-workspace \
  --task-file /path/to/exact-task.txt \
  --context-id 'toolchain-and-environment-identity' \
  --cache /path/outside/workspaces/result-memory
```

For a later request, use the same task text and context identity:

```sh
python integrations/opencode/task_replay.py materialize \
  --workspace /path/to/current-input \
  --task-file /path/to/exact-task.txt \
  --context-id 'toolchain-and-environment-identity' \
  --cache /path/outside/workspaces/result-memory \
  --out /path/to/new-candidate
```

Read the JSON `status`: `miss` makes no output; `candidate_requires_grading`
creates the new workspace. **Run your acceptance/regression checks on that
candidate before accepting it.** A successful command exit does not mean the
candidate has passed tests. The output must not already exist or be inside the
input/cache, including through a symlinked parent. Cache paths must be outside
both recording inputs. The input workspace is never patched.

Bind `--context-id` to inputs outside the repository that matter for correctness,
for example an immutable container/toolchain identity and external dependency
versions. The caller declares this boundary; the module cannot detect changes to
remote services or unspecified environment inputs. It executes no repository
scripts and makes no model requests.

Version 2 compresses changed-file content and stores a digest of the complete base
file inventory. Decompression has an explicit bound and validates each restored
file hash. Cache publication is atomic and durable on the local filesystem;
concurrent identical records converge, conflicting results are rejected, and a
failed materialization removes its own incomplete output. Version 1 records from
the frozen experiment are not silently reinterpreted as version 2 records.

## Evidence

The [full development experiment](../../reports/opencode-full-replay-20261114/README.md)
ran 80 attempts: five independent empty-memory blocks, four conditions, and the
sequence A,A,B,B within each condition. All attempts passed fresh fixed tests.
CAMI plus version 2 result memory used 53.65% less noncached token work and 49.77%
less measured pipeline time than CAMI alone, comparing medians across blocks.
Both metrics improved against plain OpenCode, static memory and CAMI in every
paired block. Ten exact-repeat hits made no model request; all ten changed-input
probes rejected reuse and their unchanged positive controls succeeded.

The first solutions, source-memory construction, replay costs and fresh quality
checks are included. Final evidence packaging is outside the timed region. This
is evidence on exact repeats of two development tasks, not 80 independent tasks
or a real-world hit-rate estimate. All 70 model sessions observed the same service
tier. Token work is not billed currency. Later SQLite compaction is measured
separately and does not retroactively change this model experiment.

### Earlier pilot

The separate prospective experiment began with an empty cache and ran two
real Click development tasks twice per condition. All eight attempts passed
fresh fixed tests. Including the initial solutions, recording, materialization,
grading and shared baseline preflight, result memory used 32.21% less noncached
normalized token work and 43.13% less measured pipeline wall time. Two expected
cache hits invoked no model. This is one dependent block of **exact repeats**,
not a result for arbitrary new tasks or a real-world cache hit-rate estimate.
Timing lacks independent host-quietness verification; token work is not billed
currency. See [the full protocol and evidence](../../reports/opencode-task-replay-20261113/README.md).

The measured runtime used version 1. Version 2 interface/storage improvements are
verified separately for source-equivalent output and fixed-test quality, without
retroactively changing that run.
