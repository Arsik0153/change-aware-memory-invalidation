# First-parent Click extension v1

Separate development experiment on the same24fixed claims and3original parents. Each trajectory contains12first-parent transitions; the36transitions include10merges. Only22transitions (176claim-child observations per variant) add coverage;14transitions repeat112previous observations per variant. This is not held-out evaluation.

The protocol authorizes source access only after its separate freeze. Every merge compares its full snapshot against its immediate first parent. Side-parent trees are outside scope. Original protocol, production code, reference v2, claims, AI records and provenance remain byte-identical.

Pre-access validation:11authored tests passed after installation; Ruff passed. Independent review checked15semantic mutation denials and the old-source deletion guard. Review evidence is in reports/research-20261104/real-first-parent-preaccess-review-v1/. All448old observation records and24parent records must match semantically after replay, excluding only explicit measurement/path fields.

Run: `.venv/bin/python scripts/run_real_structural_first_parent_replay.py --protocol examples/real_structural_first_parent_replay/protocol.json --out NEW_DIRECTORY`.

No outcome from the added real child snapshots was inspected while preparing this freeze. Original dataset preparation may already have encountered those versions; prospective here describes this extension workflow, not an unseen dataset claim. Timing speedup, causal merge effects, human review and admission are not claimed.
