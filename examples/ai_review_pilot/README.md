# Frozen AI development pilot v1

This is a parent-only, development Click study of an AI-assisted annotation method.
It does not create CAMI labels, receipts, admission or human-review credit.
`protocol.json` controls the experiment; `sealed_hashes.json` freezes every file
in this directory. Only `packet/` may be read by the two fresh AI reviewers.
Coordinator-only `private/` preserves authentic origins and authored controls.

The preparation scripts and `proposed_protocol.json` preserve the initial design.
`original_*_hashes.json` refer to that staging snapshot, whose rubric is retained
as `preparation_rubric.md`; they are historical inventories, not current seals.
The final rubric was aligned with the strict review schema before any decisions.
Cases, sources and predicates were unchanged during integration.
`build_packet.py` recreates the original preparation, when copied with its verifier
to an otherwise empty runs/<name>/ directory; the final protocol is a reviewed
integration artifact. Run `python examples/ai_review_pilot/verify_packet.py`
to verify the frozen inputs and control transformations without judging authentic claims.

The independent checker is `scripts/structural_checker.py`; the record-format audit
is `scripts/validate_ai_review.py`. Both were independently authored in restricted
contexts and tested on synthetic cases before this packet was inspected by them.
They share CPython parsing with the predicate contract. See their adjacent READMEs
for their exact coverage and limits. The tests reside in tests/test_structural_checker.py
and tests/test_validate_ai_review.py. Review identity is a declared invocation,
not an authenticated fingerprint of model weights. Agreement does not establish truth.
