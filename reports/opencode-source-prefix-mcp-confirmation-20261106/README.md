C2 / bounded-prefix C4: frozen no-model MCP profile and quiet confirmation

The changed-snapshot lookup is faster in this fixed local microbenchmark under the prospective conservative rule. Five paired samples give dispatch wall medians 2.158596 → 1.843444 seconds (14.60% lower) and CPU 2.080855 → 1.742453 seconds (16.26% lower). Wall ranges are C2 2.076170–2.198884 and C4 1.793736–1.911214 seconds. CPU ranges are C2 1.972358–2.110964 and C4 1.706436–1.782836 seconds. Every pair has the favorable sign and both median gaps exceed the larger within-side range. All four other lookup cases are no_measurable_difference. Preparation-inclusive wall and whole-namespace inclusive wall also remain no_measurable_difference under that rule.

This is a time/memory tradeoff, not a RAM improvement. Changed-process self RSS peak rises from median 185268 KiB (180.92578125 MiB) to 190028 KiB (185.57421875 MiB), +4760 KiB / +2.57%; every pair is higher. Cgroup lifetime peak medians are roughly equal, 238.73828125 versus 238.578125 MiB. The largest container peak across the quiet run is 239.43359375 MiB; observed CPU throttling is zero. Process RSS, cgroup peak and current charges have different scopes and are not added. All peaks and samples remain visible in resource-cost-summary.json and memory-comparisons.csv. No universal memory benefit or OS page-release claim follows.

Three C4 attribution namespaces ran first (15 dispatches), then passed receipt, portable result, work and all329-record semantic-state comparisons against the sealed C2 profile. The quiet phase then ran five alternating C2/C4 blocks: ten fresh namespaces, 50 dispatches and 50 containers including ten separately paid preparations. All passed, with zero retries, exclusions or failures. The profile adds 15 separate containers including three preparations. Total: 65 containers and 65 dispatches, zero models/network/heldout inputs. Profile and quiet timings are never pooled.

Separate cProfile evidence consistently retains 16 parse_module calls and 512 extracted definitions on the changed snapshot. C2 performs 512 ast.get_source_segment / _splitlines_no_ff calls; C4 performs 512 bounded _source_segment calls with 15 physical-line iterator factories. Cumulative profile times overlap and are not additive. These profiles identify repeated physical-line collection as the changed work; their instrumented times are not used as quiet speed estimates. Profile named validation _check calls remain exactly two on changed-new-process; all named work counts match. Quiet trace checked/carried values are persisted state types, explicitly not validator-call counts for that lookup.

The quiet audit rehashes 4090 namespace artifacts, authenticates all50 full/compact receipts and query hashes, verifies exact catalog bytes across all ten preparations, and checks all146 origin and all146 changed source-file hash/mode inventories. All persisted generations match across implementations under the explicit portable semantic projection: all329 payloads, revisions, state type, verdict/reason/evidence source, equivalence rule, dependency scopes/certainty and invalidation scopes. Generation 2 has329checked/supported; generation 3 has327carried/supported plus2checked/contradicted. Actual index/generation/check identities, timestamps and provenance remain retained separately rather than fabricated equal. Changed lookup selection is five records, three returned and two withheld in both implementations.

Only index.py differs between complete60-file frozen core inventories. The old nine-file adapter and eight frozen helpers are used; the new readable-display module is not loaded. Every namespace pays fresh source-only seed generation and CAMI construction. Source reset, preparation, lookup dispatch, result persistence, storage/hash and container lifecycle remain separately recorded. Dispatch excludes Python/adapter imports, Server construction and result-file write; it includes first CAMI import/refresh/ranking/serialization/storage/trace work. First-process cold does not mean flushed OS caches. Peak observations occur outside the dispatch timer. Nested timers are not added twice.

The exact prospective plan SHA6b9e9b3caaa6e16e0f13f78c1e967ab639bb08fe70fbe6dcdcac5bdd36892349 was accepted before execution. Root released the window after commit/push f355b656; no other tests/models/Docker/benchmarks/compression ran. Light metadata/source reading, code writing, hosted inference and system services remained possible. Raw uptime/nproc/process CPU counters and Docker listings are retained. This shared host was not exclusive CPU. The quiet interval was 18:58:23–19:00:35 UTC on2026-11-06. Free storage ended above5GiB; each container had2CPU/2GiB and network none, at most one active.

No model/provider path, model task quality, token reduction or end-to-end speedup was measured. C3's negative resource result and its earlier serializer failures remain immutable, separately sealed and unpooled. The earlier C4 authored screen is an admission gate, not another sample in this quiet result.

Entrypoints (plan-only default; measurement needs explicit release and NEW output):

    .venv/bin/python runs/opencode-source-prefix-mcp-confirmation-20261106/run_quiet.py --profile
    .venv/bin/python runs/opencode-source-prefix-mcp-confirmation-20261106/run_quiet.py

Read-only checks and summaries use the retained fixed paths:

    .venv/bin/python runs/opencode-source-prefix-mcp-confirmation-20261106/verify_profiles.py
    .venv/bin/python runs/opencode-source-prefix-mcp-confirmation-20261106/summarize_quiet.py
    .venv/bin/python runs/opencode-source-prefix-mcp-confirmation-20261106/verify_inputs_and_receipts.py
    .venv/bin/python runs/opencode-source-prefix-mcp-confirmation-20261106/summarize_resources.py
    .venv/bin/python runs/opencode-source-prefix-mcp-confirmation-20261106/summarize_attribution.py

The two state-exporting verifiers intentionally refuse to overwrite existing semantic-vector directories; use a fresh copy/output for a replay. Three fast authored controls verify that a large range defeats five favorable pairs, that a clear uniform improvement passes, and that mixed signs remain inconclusive. Original measurement outputs are never overwritten.
