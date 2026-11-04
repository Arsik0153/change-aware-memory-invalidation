# Research proposal: carry a bound, unchanged negative structural result

Status: staged, exploratory, not sealed and not benchmarked. No production files or original results were changed. No new real-corpus source, tree, diff or snapshot was accessed. All new execution uses authored temporary Git repositories. The primary proposed unit is now **17 explicit authored histories**, not a real-cohort replay or an exhaustive cross product. Its machine-readable plan is `challenge-protocol.json`.

The broad rule “skip a sole previously-unavailable retry whenever the old verdict is contradicted” fails a meaningful negative-result preservation contract. A narrower, last-validation-bound full-module-identity candidate is plausible and testable. It may cost more than calling the current cheap validator. The experiment therefore asks about **total maintenance CPU/wall cost**, with correctness and recovery as gates, and accepts a negative performance result.

## Why investigate

Frozen `real-structural-replay-v1` observations show eight `symbol_anchor` validations, all for `click-1e53748f80eb-04`: the first at child five, `8473b3ced140296b9dd869957e0026eebd94634b`, selected a changed signature; seven later selections contained only `previously_unavailable`. All eight actual results were `contradicted/predicate_mismatch`. This is one dependent trajectory. The root's completed source analysis identifies `ctx_args: t.Dict` changing to `t.MutableMapping`; this task did not reread child source.

Those seven retries are a retrospective opportunity count. They do not establish an achievable saving, useful latency reduction or general workload prevalence. This work is explicitly outcome-informed development research. The old broader proposal is retained as `experiment-plan.json` with historical/superseded status; its full matrix and real-cohort sensitivity are not implemented or proposed for this freeze. `design-initial-draft.md` preserves the earlier reasoning, including the assumption later refuted by the lineage counterexample.

## Contract and two counterexamples

Let `V(c,t)` be fresh production structural validation under a fixed exact syntactic contract. Skipping a check while leaving `available=false` cannot itself create false availability, even if recovery was missed. That weak availability invariant is insufficient. A useful negative-carry rule must preserve a genuine current contradiction and validate recovery promptly; historical last-check fields must remain historical.

Two actual authored-Git mechanisms constrain the design:

| Counterexample | Genuine history and observed failure | Required restriction |
| --- | --- | --- |
| Missing subject / ancestor limitation | Delete `pkg/f.py`, obtaining actual `contradicted/subject_absent`; replace ancestor `pkg` with a symlink. Production selection contains only `previously_unavailable`, but fresh validation is `insufficient_evidence/symlink_unsupported`. A naive rule carries the old contradiction/retired status. Availability stays false, hiding the stale evidence. | Exclude absence entirely; require an existing readable regular module witness. |
| Lost lineage across policy switch | Actually validate signature mismatch at t0; genuine `keep_all` crosses a recovery at t1 without checking; at unchanged t2, production symbol selection again contains only `previously_unavailable`. Adjacent before/after signatures agree, yet fresh validation supports the claim. | Bind current evidence to the **last actual negative validation**, not merely equal adjacent indexes or old state fields. |

The missing-path negative control's exact fields are retained in the historical plan and in an executable authored test. The policy-switch counterexample has a regression test using actual `select_claims(..., keep_all)` and `advance_state`, without forging state or changing the claim/parser/roots.

## Candidates and architecture

All candidates first call unmodified production `select_claims` on genuine sequential changes and then call production `advance_state`. Each maintains its own sequential state and actual validations. Neither independent reference nor another policy's state/results feed selection. No new production PolicyID, state schema, closure authority or admission record is introduced.

| Variant | Decision after original production selection |
| --- | --- |
| `production` | Unchanged `symbol_validate`, including previously-unavailable retries. |
| `signature_witness` | The deliberately expensive correctness-oriented adapter: compare available unique unambiguous subject definitions/AST/signatures across adjacent indexes **and against the last actual negative witness**. All its checks and witness work count toward maintenance. |
| `module_blob_witness` | Simpler candidate: the exact subject remains a readable regular full-module blob with the same Git OID as at the last actual mismatch. No per-attempt signature comparison or definition scan. 100644 and 100755 are explicitly equivalent for this syntactic contract; symlinks fail even with the same blob. |

`negative_carry_witness.py` provides the common immutable witness and context gate. `negative_carry.py` retains the expensive candidate. `blob_negative_carry.py` provides the module candidate. `negative_carry_challenge.py` builds authored histories and executes real production loops; `run_negative_carry_challenge.py` is the sealed-only driver.

For a legitimate complete snapshot from a genuine Git tree, an existing regular exact path cannot simultaneously lie beneath a symlink/submodule ancestor. The blob candidate relies on that structural invariant to avoid an ancestor-wide scan. It rejects absent/limited/nonregular exact paths. The more expensive adapter also checks recorded ancestor limitations. Inconsistent hand-authored Snapshot objects are outside the genuine-Git proof premise and are not fed to the candidates.

## Witness and exact context

A witness can be minted only from an actual `validate_claim` result with `contradicted/predicate_mismatch`. It verifies claim/commit/validator identity and the exact production validation input hash; it verifies an existing unambiguous matching function and that its full normalized signature actually mismatches the expected signature. Minting is performed by the trusted sealed runner, not by importing arbitrary “negative” records. Input-hash consistency is not an unforgeable attestation of execution by an untrusted caller.

The witness freezes:

- Complete claim and provenance hashes, including expected predicate, subject, text and scope.
- Exact last actually validated commit and validation input hash.
- Full regular module Git OID/byte SHA-256, function AST hash and complete normalized Signature.
- Canonical research-context hash: repo, source roots, index config, snapshot size limit, implementation source hashes, Python/parser, index/validator versions, protocol, exact-syntax scope contract, and canonical enclosing plan/input hash.

