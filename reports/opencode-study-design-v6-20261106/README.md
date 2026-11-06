# OpenCode development study v6 freeze

This is a new development cohort, frozen before its task-model outcomes. It uses the same two historical Click tasks, canonical revisions, fixed evaluator, three arms, three repetitions and four-stage sequences as v5. It requests `priority` with `openai/gpt-6.1-sol#high` identically in every arm. A separate connectivity check reported `default`; configured priority is never treated as evidence of delivered priority.

The package includes the operation-local exact-subject index, unresolved-membership optimization, complete pinned control-message admission and independent service-tier analysis. All1556 project tests passed on the core implementation;539 controller/harness/analysis checks and three actual no-model OpenCode arms passed. Sealed lint findings and their narrow artifact-only exclusions are preserved in the linked reports.

The full protocol and source/study inventories are immutable. All36 outcomes and their costs remain included, including failed attempts. Mixed or missing provider response tiers disable primary wall eligibility; mismatched configuration disables both primary metrics while preserving observed quality and costs. Uniform reported default remains comparable and is labeled default. No pooling with prior attempts; no inference of subscription billing.

The first three scheduled trials are run individually to verify operational admission before continuing the remaining33. Model-task sessions are sequential. No auxiliary tests, packaging, agents or implementation changes run during measurement. The final heldout task model count remains0 at freeze.

`implementation-source.tar.gz` contains140 current source/dependency/schema files from commit `fa415f0c85d51c886f8f509d26241cb8a836634c`; `source-freeze.json` binds every member. The runtime image and its separate offline archive are specified in protocol.json. Absolute local study paths are retained as original evidence; relocation requires explicit equivalent source binding.

Execution (first scheduled trial):

```sh
.venv/bin/python scripts/opencode_benchmark/controller/study_controller.py \
  --study runs/opencode-development-study-v6-20261106/study.json \
  --study-sha256 b66e4d557b7b7cdf0800b4c9121e793659f3a02029a74b026c7f7c4d75243cdd \
  --run-model --one-trial r1-plain-s1 --out runs/opencode-development-v6-20261106
```

Use `--resume` with the next planned trial for subsequent admission checks, then resume the remaining fixed schedule without `--one-trial`. Never rerun or replace a terminal attempt.
