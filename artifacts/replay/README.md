# Standalone exact-task replay

`cami-replay.pyz` is a 3,450-byte CLI containing the unchanged production
`integrations/opencode/task_replay.py` module and its entry point. It requires
Python 3.12 or newer; Python itself is not included. No CAMI installation,
Pydantic, or third-party Python packages are required. Verified on macOS ARM64
and Linux ARM64 in separate empty environments.
This is a packaging result, not a new speed measurement.

Record a successful source change from two isolated workspace snapshots:

```sh
python3 -I artifacts/replay/cami-replay.pyz record \
  --before /path/to/original --after /path/to/graded-result \
  --task-file /path/to/task.txt --context-id pinned-environment-v1 \
  --cache /path/to/result-cache
```

On an exact repeat, materialize a separate candidate:

```sh
python3 -I artifacts/replay/cami-replay.pyz materialize \
  --workspace /path/to/original --out /path/to/new-candidate \
  --task-file /path/to/task.txt --context-id pinned-environment-v1 \
  --cache /path/to/result-cache
```

The caller must grade the original result before recording it, and freshly
grade every materialized candidate before accepting it. The CLI does not run
tests or a model. A hit reports `candidate_requires_grading`; it does not imply
that the result is correct. Only changes under `src/` are replayed. Candidate
test or configuration edits are not replayed.

The key binds exact task text, regular workspace file contents and modes, and
the supplied context ID. Change the context ID when external dependencies or
other relevant execution conditions change. Changed input produces a miss;
there is no semantic reuse across different repositories. Use clean snapshots
with at most 10,000 regular files and 64 MiB total content; keep the task file,
cache and output outside both snapshots. The output must not already exist.

`build.json` records size, hashes and the build interpreter/compressor;
`verification.json` and `verification-linux.json` record the empty-venv
behavioral checks, including corrupt-cache rejection and changed-input misses.
The shipped module matches production commit `a8c34cd`. Two independent builds
produced identical archive bytes:

```text
SHA-256 30ab9c7e2429717cf2483dcbc7e222750d53bb965a1de3272ed04eab80621bb8
```

Rebuild and verify using new output paths:

```sh
python3 scripts/build_replay_zipapp.py --out /tmp/cami-replay.pyz --receipt /tmp/build.json
python3 scripts/verify_replay_zipapp.py --artifact /tmp/cami-replay.pyz \
  --out /tmp/replay-verification --report /tmp/verification.json
```
