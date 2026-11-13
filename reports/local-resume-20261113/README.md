# Local continuation, 13 November 2026

Work resumes on the user's macOS ARM64 laptop from `399134f`. New timing
measurements must not be pooled with the previous VPS series.

## Verified

- Created `.venv-local` with Python 3.12.14 and `uv sync --locked --extra dev`.
  The old `.venv` points to a missing interpreter under `/private/tmp` and is
  retained unchanged.
- Started the existing Docker Desktop installation (engine 28.3.3).
- Installed the official `@opencode/cli` 2.2.5 under ignored `.tools/opencode`.
  The native ARM64 executable reports `opencode v2.2.5`.
- Installed the project's trusted TypeScript 6.0.3 compiler with `cami setup-typescript`.
- The focused adapter/controller/analysis/harness suite passes 798 tests.
  The exact command is below. Ruff on the two edited test modules and
  `git diff --check` also pass.

The first focused run failed nine tests. Four analysis checks used a temporary
path beneath macOS's `/var` symlink, which the evidence guard correctly rejects.
The fixture now resolves its own temporary root before creating evidence. Five
mocked harness checks depended on the real VPS executable and root-only chown.
They now supply a synthetic executable with its actual digest and mock ownership
changes alongside the already mocked Docker calls. Production guards are unchanged.
These unit checks do not verify real container ownership or binary compatibility.

```sh
.venv-local/bin/pytest -q tests/test_opencode_readable_response.py \
  tests/test_opencode_readable_adapter_wiring.py \
  scripts/opencode_benchmark/controller scripts/opencode_benchmark/analysis \
  scripts/opencode_benchmark/harness
```

The initial full non-Docker run was interrupted after missing-TypeScript failures.
A separate fail-fast run confirmed that cause (13 passed, one failed). A new
full run after compiler setup is in progress. Neither is a full-suite PASS.
Raw working logs are under ignored `runs/local-resume-20261113/`.

## Next execution units

1. Finish the local full suite and Linux ARM64 runtime build, then exercise actual
   no-model container transport, memory catalogs, publication and cleanup.
2. Remove VPS-specific assumptions through explicit frozen runtime configuration:
   binary identity, Docker endpoint, certificate bundle and host ownership.
   Existing frozen studies must retain their old meaning.
3. Implement and verify the proposed five-condition, twenty-session development
   schedule. The current controller enforces three arms and three repetitions;
   readable wiring alone does not implement this experimental design.
4. Freeze the local source/runtime/protocol and run the authorized development
   comparison. Do not run cleanup or auxiliary benchmarks during timed sessions.
   Record actual provider tier, all failures and complete construction/audit cost.
5. Analyze the preregistered token/read-byte direction within both memory backends.
   A single block supplies development evidence, not confirmed superiority.

No task-model or heldout sessions have been launched in this continuation.
