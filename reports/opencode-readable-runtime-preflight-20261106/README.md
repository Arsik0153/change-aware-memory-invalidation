# Readable integration: pinned runtime correctness

The complete second attempt passed six configured MCP stdio cases (static/CAMI ×
full/compact/readable) and three actual OpenCode no-model sessions
(plain/static/CAMI). Both memory catalogs contain the same329 literal records.
The independent receipt verifier checks original bytes before any publication
scrubbing. Every no-model session reports the pinned runtime identity, requested
priority and high reasoning, zero model launches, successful publication guard
and removed private state. No credentials were transferred. Served provider tier
is unavailable because no model was called.

Source is frozen from fe0766761532d4544d3f39a95f4a4a622bf9707a; the
runtime image is sha256:3e5f5aee66022082251b8cc1fb5c3ea9399ec9589ab98ba3d190a8b0ab46b387.
The runtime archive, exact file inventories, executable hash and installed helper
pins are retained in freeze.json, runtime-manifest.json and preflight-study.json.
The study has execution_authorized=false. It is a correctness preflight, not a
frozen v7 efficacy protocol. Task models and heldout models remain unstarted here.

Attempt1 passed all six stdio cases and the plain/static no-model sessions, then
failed because the root driver tried to write progress.json twice through an
exclusive-create helper. The original runner, traceback, partial summary and
all outputs remain intact. Attempt2 uses separate progress files per arm and a
fresh output tree; it repeats the entire preflight. Production source did not
change. No timing samples are pooled or used to claim an improvement.

Executed commands, with the repository as working directory:

```
.venv/bin/python runs/opencode-readable-runtime-preflight-20261106/prepare.py
.venv/bin/python runs/opencode-readable-runtime-preflight-20261106/run_checks.py
```

The second command's first and repaired source versions, separate logs and output
trees are retained. The reusable production entrypoint for the six-case portion is
`scripts/opencode_benchmark/controller/verify_literal_containers.py --run --study
<preflight-study.json> --controller-dir <pinned-installed-controller> --out
<new-output>`. It refuses existing output. Reproduction requires restoring the
pinned source/image and matching local absolute paths or creating a new declared
freeze; do not overwrite archived outputs or silently repoint their study pins.

The full suite on the unchanged source passed1694 tests, Ruff and mypy before
these checks. These are functional/identity/cleanup checks. Host cleanup and
packaging may overlap; their durations do not establish performance or quality
on model tasks. Original failures and all resource artifacts are retained.
