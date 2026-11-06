# Source-line reuse full verification

At commit a91ae44f5c87b4b3fbc11e7a92214542952c009b, all 1601 tests passed, including Docker probes; Ruff passed and mypy passed on 54 production files. The verification wrapper observed identical source snapshots before and after the run. The pinned probe image and exact commands, source hashes, logs and timings are in checks.json.

This is correctness evidence, not a latency or memory benchmark. The source-line candidate still needs a separate memory-regression screen for a function near the start of a large file, followed by actual-tool timing if it passes. Resource observations are instantaneous host readings, not measured candidate peaks.
