# Initialization profile and staged public batch API

The measured problem is repeated whole-view preparation plus repeated persisted state generations, not expensive row insertion. The staged API resolves a bounded set of queries from one verified union of subject-path probes, then registers a batch in one atomic knowledge publication. The existing database size guard remains unchanged. No production files were edited or installed by this agent.

## Preserved diagnostic evidence

`profile16/` is one cProfile run of the existing sequential adapter prepare on the first 16 real origin notes, with globally unique note keys. All 16 Python source files under the original source root were copied byte-for-byte into a private authored Git fixture: 347,845 Python bytes plus the original `.gitignore`. The selected 16 notes share one source path, `src/click/_compat.py`. No task prompts, future solutions, evaluation oracles or models were used. The original source hashes remained unchanged.

| Observed work | Sequential16 | Final staged batch16 |
|---|---:|---:|
| Public context calls | 16 | 1 `context_many` |
| Registration calls | 16 `remember` | 1 `remember_batch` |
| Final refresh | 1 | 1 |
| Shared preparation operations | 33 | 3 |
| Verified live captures | 99 | 9 |
| Python index builds | 1 | 1 |
| Full Python view projections | 33 | 3 |
| Signature projections | 16,896 | 1,536 |
| Note-state transitions | 136 | 16 |
| Saved revisions / receipts | 16 / 16 | 16 / 16 |
| Stored memory generations | 17 | 2 |
| Stored record-state rows | 136 | 16 |
| SQLite bytes | 4,722,688 | 1,277,952 |
| Whole state-directory bytes | 6,468,919 | 3,024,183 |

Both output catalogs are exactly equal, and all 16 records are initially available as manual notes. The batch intentionally has one atomic post-batch generation instead of serial intermediate publications. It does not create fake per-record check events or fabricated per-item timings.

For the sequential run, catalog capture was 10.156 s wall (16 contexts), registration was 9.694 s total (16 remembers), final refresh 0.497 s, total 20.369 s wall / 17.235 s self+completed-child CPU. Final batch measured context_many 2.465 s, remember_batch 0.642 s, final refresh 0.509 s, total 3.634 s wall / 3.492 s CPU. **These are single instrumented diagnostic runs, not a speedup estimate or a repeated timing benchmark.** The sequential side overlapped a separate full-catalog job; the final batch run had different contention and briefly overlapped a mypy check. Imports are outside the profile, cProfile/observer overhead is included, and no randomized alternating repetitions were run. Do not extrapolate the first16/single-path timings to329 or to model-task latency.

The sequential profile's cumulative stacks identify full Python projection at 7.326 s, capture at 3.115 s, cache loading at 2.498 s and initial index build at 1.863 s. Pydantic core JSON validation was 4.306 s across overlapping callers. SQLite connection validation was 0.892 s; saving 16 revisions was 0.003 s. Cumulative times overlap and must not be added. There were 925 subprocess.run calls (including 496 repository Git calls and 396 Git-ignore checks). Batch final has 85 subprocess.run calls. `PythonIndexAdapter.project` reparses all captured modules and normalizes all512 definitions on every prepared view, even when the saved index is reused. No Rust rewrite is justified by this profile.

Raw evidence: `profile16/{prepare.prof,top-cumulative.txt,top-cumulative.json,counters.json,phase-observations.json,result.json,input-manifest.json}`, corresponding `batch16-final/` files, and `sqlite-comparison.json`. `batch16/` preserves an earlier draft profile before the final two coordinator refinements; it is not the final source or a same-version repeat. Baseline production source is preserved by root at `runs/opencode-runtime-development-20261104/baseline-v1/extracted/src/cami`.

## Why unchanged source produced different index generations

The read-only sample of root's running 329-note state captured19 completed index manifests: one analyzer fingerprint, one captured-entry hash, one policy hash, but19 distinct `path_coverage` sets. Fifteen were single-path query sets and the others were growing registration-path sets. This is recorded in `root-running-state-observation.json`; it is a sample during execution, not a complete final inventory.

`_probes` includes each path-qualified query and registered subjects. `capture` includes probe coverage in snapshot identity. `refresh_locked` keys generation by captured snapshot plus analyzer fingerprint and verifies matching coverage when loading. Thus querying a different file or adding a new path to the registered set changes the index generation despite identical code bytes. The small16 run demonstrates real reuse when all queries share the same path:33 prepares but only one index build.

Do not delete coverage from snapshot identity: absent-path witnesses and compatible saved readsets depend on it. `context_many` fixes the complete probe union before the first preparation, and `remember_batch` retains the same union through current validation. Path-qualified seed selectors provide this benefit directly. Unqualified queries are still supported but may discover subject paths only at registration, causing a further legitimate coverage expansion.

Root's separate full329 sequential v2 later failed at the existing database guard after131 registrations: published DB266,428,416 bytes, state293,344,050 bytes. Its diagnostic reports146 memory-generation JSON rows totaling122,227,344 bytes and8,646 record-state rows totaling122,108,177 bytes, versus290,989 bytes of revisions and41,658 bytes of receipts. That evidence is owned/preserved by root, not rerun here. It confirms that serial repeated state history, including duplicated state JSON in two representations, is material to the practical failure. The staged batch keeps the same storage guard and current-state representation; it changes only explicit batch history granularity.

