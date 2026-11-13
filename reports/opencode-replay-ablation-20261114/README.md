# Source-memory ablation with result replay

Verdict: **the proposed removal of CAMI is not supported**. All40 scheduled attempts completed;38 passed the primary gates. One plain+replay model session retained incomplete provider telemetry despite passing fresh quality checks; its dependent expected replay then missed because the frozen policy does not learn from a failed primary attempt. Primary eligibility is false.

Only two of the four complete paired blocks improve both token work and time with plain+replay. Block2 uses more token work despite being faster; block5 uses more token work and is slower. Thus the missing block is not the only reason the all-five success criterion is unmet. The main workflow is not switched to plain+replay on this evidence.

| Condition | Complete blocks | Token work median (min–max) | Pipeline seconds median (min–max) |
|---|---:|---:|---:|
| cami_replay | 5/5 | 50,716.0 (46,935–81,376) | 223.15 (216.70–230.85) |
| plain_replay | 4/5 | 51,892.5 (45,183–61,233) | 206.12 (199.08–237.11) |

The four-block candidate and five-block comparator medians are descriptive only; do not compute a pooled reduction between these unequal sets. Each complete pair is compared within its own block. Ranges overlap and are not confidence intervals.

| Block | Plain+replay token work | Plain+replay time |
|---|---|---|
| 1 | lower | lower |
| 2 | higher | lower |
| 3 | incomplete | incomplete |
| 4 | lower | lower |
| 5 | higher | higher |

`r3-plain_replay-s3` encountered a native `provider.transport` WebSocket1000 error, followed by one internal retry. One assistant response lacks tokens/tier. Its known subtotal is21,433 token work plus140,032 cache-read tokens; unknown usage is not zero. The amended controller preserved source and freshly graded it:35 acceptance passes; regression593 passes,22 skips and1 expected xfail (594 executed), with zero failures/errors. It then retained the primary `TierEvidenceError` and did not record the result.

`r3-plain_replay-s4` consequently missed its expected cache hit. It made no model call, was not replaced and has no quality score. In total,39 attempts received passing quality evaluations,20 model sessions ran and19 exact-repeat hits passed fresh grading. Nineteen of20 full changed-input/positive-control pairs passed; the missing positive control is the same unlearned task. A changed-input miss without a successful exact-input control is not counted as a passing protection test.

The physical guard, source/grade binding, all-attempt accounting and independent primary audits completed. The14,627,700-byte evidence archive reproduces251,207,680 raw tar bytes. Full token-component dominance is not asserted because candidate telemetry is incomplete; the heldout baseline-only lower-bound argument does not apply when the unknown usage belongs to this candidate. No invoices are inferred.

Launcher timestamps: 2026-11-13T21:43:58.468529+00:00 through 2026-11-13T22:21:09.909955+00:00. Maximum one-minute host load was 5.48 on8 logical CPUs. Host load was observed, not independently isolated. No retry, replacement, extension or pooling was used.


Admission passed six actual configured MCP cases, eight fixed-quality gold/replay evaluations and four changed-input/control probes. Source snapshot24e91fe retains production source/adapter a8c34cd; only the experimental controller includes the previously declared telemetry-preservation correction. Protocol SHA256: `cf18c9534d7dcc1a55a3c477c1f52c953cfc390c066ad513a0c07091ff452cea`.

`preregistration.json` fixes40 attempts, five blocks, two conditions and20 expected exact-repeat hits. Plain+replay is the candidate; CAMI+replay is the comparator. Both must solve and freshly grade the initial tasks, maintain separate empty-at-start caches, and freshly grade every replay. Every block must improve both token work and charged pipeline time for a positive conclusion. The inputs are already exposed development tasks, not the heldout Packaging tasks.

The existing full-study engine now supports this one explicit registered ablation. The independent auditor separately reconstructs its schedule, accounting denominator, cache ownership by condition, and20 changed-input/control probes. Existing four-condition studies retain their80-attempt schedule and decision rules; re-auditing the original full development raw artifacts still verifies its positive result. The completed heldout execution used immutable runtime-v14 and none of these later controller changes.

Before model execution, a secondary component audit is also specified: if all quality/telemetry gates are complete, compare all five disjoint token components in each of the five pairs, including provider cache reads. Componentwise nonincrease would support only a conditional nonincrease in modeled charge under identical nonnegative linear token prices. Mixed components cannot establish price-independent savings. This does not change the primary token-work/time gate, allow missing usage to become zero, or estimate actual invoices.
