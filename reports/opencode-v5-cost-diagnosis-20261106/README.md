# v5 cost diagnosis, read-only

CAMI's measured memory costs are real but small relative to the whole task session. All36 original trials are included, with35 operational passes,1 original operational failure, and36 fixed-quality passes. All8094 terminal artifact hashes and exact file coverage verify. No trial is excluded and no model/network/container/profiler run was performed for this report.

| Across12 stages per arm | Plain | Static | CAMI |
| --- | ---: | ---: | ---: |
| Charged wall, seconds | 1617.57 | 1629.77 | 1701.46 |
| Origin construction, seconds (3 per memory arm) | 0 | 3.21 | 13.94 |
| Memory tool execution union, seconds | 0 | 0.43 | 17.63 |
| Native tool execution union, seconds | 42.39 | 40.54 | 40.83 |
| API span outside recorded tool execution, seconds | 1489.86 | 1499.71 | 1540.35 |

Charged wall is construction + inclusive session + guard/orchestration. The API partition is nested inside session; the rows in this table must not all be summed. Parallel native tools use interval unions. Backend lookup timers, CPU, startup/readiness/auth and preparation subtimers remain nested in JSON rather than being added twice. Fixed-test/canonical infrastructure remains separate.

CAMI's four-stage block totals are570.97/561.69/568.80s, static538.75/521.53/569.49s, plain526.82/546.72/544.03s. CAMI-minus-static block deltas are+32.22/+40.16/−0.69s. These are3 dependent development repetitions with different generated tool sequences; no causal/superiority claim follows, and the primary all36 operational prerequisite remains unmet.

The largest measured controllable memory scope is lookup:12 backend calls total17.43s wall/16.11CPU seconds, versus0.265s static. API ran-to-completed memory execution totals17.63s. Stage3 changed-snapshot lookup is2.52–2.63s (median2.600), while stage2 unchanged-head lookup is0.95–1.10s (median1.036) and stage4 is1.13–1.23s. Each session is a new process and first CAMI import is charged to its first lookup. The frozen trace cannot separate import, observe/refresh, origin verification, ranking, serialization, or storage traversal. `generation_changed` compares to a new process-local `None`, not proof of an input transition. Checked/carried state counts are not validator call counts.

Three CAMI origin constructions total13.94s, with nested adapter-function11.31s, catalog/context capture3.99s, registration4.05s, origin reauthentication0.31s and seed generation0.48s. Subtimers are incomplete and not added to inclusive totals. Static origin work totals3.21s. The common full setup is identical at origin and preparation is charged once per memory arm/repetition.

Eliminating every measured CAMI construction and memory execution interval on this fixed trace removes31.57s, or1.86% of CAMI charged wall. This is an accounting ceiling with every other event held fixed, not a predicted speedup or a counterfactual about model behavior. The71.69s aggregate CAMI-static difference cannot all be attributed to memory work. Their non-tool API residual differs by40.64s, but no provider-only wait/compute meter exists. This residual includes model/provider streaming, waits and coordination. Some patch `created→ran` spans exceed55s while actual execution is about0.07s; those intervals may include argument generation and must not be called tool execution or pure queue wait.

The next bounded target is the cold lookup/refresh path, especially stage3. Profile fresh owned copies with a cold process, unchanged head and changed canonical snapshot; charge preparation separately. Measure where the CPU goes before changing core code. A candidate must remove demonstrably redundant capture/index/materialization/serialization work while retaining final fresh guards, all329 records, exact literal predicate, withholding, ranking/budget and receipt checks. Eager import that only moves work into startup is not an optimization. No Rust or broad rewrite is justified by this evidence.

## Reproduce without model calls

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python runs/opencode-v5-cost-diagnosis-20261106/diagnose_costs.py \
  --run runs/opencode-development-v5-20261104 \
  --published reports/opencode-development-v5-final-20261105 \
  --out NEW_OUTPUT_DIRECTORY
```

Existing outputs cannot be overwritten. Final output is `analysis-v2/`; `analysis-v1/` preserves the first read-only iteration. `diagnose_costs.py` verifies public terminal hashes/coverage and reads only named preparation metrics from memory namespaces, checked against terminal hashes. It never reads private state or mutates v5. `finalize_diagnosis.py` derives `findings.json` from the final report. Three authored tests verify union accounting, streaming/preexecution distinction, and missing metrics remaining unknown. No new live benchmark was run; historical load and provider nondeterminism cannot be reconstructed completely. Evaluation-only script time is not trial/model cost.
