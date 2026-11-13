# Opt-in explicit identifier ranking

The adapter now accepts `serve --ranking-policy identifier-mentions/1`. In a
compound query, explicitly named qualified or snake-style symbols precede
results matching only shared words. Capitalized unqualified names require their
written spelling. Whole-query exact matches retain first priority, then qualified
mentions, unqualified mentions, lexical score and stable record ID. The standard
policy remains `lexical-overlap/1`.

The motivating defect is in compound queries: legacy exact matching applies only
to the entire query, so a named function can lose to snippets containing more
common terms. This change is generic; no Click/task names are encoded in it.
No task, evaluator, payload, catalog, freshness rule or origin-byte budget changes.
Ranking still precedes availability. A selected unsupported CAMI record is
withheld without filling its place with another result. The opt-in policy is
recorded in startup and lookup traces, including backend errors.

## Evidence and limits

`replay.json` replays all17 recorded memory queries against the same329-record
origin catalog, with their original limits and16384-byte selection budget.
Legacy selections and their visible/withheld ordering match the frozen evidence.
There are16 explicit-symbol observations under the declared matching rule.
Legacy ranking omits four; the candidate omits none. All four omissions concern
one function, `help_option`, in four queries. These are dependent post-hoc
observations, not four independent bugs or a general retrieval-quality estimate.

The replay changes no model session and has no new model calls. It does not
establish reduced tokens, read bytes or latency, or preserved task quality under
the new ranking. The existing fixed controller deliberately does not admit the
new flag; a separate prospective study is necessary before an agent utility claim.

`tests.log` records886 passing adapter/controller/harness/analysis checks.
Generic authored fixtures cover compound references, qualification, accidental
substring matches, case, exact-query priority, deterministic ordering and the
unchanged byte ceiling. Real static/CAMI backends and stdio processes verify the
selected symbol, trace identity and withholding after a source edit.

`format-diagnostics.json` is a separate post-hoc description of the closed format
cohort. Native reads remain frequent, and measured CAMI backend lookup spans
occupy less than1% of inclusive session time in each CAMI condition. Those spans
exclude RPC and trace append and are nested costs, not additional charged totals.
This does not identify an avoidable read or prove causality. It gives no reason
to prioritize a language rewrite of the lookup backend over retrieval utility.

## Next bounded unit

Freeze a separate ranking comparison with identical display, prompts, model,
limits, source/runtime and evaluator identities. Compare legacy versus explicit
identifier ranking in CAMI; preserve a plain control if making a claim against
no memory. Use the pre-publication native-read measurements and explicitly define
how failed reads enter the read-byte endpoint before any calls. Require complete
telemetry and fixed quality; count independent construction, lifecycle and audit
cost once. Predeclare session count and order, preserve all failures, and do not
extend the closed format block or pool these replay counts with model outcomes.
