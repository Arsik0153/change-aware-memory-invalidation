# Indexed lookup verification

The unchanged implementation at commit `10b81df84066990c466b410d69470caab90504c6` passed all **1556 tests** and the project type checker. `checks.json` records identical source inventories before and after execution and retains the original overall failure: Ruff found E402 in a sealed experimental replay artifact.

A subsequent narrow per-file E402 exception in `ruff.toml` preserves that artifact byte-for-byte. `.venv/bin/ruff check .` then passed. `verification.json` records the separate remediation and exact configuration hash. The full tests were not repeated for this lint-only change. Original logs and original failed aggregate status remain unchanged.

The implementation replaces repeated per-module unresolved membership scans and builds one exact-subject definition index per memory transition operation. Existing single-record entry points, duplicate-definition order, source authentication, persisted models and wire formats remain covered. Frozen-reference behavior tests and real-source replay evidence are separate reports.

This report establishes correctness checks, not end-to-end performance superiority. Unprofiled repeated local measurements and a separately frozen OpenCode development cohort are required before new efficiency claims.
