# Registered-input negative carry: staged research unit

Status: development staging, not sealed or timed. Original production files, the three previous algorithms, the first negative experiment and its results are unchanged. New execution has used only authored temporary Git histories. No new real-corpus data was accessed.

The candidate tests a small ownership alternative to repeated identity reconstruction. It may still be slower. It retains the original 17 histories, 31 transitions, 21 paired repetitions and 100 complete history-pack repetitions per block; it does not introduce longer histories or amortize work across independent resets.

## Owner and executable invariants

`registered_negative_carry.py` owns one logical entry with one immutable input bundle, its maintained MemoryState and its latest actual negative event. The public transition API consumes owned inputs; it never accepts a caller-provided MemoryState or witness.

- `register(claim, provenance, context)` recursively rejects mutable nested values, strictly reparses Claim/Provenance into private immutable schema copies, validates/freeze-copies ResearchContext, and records the original submitted objects by strong reference. Reusing the exact same immutable objects reuses the registration. Any distinct claim/provenance/context object—even one with equal fields—registers a new epoch and clears the negative event. Same-ID expected-signature changes cannot reuse old ownership. A changed run binding or claim ID requires a new owner.
- `initialize_checked_negative(result, snapshot, index)` once verifies an actual parent-negative result from the trusted frozen history builder. It strictly reparses the result, verifies the complete production validation input hash and identity, checks regular readable source, configured visibility/size, and complete unique unambiguous mismatching definition facts. It then creates the owner-bound event and initializes state through production `advance_state`. It cannot import a MemoryState, foreign witness, positive result or arbitrary retired status. This verifies binding/source consistency, not cryptographic authentication of untrusted fabricated result files.
- `initialize_fresh(snapshot, index)` is the alternative for a new owner: actual production validation creates the initial state/event. Tests use it to cover fresh-supported initialization. The benchmark uses the once-verified already-actual parent record, preserving its original parent-validation setup.
- `step(...)` accepts only `symbol_validate` and the explicit `keep_all` lineage control. Unsupported policies fail before state mutation. It always obtains the original decision from genuine production `select_claims`. Only the sole `previously_unavailable` decision on an eligible stale/unavailable actual signature mismatch may be suppressed. Any registered-input change forces a check at the next symbol-validation step. Keep-all retains its diagnostic no-validation semantics; it never mints or refreshes a negative event.
- Carry requires exact current bundle/event ownership, original last checked commit, owned provenance, fixed negative reason, and readable regular before/after subject modules with the same Git OID as the **last actually validated negative module**. 100644/100755 are equivalent for exact syntax. Same-blob symlinks, missing paths, limitations, uncertainty, known incomplete, unresolved remarks, dependencies, unsupported scope or extra production reasons refuse carry.
- Actual validation is called internally with the owned bundle. A supported, uncertain or absent result clears negative eligibility; only an actual predicate mismatch may create a new negative event. A skipped step keeps historical last-check fields. After any real result, production `advance_state` controls availability/state.

Registration followed by a controlled step is one internal epoch transition. Between re-registration and that step, the stored MemoryState is historical and must not be published as a verdict for the new inputs. The fixed runner calls step immediately and captures only its completed state; this research API does not claim atomic external publication across that pending interval.

The negative event stores the actual validation input hash already produced by the validator and the last checked module/commit. It never reconstructs that hash on every carry: the event is bound once at verified ingress or produced directly by the owner’s actual validation call. No public method accepts an arbitrary event for reuse. The policy-switch recovery fixture still validates when a prior mismatch was carried by keep-all across recovery.

These are invariants for a trusted in-process research runner using normal frozen-schema interfaces and genuine matching snapshot/index/context construction. Arbitrary Python attacks through `__dict__`, `object.__setattr__`, monkey-patched validators or forged private internals are outside that trust boundary; foreign-owner fault injection still verifies that ordinary accidental event mixing refuses carry.

## Which identity work belongs in timing

Full canonical claim/provenance/context digests are **trace metadata**, not guards in this owner design. `RegisteredInputs` has no cached digest fields. The capture path computes these digests only during serialization, outside timing, matching the original three variants’ trace policy. This removes unnecessary metadata work from the domain rather than deleting an integrity check.

Actual algorithmic work stays inside every measured logical history:

1. Create a new owner.
2. Deep-immutability checks, strict schema canonicalization/private cloning and context registration.
3. Once verify the actual parent result's input hash and source witness, and initialize owned state/event.
4. On each distinct input/context object, perform the complete registration again and invalidate the old event.
5. Execute genuine selection, all carry guards, owner-created actual validations/events and state advance.

No owner or registration cache survives a history reset. The fixed pack currently pays 22 registrations (17 initial resets plus five input/context edits), 17 parent-result ingress verifications, 22 child actual validations and seven suppressions. These are correctness-run counts, not measured performance results. If a different producer constructs fresh model objects on every step, registration will occur on every step; this API does not silently assume semantic equality permits handle reuse.

Global setup remains the previous authored Git/index/reference preparation and context construction, separately reported by the derivative driver. The new modules add class/function definitions, with no new global registration cache. Parent actual validation remains shared setup as in v1; the new owner’s verification of that result is additionally charged on every logical reset.

## Comparison and freeze boundaries

`registered_negative_carry_challenge.py` dispatches the original variants directly to the unmodified original `run_history`, and adds only `registered_inputs`. It reuses the unchanged authored preparation/reference helper. `run_registered_negative_carry.py` derives the prior driver’s measurement/profile loop, adding the new dispatch, lifecycle description and strict baseline pins. It checks:

- The original protocol raw hash and all five original runtime source hashes.
- Exact canonical equality of history definitions and all fixed workload/profile block choices with the original protocol.
- Its new protocol/source/test/production/reference/configuration seal before setup and after execution.

The fourth variant requires a new measurement order. Full-cycle rotation reversal makes each variant occupy each rank twice across eight repetitions; with the fixed 21 repetitions, the remaining partial cycle is disclosed. The old three-variant odd-repetition reversal would confound rank parity for four variants. The static balance test verifies the new order without running timing. No history or repeat count changes.

The driver retains paired CPU/wall measurements, separate candidate context setup costs, a separately instrumented one-pack cProfile phase, actual work counters, fresh-production/state/reference correctness gates and failed-output preservation. It reports no speedup automatically. A new slower or inconclusive result remains valid; the first negative result is neither overwritten nor relabeled.

## Verification

Seventeen authored tests pass, including all 31 complete MemoryState rows against the original module-blob candidate and fresh semantic state checks. Tests cover same-ID predicate changes, equal-but-distinct input objects, provenance/context/root/limit changes, nested immutability and invalid model copies, last-actual policy-switch lineage, foreign owner/imported state/witness refusal, fresh-supported initialization, uncertainty, known incomplete, symlink/absence, unsupported policy refusal and measurement-order balance. Ruff passes.

Only correctness/unit tests have executed. Neither the timing driver nor cProfile phase has run. Root must review, relocate if desired, freeze the new protocol/seal and use a fresh output directory. See `INSTALL.md`.

Root integration additionally makes pending epochs unpublishable through the state property and rejects keep_all until changed registered inputs have been validated. The added boundary test passed together with all original tests (31 total across both modules). These two guards were added after the archived review and before timing freeze.
