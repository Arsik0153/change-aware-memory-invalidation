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
full run after compiler setup was interrupted with 80 passes and 19 failures.
All 19 failures came from Linux-only `/proc/self/fd` tracing in the publication
crash-test hook. The hook now uses `F_GETPATH` on macOS, retaining actual fsync
and all durability assertions. All 24 publication checks then passed. Neither
interrupted run is a full-suite PASS.
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

The Linux ARM64 image builds successfully and its pinned OpenCode executable
passes a network-disabled, read-only, non-root version smoke. See
`runtime-smoke.json`. Existing local OpenCode authentication lists an OpenAI
credential; no credential contents were printed or copied into this report.

## Fresh-clone and filesystem checks

The next full run reached 1665 passes, 13 failures and 12 setup errors. The
remaining causes were test assumptions: unresolved macOS temporary paths,
Linux `/proc` socket creation, an overlong Unix socket path, a Linux-only
subreaper driver, and a collector fixture reading ignored VPS `runs/` files.
The collector now uses the tracked study plan and vocabulary and seals the
installed tokenizer's real files. `tiktoken==0.12.0` is a locked dev dependency.
Socket fixtures bind relative names in their actual parent directories.

The affected groups pass 130 tests, with the Linux subreaper test explicitly
skipped on macOS. Ruff passes and mypy passes for 54 source files. A further
full non-Docker run is in progress; do not treat these focused results as its
completion.

The original Linux Node-stop driver passed against a separately installed wheel
inside Docker, using container-internal working data. It verified Node was gone
at stop confirmation, the watcher exited, the unrelated sentinel survived and
no subsequent memory head appeared. The same driver failed with working data
on a Mac bind mount: status incorrectly observed a free lease while the watcher
was running. The failed attempt and control commands are preserved.

A separate two-process `flock` probe reproduces the filesystem difference:
the contender is excluded on internal `/tmp`, but obtains the lock on the host
bind mount. This is evidence about this Docker Desktop configuration, not all
macOS filesystems. The small script and raw result are retained. Repeat it in a
container with a writable host directory mounted at `/evidence`; both probe
files must be absent before invocation. It creates and removes only those files.

**Local experiment admission now requires working repositories, SQLite state,
and leases on the internal Linux filesystem or a verified Docker volume.** Host
bind mounts are suitable for read-only inputs and post-run evidence export, but
cannot host this experiment's live locking state. A passing binary-version
smoke does not establish filesystem compatibility.

Earlier image attempts remain under ignored `runs/`: one lacked dependencies
when the driver removed `PYTHONPATH`, then the host-bind filesystem failed the
real lease test. Model calls remain zero.
