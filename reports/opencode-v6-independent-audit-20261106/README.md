# Independent closed v6 audit

The independent stdlib audit passes. All36 scheduled trials are terminal and pass operational/fixed-quality checks; all8130 terminal artifact hashes and exact file coverage verify. The cyclic schedule, predecessor/task IDs, restored fixed tests, runtime/image/binary/source inventories, cost identities and session-versus-assistant token sums check independently. No trial or historical cohort is excluded or pooled.

The copied analysis runtime comes from Git commit `fa415f0c85d51c886f8f509d26241cb8a836634c` and matches the pre-model source-freeze hashes. Reaggregation with the **mandatory timing caveat** is byte-identical to root's closed report SHA256 `632953c9879fb1f4f05c059d2dde747e0d4d8ead7724a13c1d7d7805faa1100b`. Frozen secondary-resource aggregation agrees with independent per-trial container CPU/peak/persistent-storage arithmetic.

Primary superiority is **not established**. CAMI token-work block totals are133132/121785/112402, plain108089/147233/98081, static134812/108609/112594. CAMI wins1/3 against plain and2/3 against static, failing the same-metric all-six rule. All36 rows and raw timings remain. Shared-host download-cache cleanup affects r2-plain/static/cami-s3; the verified caveat disqualifies primary wall time for the **whole cohort**, rather than dropping those three rows. Tier uniformity does not override that disqualification.

## Tier and normalized counters

All36 effective configurations request priority and high reasoning for the frozen model. All469 independently joined exported assistant observations report `default`, not priority. Each projection is bound by assistant ID/completion time and pinned runtime source; the native field was projected before public scrub. This is not independent wire/scheduler/entitlement/billing verification. Actual request-on-wire evidence is unavailable for these sessions.

| Normalized field, all12trials per arm | Plain | Static | CAMI |
| --- | ---: | ---: | ---: |
| input (noncached) | 294780 | 298537 | 307058 |
| cache.read | 2278272 | 2472576 | 2380800 |
| cache.write | 0 | 0 | 0 |
| visible output | 41051 | 40181 | 41361 |
| reasoning | 17572 | 17297 | 18900 |
| token work (input+write+output+reasoning) | 353403 | 356015 | 367319 |

These are client-normalized resource proxies. The normalizer can map missing provider fields to0; complete exported counters do not prove raw-provider completeness. Cache reads stay visible separately; session and assistant-step totals agree and are never added together. No subscription bill or equal token pricing is inferred.

## Resource and visible-context diagnosis

CAMI construction totals12.470s versus static2.959s and plain0. Local construction+session container CPU totals193.954/167.650/168.491s for CAMI/static/plain. Peak cgroup memory is a maximum, not a sum; remote inference resources and continuously sampled storage peaks are unavailable. All wall numbers are descriptive because of the cohort caveat. Core CPU optimizations cannot directly explain the token result, and no v5/v6 causal comparison is made.

CAMI has fewer native tool calls286 than plain302/static294, and fewer assistant responses152 than158/159. It still emits507712bytes of native read output and198673bytes of shell output (plain494888/174195; static497077/180219). Sixteen CAMI shell commands have nonzero exits, yielding127332bytes of developer test/debug output; final fixed-quality checks still pass. Large parameterized test failures can repeat substantial context. Different generated solutions and debug trajectories are observations, not effects proven to be caused by memory.

Each memory arm makes12lookups. Precise model-visible inner JSON partition:

| UTF8 byte component | Static | CAMI |
| --- | ---: | ---: |
| Raw displayed literal source | 58884 | 45333 |
| JSON escape expansion | 2411 | 1826 |
| Literal string quote delimiters | 120 | 96 |
| All nonliteral JSON remainder | 38676 | 36128 |
| Total model-visible JSON text | 100091 | 83383 |

Thus wire-minus-raw-literal is not pure metadata. The nonliteral remainder includes necessary trust, subject, source/span, withholding, budget and receipt data plus syntax and repeated fields. It is not assumed wholly avoidable. These are inner model-visible text bytes, not TLS/MCP transport bytes, BPE token counts or measured billing. The hypothetical replay-byte proxy in the detailed report is explicitly not actual provider prompt volume.

CAMI has46native reads after memory on the same returned-source file;17also contain the displayed literal prefix after native line-number framing is removed and visible lines are joined withLF. Static counts are52/18. Ten such prefix-overlap reads per memory arm precede any recorded possible intervening write. This is an overlap review signal, not proof that the read was unnecessary: adjacent source, truncated remainder, source verification and edits can justify it. Long tool `created→ran` spans can be argument streaming; they are not pure native execution or provider wait. Raw per-trial evidence stays in `visible-costs.json`.

The data supports a **bounded next development target**: offline prototype a generic lossless readable compact projection on all24 closed packets, identical for both arms, with no ranking/limit/catalog/predicate change. Preserve every displayed prefix character, truncation, subject/source/span mapping, trust and withholding, and full original payload/receipts. Factor repeated JSON/provenance without hiding meaningful information. Prove reversible semantics for newline/Unicode/decorator/control/backtick cases, then freeze a separate protocol before any new model comparison. No implementation or model test was performed here, and no token/quality benefit is established. A Rust rewrite does not address the observed context volume.

## Artifacts and reproduction

`summary.json` is the compact handoff; `independent-v1/report.json` and `input-hashes.json` contain independent calculations and every public terminal hash. `frozen-analysis-pins.json` binds the historical runtime; `frozen-reaggregation/` and `frozen-resources/` preserve its outputs. `wire-accounting.json` gives the exact escaping-aware partition. `memory-packet-roster.json` binds every closed memory call to message pointer, JSONL line, full-result/receipt/query hashes for future offline display prototypes; no arm/outcome selection occurs.

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python runs/opencode-v6-independent-audit-20261106/audit_v6.py \
  --run runs/opencode-development-v6-20261106 \
  --protocol reports/opencode-study-design-v6-20261106/protocol.json \
  --analysis runs/opencode-development-v6-final-analysis-20261106/report.json \
  --timing-caveats runs/opencode-development-v6-timing-caveats-20261106.json \
  --out NEW_SEPARATE_OUTPUT
```

`reproduction.json` records the frozen aggregation/resource commands and input hashes. Outputs are new-only and failures are preserved. All analysis is read-only for source/run/protocol data, uses no CAMI/runner import for audit decisions, and performs no model calls, heldout reads, tracked writes or commits.
