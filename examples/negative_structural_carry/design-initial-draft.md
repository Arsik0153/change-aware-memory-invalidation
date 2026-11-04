# Research design: carrying an unchanged negative structural result

Status: exploratory proposal and authored prototype, 2026-11-04. Production policy, protocol 1.1, admission, provenance and existing result files remain unchanged. This proposal was motivated by already observed development outcomes and is not a preregistration of those outcomes. No new corpus snapshots, trees, diffs or source files were accessed. Work read the frozen replay's report/observations and production/helper/documentation source; the prototype runs only on newly authored temporary Git histories.

A limited exception is plausible for an existing exact function whose complete signature still mismatches the frozen expectation. Removing `previously_unavailable` for every contradicted structural claim is too broad. An authored Git history already supplies a counterexample to preserving fresh production verdicts for the broad rule. The proposal therefore excludes absent subjects entirely and treats a future result of no useful reduction as valid.

## Motivation and what is already known

The frozen `real-structural-replay-v1` selected eight `symbol_anchor` validations, all for `click-1e53748f80eb-04`. The first occurred at its fifth child, `8473b3ced140296b9dd869957e0026eebd94634b`, with `subject_changed` and `symbol_or_dependency_changed`; seven later children selected only `previously_unavailable`. All eight actual validation records say `contradicted/predicate_mismatch`. This follows directly from the frozen observations and is an observation about one trajectory, not a general workload property. The root's completed analysis identifies the changed annotation as `ctx_args: t.Dict` to `t.MutableMapping`; this design did not reread child source to infer it.

Those seven repeated calls motivate a question. They do not establish that a safe adapter would suppress seven calls, reduce elapsed time, or help another history. The prototype's additional evidence checks consume work. Full index/snapshot/reference work remains, so fewer calls may have no useful performance effect.

## Two different safety questions

Let `V(c,t)` be the fresh production structural verdict for fixed claim `c` at revision `t`, and `A(c,t)` maintained availability.

1. Availability safety: an omitted negative check keeps `available=false`. Even a completely obsolete negative verdict cannot itself create false availability on that omitted step. This weak invariant can hide missed recovery and stale negative status.
2. Negative-result preservation: when carrying a definitive mismatch, require `V(c,t+1)=contradicted` and preserve the mismatch reason. Also require immediate validation when the subject changes, so a newly supported claim can recover. This is the meaningful optimization contract.

`last_checked_commit` and `last_verdict` remain historical fields. A skipped step must not claim a fresh validation, advance the last-check timestamp, produce a validation result, or turn uncertain evidence into a current contradiction. Carrying changes the current revision and basis through the existing `advance_state`; availability stays false.

Neither invariant says that production and the independent v2 reference agree. Reference uncertainty and structural parser limitations remain separate outcomes. This work creates no truth label, receipt, human review or real provenance closure.

## Alternatives considered

| Candidate | Rule | Assessment |
| --- | --- | --- |
| Broad reason filter | Any unavailable structural state with previous verdict contradicted can drop a sole `previously_unavailable`. | Reject for a fresh-verdict contract. Absence has no persistent definition witness; an authored ancestor-symlink transition changes fresh contradiction to uncertainty without another selection reason. |
| Existing-signature mismatch adapter | Only previous `predicate_mismatch` on an existing unique exact top-level function; preserve every other reason and require unchanged readable structural witnesses. | Proposed research candidate. Reuses selection and state transition, with explicit sufficient assumptions and conservative checks. |
| Full-module identity adapter | Require previous mismatch plus identical regular full-module blob identity and effective path/type envelope. | Useful conservative comparator; less dependent on symbol change coverage, but cannot skip a retry if unrelated code in the module changes. No benefit is presumed. Not implemented here. |

## Proposed integration and small interface

Use a research wrapper after genuine production selection and before actual validation. Production `select_claims`, `validate_claim`, and `advance_state` remain unchanged. The wrapper receives both snapshots and indexes that the replay already built. It produces the original selection, an effective selection, a suppression Boolean and an audit reason. It never reads independent reference output.

```python
base = select_claims(real_selection_context, symbol_validate)
decision = select_negative_carry(claim, provenance, previous, base_for_claim,
                                before, after, old_index, new_index)
result = validate_claim(...) if decision.effective.selected else None
state = advance_state(previous, decision.effective, symbol_validate, result, True)
```

The staged `negative_carry.py` implements this interface. The caller must preserve both original and effective selections. A suppression audit reason is recorded separately; it cannot be placed in the production selection reasons because the effective production selection must have `selected=false` and no triggering reasons. No new production PolicyID or MemoryState field is needed.

## Exact proposed eligibility

The experimental run freezes claims, provenance, source roots, protocol 1.1, snapshot/index/parser/normalizer/validator versions and Python identity. It uses the actual complete sequential snapshots and production ChangeSet without suppressing symbols or limitations. Each variant retains its own state and provenance.

A check may be omitted only when all of the following hold:

- Claim is `signature_equals`, subject is an exact simple top-level function, and scope promises only the existing exact normalized syntax. `symbol_exists` with expected true has no existing-function contradiction; its `subject_absent` results are deliberately outside this exception.
- The genuine production `symbol_validate` decision is selected and has exactly the sole reason `previously_unavailable`. Every subject-change, anchor-change, known-incomplete, analysis-limitation, dependency, unknown or additional future reason preserves validation.
- Previous state is unavailable and stale, its actual last production verdict is contradicted, and its withheld reason is exactly `predicate_mismatch`. No pending/retired/uncertain or policy-reset state qualifies.
- Provenance is unchanged, has anchors, no dependencies, no unresolved remarks and `known_incomplete=false`. Research eligibility of this provenance does not certify closure or remove original remarks.
- Claim/state/provenance/selection/snapshot/index identities match this transition. Claim and configuration hashes remain fixed by the enclosing sealed research protocol; the adapter alone is not an admission or integrity boundary.
- Both snapshots contain the exact subject path as a readable regular blob with no limitation or unsupported ancestor. Both indexes have one available subject module, exactly one matching unambiguous function definition, and equal AST hashes and complete normalized Signature objects. The explicit Signature comparison avoids relying solely on an AST-hash implication.

