# Lookup profile publication handoff

Ready; no tracked writes/commits, models, Docker, profile reruns or target-source execution. Quiet timing was held during packaging and explicitly released after compression/readback/offline verification completed.

`public-profile-evidence.tar.gz`: **7,132,294 bytes**, SHA256 **`dad2a64d060cbd8144f78487711e88862b442670d34465d6a2e52731bf2ef435`**. Contains 784 payload files plus the internal manifest, 785 ordinary tar members. Two deterministic builds matched; extracted SHA/size/mode checks and admitted-original rehashes passed.

Coverage is deliberately partial in bodies, complete in original declared inventories:

| Original report | Declared artifacts | Included bodies | Omitted bodies, SHA retained |
|---|---:|---:|---:|
| Baseline | 2,431 | 403 | 2,028 |
| Candidate1 | 1,258 | 202 | 1,056 |

All **45 `.prof` files** (30 baseline + 15 candidate1), their profile JSON/MCP outputs/backend traces and container/preparation evidence are retained. Full workspace/Git and memory/cami-state bodies are omitted without reading them. This is not an all-raw-payload backup. The exact per-file original omission inventory is `publication-analysis/coverage.json` inside the archive.

The offline helper reproduced all 15 original candidate comparison rows, changed-snapshot attribution statistics and portable MCP equality excluding original receipts. It verified the 60-file baseline/candidate core inventories differ only in `cami/index.py`, shared nine-file adapter and immutable catalogs. Existing exact-index equivalence cases are preserved, not rerun. Instrumented/concurrent profile timings remain attribution only, never a quiet/model/end-to-end speedup claim. Candidate2 and future quiet measurements are separate.

Controller provenance is explicit: actual profile plans pin preparation_worker, profiler worker/orchestrator and production/adapter. Other current controller copies are publication-time corroboration; frozen v5 expected controller sources are separately labelled. Neither is retrospectively claimed as separately captured profile-start loaded bytes. External full development fixture archives and original model-transcript body are not copied; the frozen study/query/reset/source inventories remain included.

Publication overhead only: **2.805s wall / 2.483s CPU** for hashing, double compression, extraction and admitted-source rechecks; offline verification was a separate short standard-library process. These values are not original lookup or benchmark costs.

Publish the archive plus README, this handoff, build/reproduction scripts, packaging/verification reports and final `manifest.json`. The extracted tree is an ignored verification copy and need not be duplicated. All original baseline/candidate1 files are unchanged. There were no packaging failures. Root owns publication/commits; this agent is finished.
