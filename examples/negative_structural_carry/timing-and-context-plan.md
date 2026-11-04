# Proposed next gate: total maintenance cost and a bound module witness

Status: design only, not executed. The initial signature-comparison prototype remains an exploratory correctness demonstrator. It scans substantial portions of the same evidence as `validate_claim`, sometimes twice. Its lower number of `validate_claim` entry-point calls is not evidence that it saves substantive work. Stop expanding that adapter until the following alternatives and measurement are frozen.

## Candidate to compare

Keep the existing broad-rule absence counterexample as a rejected negative control. Compare three genuine policies on the same fixed authored histories:

1. Unmodified production `symbol_validate`, including every previously-unavailable retry.
2. The existing proof-oriented signature-witness adapter, with every eligibility lookup/comparison charged to the candidate.
3. A simpler **full-module identity** negative adapter, still research-only. It carries only a previous actual signature `predicate_mismatch`, and only when the current exact subject path is the same readable regular full-module blob as the blob at that actual validation. It preserves every original reason other than a sole `previously_unavailable`, retains all known-incomplete/uncertain retries, and binds exact context as described below.

Candidate 3 would not compare signatures or scan definitions during each attempted carry. Its negative witness comes from a real previous `validate_claim` result. Git blob identity under unchanged path/root/parser/validator context preserves complete module bytes, parser output, binding facts and normalized signature. A changed unrelated statement in the same module invalidates the witness and triggers validation; any smaller scope is an explicit later experiment. Regular file mode is checked on every attempt, even if a symlink has the same blob object ID. Absence is excluded.

For a valid snapshot read from an authentic Git tree, presence of the exact path as a regular blob also rules out a non-directory ancestor on that path: a tree cannot contain both `pkg/f.py` and symlink/submodule `pkg`. This supplies a structural reason to avoid scanning all ancestors on every attempt. The validity of the full snapshot producer remains an explicit, version-bound premise. A hand-constructed inconsistent Snapshot must not qualify for the prospective genuine-Git challenge.

## Required binding before a reusable implementation

Create an immutable research-only witness only after an actual structural validation says `contradicted/predicate_mismatch`. It records:

- Complete canonical claim hash, including ID, expected signature, text, scope and subject.
- Complete provenance hash and the independent enclosing context hash.
- Exact actual validation commit, validation input hash, result identity and reason, tied to that state’s `last_checked_commit`.
- Subject path, regular Git mode class, full module Git object ID and available byte SHA-256 from the actual snapshot; no symbol-only anchor hash substitutes for the full blob identity.
- Context version, repo ID, source roots, protocol version, production validator/index/snapshot implementation/version identity, Python/parser/normalizer identity, snapshot size/encoding/limit configuration, and enclosing sealed run/input identity.

At every carry attempt, recompute and compare the small claim/provenance/context identities or reuse their genuinely immutable, precomputed run-scoped identities. A changed same-ID expected signature must invalidate the witness before checking blob identity. Require previous state to reference the actual captured contradictory validation, remain stale and unavailable with the same provenance, and never have received an intervening uncertain result. Unknown/new context fields or scope flags fail closed. Enforce an exact syntactic scope allowlist; runtime and unsupported type-parameter scopes do not qualify. Context flags and complete original selections remain in audit output.

The enclosing run can precompute immutable claim/provenance/context digests once, but their construction and enforcement costs must still be reported. A public adapter must not depend on an undocumented “caller never changes it” assumption. No witness is a receipt, independent label or evidence of closure authority.

## Timing hypothesis and procedure

The question is whether a candidate reduces total maintenance work relative to the actual retries. The primary measured quantity is complete policy maintenance: original selection, candidate eligibility/witness work, any actual `validate_claim`, and `advance_state`. The cost of candidate witness creation/refresh is included on acquisition steps. Separately report production snapshot/index/compare work, which is shared and may dominate the full run.

Before timing, freeze the expanded challenge cases, source and environment identity, candidate implementations, repetitions and order seed. Correctness must pass first, using fresh full-validation comparison and the independent reference where applicable. Never execute source or use new corpus accesses for timing. Existing development results may only support a clearly labeled retrospective sensitivity analysis under the already allowed commit IDs after its own seal.

Use real prebuilt immutable snapshots/indexes from the fixed authored histories. Construct those identically for each policy and report their separate cost. Each timed repetition begins from the same actual validated parent/witness and uses its policy's own sequential states. Reusing one baseline policy's states in another would measure a different workload and is prohibited. Repeat the complete history, not a chosen empty or favorable step. Include unchanged modules, changes inside the module, signature recovery, incomplete/uncertain states and early rejection cases so the branch mix is explicit.

Run a small frozen number of untimed warmups, then paired repetitions with deterministic alternating/randomized candidate order. Use `perf_counter_ns` for whole-loop wall time and `process_time_ns` for CPU time; report the number and duration of repetitions, scheduler/process conditions and dispersion. Aggregate many complete tiny histories per timed block so timing overhead does not dominate. Resolve the block/repetition count during an explicitly separate calibration phase before final measurement; disclose the calibration and freeze counts afterward. Use identical garbage collection and output behavior. Artifact serialization, reference checking and correctness assertions occur outside timed blocks and are charged separately where needed. Do not insert per-microstep timing probes that cost as much as the work; obtain component costs from separate full blocks with disclosed instrumentation.

Verify state/availability/recovery endpoints and work counters after every timed block. Record actual validator executions, witness acquisitions, accepted carry attempts, rejected attempts, module metadata lookups and full signature comparisons. Include the frozen branch mix and every complete history's outcome. The normal fresh validator must actually execute in the baseline; replacing it with a lookup of stored results would hide the cost being compared. Cached snapshot/index facts may be shared only equally and explicitly.

No elapsed-time claim is made until the timing protocol is frozen, the implementation cost is included, noise and overhead are bounded, and paired total-cost results agree with the work counters. If the candidate saves calls but has equal or worse total maintenance cost, reject it as a performance optimization on that workload. If index cost eliminates a meaningful end-to-end difference, say so. Any tiny microbenchmark benefit is limited to the authored workload and process; it cannot be presented as a Click or population speedup.

## Prospective challenge additions before implementation

The machine-readable experiment plan must freeze at least: direct and nested class/global cases; equal function AST plus module rebinding/ambiguity; scope flags and exact claim/context changes; regular executable mode changes; same-blob symlink and ancestor symlink/submodule cases; size/LFS/parse/encoding limits; incomplete and uncertain states; negative acquisition and consecutive carries; defaults/annotations/decorators/async recovery; deletion and later absent-subject recovery; full-module changes outside the subject; warm/fresh indexes; and the exact absence counterexample fields.

Context-changing cases must include same-ID expected predicate becoming equal to the unchanged function, changed provenance, changed roots/versions/Python/limit settings, altered scope flags and mismatched validation input identity. Their endpoint is **retry or reject**, never carry. Full-module identity may conservatively reject a case where the signature-witness adapter carries; that outcome is expected and must remain in the denominator.
