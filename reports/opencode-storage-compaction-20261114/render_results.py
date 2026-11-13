"""Render the frozen storage samples; timing bars are observed ranges."""
import base64
import json
from pathlib import Path
from statistics import median

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


root = Path(__file__).resolve().parent
cases = json.loads((root / "summary.json").read_text())["cases"]
fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
colors = ["#64748b", "#0f766e"]
sizes = [median(c["database_bytes"][side] for c in cases) / 1e6
         for side in ("baseline", "compact")]
axes[0].bar(["Before", "After"], sizes, color=colors)
axes[0].set(ylabel="Database MB (decimal)", title="Same histories, 44.13% less storage")
for i, value in enumerate(sizes):
    axes[0].text(i, value + .5, f"{value:.2f}", ha="center")
for i, side in enumerate(("baseline", "compact")):
    center = [c["warm_summary"][side]["median"] * 1000 for c in cases]
    low = [v - c["warm_summary"][side]["min"] * 1000 for v, c in zip(center, cases)]
    high = [c["warm_summary"][side]["max"] * 1000 - v for v, c in zip(center, cases)]
    axes[1].errorbar([n + (i - .5) * .2 for n in range(10)], center,
                     yerr=[low, high], fmt="o", capsize=2, color=colors[i],
                     label=["Before", "After"][i])
axes[1].set(ylabel="Validated store operation (ms)", xlabel="Source database",
            title="Warm latency: inconclusive", xticks=range(10),
            xticklabels=range(1, 11))
axes[1].legend(frameon=False)
for ax in axes:
    ax.spines[["top", "right"]].set_visible(False)
fig.savefig(root / "results.png", dpi=160)
fig.savefig(root / "results.pdf")
chart = base64.b64encode((root / "results.png").read_bytes()).decode()
(root / "chart.html").write_text(
    '<!doctype html><html lang="ru"><meta charset="utf-8"><style>'
    'body{margin:0;font:15px var(--font-sans);color:var(--foreground)}'
    'img{width:100%;height:320px;object-fit:contain}p{line-height:1.5}</style>'
    '<p><strong>Размер базы: −44,13%</strong> · 10 баз из полного эксперимента · '
    'история и результаты чтения сохранены</p>'
    '<img alt="Размер базы и пять замеров времени на каждую базу" '
    'src="data:image/png;base64,' + chart + '">'
    '<p>Точки — медианы пяти чередующихся запусков, линии — минимум и максимум. '
    'В пяти случаях диапазоны пересекаются: уверенное ускорение не доказано. '
    'Первое открытие с обновлением формата дороже: медиана 0,500 с вместо 0,187 с. '
    'Это проверка хранилища без вызовов модели.</p></html>')
