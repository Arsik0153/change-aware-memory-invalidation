Optional compact memory responses, staged only

`memory_adapter.py serve` defaults to the existing full response. Opt in for either backend with:

```sh
python memory_adapter.py serve --binding /absolute/prepared/binding.json --trace /absolute/audit.jsonl --response-format compact
```

Install `compact_response.py` beside `memory_adapter.py`. The existing `memory_backend.py` is copied here unchanged for a self-contained review stage. This stage does not change the frozen v3 runtime, current trial configuration, or any CAMI core behavior.

The compact format retains exact entry IDs (including the ID query route), note keys, complete subject selectors, all user note text without header parsing, typed expectations, trust/availability/state fields, withheld reasons/actions, freshness, errors, truncation, and selection/budget metadata. It removes only per-entry `origin_source`, `payload.sources`, and top-level catalog/snapshot/memory-generation hashes. The same pure projection runs after either backend's normal lookup; ranking, selected records, limits, 16 KiB original-record selection budget and availability are unchanged. Withheld entries are never replaced with other results or historical text.

Each compact response has `response_format: research-memory-compact/1` and one full SHA-256 `audit_receipt`. Before returning the model response, the existing JSONL trace append records `response_audit` containing:

- `full_result`: the original complete MCP result, including its full canonical JSON content and `isError`.
- `receipt_payload`: format, SHA-256 of the complete original result, and SHA-256 of the complete compact result before inserting the receipt.
- `receipt_sha256`: SHA-256 of canonical `receipt_payload`, matching the model-visible receipt.
- `model_result_sha256`: SHA-256 of the final complete MCP result with the receipt.

All hashes use the existing canonical JSON function (sorted keys, ASCII encoding, compact separators). To verify, hash the stored full result; parse the compact content, remove only `audit_receipt`, reconstruct its MCP result preserving `isError`, and hash it. Rehash the receipt payload and final model result. The tests perform these independent comparisons and check changes to provenance, text and error status. A failed trace append prevents the corresponding compact result from being returned; this is a local append guarantee, not a new fsync/durability claim.

Full mode keeps its original model-visible bytes and trace shape. Compact mode includes projection and digest work inside the existing lookup timer. Appending/serializing the larger audit JSONL remains outside that span, as before; an outer harness must charge total process time, I/O and retained storage. Error/empty results can grow because of the receipt overhead. The original backend response byte metric remains the complete model-facing MCP result, not token count.

Exact byte receipt verification applies before any later publication scrub. If a publisher changes email/credential-bearing content in the model result or full trace, the original digest must fail verification against that modified copy. Do not bypass credential redaction or silently rebind that evidence as though it were the original model-visible response.

Verification used only authored pure fixtures and the three already-public first-task response bodies:

```sh
.venv/bin/python -m pytest -q runs/opencode-compact-response-development-20261104/test_compact_response.py
.venv/bin/python runs/opencode-compact-response-development-20261104/measure_preserved_responses.py
.venv/bin/ruff check runs/opencode-compact-response-development-20261104
```

20 tests passed in 0.20 seconds; Ruff passed. No CAMI registration, Docker, network, model or authentication calls were run. The tests exercise both backend formats through an authored fake backend; they do not establish a new CAMI validation policy. Actual backend source is unchanged.

Preserved response text sizes: static first 9,808 → 8,513 bytes; static post-edit 3,217 → 2,730; CAMI first 9,425 → 7,969. Complete note strings, IDs, original budgets and freshness are verified equal. Across those responses this removes 3,238 model-facing bytes (14.42%) while adding 25,447 bytes of canonical audit objects, before their outer trace field/newline overhead. These are byte measurements, not token, billing, quality or speed estimates. Source hashes, receipts and exact sizes are in `preserved-response-byte-measurement.json`.
