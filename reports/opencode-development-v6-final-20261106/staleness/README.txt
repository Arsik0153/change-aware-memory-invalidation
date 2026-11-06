Development v6 literal-source analysis (closed 36-trial run)

All 36 quality and operational outcomes are retained and passed. All 24 memory
calls (12 static, 12 CAMI) join their public backend traces and verify their
compact audit receipts. Every call precedes any prior/overlapping possible write
under the frozen boundary classifier. No unsupported calls, post-write unknown
observations or redaction-invalidated receipts were found.

Actual observations: static returned 49 matching literal tuples and 11 obsolete
tuples; CAMI returned 48 matching tuples and withheld 12 obsolete tuples. The
obsolete observations in each arm involve the same TWO unique records:
src/click/decorators.py:help_option and src/click/core.py:Command.get_help_option.
These are repeated observations, not 11 or 12 independent cases. The returned
and withheld selections are actual model-query outputs; do not treat them as a
matched counterfactual retrieval comparison. Record sets overlap across stages.

The fixed predicate is the exact first <=2400 Unicode characters from the
physical Python definition/decorator span plus its truncation flag. No complete
body, behavior, causal model reliance or human annotation is inferred. Withheld
current-source tuples in this report are reviewer context, not text shown to the
trial agent. Plain has no external-memory observations; this does not assess the
freshness of its internal model knowledge.

Integrity: study SHA b66e4d557b7b7cdf0800b4c9121e793659f3a02029a74b026c7f7c4d75243cdd;
36 terminal hashes agree with the closed primary aggregate (SHA
632953c9879fb1f4f05c059d2dde747e0d4d8ead7724a13c1d7d7805faa1100b).
The frozen analyzer verified 8130 terminal-listed artifact hashes and all canonical
reset inventories; both approved canonical source inventories match their prior
pinned digests. Current frozen production/controller/harness/adapter source pins
and all six unchanged analysis-source hashes were checked separately.

The primary wall comparison remains ineligible because of the declared user
cache-cleanup timing caveat affecting repetition2/stage3 in all arms. No trial was
excluded, and this source analysis neither repairs that caveat nor makes an
efficiency claim. Literal classification is separate from primary inference.

Use analysis-invocation.json for the exact original frozen CLI invocation; a
rerun requires a fresh output directory. build_summary.py re-derives the summary
and pin checks from the raw report. Offline analysis cost is separate from agent
trial costs, with the timer boundary stated in the JSON. No models, Docker,
heldout reads, historical-state mutations, tracked edits or commits were used.