Every attempt compares claim, provenance and context hashes with that witness, binds `last_checked_commit` to its real check, requires prior unavailable/stale/contradicted/predicate_mismatch state, and preserves every original production reason except a **sole** `previously_unavailable`. Same-ID changed expectations, changed roots/limits/version/scope/provenance, missing/mismatched witness or changed last-check identity refuse carry. Known incomplete, unresolved remarks, explicit dependencies, no anchors, runtime scope and uncertain/absent/retired states never qualify.

Both candidates are restricted to `signature_equals` on an exact simple top-level function and the existing exact normalized-syntax scope allowlist. `symbol_exists(expected=true)` has no existing-definition mismatch to exploit; its negative absence cases are excluded. Unsupported type-parameter/runtime interpretations remain outside the claim contract. Passing a source through this research gate does not establish independent reference truth or real provenance closure.

## Conditional preservation argument

Assume authentic, complete Git snapshots and matching indexes; fixed faithfully recorded production/parser/normalizer behavior; collision-free evidence identities; immutable claim/provenance/context; and a genuine last-actual mismatch witness.

For the module candidate, the current exact regular module has the same full source bytes, path and fixed parsing/indexing context as at the real mismatch. The same unique definition, ambiguity status and normalized signature are therefore reconstructed. Its frozen expectation is unchanged, so the signature still differs and fresh production returns `contradicted/predicate_mismatch`. A skipped step keeps unavailable state and the original last actual check; it does not invent validation. Direct recovery, source change, mode limitation, changed context or uncertainty invalidates this witness or preserves an original selection reason and therefore executes validation.

The signature candidate instead establishes equal exact definition/signature facts relative to that actual witness and rejects any observed ambiguity or unavailable module. Its lookups may duplicate most of the validator's useful work. Adjacent equality alone is explicitly insufficient, as the policy-switch history demonstrates.

The conditional argument is about equivalence to a frozen **production** validator, not arbitrary Python runtime bindings or independent truth. CPython AST and parser/normalizer defects remain shared limitations. Structural-closure v1 remains its narrower fixture-only addendum; this optimization discharges no review-pending remark. Independent v2 decisions are measured separately and never used as optimization authority.

## Bounded challenge and measured region

`challenge-protocol.json` fixes 17 selected histories covering unchanged module/other-file edits; same module with comment change and equal function AST; direct and nested class/global ambiguity with unchanged function AST; same-blob symlink and restoration; exact signature recovery; same-ID expected signature change; context/scope/index/size-limit changes; known incomplete; parse failure/recovery; regular executable mode; absence/ancestor symlink; and policy-switch lineage. This is a finite mechanistic challenge, not the old proposed exhaustive matrix. Other decorators/async/encoding/LFS/submodule combinations are not claimed covered by this freeze.

Every authored transition has frozen fresh-production and independent-reference expectations. Setup builds actual Git commits, reads production snapshots/indexes, checks warmed versus fresh indexes, computes genuine changes and records raw independent reference packets. Correctness checks run all three policies on their own sequential states against the fresh outcomes. The deliberately injected intermediate `keep_all` step may miss recovery by definition; the following symbol-policy step must recover, proving the old mismatch cannot be reused. Every suppressed step must remain fresh-contradicted, with no new last-check timestamp.

The primary endpoint is paired total maintenance process CPU and wall nanoseconds: **selection + candidate gate/context hashing + all witness creation/refresh + actual validation + state advance**. Parent actual validation, authored Git/index/reference setup and serialization are outside the region and reported separately. Candidate-only context/code-hash setup is explicitly identified; it cannot be called shared free work or ignored in an end-to-end benefit claim.

The proposed driver uses two warmup blocks, 21 paired repetitions, and 100 repetitions of the entire 17-history pack per timed block. That means 1,700 history executions per block; the artifact records history-pack repetitions, actual history executions and actual transition executions separately. Candidate order rotates and reverses across repetitions, covering all six orders. Blocks below the fixed 10 ms floor are flagged, not silently retuned. Full work counts and final deterministic endpoints are checked outside each timed block. Per-variant sequential correctness is checked before timing; results/reference are never substituted for the actual baseline validations inside timing.

The host is shared. Root reported the tracked full suite finished with 1,259 passes before this proposed measurement. The driver records CPU count, load averages, platform and source before/after and reports median/range plus paired deltas. After all timed blocks, each variant gets one separately marked cProfile execution of the complete 17-history pack. Stripped-path `.prof`, top-20 cumulative function JSON and separate actual-work counts are retained; profiling never enters timing samples or their work counts. The result remains performance-inconclusive until that limiter profile, run-to-run variation and relevance have been reviewed. Fewer entry-point calls alone are not success. Equal/slower total maintenance or index-dominated end-to-end cost is an acceptable negative outcome.

## Verification and handoff

Fourteen authored unit tests currently pass, including all 17 challenge histories × all three candidates for correctness only, witness/context identity refusals, the policy-switch lineage regression and draft-protocol measurement refusal. Ruff passes. **The benchmark driver has not been executed and no timing result is reported.** Already run correctness fixtures are disclosed development checks, not held-out evidence.

Root must review the bounded protocol and sources, finalize status/ID/paths and a new SHA-256 seal, and use a new output directory before invoking the benchmark driver. The draft protocol is rejected by the driver. Required seal inventory includes all staged Python sources, production Python modules, source-snapshot helper, independent Git-reference helper/checker and any root-required rubric/test artifacts. Failure is preserved in the output manifest; existing outputs are never overwritten.

The next result should be one of: refuted correctness; no useful reduction; inconclusive timing; or an authored-workload maintenance improvement with the setup costs and limits disclosed. No new real-corpus experiment is part of this staged unit.
