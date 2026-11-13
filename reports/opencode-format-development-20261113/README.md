# Local format development experiment — 13 November 2026

**Verdict: inconclusive under the frozen combined criterion.** All20 attempts
passed fixed acceptance and regression grading, runtime admission and memory
integrity. There were no retries or dropped trials. Token telemetry is complete;
exact native read-result bytes cannot be reconstructed from redacted transcripts.
No superiority, monetary saving or wall-time improvement is established.

| Condition | Passed stages | Noncached normalized token work |
|---|---:|---:|
| Plain | 4/4 | 147385 |
| Static compact | 4/4 | 115252 |
| CAMI compact | 4/4 | 122841 |
| Static readable | 4/4 | 108919 |
| CAMI readable | 4/4 | 118193 |

In this one exploratory block, readable used5.49% fewer normalized noncached
tokens within static and3.78% fewer within CAMI. These are descriptive totals
across four dependent stages on two fixed development tasks, not replicated
estimates or billed prices. Input, cache.write, output and reasoning are counted
once; cached reads remain a separate field in `analysis.json`. The declared
hypothesis additionally requires lower native read-result bytes in both backends
and complete metrics for all20 trials. That requirement is not met.

All16 memory sessions made actual memory lookups, with17 completed lookups total.
Their recorded display formats matched the frozen condition. Plain made zero
memory lookups. Every session requested Sol high with priority, while every
recorded provider response reported default. Requested tier is not served tier.
Wall totals include independent construction and session lifecycle costs, but
remain descriptive because independent host-quietness evidence is absent.

The frozen analyzer also incorrectly expects a `content` array on non-assistant
user/idle messages. Fixing that parser defect alone cannot recover original
bytes: every trial contains redacted native read text. One plain trial also
includes a failed read operation. Preserve these observations and the original
inconclusive report; do not reinterpret missing bytes as zero or rerun selected
trials. A prospective measurement change must count bytes before publication
redaction and retain explicit completeness and per-call identities.

## Reproduction and evidence

- Source commit: `420730d`; admission commit: `0fff15d`.
- Frozen study SHA256: `d6199ba3b2b3b6952901b64325928213a7802b484574a4362d453f14637aa05d`.
- Prior proposal, fixed protocol, source pins, complete schedule and no-model
  admission: `../local-resume-20261113/format-freeze-v4.tar.gz`.
- `evidence.tar.gz`: complete20-trial output, final owned namespaces, controller
  logs and original frozen analysis. All private session states were removed
  before export. No common service credentials are included.
- `analysis.json`: output of the exact pre-call frozen analyzer, unchanged.
- `driver.jsonl`: attempt order and terminal outcomes.
- `token-work.png`, `token-work.pdf`, `plot.py`, `chart.html`: reproducible chart
  and inline display. No native-read bars are drawn from missing measurements.

Run the frozen snapshot's `scripts/opencode_benchmark/analysis/format_probe.py`
with `--run <extracted>/format-model --out <new-file.json>`. Verification checks
terminal hashes, exact artifact coverage, frozen run binding and trial schedule.
Do not combine this run with historic36-trial cohorts. Heldout remains unrun.

## Next work

1. Correct non-assistant message handling and add a numeric pre-redaction native
   read receipt, including interrupted export and malformed/error outcomes.
2. Verify the full pagination-to-publication path with synthetic sensitive text
   and a real no-model OpenCode session; ensure raw contents never enter receipts.
3. Inspect the preserved read and lookup sequences for targeted retrieval changes.
   Any new model experiment needs a separately frozen protocol; this20-trial
   block is closed and is not extended based on its observed token direction.
