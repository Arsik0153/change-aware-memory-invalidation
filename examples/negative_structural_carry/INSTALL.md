Install the five runtime files together in `scripts/`:

- `run_negative_carry_challenge.py`
- `negative_carry_challenge.py`
- `negative_carry.py`
- `negative_carry_witness.py`
- `blob_negative_carry.py`

Install `test_negative_carry.py` as `tests/test_negative_structural_carry.py`. It detects staged versus installed helper/protocol locations. Install `challenge-protocol.json` as `examples/negative_structural_carry/protocol.json`. Root should update:

- `status` and protocol ID after review.
- `root` to `../..` (already correct for this destination).
- `seal_path` to `examples/negative_structural_carry/seal.json`.
- `test_path` to `tests/test_negative_structural_carry.py`.
- `implementation_paths` to contain the five installed runtime files, installed test, all production `src/cami/**/*.py`, `scripts/verify_cami.py`, `scripts/real_structural_replay_support.py`, `scripts/structural_checker_v2.py`, `pyproject.toml`, `.python-version`, and `uv.lock`. Include any additional rubric/test/evidence artifacts root requires.

The driver independently checks this explicit runtime/test/reference/source-config inventory; it does not require unrelated scripts or incidental `__pycache` files. The seal is `{ "protocol_sha256": "RAW_PROTOCOL_SHA256", "files": {"ROOT_RELATIVE_PATH": "RAW_SHA256"} }`, with every `implementation_paths` entry covered. The protocol itself is bound by `protocol_sha256`; the seal is not self-hashed. Required files are verified before any authored fixture setup and again afterward.

Invoke `.venv/bin/python scripts/run_negative_carry_challenge.py --protocol examples/negative_structural_carry/protocol.json --out NEW_DIR`. The driver also supports `-m scripts.run_negative_carry_challenge`; it resolves its helper directory explicitly. Both protocol/output paths are resolved before use, and an existing output directory is rejected.

No real-repository path or revision is an input to this driver. Histories are authored from the fixed protocol strings into a new `git-fixtures/` output directory. The full maintenance loop is the only timed region; Git/index/reference setup and candidate-specific context binding are separately reported. Correctness executes before timing. After timing, a separate fixed one-pack cProfile phase per variant writes `.prof` and cumulative top-20 JSON; its counters/samples are separate. The draft protocol refuses measurement. No timing run was performed while staging.
