"""Show the incomplete block's observed lower bound, separately from the primary chart."""
import base64
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

REPORT = Path(__file__).resolve().parent
result = json.loads((REPORT / 'post-hoc-lower-bounds.json').read_text())
if result['status'] != 'verified_post_hoc_bounds' or result['primary_eligible']:
    raise ValueError('verified separate bounds with unchanged incomplete primary result required')
row, = [p for p in result['pairs'] if p['unknown_baseline_usage_trials']]
fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), layout='constrained')
for ax, candidate, baseline, title, unit in (
    (axes[0], row['candidate_token_work'], row['baseline_token_work_lower_bound'], 'Noncached token work', 'tokens'),
    (axes[1], row['candidate_pipeline_seconds'], row['baseline_observed_pipeline_seconds_lower_bound'], 'Observed pipeline work', 'seconds'),
):
    ax.bar(0, candidate, color='#16a085', width=.6)
    ax.bar(1, baseline, color='#8798b0', hatch='///', edgecolor='#53647a', width=.6)
    ax.text(0, candidate, f'{candidate:,.1f}', ha='center', va='bottom')
    ax.text(1, baseline, f'≥ {baseline:,.1f}', ha='center', va='bottom')
    ax.set_xticks([0, 1], ['CAMI + replay\ncomplete evidence', 'Static baseline\nknown lower bound'])
    ax.set_title(title)
    ax.set_ylabel(unit)
    ax.spines[['top','right']].set_visible(False)
    ax.grid(axis='y', alpha=.2)
    ax.set_axisbelow(True)
    ax.margins(y=.22)
fig.suptitle('Post-hoc bound for the incomplete third block\nThe primary verdict remains inconclusive', fontsize=13)
fig.savefig(REPORT / 'lower-bounds.png', dpi=180)
fig.savefig(REPORT / 'lower-bounds.pdf')
plt.close(fig)
data = base64.b64encode((REPORT / 'lower-bounds.png').read_bytes()).decode()
(REPORT / 'lower-bounds.html').write_text('''<!doctype html><html lang="en"><meta charset="utf-8">
<title>Separate observed-cost bounds</title><style>body{margin:0;font:15px var(--font-sans);color:var(--foreground)}
img{width:100%;height:320px;object-fit:contain;background:white;border-radius:var(--radius)}p{line-height:1.5}</style>
<p><strong>Post-hoc bounds · primary verdict unchanged</strong></p>
<img alt="Complete replay cost below the incomplete baseline’s known lower bound" src="data:image/png;base64,''' + data + '''">
<p>The two missing-usage attempts belong to the static baseline. Unknown nonnegative
usage can only increase its known subtotal; any omitted grading adds time.
The replay candidate has complete primary evidence. Both preserved baseline solutions
passed separate fixed grading after the run.</p>
<p>All 15 observed pairs satisfy the work/time bound and componentwise nonincrease.
This is analysis chosen after seeing the completed results, not a new primary success,
an invoice, a retry-free timing estimate or a population confidence claim.</p></html>''')
