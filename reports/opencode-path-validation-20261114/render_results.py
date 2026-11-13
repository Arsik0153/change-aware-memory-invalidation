"""Plot observed median/range for every case, including overlapping ranges."""
import base64
import json
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

root = Path(__file__).resolve().parent
fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout='constrained')
for ax, name, title in zip(axes, ('local', 'mcp'), ('Local process: 10 cases', 'Linux MCP: 10 cases')):
    cases = json.loads((root / (name + '-summary.json')).read_text())['cases']
    for i, side in enumerate(('baseline', 'candidate')):
        stats = [case['summary'][side]['process_wall_seconds'] for case in cases]
        values = [s['median'] * 1000 for s in stats]
        low = [(s['median'] - s['min']) * 1000 for s in stats]
        high = [(s['max'] - s['median']) * 1000 for s in stats]
        ax.errorbar([n + (i - .5) * .2 for n in range(10)], values,
                    yerr=[low, high], fmt='o', capsize=2,
                    color=['#64748b', '#0f766e'][i], label=['Before', 'After'][i])
    ax.set(title=title, ylabel='Complete process (ms)', xlabel='Source database',
           xticks=range(10), xticklabels=range(1, 11))
    ax.spines[['top', 'right']].set_visible(False)
    ax.legend(frameon=False)
fig.savefig(root / 'results.png', dpi=160)
fig.savefig(root / 'results.pdf')
chart = base64.b64encode((root / 'results.png').read_bytes()).decode()
(root / 'chart.html').write_text(
    '<!doctype html><html lang="ru"><meta charset="utf-8"><style>'
    'body{margin:0;font:15px var(--font-sans);color:var(--foreground)}'
    'img{width:100%;height:320px;object-fit:contain}p{line-height:1.5}</style>'
    '<p><strong>Проверка путей: положительный сигнал, строгий критерий не выполнен</strong></p>'
    '<img alt="Медианы и диапазоны времени каждого полного процесса" '
    'src="data:image/png;base64,' + chart + '">'
    '<p>Медиана полного MCP-вызова: 528 → 499 мс (−5,41%). '
    'На каждой базе — пять чередующихся запусков каждой версии. '
    'Во всех случаях медиана ниже; в двух из десяти диапазоны пересекаются. '
    'Линии — минимум и максимум, не доверительный интервал.</p>'
    '<p>Все 120 MCP-проверок прошли; вызовов модели не было. '
    '1 750 тестов прошли до измерений. Это не оценка ускорения всей работы агента.</p></html>')
