# Reproduce and audit CAMI v2

The baseline is commit `807285f` (tag `cami-baseline-20261115`). The branch never
changes main or that tag. The study uses the authorized local OpenCode 2.2.5
service with explicit directory and `openai/gpt-6.1-sol#high` bindings. It does
not use Docker model responses, hidden gold responses or a zero model budget.

```sh
uv sync --locked --extra dev --extra llm
uv run pytest -q tests/test_task_v2.py tests/test_task_session.py tests/test_task_recovery.py tests/test_opencode_task_entrypoint.py tests/test_opencode_task_replay.py
uv run ruff check integrations/opencode tests/test_task_v2.py scripts/cami_v2
uv run mypy src/cami
uv run python scripts/cami_v2/analyze.py
```

Raw artifacts live under `runs/cami-v2`. The tracked `raw-evidence.tar.xz` can
restore them in a separate audit checkout. Do not unpack over existing runs.
The raw archive excludes virtual environments and the large baseline Git archive;
the two wheel files and package versions are retained separately. The evaluator
wheel is frozen before measured execution. The final wheel adds strict eligible
journal/replay receipt checks, worktree binding and v2 module identity to context;
its admission is separate. The measured result describes the evaluator wheel,
not a second experiment on the final hardened wheel.

For a new, potentially paid experiment use a separate audit checkout with no
`runs/cami-v2/study`, no report protocol and no pre-existing attempt directories.
Prepare the baseline using `git archive 807285f` into
`runs/cami-v2/baseline` (this is an immutable source export, not a worktree).
Build/install the chosen evaluated wheel in `runs/cami-v2/installed`, record its
hash and packages, and admit it against the intended local service first.

```sh
uv run python scripts/cami_v2/study.py freeze
uv run python scripts/cami_v2/admit.py
uv run python scripts/cami_v2/study.py run
uv run python scripts/cami_v2/analyze.py
```

`freeze` refuses to replace its protocol. `run` refuses even an existing failed
attempt directory. Do not use deletion to bypass those guards in the evidence
checkout. All 12 attempts run in a fixed alternating order with no result-based
extensions. Audits rerun only the fixed grader on preserved solutions, not models.
Per-attempt start receipts include host load. The host is shared and was not
independently isolated; the concurrent local test suite is recorded. This is a
small synthetic sequence with dependent repeats, not a confidence interval.

The timer starts before restoration of the attempt input and ends after the
result JSON fsync. It includes capture, context preparation, OpenCode API calls,
model/tool execution, final grading and permitted persistence. The timing receipt
and post-run analysis/packaging are outside that interval. A timestamp inside the
result is not used as the timer endpoint. Token work sums input, output, reasoning
and cache-write; cache-read is retained separately. Missing components never
become zero. The observations do not certify hidden retries or billed charges.
