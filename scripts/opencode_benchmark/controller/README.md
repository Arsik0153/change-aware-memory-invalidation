# Sequential source-memory study controller (installed)

No task models have been called by this implementation. Default invocation validates pins and writes a 36-trial plan without launching Docker. The authored integration uses only a synthetic two-version source fixture, no prompts admitted to models, no authentication import, and zero assistant messages/tokens.

Modules: `study_schema.py` validates/normalizes bundles and pins; `study_workspace.py` owns canonical resets and source export; `study_runtime.py` runs construction, sessions and isolated grading; `study_ledger.py` preserves terminal attempts and summaries; `study_controller.py` is the CLI. `preparation_worker.py` and `fixed_grader.py` are trusted container entrypoints. Tests and authored integration are separate.

## Freeze and plan

Use absolute immutable runtime-copy paths for the final study. Run this only after the harness owner declares its helpers stable. The output directories must be new paths under the repository's ignored `runs/`.

```sh
.venv/bin/python scripts/opencode_benchmark/controller/study_controller.py \
  --make-study --kind development \
  --bundle examples/opencode_benchmark_development_v1 \
  --harness ABS_HARNESS_DIR/container_session.py \
  --runtime-manifest ABS_RUNTIME_MANIFEST_JSON \
  --cami-source ABS_IMMUTABLE_SRC --adapter ABS_IMMUTABLE_ADAPTER \
  --image sha256:IMMUTABLE_IMAGE_ID --out runs/NEW_STUDY_CONFIG
```

`study.json` initially has `execution_authorized:false`. Root may set it to `true` under the already authorized study, then freeze its exact bytes and record its SHA. This does not request further user permission. All top-level harness Python modules plus the sentinel are pinned; additions/changes fail validation. Production and adapter inventories include all non-cache regular files, not only Python. Controller modules, source generator, base archives, prompts, seed and fixed evaluator assets are pinned.

```sh
.venv/bin/python scripts/opencode_benchmark/controller/study_controller.py \
  --study runs/NEW_STUDY_CONFIG/study.json --out runs/NEW_PLAN
```

Heldout format: use `--kind heldout --bundle ABS_EXTRACTED_PORTABLE_BUNDLE`; its `tasks.json` supplies prompts/base archives, sequence, fixed private oracle roots and node IDs. No gold source archive is read or mounted. Root's tracked heldout delivery is an archive and must first be verified/extracted privately. Do not replace it with the ignored preparation directory in a published protocol.

## Explicit execution and resume

Only root invokes model execution after freeze. `--one-trial` is development-only and must name the next pending scheduled trial. Execution requires authorization plus exact study SHA and exact runtime manifest equality. A plan directory cannot be converted into a model run.

```sh
.venv/bin/python scripts/opencode_benchmark/controller/study_controller.py \
  --study FROZEN_STUDY_JSON --study-sha256 EXACT_SHA \
  --run-model --one-trial r1-plain-s1 --out runs/NEW_EXECUTION
# Later, same arguments and study, with --resume and optionally next --one-trial:
.venv/bin/python scripts/opencode_benchmark/controller/study_controller.py \
  --study FROZEN_STUDY_JSON --study-sha256 EXACT_SHA \
  --run-model --resume --out runs/EXISTING_EXECUTION
```

Order is cyclic across repetition and canonical stage, sequential only: three arms × four stages × three repetitions. Each repetition/arm has a unique memory namespace and a fixed host workspace inode/path. Every stage destroys the previous `.git` and source children, restores only that stage's canonical base, and creates one fresh commit with no remotes or previous/unreachable history. No model patch becomes a later input. The persistent memory DB is never copied between namespace identities.

Plain skips memory generation/preparation completely and requires an empty dummy memory directory. Static/CAMI each generate and pay for the same origin seed independently, inside the same image at `/workspace`, then prepare once at `/memory`. Later stages preserve that memory and verify the exact seed/catalog/binding bytes before and after sessions. Subject byte hashes in the initial catalog must equal canonical origin files. Generator/prepare use trusted absolute scripts, cwd `/` and trusted Python import paths. Native agent task tools retain workspace-first imports through the harness.

Terminal records are new-only and never rerun, including failures. `--resume` validates terminal artifact hashes. An incomplete directory becomes an explicitly abandoned terminal attempt with unusable memory, never a retry. Dependent stages are blocked if their memory namespace is unusable; other eligible trials continue. Initialization failure never falls back to plain. Operational session status and fixed-patch test quality are separate fields.

Source capture uses actual filesystem bytes, independent of agent commits or deleted Git. It includes additions, deletions, changed modes, exact source hashes and non-source change inventories. Only regular `src/**` is admitted, with symlink, FIFO, special-file, traversal and hardlink rejection and bounded source export. Candidate tests/config are ignored by evaluation. Fixed tests are restored outside the agent workspace, mounted read-only into a separate UID65534, network-none, 2CPU/2GiB container. Trusted pytest is imported before candidate source; preloaded subject packages are removed so the candidate package is tested. Gold source, memory, credentials and other trials are never mounted in the grader. A passing model narrative is never a score. Trusted pytest hooks retain collected/executed/passed/failed/skipped/xfailed/xpassed/error counts and exact node IDs. Acceptance requires at least one executed test and no skip/xfail/xpass. Before any model trial for a task, the canonical base supplies a preserved regression collection/skip allowance as common fixture infrastructure. Candidate regressions cannot reduce collection below that baseline or introduce additional skipped/xfail nodes; legitimate baseline skips remain allowed. No gold source is involved in this allowance.

## Evidence and accounting

Every trial retains canonical archive SHA/full reset inventory, immutable origin catalog SHA, recursive session evidence (including CLI/backend trace when supplied), candidate source snapshot and patch metadata, fixed-test logs and resource records. Setup/generation/preparation/session/cleanup failures stay in place. The construction and session timers are inclusive; guard/orchestration remainder is also charged, and nested phase times are never added again. Plain construction cost is zero. Canonical fixture work and fixed evaluator work are separate infrastructure. Session inclusive cost retains auth transfer/startup/cleanup; the harness separately records auth transfer so it is not silently subtracted.

Per-trial costs retain container cgroup CPU deltas/peak memory, host controller/child CPU, inclusive elapsed times, logical workspace/memory bytes and state cleanup evidence. Docker daemon CPU is outside these CPU counters. Cgroup snapshots do not measure a model provider's computation or subscription billing; session token evidence has the pinned client's normalization limits. Failed/incomplete measurements are labeled incomplete, not imputed as zero. Summaries retain three dependent four-stage sequences per arm, quality failures and raw token records; they make no speedup, causal or generalization claim.

## Authored verification

```sh
.venv/bin/python -m unittest discover -s scripts/opencode_benchmark/controller -p test_controller.py -v
.venv/bin/ruff check scripts/opencode_benchmark/controller/*.py
.venv/bin/python scripts/opencode_benchmark/controller/authored_integration.py \
  --harness ABS_STABLE_HARNESS/container_session.py \
  --runtime-manifest ABS_RUNTIME_MANIFEST_JSON \
  --cami-source ABS_IMMUTABLE_SRC --adapter ABS_IMMUTABLE_ADAPTER \
  --image sha256:IMMUTABLE_IMAGE_ID \
  --out runs/NEW_AUTHORED_INTEGRATION
```

The integration has no model execution flag. It tests real container seed/preparation and no-model sessions for three arms at two canonical synthetic versions, plus fixed grading. A deliberate `src/pytest.py` poison module verifies the test runner comes from the trusted runtime.
