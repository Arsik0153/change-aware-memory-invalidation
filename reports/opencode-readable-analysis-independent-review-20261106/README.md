# Independent readable analysis review

One admission bug was proven and fixed by root. Before the fix, the preserved
authored terminal declared compact format but its readable response was assessed
as supported, without a readable verifier source pin. `mode-admission-proof.json`
and the complete before-fix report preserve that behavior. After root's fix, the
same fixture is rejected before the classifier is invoked, its passed terminal
outcome remains, and no record observations are generated. A separate copied
fixture declaring readable format succeeds and includes the helper source hash.

The explicit protocol admission checks pass: v6 accepts its compact cohort and
refuses readable; v7 admits only its readable development schema2 cohort and
retains the existing priority/high policy and frozen success/cost rules. Invalid
formats, heldout bundle kind, nonpriority tiers and missing policy keys are refused.
No additional proven admission/tier/fallback/publication finding was found.

The complete sealed public24-packet roster passes independent exact receipt
authentication and full classifier replay. Original compact classifications,
derived readable classifications and the frozen v6 staleness report have equal
record observations. Static retains49 same and11 obsolete returned observations;
CAMI retains48 same returned observations and12 obsolete withheld observations.
There are exactly two unique obsolete record IDs. Per-packet evidence preserves
the original roster row, derived event/result, and both classifications.

This is **derived format-only offline verification**. The changed tool text and
event are not actual output seen by a model. Exact original full responses,
arguments, call IDs, timestamps and all nondisplay fields remain bound. Catalog,
source inventories, original messages/traces, producer packet files and roster
were rehashed and remain unchanged. No token, latency, quality or model behavior
effect is inferred; no model, network, Docker, heldout read, commit or push ran.

`review-summary.json` pins reviewed source files. `replay.py`,
`review_admission.py`, `reproduce_mode_admission.py` and
`recheck_mode_admission.py` are auditable runners; the last two intentionally use
new-only fixture directories so the before-fix proof cannot be overwritten.
No source edits outside this new evidence directory were made during this review.
