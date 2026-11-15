# Run tasks with the opt-in v2 pipeline

Install CAMI from this branch. Python remains the implementation language. Use the
same task, declared external context and fixed grader contract as
[TASK_SESSION.md](TASK_SESSION.md).

```sh
cami task --mode legacy --workspace /path/project --task-file /path/task.txt \
  --context-file /path/context.json --grade-json '["python", "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"]'
cami task --mode v2 --memory-root /path/private-memory \
  --workspace /path/project --task-file /path/task.txt --context-file /path/context.json \
  --grade-json '["python", "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"]'
```

`legacy` is the default. No old database is migrated. V2 uses
`MEMORY_ROOT/task-v2/SHA256(resolved-workspace-path)/`: `index-v2` holds the
existing ProductMemory/index store, `replay` holds existing exact-task replay v2
artifacts, and `methods` holds verified method records. Changing the workspace
path gives a separate namespace. All repository bytes and modes, exact task text,
external context, model, runner/capture/replay code and fixed grader are bound by
the existing strict input key. Put memory and journals outside the input tree.

The ordinary command captures durable input before searching result memory.
A hit materializes into the journal's `solution`, never into the user's worktree.
The fixed grader runs freshly; a rejected candidate is kept as `rejected-replay`
and the agent solves the original input. A valid hit undergoes the ordinary final
grading again. Read the returned `journal` and `replayed` fields. Model solutions
continue to edit the declared worktree, as in legacy mode.

On a miss, v2 prepares a source packet before model admission. It reuses the
existing worktree refresh, static graph and ProductMemory context APIs. Its
lexical ranking uses the existing adapter's identity/body weights (4/1), rather
than semantic embeddings. Find/context already provide exact selectors and
verified generations; they do not rank an unrestricted natural-language task.
The frozen literal adapter exposes 2400-character prefixes. This packet reads
whole definitions or query-centered windows, related definitions and test/config
windows instead. Every block includes path, physical lines and full-file SHA256.
Metadata identifies the snapshot/generation, incomplete graph and selection
limits. The complete packet is capped at 14000 UTF-8 bytes, including its metadata.
Native agent tools remain available to read omissions and verify current source.

The index and ProductMemory databases persist across commands. Existing refresh
validates captured inputs before reuse and reuses a matching generation; this is
not a new incremental indexer. Changed snapshots use the existing rebuild policy;
v2 does not claim per-file incremental parsing or a new resident daemon. It avoids
constructing the separate frozen prefix catalog on every task. `cache_reused` in
`context.txt` reports index reuse, not solution correctness. Freshness is checked
again before admitting the model. A source packet is an observation, not a claim
that it contains all code needed for the task.

## Eligibility and structured methods

A model result may train result memory only when fixed grading passes without
mutating the submitted artifact, execution succeeded without timeout, every
adapter-declared request has all five nonnegative integer usage components and no
accounting errors, and the caller explicitly declares request coverage. Existing
`task_session.run` supports that declaration for a controlled adapter. OpenCode's
ordinary command deliberately supplies `request_coverage=False`: hidden provider
retries have not been proved fully visible. No CLI flag overrides that protection.
Consequently ordinary OpenCode results currently do **not** train replay or method
memory, even when all observed requests have complete usage. Unknown usage is not
zero. Local contract tests use controlled child processes, not substitute model
responses in the live experiment.

Eligible ordinary `task_session.run(..., v2_state=..., cache=...)` calls create both
existing exact replay artifacts and structured methods automatically. Methods
contain the observed task/symptom, cause explicitly unknown unless established,
changed components, actual unified patch, fixed command/quality/log digest,
input/context applicability and journal provenance. They never contain model
reasoning. Similar tasks receive at most two lexical method hints; large patches
are omitted with a provenance pointer. Similarity never materializes a patch.
Only exact task replay can do that, with fresh grading.

Recovery uses the existing `cami task recover --directory JOURNAL`. It stops the
bound orphan OpenCode session before capture and never launches a second model.
Terminal recovery is idempotent. Interrupted/failed/unknown-usage attempts cannot
train memory. Replay has zero model usage only when no provider was invoked.

## Roll back mode or installed version

Use `--mode legacy`, or omit `--mode`. V2 namespaces remain on disk and are not
read or written by legacy. Switching back to v2 preserves its prepared memory.
To roll back the installed code, install the baseline wheel built from tag
`cami-baseline-20261115` in a separate environment and select that executable.
No reset, clean, schema downgrade or database restoration is needed.

## Roll back changes in the target project

Mode/version rollback does not undo source changes already made by a model.
Inspect the journal's `before` and `solution` inventories and compare the desired
files with the current worktree. Restore only the selected patch after checking
for later user edits. Keep the journal. Exact replay candidates live outside the
worktree and require no project rollback unless you separately applied them.

The final implementation also requires a committed eligible task journal, an
immutable grade-log receipt and the recorded replay digest before materialization.
Calling the low-level `task_replay.record` alone cannot admit a result to this
pipeline. A durable `binding.json` rejects reuse of a v2 state directory by another
worktree, including direct Python callers. Recovery after method publication keeps
the first verification receipt and safely completes the terminal journal record.

The existing `compact_response` removes redundant provenance fields with full
responses in audit receipts; `readable_response` renders only supported literal
prefix payloads and otherwise falls back to compact. Neither selects different
code or expands a truncated prefix. V2 therefore uses a separate readable task
packet over existing index/context APIs rather than treating those display
projections as a task-context builder. Its source and provenance remain together
in `context.txt` and the durable `task_prompt` journal event.
