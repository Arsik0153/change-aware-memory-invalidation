# Local memory timing figure

The figure plots the sealed unprofiled five-block experiment, all samples, medians and min–max ranges. Source summary SHA256: `19211a707a267170014298cfa5307f640aa0045208ece6f1c8c2eae86e356870`.

Candidate1 replaces repeated membership scans over unresolved module bindings. Candidate2 additionally builds one exact-subject definition index per memory transition operation. All variants use the same329literal source records and canonical source snapshots.

The prespecified primary changed-source lookup comparison against baseline is **noise-limited** under the frozen range rule. Candidate2 is lower than candidate1 under that rule. Memory construction and the full local five-lookup workflow are secondary measurements; candidate2 is lower than both predecessors. The local workflow includes source materialization/reset, memory construction, container lifecycle, five actual calls and storage observation/hashing. It excludes the model/provider path, grading and some outer report bookkeeping. It is not an OpenCode task speedup.

Every local attempt and semantic check passed. No sample was removed or retried. Active hosted-agent processes, light source editing and metadata reads are disclosed in the source report; the machine was not exclusive. OS caches were not flushed.

Reproduce with `.venv/bin/python reports/opencode-quiet-lookup-figures-20261106/build_figure.py` from a checkout retaining the sealed source summary at its recorded path. PNG/SVG are standalone exports; HTML uses the same plotted data and includes the interpretation caveat.
