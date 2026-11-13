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

## Local runtime admission completed

The full non-Docker suite passed **1689 tests**, with one explicit Linux-only
skip and four Docker tests deselected. The Linux-only Node cleanup check passed
separately as described above. This result predates the explicit executable-path
change; the affected controller/harness suite after that change passes 573 tests.

New studies can select `--opencode-binary` during `--make-study`. The frozen
study binds the resolved path and SHA256. The session harness receives both,
checks the bytes before Docker/authentication, forwards the same digest to the
container worker, and checks the executable again after the session. Default
standalone harness behavior retains the original executable and expected hash.
Loaded studies reject binary-path overrides. Corrupted custom executables are
covered by a failure test that rejects before Docker or credential export.

The first local stdio-only freeze passed all six static/CAMI format combinations
with identical 329-record catalogs. Runtime attempt v2 then failed its first
plain no-model session: the worker still enforced the old x64 digest. That
failure remains in the archive. After forwarding the frozen digest to the
worker, a fresh v3 source snapshot, independent preparation and new output tree
passed all six stdio cases and all three no-model OpenCode sessions. Each session
reports model_requested=false, successful cleanup, and passed admission.

The Linux Docker volume is `cami-local-study-20261113`. Each source snapshot has
its own directory and is never changed after freezing. Docker controller and
sibling session containers use the volume's daemon path; target workspaces never
receive the Docker socket. The controller is trusted orchestration. The working
runtime image is bound by digest in each study. The source changes, scripts,
archived failed/successful attempts and hashes preserve what was actually run.

See `runtime-preflight-summary.json` and `runtime-preflight-evidence.tar.gz`.
The retained drivers contain local absolute paths; reproduction on another host
requires a new declared freeze, not editing the archived studies. These are
correctness and isolation checks, not timing measurements. Task-model calls and
heldout calls remain zero. The twenty-session format-only design still needs
its own schedule and analysis before model execution.

## Five-condition development design

The controller now supports the explicit `format-only-development-v1` schema2
study: one block, five conditions, four canonical stages, at most20 model
sessions. Each condition has a distinct persistent memory namespace and its own
origin construction charge. The deterministic condition order rotates by stage;
four stages do not fully balance five positions. Historical schema1 studies
retain their36-trial schedule. No result-selected retries or extensions are allowed.

`analysis/format_probe.py` applies the existing artifact, grade, cost and token
checks to this separate design. Direction is supported only if every trial has
complete operational/quality/metric evidence and **both** memory backends have
strictly lower noncached normalized token work **and** native read-result UTF8
bytes with readable formatting. Shell reads are not inferred. Redacted or
malformed read evidence is incomplete. The tool never asserts superiority.
Wall totals remain descriptive because host quietness is not independently
established. Provider tiers are retained separately from the requested priority.

A frozen optional local `shared_server` endpoint supports Docker Desktop.
Credentials still pass directly through the private exporter/importer pipe.
The exporter runs from `/`, which exists on both hosts; inheriting `/workspace`
failed because the native service validates client location before exporting.
Both the failed and successful no-model auth attempts are retained. The successful
attempt removed its temporary private state and owned container. The common
service configuration is mounted only in the trusted controller, never the
trial agent's container.

The immutable `runtime-v4` source is commit `420730d`. Before any measured call,
four independently prepared memory catalogs were byte-identical (329 records),
12 real stdio cases passed, and all five configured OpenCode no-model sessions
passed with private state removed. The frozen study SHA256 is
`d6199ba3b2b3b6952901b64325928213a7802b484574a4362d453f14637aa05d`.
`format-freeze-v4.tar.gz` contains the protocol, study, exact plan and complete
no-model admission artifacts. The driver attempts the20 declared trials in order
without retries. The published proposal is retained unchanged; its hash and
explicit authorization are recorded in the new protocol.

## Completed continuation and current next step

The20-session format experiment is complete: every attempt passed fixed quality,
with no retries. The combined hypothesis remains inconclusive because published
native read text was redacted before exact byte measurement. See
`../opencode-format-development-20261113/README.md` for the untouched frozen
analysis and complete evidence.

Source `66ed57a` repairs pre-publication byte measurement and non-assistant
message handling; no-model verification and limitations are preserved in
`../opencode-native-read-measurement-20261113/README.md`.

Subsequent post-hoc diagnosis identified explicit symbol omissions in compound
queries. The opt-in identifier ranking now addresses that case without changing
the default or CAMI freshness rules. Its authored tests and offline fixed-query
replay are in `../opencode-identifier-ranking-20261113/README.md`. A separate twelve-session ranking-only agent comparison is now complete; see
`../opencode-ranking-development-20261113/README.md`. All 12 sessions passed quality
and telemetry, but identifier ranking increased token work 13.44% and native read
text 21.90% versus lexical CAMI. The frozen criterion failed. Lexical stays default.
Native-read version2 preserved full counts including one failed read; macOS
reanalysis reproduced the frozen result byte-for-byte. No retries or heldout calls.

Next work is a no-model information-sufficiency audit of the returned prefixes
and subsequent reads. A further paid comparison needs a materially different,
authored-case-supported intervention and a new prospective freeze; do not extend
or pool the closed blocks.
