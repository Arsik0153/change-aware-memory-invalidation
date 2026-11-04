# Extend the research replay to ordered first-parent snapshots

The old protocol remains frozen. Its access scope explicitly excludes rejected explored successors and side-parent snapshots. The new proposal needs its own driver, tests and seal before it permits any of the additional development snapshots.

## Change only the research driver

`src/cami/repository.py:60–69` requires every child to have exactly one parent. It intentionally rejects a merge even when the preceding snapshot is its first parent. Keep this production API unchanged.

The old research driver calls that API for every group before reading snapshots, at `scripts/run_real_structural_replay.py:72–76`. Its snapshot loop already compares `before` with the current child and advances `before` after each step, at lines131–135 and194. That comparison remains correct for the proposed merge semantics.

Create a separately named research driver, such as `scripts/run_real_structural_first_parent_replay.py`. Preserve the frozen old runner. Reuse the unchanged sealed-input checks and reference helpers where possible. Do not monkeypatch `chain` or silently make an old protocol accept merges.

The new driver's preflight needs these checks:

1. Require the new protocol ID and `trajectory_mode=ordered_first_parent_snapshots_v1`.
2. Verify the new seal, input hashes and complete frozen topology for all groups before any source reader runs.
3. Resolve exact commit IDs with replacement objects and lazy fetch disabled.
4. Read each commit's ordered parent IDs. Require equality with its frozen full parent list.
5. Require a nonempty parent list and `parents[0] == previous_commit`. Permit additional parents only as recorded metadata.
6. Require exactly the12 frozen first-parent successors per group under the pinned boundary. Preserve the old sequence as the unchanged prefix.
7. Reject duplicates, gaps, reordered steps, alternate ancestors, a changed boundary or a shortened history. Do not search for replacements.

After preflight, restart each variant at its original parent and replay all12 steps. At a merge, compare the current merged snapshot only to the preceding first-parent snapshot. Do not read another parent's tree, compute a merge base, request a combined diff or reset state at a merge.

Preserve all four original research variants, reference v2, claim hashes, eligibility rules and cost accounting. Include `previous_commit`, the complete ordered `parent_commits`, `first_parent_commit`, `is_merge` and `comparison_basis=preceding_first_parent_tree` in transition evidence. The comparison must use the actual frozen merge result, without inferring how its branch was merged.

## Test with authored Git histories before touching the corpus

Create new temporary fixture repositories under an isolated test directory. Do not run real corpus replay during implementation tests.

- Accept a two-parent merge whose first parent equals the previous frozen snapshot. Preserve both parent IDs and their order in evidence.
- Reject the same merge when the previous snapshot equals its second parent. Reject a gap, reordered children, duplicate child and changed full-parent list.
- Accept an authored merge with more than two parents if its recorded first parent is the previous snapshot. This checks the generic rule without assuming actual Click merges have that shape.
- Put a signature change on a feature branch and merge it into a first parent that retains the original signature. Check that the selector compares against that first parent and detects the merged change. Comparing against the feature parent would miss it.
- Resolve an authored merge to a tree identical to its first parent but different from its second parent. Check that the merge alone does not manufacture a subject change or a validation call.
- Preserve signature staleness, deletion, ambiguity and recovery behavior through a merge sequence. Keep reference-unknown observations separate from false availability.
- Make a source reader fail if queried for any side-parent snapshot. Metadata may list side-parent IDs; the replay must never request those trees or blobs.
- Give the final group an invalid first-parent edge. Mock both production and independent source readers and assert that no group reads any snapshot before the global preflight rejects the protocol.
- Repeat seal-mismatch and implementation-change denial tests. Preserve a failure manifest and never overwrite an existing run.
- Check fixed candidate denominators:24 claims, three groups,12 steps per group,288 observations per variant,1152 across four variants. Keep excluded-parent records and show176 added observations separately from112 old-overlap observations.
- Check topology strata:10 merge steps and26 nonmerge steps give80 and208 candidate observations per variant. These are accounting checks, not expected scientific outcomes.
- Keep a regression check that production `repository.chain` and the old runner still reject a merge under the old protocol contract.

Do not weaken the old seal to reuse its runner. If common execution code cannot be reused without changing a frozen implementation file, keep the new research entrypoint separate and record its small implementation difference. The new entrypoint and its dependencies need a new seal.

## Interpret the added coverage

The whole extension has36 transitions and288 candidate claim-child observations per variant. Only22 transitions are new relative to the completed old replay. They add176 observations,88 in each formerly one-step group and zero in the group already replayed for12 steps.

Report the added subset as new coverage, and report the old overlap and full trajectory separately. The extension is motivated after observing the old study and uses the same selected claims. It does not become held-out evidence or an independent sample. Merges can aggregate several branch changes into one observed step, so a merge-versus-nonmerge comparison cannot identify a causal merge effect.

Keep false availability restricted to independent-reference `contradicted`. Report `available_unknown` separately. Report logical validation calls and actual executions, without a wall-time speedup claim. Zero contradicted observations give a null conditional false-availability rate and do not establish universal safety.
