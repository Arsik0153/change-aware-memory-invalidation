# Native read measurement repair

Source commit `66ed57a` records native read UTF8 text sizes before publication
redaction. Receipts contain only counts, call/message IDs, states and explicit
completeness; no source text, paths, tool inputs or content hashes. Repeated
pagination exports replace the previous measurement instead of adding it again.
Partial exports retain observed subtotals but their total is null. Failed,
nontext, missing and malformed read outcomes are unknown, never zero.

The analyzer checks receipt coverage against public message/call IDs and states,
recomputes arithmetic and checks unredacted content sizes. It verifies the
receipt's session artifact hash. Counts for redacted bodies are a pinned runtime
projection, not independently recoverable original text or wire-byte evidence.
Non-assistant records use the existing pinned OpenCode schema validation.

Verification:772 controller/harness/analysis checks passed. Synthetic paginated
exports prove that email and Unicode text are counted before redaction, original
bodies do not enter receipts, incomplete pagination remains incomplete, and
changed identities/totals cannot silently verify. Full repository Ruff passes.

The frozen `runtime-v5` snapshot also passes six real configured stdio cases and
three actual no-model OpenCode sessions (plain/static/CAMI). Each no-model
session publishes a complete zero-read receipt bound by its artifact manifest,
with private state removed. No additional model calls were made. The source
snapshot, study identity and full runtime artifacts are in `no-model-evidence.tar.gz`.

Re-analyzing the prior20 trials with corrected non-assistant parsing still gives
`negative_or_inconclusive`. Every trial has redacted native read text, and one
has an errored read. `historical-parser-check.json` preserves this check. It does
not replace the original frozen analysis or reconstruct missing original bytes.
The closed20-trial cohort was neither retried nor extended.