## Public staged API

Affected files are only `batch-api/src/cami/product/service.py` and `batch-api/src/cami/product/memory/models.py`.

```python
contexts = memory.context_many(("a.py:alpha", "b.py:beta"))
requests = (
    RememberInput(kind="note", query="a.py:alpha", context=contexts[0],
                  request_id="seed-a", note_key="excerpt:a", text="Origin source assertion..."),
    RememberInput(kind="note", query="b.py:beta", context=contexts[1],
                  request_id="seed-b", note_key="excerpt:b", text="Origin source assertion..."),
)
receipts = memory.remember_batch(requests)
```

Both arguments must be tuples with1–1024 items. Queries retain existing nonempty/NUL rules. RememberInput contains kind, query, an actual AgentContext, request ID and optional note key/text. It has no caller-supplied expected-signature field. Batch request IDs must be distinct; note keys must be globally distinct inside the batch, matching existing worktree-wide note identity. Global conflicts with established records still use the existing semantic-identity checks.

`context_many` prepares one verified view and projects each query from the same index/memory generation. The single `context` delegates to a one-element batch. `remember_batch` authenticates all contexts against immutable stored views and context generations; a shared origin view is loaded once. The existing authenticated payload derivation is shared with the single mutate/update path. Signatures and source refs are derived from trusted backend context, never from agent-declared expectations.

A single multi-request coordinator handles both old single operations and new batches. It preserves current capture, source-CAS checks, current validation/withholding, final recapture, database transaction and durable store publication. All new batch receipts name the one final batch generation. Retried existing receipts retain their exact original generation and contents, even in a mixed retry/new batch. The complete receipt tuple is built and checked before COMMIT. Failed authentication, conflict, CAS corruption or final verification does not publish partial records, receipts or a new knowledge head. Valid immutable cache/index/source objects may remain, as in the existing failed-refresh contract; filesystem-wide rollback is not promised.

Stale authentic origin contexts are accepted, preserving their original expectations, and current contradictions/uncertainty are withheld. No auto-retargeting or note-truth validation is added. Existing single remember/update/history/CAS/idempotence semantics remain in the shared coordinator. No storage cap, validator/analysis rule, source policy, absence proof, capture retry or verified-readset guarantee is relaxed.

## Verification and remaining work

Final staged sources passed13 authored batch tests plus all19 existing `tests/memory/test_memory.py` tests:32 passed in27.13 s. Ruff is clean; strict mypy found no issues in the two affected files. Batch tests cover common union/view, equivalent sequential payload/current availability, atomic receipt generation, per-request retries and conflicting reuse, mixed retry/new receipt generations, duplicate global note keys/request IDs, conflict rollback, forged context rollback, source edits between projection and verification, final-verify rollback, stale-origin withholding, source-CAS corruption, bounded inputs and individual mutation/update/history compatibility.

The isolated `batch-api/runtime/cami` copy contains all unchanged baseline files plus these two staged replacements for authored tests and profiles. It is not installed production code. Root's batch adapter was read-only reviewed: it calls context_many once for either seed spec or explicit catalog, remembers once, retains final refresh/source/availability/payload checks and reports a single batch-registration span without allocating fake per-item timings. Static behavior is unchanged.

Root must review/apply exact source hashes, run broader product/watch/full suites and perform the full329 batch feasibility test before claiming that the catalog now fits. A repeated unprofiled, alternating controlled benchmark is required for any speedup estimate. Real OpenCode task quality/latency/cost remains a separate study. No model calls or full329 duplicate run were performed here.

## Reproduction

The profile helpers use only source-only origin inputs and independent private Git/state copies. Output directories must be new.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python runs/opencode-memory-profile-development-20261104/profile_prepare.py \
  --adapter-dir runs/cami-opencode-adapter-development-20261104 \
  --origin runs/opencode-study-development-20261104/preflight/help-api-base \
  --seed-spec runs/opencode-study-development-20261104/seed-origin/seed-spec.json --count 16 --out NEW_SINGLE_OUT
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=runs/opencode-memory-profile-development-20261104/batch-api/runtime \
  .venv/bin/python runs/opencode-memory-profile-development-20261104/profile_batch.py \
  --runtime runs/opencode-memory-profile-development-20261104/batch-api/runtime \
  --adapter-dir runs/cami-opencode-adapter-development-20261104 \
  --baseline runs/opencode-memory-profile-development-20261104/profile16 --out NEW_BATCH_OUT
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=runs/opencode-memory-profile-development-20261104/batch-api/runtime \
  .venv/bin/python -m pytest -q runs/opencode-memory-profile-development-20261104/batch-api/test_batch_memory.py tests/memory/test_memory.py
```

To reproduce the old sequential runtime after production changes, place the preserved baseline source directory first in PYTHONPATH. The source inventory and raw profile are pinned; the command must not accidentally use installed batch code when reproducing the old baseline. The root full329 failures and source copies remain separate preserved artifacts.
