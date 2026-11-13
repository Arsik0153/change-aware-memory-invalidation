# Heldout full replay replication

Verdict: **inconclusive under the preregistered full-study gate**. All80 attempts completed;78 primary attempts passed and2 retained incomplete provider telemetry. All10 exact-repeat hits passed fresh fixed grading without a model session, and all10 physical changed-input/control probes passed. No trial was replaced.

All14 evaluable paired comparisons favor replay in both token work and pipeline time. The third static block is incomplete, so the required15/15 complete comparisons and all80 successful primary attempts are unavailable. These observed directions do not override the failed eligibility gate.

| Condition | Complete blocks | Token work median (min–max) | Pipeline seconds median (min–max) |
|---|---:|---:|---:|
| plain | 5/5 | 102,151.0 (88,659–119,036) | 440.61 (403.22–515.49) |
| static | 4/5 | 124,279.5 (98,085–133,717) | 460.16 (422.74–495.59) |
| cami | 5/5 | 118,768.0 (94,945–126,322) | 450.30 (427.29–489.50) |
| cami_replay | 5/5 | 64,561.0 (44,667–74,811) | 264.95 (225.35–295.97) |

Static statistics describe only its four complete blocks and must not be pooled with or imputed into the missing block. All failed-attempt known token subtotals and observed wall time remain in `all-attempt-accounting.json`; missing failed-response usage is explicitly unknown. These are tokens and observed pipeline time, not actual billed currency.

After the main run, both preserved failed-trial sources passed separate fresh fixed grading:159/185 acceptance cases and26,828/26,857 regression cases, respectively, with zero failures/errors. All80 primary terminal hashes remained unchanged. These forensic results establish solution quality only; they do not repair primary telemetry or timing. Full diagnostics are in the evidence archive; `forensic-quality-summary.json` provides the compact receipt.

Actual memory trace audit found50 configured-memory sessions with traces,49 with at least one lookup; the failed `r3-static-s3` session made none. Observed responses returned168 entries and withheld75 under `manual_review_required`, with no observed backend errors. These counts bind original75-note payloads and recorded trust labels, not an independent reconstruction of filesystem state at every query.

The complete archive is29,347,616 bytes and reproduces1,265,776,640 raw tar bytes exactly. `audit.json`, `binding-audit.json`, `physical-guard-audit.json`, `note-usage-audit.json` and `all-attempt-accounting.json` all completed. Launcher timestamps: 2026-11-13T19:22:04.706627+00:00 through 2026-11-13T21:38:29.395410+00:00. Maximum one-minute host load was 3.69 on8 logical CPUs; no independent quiet-host guarantee is made.


The decision rules in `preregistration.json` were committed as 49dfc24 before task prompts or solutions were opened. The production implementation remains a8c34cd, including schema3 compression. Only the experiment controller and independent admission/audit tools were adapted for the pre-existing Packaging task boundary and legacy note format.

The planned experiment has 80 attempts: four conditions, five independently initialized blocks per condition, and canonical A,A,B,B stages. Ten expected exact-repeat hits avoid model calls and must pass fresh fixed grading. The strict success gate requires all attempts to pass quality and operation checks, complete token/tier evidence, positive and changed-input cache controls, and lower block token work **and** complete charged pipeline time than each comparator in every block. Failures, costs, and incomplete evidence are retained; no retries, replacements, extension, or outcome-driven tuning.

Packaging was previously used for structural research: the two tasks and their outcomes are held out, the project is not unseen. These are public historical tasks and exact repeats, not proof for arbitrary new work or an estimate of production hit rate. Token work is not billed currency.

`environment.json` records the portable runtime adaptation. The sealed task preparation used Linux x86 CPython3.12.3; this replication uses the same immutable Linux ARM CPython3.12.12 image as the completed development full study. Pytest8.4.2 and pretend1.0.9 match; other dependency versions differ and are explicitly recorded. Every condition uses the same image. Admission rechecks base assertion failures, gold acceptance/full regression, and evaluator restoration controls on that image.

Only regular candidate files under `src/packaging` enter heldout grading. Original evaluator tests and canonical configuration are restored outside the agent. The agent receives neither private gold/evaluator assets nor the other task's archive/history. Static and CAMI receive the same original sealed75 generic origin-source notes. Requested readable formatting uses the existing compact fallback for notes, with full payloads bound in audit receipts; no task-dependent note regeneration or selection is introduced.

The first no-model admission (runtime-v13, b79e4fc) passed both gold tasks and restoration controls, but its generic MCP checker incorrectly expected provenance fields in the visible compact note payload. Actual compact responses retain those fields in a bound full-response receipt. Commit38ad3c3 corrects the checker and verifies both visible fields and the original full payload; production code is unchanged. The failed admission, including zero model calls, is retained in `failed-admission-v13.tar.xz` and `failed-admission-v13.json`. The corrected checker passed84 focused tests; the preceding controller/harness suite passed816.

Final runtime-v14 admission passed both fixed gold evaluations, both poisoned-base restoration controls, and six real MCP cases across static/CAMI and full/compact/readable formats. Static and CAMI catalog bytes match exactly. The80-attempt schedule and full runtime/input/code identities are frozen in `protocol.json`; `admission.json` binds to its SHA256. Production source and adapter match a8c34cd.


During the frozen run, `r3-static-s1` encountered two native OpenCode `provider.transport` WebSocket1006 errors. OpenCode internally retried and completed the model session; both failed assistant responses lack token/tier evidence. This is a provider-telemetry failure, not a controller trial retry. Its normalized known subtotal is19,994 token work plus150,784 cache-read tokens; unreported failed-response usage remains unknown. Runtime-v14 rejects the trial before capture/grading, so it remains a failed primary attempt. Its source was separately preserved at `diagnostics/r3-static-s1-source` before the next canonical reset, without changing terminal artifacts or rerunning a model. The preregistered full-study eligibility gate therefore cannot pass. All remaining scheduled attempts were completed and retained; no outcome was replaced. A future-controller correction preserves/grades completed source before rejecting missing-tier evidence, while keeping all primary gates and no-learning rules unchanged.

`r3-static-s3` subsequently encountered the same transport failure with one missing-token/tier assistant response and an internal native retry. Its primary attempt also remains failed and ungraded. The completed source was preserved separately at `diagnostics/r3-static-s3-source` before the next canonical reset. `grade_preserved.py` graded both preserved candidates after all80 primary attempts terminated, with zero model calls and unchanged primary terminal hashes. Those forensic grades cannot repair missing usage or make the original study eligible. `account_all_attempts.py` retains known normalized subtotals and explicit unknown usage from every attempt, including both failures.
