# Read-only independent study aggregator

Implementation uses only Python's standard library and does not import the controller, harness or CAMI. It was verified only against authored synthetic records. It makes no model calls and does not load task source, candidate source, heldout outcomes, or private session state.

Install `aggregate_study.py`, `aggregate_metrics.py` and `supported_rules.json` together. The JSON file freezes the independently implemented success rule and cost/token semantics from `reports/opencode-study-design-20261104/protocol.json`. A different success rule is rejected rather than silently interpreted. Runtime image/token-limit revisions remain identified by each input study SHA; attempts from different versions are never pooled.

```sh
.venv/bin/python runs/opencode-study-analysis-development-20261104/aggregate_study.py \
  --run runs/ONE_FROZEN_STUDY_VERSION \
  --protocol reports/opencode-study-design-20261104/protocol.json \
  --study-sha256 EXACT_FROZEN_STUDY_SHA \
  --out runs/NEW_ANALYSIS_DIRECTORY
```

Outputs must be new and separate from the run. Existing output is never overwritten or deleted. `--study BYTE_IDENTICAL_RELOCATED_STUDY_JSON` supports archive relocation while retaining the original study SHA check. Without it, the original public study path in `run.json` is used. Supplying the externally frozen `--study-sha256` is recommended and its verification status is recorded.

The aggregator reconstructs the 36-trial cyclic schedule independently, checks the stored plan and frozen study binding, and rejects unknown trial directories. It opens trial payloads only after `terminal.json` exists. Active trial contents are never traversed. Terminal artifact coverage and every hash are checked; symlinks, special files, unsafe paths and private-state entries are refused without reading their contents. No incomplete run is recovered or modified by analysis.

Hashed raw session usage is joined against terminal summaries. Paid failed attempts retain observed counters. Missing or explicitly partial telemetry remains unknown; it is never zero-filled. All five counters stay separate: `input`, `cache_read` (cache.read), `cache_write` (cache.write), `output`, `reasoning`. Token work is exactly `input + cache_write + output + reasoning`. Cached reads remain visible. Session totals and assistant-step sums are never combined. Client-normalized zero does not prove a raw-provider zero, and missing provider fields may be unrecoverable after normalization.

Charged wall is checked against inclusive controller time minus separately timed fixture/export/grading infrastructure. It must include construction and session spans; construction is zero for plain and occurs only at the memory origin. Charged wall is summed once. Nested CPU, memory, preparation and session details remain in each trial's `resource_components`; nested spans are never added into wall totals. Final terminal-evidence hashing/publication follows the controller's operational timer and is separately disclosed bookkeeping.

Every repetition/arm block reports four-stage totals, observed subtotals, known-stage counts and unknown trial IDs. A total is null if it is incomplete; an observed subtotal is explicitly labeled. Medians/ranges of complete block values and the six paired CAMI/comparator deltas and ratios are retained, including failures. There is no trimming or favorable run selection.

Primary superiority is conservative: all36 trials must be operationally complete, pass fixed quality checks, and have complete wall plus all five normalized token counters. CAMI must be strictly lower in all three blocks against both plain and static using the same metric across all six comparisons. Ties, mixed metrics, missing telemetry or any failure prevent a win. Development/synthetic applications are labeled as such, never as a final heldout success or a population claim.

Outputs:

- `report.json`: provenance, immutable terminal hashes, trial records, nested resources, nine blocks, six paired comparisons, medians/ranges, eligibility and limitations.
- `trials.csv`: all36 rows, statuses, complete/unknown flags, charged/component wall values and five counters; unknown numeric cells are blank.
- `blocks.csv`: nine block totals and separately labeled observed subtotals.
- `paired.csv`: six comparator pairs × two metrics, with deltas/ratios and strict-lower flags.
- `rejection.json`: integrity/schema failure with no superiority claim; CLI exits nonzero.

## Authored verification

```sh
.venv/bin/python -m unittest discover -s runs/opencode-study-analysis-development-20261104 -p test_aggregate.py -v
.venv/bin/ruff check runs/opencode-study-analysis-development-20261104/*.py
.venv/bin/python runs/opencode-study-analysis-development-20261104/verify_authored.py \
  --out runs/opencode-study-analysis-development-20261104/NEW_AUTHORED_EVIDENCE
```

Fourteen controls cover complete wins, paid failures, missing/partial telemetry, active private-state non-access (with an open guard), unknown metrics, mixed-metric false wins, ties, raw and rehashed tamper, extra/version-pooled rows, and CSV unknowns. `authored-cli-final/verification.json` preserves six end-to-end CLI cases: complete, partial failure, missing usage, mixed metrics, artifact tamper and rehashed forged cost. No actual study or heldout results were aggregated during development.

## Timing-caveat extension (analysis v2)

This is a separate staging copy. Earlier analysis source, all measured runs and installed/frozen benchmark modules remain unchanged. Verification used only quick authored unit checks, with no model/auth calls, Docker, task source or heldout outcome access.

Add `--timing-caveats PATH.json` to the same CLI. The file uses this shape:

```json
{
  "schema_version": 1,
  "caveats": [{
    "trial_ids": ["r1-plain-s1"],
    "reason": "Known concurrent infrastructure on the shared CPU host",
    "evidence_path": "phase-timing.json",
    "evidence_sha256": "64 lowercase hexadecimal characters"
  }]
}
```

`evidence_path` is optional when an evidence SHA is supplied; a path alone is also accepted and its full SHA is recorded. Relative paths resolve against the caveat file's directory. With both fields, a mismatch is rejected. Hash-only declarations are explicitly labeled as not having their evidence file read. Each entry needs nonempty known trial IDs and a reason. Optional top-level `study_sha256` binds the caveat file to one input study version. Unknown IDs, private/unsafe evidence paths and invalid hashes are rejected.

The report retains the full caveat input path/SHA, normalized entries and evidence path/SHA. Every trial remains in JSON and CSV. All raw charged-wall values, complete block totals, medians/ranges and all six paired deltas/ratios remain unchanged. Affected trial flags and block ID lists make the context visible. `excluded_trial_ids` is always empty.

If any trial is affected, `primary_metric_eligibility.charged_wall` is false and charged-wall cannot appear in `winning_metrics_satisfying_all_six_pairs`. This applies to the entire wall metric; no selective trial removal or retry occurs. `primary_metric_eligibility.token_work` continues to depend on the original all36 operational/quality/complete-telemetry gate. A valid token-work win can still satisfy all six comparisons. CSV pairs include a `primary_metric_eligible` column so raw faster timings cannot be mistaken for an eligible time claim.

`timing-caveats-v3-example.json` stages the known v3 `r1-plain-s1` overlap declaration, referencing only the authorized timing metadata and its full file hash. Root should add its frozen study SHA before freezing a run-specific declaration. Supplying known caveats is the caller's responsibility; omission is not evidence of timing isolation. No actual study aggregation was performed here.

Nineteen authored checks pass. The five new checks cover wall-only false-win prevention, preserving a valid token win and unchanged raw pairs, unknown IDs, evidence-hash mismatch, and declared hash-only provenance. See `unit-final.json` and `ruff-final.json`.