The draft prototype accepts the scope restriction as a caller precondition. Before integration, the enclosing research protocol must enforce the exact existing syntactic scope allowlist and immutable context, just as it already binds exact original claims. Unsupported type parameters, runtime-binding promises and behavior/prose claims remain outside this proposal. An implementation with a public, reusable API should enforce these scope conditions directly rather than relying on a caller contract.

## Conditional proof argument

Assume the frozen versions faithfully produce the supplied snapshots and indexes; both matching definition lists are complete; normalized signatures are deterministic; regular source bytes and index identity agree; and the claim/configuration remain fixed. Let the previously checked result be a genuine production `predicate_mismatch` on the accepted exact function.

On an omitted step, both indexed definitions are present, unique, unambiguous functions. The current subject module is available under fixed roots and has no recorded limitation. The complete normalized signature equals its previous value. The frozen expected signature is unchanged. Its previous inequality therefore remains inequality, so the same production validator branch returns `contradicted/predicate_mismatch`. Keeping the previous unavailable state is consistent with that fresh result.

For consecutive omitted steps, repeat the argument over each actual adjacent snapshot/index pair. The induction begins at the last actual contradictory validation; inherited state retains that original last-check commit. A subject change or changed ambiguity/limitation preserves the original selection or fails the explicit witness checks; normal production validation then determines recovery, contradiction or uncertainty. Any uncertain actual result stops eligibility until a new genuine mismatch is obtained.

This is a conditional consistency argument about a fixed implementation, not a proof of arbitrary Python binding semantics. The structural-closure v1 whole-module allowlist is substantially narrower, remains fixture-only, and cannot be widened by this adapter. The existing structural carry argument concerns positive supported results; its premises cannot simply be inverted to cover absence. Shared parser/normalizer bugs, hash/index identity bugs or an incomplete binding model can invalidate assumptions. Independent reference remains observational and never controls the decision.

## Concrete counterexample to the broad rule

The authored test uses an actual temporary Git repository and the production snapshot/index/compare/select/validate functions:

1. `pkg/f.py` contains `def f(x=2)`, while the claim expects `x=1`. A fresh result is `contradicted/predicate_mismatch`.
2. Delete `pkg/f.py`. Production selects it and returns `contradicted/subject_absent`, so the maintained state is retired and unavailable.
3. Replace directory `pkg` with symlink `pkg -> elsewhere`. Both adjacent indexes lack the subject definition. `pkg` does not end in `.py`, so no indexed module adds it to `limited_paths`; the exact subject path does not otherwise change its symbol marker. The production selection has only `previously_unavailable`.
4. Fresh production validation checks ancestor snapshot limitations and returns `insufficient_evidence/symlink_unsupported`. The broad filter would carry a historical contradiction and retired status instead. Availability remains false in both, which is why an availability-only comparison misses the failure.

The narrow candidate refuses step 3 because the previous reason is absence and the current exact regular module/definition witness is missing. The fixture preserves this as a negative control, rather than changing production selection to make the counterexample disappear.

## Other boundary cases

| Boundary | Required behavior and limit |
| --- | --- |
| Signature recovery, including defaults/annotations/decorators/async | Validate on subject-change markers or changed witness; allow support to restore availability immediately. |
| Deletion, renamed file, absent function, wrong node kind | Validate; never negative-carry `subject_absent`. |
| Absent subject reappears | New definition triggers validation; test the recovery delay explicitly. |
| Duplicate or conditional definitions, rebinding, wildcard import, class global | Keep production ambiguity/fallback reasons and reject ambiguous witnesses. Unknown parser coverage remains a limitation rather than proof of truth. |
| Unrelated function body or global change | Candidate may omit only if the exact witness and all remaining conditions survive; no runtime-binding claim is inferred. Independent v2 may still become uncertain and must be reported. |
| Direct or ancestor symlink/submodule, LFS, parse/encoding/size failure | Preserve validation/fallback; regular readable exact-path witness is required even if a reason marker is absent. |
| Cached index inconsistent with mode or source | Outside the proof premises; compare warm and fresh indexes in authored tests, preserve the existing same-blob/mode regression, and stop on disagreement. |
| Known incomplete, remarks, explicit dependencies | Preserve existing validation. No provenance flags change. |
| New/unrecognized selection reason | Fail closed: preserve original selection. |
| Claim, roots, version or provenance mutation | Stop the enclosing research replay or disable carry; never continue the induction under a new contract. |

## Staged verification and planned next step

Eight authored fixture tests currently pass, including chained negative carry, ordinary recovery, absent-subject recovery, known-incomplete and uncertain retries, parse failure, duplicates/conditional definitions, module/class-global rebinding, same-blob symlink, deletion, the broad-rule counterexample, and preservation of extra reasons or changed provenance. Ruff passes. These are implementation checks already executed during design; they are not held-out or preregistered confirmation.

`experiment-plan.json` proposes a new sealed exploratory sensitivity comparison over only the already authorized fixed development cohort, plus a separately frozen expanded authored test matrix. It is not executed by this task. A future run must obtain its own protocol ID, seal, implementation hashes and new output directory, keep the original four variants untouched, disclose the already seen outcomes, and report zero reduction or any mismatch without cohort repair. No additional corpus or held-out access is proposed.
