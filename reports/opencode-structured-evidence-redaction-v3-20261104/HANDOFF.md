V3 structured evidence redaction, staged only

Install the four changed runtime files and the two changed/new tests only after review. Existing mounted container_common.py supplies the shared sanitizer; there is no new container dependency or mount.

JSON and JSONL are parsed before recursively redacting string keys/values; serialization is the last operation. Nested serialized JSON is parsed separately, scrubbed structurally, and safely reserialized. Plain text is string-redacted; actual and literal escaped newline decorators remain intact. Known opaque secrets and their JSON-escaped spellings, plus-tag email addresses, JWTs and OAuth fields remain redacted. Redacted key collisions and more than eight nested serialized JSON envelopes reject that artifact.

Host filesystem/root/link/name/size/credential guards remain fail-closed. After those global checks, malformed or unpublishable JSON/JSONL is deleted individually with a filename and error-type diagnostic. Other sanitized artifacts, including usage, are copied; the host result is failed. No malformed JSON is published under a JSON suffix and no raw rejected text is exported. Worker final sanitation also records individual rejections, marks its manifest failed, and leaves safe siblings for host export.

Verification: 46 tests passed (existing 27 + 19 authored controls/cases), Ruff passed. The entire already-public v1 evidence copy passed both stages: 21 JSON, 2 JSONL, 1 text; source hashes unchanged. See public-v1-trace-verification.json. The public v1 trace had already lost some decorator text during v1 redaction; the authored tests supply that missing trigger. V2 private payload was discarded during prior cleanup and cannot be recovered. No model/auth calls or tracked writes were made.

Commands from repository root:

    .venv/bin/python -m pytest -q runs/opencode-structured-evidence-redaction-v3-20261104/test_failure_contracts.py runs/opencode-structured-evidence-redaction-v3-20261104/test_publication_guards.py runs/opencode-structured-evidence-redaction-v3-20261104/test_structured_redaction.py
    .venv/bin/python runs/opencode-structured-evidence-redaction-v3-20261104/verify_public_trace.py
    .venv/bin/ruff check runs/opencode-structured-evidence-redaction-v3-20261104
