"""Reproduce descriptive figures; agent experiment and storage verification are separate."""
import json
from pathlib import Path
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, FuncFormatter

root = Path(__file__).resolve().parent
blocks = json.loads((root / 'audit.json').read_text())['blocks']
storage = json.loads((root / 'storage-v2.json').read_text())
fig, axes = plt.subplots(3, 1, figsize=(8, 8), layout='constrained')
series = [
    ('Noncached token work: four stages per condition', ['Plain', 'Exact replay'], [blocks[c]['token_work'] for c in ('plain', 'exact_replay')]),
    ('Measured pipeline seconds: includes learning and grading', ['Plain', 'Exact replay'], [blocks[c]['charged_wall_seconds'] for c in ('plain', 'exact_replay')]),
    ('Separate storage verification: serialized entry bytes', ['Version 1', 'Version 2'], [storage['previous_total_bytes'], storage['compressed_total_bytes']]),
]
for ax, (label, names, values) in zip(axes, series):
    ax.barh(names, values, color=['#64748b', '#2563eb'])
    ax.invert_yaxis()
    ax.set_xlim(0, max(values) * 1.23)
    for i, value in enumerate(values):
        ax.text(value + max(values) * .025, i, f'{value:,.2f}' if isinstance(value, float) else f'{value:,}', va='center')
    ax.set_title(label, loc='left', fontsize=10)
    ax.spines[['top', 'right', 'left']].set_visible(False)
    ax.xaxis.set_major_locator(MaxNLocator(4))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f'{v:g}'))
fig.suptitle('Exact-repeat development prototype: 8/8 quality gates passed\nOne dependent block; no general new-task or population speed claim', fontsize=11)
fig.savefig(root / 'results.png', dpi=180)
fig.savefig(root / 'results.pdf')
