"""Reproduce storage, process-RSS and timing charts from audited raw summaries."""
import base64
import json
from pathlib import Path
from statistics import median

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

root = Path(__file__).resolve().parent
local = json.loads((root / 'local-summary.json').read_text())['cases']
mcp = json.loads((root / 'mcp-summary.json').read_text())['cases']
prior = root.parent / 'opencode-storage-compaction-20261114'
old = json.loads((prior / 'summary.json').read_text())['cases']
old_audit = json.loads((prior / 'audit.json').read_text())['cases']
inputs = json.loads((root / 'local-protocol.json').read_text())['cases']
for current, earlier, audit, case in zip(local, old, old_audit, inputs, strict=True):
    assert current['id'] == earlier['id'] == audit['id'] == case['id']
    assert current['database_bytes']['baseline'] == earlier['database_bytes']['compact']
    assert audit['compact_sha256'] == case['files']['memory.sqlite3']

fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout='constrained')
sizes = [median(c['database_bytes']['baseline'] for c in old),
         median(c['database_bytes']['baseline'] for c in local),
         median(c['database_bytes']['candidate'] for c in local)]
axes[0].bar(['Original\nschema 1', 'Compact\nschema 2', 'Compressed\nschema 3'],
            [s / 1e6 for s in sizes], color=['#94a3b8', '#64748b', '#0f766e'])
axes[0].set(ylabel='Median SQLite file (MB)', title='79.00% smaller than original')
for i, size in enumerate(sizes):
    axes[0].text(i, size / 1e6 + .5, f'{size / 1e6:.2f}', ha='center')
rss = [[sample['peak_rss_bytes'] / 1e6 for case in local for sample in case['samples'][side]]
       for side in ('baseline', 'candidate')]
rss_medians = [median(c['summary'][side]['peak_rss_bytes']['median'] for c in local) / 1e6
               for side in ('baseline', 'candidate')]
axes[1].bar(['Schema 2', 'Schema 3'], rss_medians, color=['#64748b', '#0f766e'])
axes[1].set(ylabel='Peak RSS of local read process (MB)', title='39.18% less peak process memory')
for i, value in enumerate(rss_medians):
    axes[1].text(i, value + 3, f'{value:.2f}', ha='center')
for ax in axes:
    ax.spines[['top', 'right']].set_visible(False)
fig.savefig(root / 'storage-memory.png', dpi=160)
fig.savefig(root / 'storage-memory.pdf')
plt.close(fig)

fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout='constrained')
for ax, cases, title in zip(axes, (local, mcp),
        ('Local process: separated in 10/10 cases', 'Linux MCP: inconclusive (5/10 separated)')):
    for i, side in enumerate(('baseline', 'candidate')):
        stats = [case['summary'][side]['process_wall_seconds'] for case in cases]
        ax.errorbar([n + (i - .5) * .2 for n in range(10)], [s['median'] * 1000 for s in stats],
                    yerr=[[(s['median'] - s['min']) * 1000 for s in stats],
                          [(s['max'] - s['median']) * 1000 for s in stats]],
                    fmt='o', capsize=2, color=['#64748b', '#0f766e'][i],
                    label=['Schema 2', 'Schema 3'][i])
    ax.set(title=title, ylabel='Complete process (ms)', xlabel='Source database',
           xticks=range(10), xticklabels=range(1, 11))
    ax.spines[['top', 'right']].set_visible(False)
    ax.legend(frameon=False)
fig.savefig(root / 'timing.png', dpi=160)
fig.savefig(root / 'timing.pdf')

images = [base64.b64encode((root / name).read_bytes()).decode()
          for name in ('storage-memory.png', 'timing.png')]
(root / 'chart.html').write_text(
    '<!doctype html><html lang="ru"><meta charset="utf-8"><style>'
    'body{margin:0;font:15px var(--font-sans);color:var(--foreground)}'
    'img{width:100%;height:300px;object-fit:contain}p{line-height:1.5}</style>'
    '<p><strong>Данные сохранены: меньше база и пиковая память</strong></p>'
    '<img alt="Размер SQLite и пиковая память процесса чтения" src="data:image/png;base64,' + images[0] + '">'
    '<p>10 реальных баз. Сжатие поверх предыдущего формата: −62,42% размера, '
    '−39,18% пиковой памяти отдельного процесса чтения на macOS. '
    'Все строки SQL и исходные данные восстановлены точно.</p>'
    '<img alt="Все медианы и диапазоны времени локального процесса и MCP" src="data:image/png;base64,' + images[1] + '">'
    '<p>Пять чередующихся запусков каждой версии на каждой базе. '
    'Полный локальный процесс: −4,70%; полный MCP: −2,77% по медиане, '
    'но диапазоны пересекаются — устойчивое ускорение MCP не доказано. '
    'Линии — минимум и максимум, не доверительный интервал.</p>'
    '<p>Первое локальное открытие с миграцией: 442 мс вместо 257 мс. '
    '1 781 тест, 24 этапа живого watcher и 120 сравнительных MCP-проверок прошли. '
    'Запросов к модели в этих замерах не было.</p></html>')
