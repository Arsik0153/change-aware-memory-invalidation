# Separate development replay of fixed Click claims

This experiment extends the existing 24 authentic parent claims into the explicitly
listed 1/12/1 child trajectories. It is a separate research library replay with
`evaluation_eligible=false`; it changes no original claims, provenance remarks,
configurations, labels, receipts or main admission. Human review count is zero.

`protocol.json` defines access and measurements. `seal.json` binds the protocol,
complete preparation files, exact original AI records and mappings, reference
contract/tests, and production implementation before any child sources are read.
`proposed_protocol.json`, `metadata_manifest.json` and `planning_hashes.json`
preserve the earlier planning snapshot; its status text is historical. All
planning hashes still identify unchanged files. `binding_audit.json` and the
independent parent-input audit join the original claims to authentic AI cases;
controls do not enter the cohort. The driver repeats the exact join at preflight.

The production selector and state transitions use only production validations.
Independent child references are computed afterward and used solely to score
observations. Parent eligibility and actual production initialization are reported
separately. Excluded claims remain in the candidate denominator. Unknown reference
outcomes are never counted as proven false. Raw exact-path Git evidence is saved.

Read `runner_README.md` for the driver/output interface. Run from the repository:
`.venv/bin/python -m scripts.run_real_structural_replay --protocol
examples/real_structural_replay/protocol.json --out NEW_DIRECTORY`.
The implementation source must be committed and match the seal. No fetching or
alternative history is allowed. Use a new protocol/version if implementation or
inputs change after the first run; never overwrite an existing report.
