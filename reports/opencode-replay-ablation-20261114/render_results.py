"""Render the completed audit; never publishes partial-run performance results."""
import argparse
import base64
import html
import json
from pathlib import Path


def render(audit_path, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    result = json.loads(audit_path.read_text())
    if result['status'] != 'verified' or len(result['trials']) != 40:
        raise ValueError('completed independent40-attempt audit required')
    conditions = ['cami_replay', 'plain_replay']
    labels = ['CAMI + exact reuse', 'Plain + exact reuse']
    colors = ['#5b7798', '#16a085']
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5), layout='constrained')
    rows = []
    for ax, metric, title, unit in zip(axes,
            ['token_work', 'charged_wall_seconds'],
            ['Token work per four-stage sequence', 'Complete pipeline time per sequence'],
            ['tokens (excludes cache reads)', 'seconds']):
        for i, condition in enumerate(conditions):
            data = result['statistics'][condition][metric]
            if data['complete_blocks'] != 5:
                ax.text(i, 0, f"{data['complete_blocks']}/5 complete", ha='center', rotation=90)
                continue
            value = data['median']
            ax.bar(i, value, color=colors[i], width=0.65)
            ax.errorbar(i, value, yerr=[[value-data['min']], [data['max']-value]],
                        color='#1a2433', capsize=6, fmt='none')
            ax.text(i, data['max'], f'{value:,.0f}', ha='center', va='bottom', fontsize=10)
        ax.set_xticks(range(2), labels, rotation=20, ha='right')
        ax.set_title(title, fontsize=12)
        ax.set_ylabel(unit)
        ax.grid(axis='y', alpha=.2)
        ax.set_axisbelow(True)
        ax.spines[['top', 'right']].set_visible(False)
        ax.margins(y=.17)
    verdict = ('Fixed criterion passed' if result['direction_supported'] else
               'Fixed criterion not met' if result['eligible'] else 'Inconclusive: quality/telemetry gates incomplete')
    fig.suptitle(verdict + '\nMedian and observed range; five blocks, two exposed development tasks', fontsize=14)
    out.mkdir(exist_ok=True, parents=True)
    fig.savefig(out/'results.png', dpi=180)
    fig.savefig(out/'results.pdf')
    plt.close(fig)
    for condition,label in zip(conditions,labels):
        stats=result['statistics'][condition]
        cells=[]
        for metric in ('token_work','charged_wall_seconds'):
            v=stats[metric]
            cells.append('unavailable' if v['median'] is None else f"{v['median']:,.1f} ({v['min']:,.1f}–{v['max']:,.1f}); {v['complete_blocks']}/5")
        rows.append('<tr><th>'+html.escape(label)+'</th>'+''.join('<td>'+html.escape(c)+'</td>' for c in cells)+'</tr>')
    chart=base64.b64encode((out/'results.png').read_bytes()).decode()
    paired_rows = []
    for pair in result['pairs']:
        def label(value):
            return 'incomplete' if value is None else 'lower' if value else 'higher'
        paired_rows.append(f"<tr><th>{pair['repetition']}</th><td>{label(pair['token_work'])}</td><td>{label(pair['charged_wall_seconds'])}</td></tr>")
    (out/'chart.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>Source-memory ablation</title>'
        '<style>body{font:15px var(--font-sans);margin:0;color:var(--foreground)}img{width:100%;height:340px;object-fit:contain;background:white;border-radius:var(--radius)}'
        'table{border-collapse:collapse;width:100%}td,th{padding:12px;text-align:left;border-bottom:1px solid var(--border)}p{line-height:1.5}</style>'
        '<p><strong>'+html.escape(verdict)+'</strong> · 40 attempts · 2 conditions · 5 fresh memory blocks · A,A,B,B</p>'
        '<img alt="Median and observed range per condition" src="data:image/png;base64,'+chart+'">'
        '<table><tr><th>Condition</th><th>Token work: median (range)</th><th>Seconds: median (range)</th></tr>'+''.join(rows)+'</table>'
        '<p>Within-block Plain+replay compared with CAMI+replay:</p><table><tr><th>Block</th><th>Token work</th><th>Pipeline time</th></tr>'+''.join(paired_rows)+'</table>'
        '<p>Success requires lower token work AND full pipeline time for Plain+replay than CAMI+replay in every block, with every quality and evidence gate passing. '
        'Range bars are observed minima/maxima, not confidence intervals. This is exact-repeat evidence on two exposed Click development tasks, not40 independent tasks. '
        'Token work is not billed dollars; cache-read tokens are reported separately. Pre-model environment and MCP admission are preserved separately.</p></html>')

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('audit',type=Path)
    p.add_argument('out',type=Path)
    a=p.parse_args()
    render(a.audit,a.out)
