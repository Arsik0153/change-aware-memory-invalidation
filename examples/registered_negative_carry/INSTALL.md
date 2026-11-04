Install these three new files together under `scripts/`, without modifying the five original negative-carry runtime files:

- `registered_negative_carry.py`
- `registered_negative_carry_challenge.py`
- `run_registered_negative_carry.py`

Install `test_registered_negative_carry.py` under `tests/` with the same basename. Install `protocol.json` under `examples/registered_negative_carry/protocol.json`.

Before sealing, root should update the protocol ID/status, `seal_path` to `examples/registered_negative_carry/seal.json`, `test_path` to `tests/test_registered_negative_carry.py`, and the three staged runtime/test entries in `implementation_paths` to their installed paths. Remove obsolete staged entries from that inventory. `root:"../.."` is correct for the proposed installed protocol directory. Preserve `baseline_protocol_path`, `baseline_protocol_sha256`, `original_implementation_hashes`, all histories and every workload/profile count. Additional review/rubric/test artifacts may be included in the seal.

The new seal format matches the prior driver: `{ "protocol_sha256": "RAW_NEW_PROTOCOL_SHA256", "files": { "ROOT_RELATIVE_FILE": "RAW_FILE_SHA256" } }`. All implementation paths, production modules, reference/configuration/test paths and original pinned comparison files must be covered. The baseline protocol must also be retained and hashed by its existing bound `baseline_protocol_sha256` field. The seal does not self-hash.

Invoke `.venv/bin/python scripts/run_registered_negative_carry.py --protocol examples/registered_negative_carry/protocol.json --out NEW_DIR`. Package invocation via `-m scripts.run_registered_negative_carry` also resolves the original and new helper directory. Relative protocol/output paths are resolved before use. Existing output directories are rejected.

The tests detect staged versus installed helper/protocol locations. Their temporary Git histories contain authored source only. The staged protocol is deliberately draft and refuses measurement. No performance/profile run was executed while preparing this unit.
