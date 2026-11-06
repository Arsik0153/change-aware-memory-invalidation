# Separate readable receipt verifier

`scripts/opencode_benchmark/controller/readable_receipts.py` is standalone stdlib
code and does not import the producer, its encoder, or its validator. The authored
test fixture may call the producer. This separation is an implementation check,
not a claim of semantic oracle independence or cryptographic identity.

`verify_readable_result(model_result, audit)` returns the original parsed full JSON
object and raises `ValueError` on mismatches. It checks the exact seven audit
fields, requested/effective/fallback selection metadata, original full-result
digest, receipt-free base-display digest, receipt digest, and final model-result
digest. Its readable parser compares canonical shared and per-record metadata,
physical source bytes, CR/LF/CRLF handling, fence width, artificial newline flag,
record order, and end-of-display against the full result. Fallbacks independently
apply compact/1's exact projection, retaining arbitrary unknown/error claims and
the original compact receipt contract. Malformed inputs outside the single-text
JSON-object backend contract are rejected, not repaired.

`extract_readable_header(text)`, `readable_text_marker(text)`,
`readable_result_marker(model_result)`, and `readable_audit_marker(audit)` are
metadata checks only. The text helper makes no assertion about MCP `isError`,
which OpenCode's published tool text does not expose. Root owns integration into
the existing observer, configured stdio probe, and analysis; historical compact
paths are outside these two source files.

Final focused validation: **80 passed**, Ruff clean. Logs preserve both successful
iterations (71 tests before additional boundary tests, then 80); there were no
failed attempts. Cases include rehashed visible claim tampering, all receipt
layers, full-result tampering, stale trace reuse with identical source prefixes
and different provenance, source/trust/subject/span/budget/withheld claims,
backticks, Unicode, bare CR, CRLF, truncation, unexpected suffixes, error/empty/
mixed/unknown/control fallbacks, and malformed nested/transport types.

`verification-summary.json` records commands and source SHA256 pins. No models,
Docker, network, heldout packet reads, full suite, commits, or pushes were run by
this worker. No performance or quality result is inferred from these tests.
