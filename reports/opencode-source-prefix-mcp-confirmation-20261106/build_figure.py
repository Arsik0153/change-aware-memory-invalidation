"""Render sealed five-pair local lookup evidence; no timing or model execution."""
import json
from pathlib import Path
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
report = json.loads((ROOT / "summary.json").read_text())
rows = [r for r in report["lookup_rows"] if r["case"] == "changed-new-process"]
series = {v: sorted([r for r in rows if r["variant"] == v], key=lambda r: r["block"])
          for v in ("candidate2", "candidate4")}
assert all(len(r) == 5 for r in series.values())
plt.rcParams.update({"svg.fonttype": "none", "font.family": "DejaVu Sans", "font.size": 10})
fig, axes = plt.subplots(1, 3, figsize=(10, 3.6), layout="constrained")
metrics = [("dispatch_wall_seconds", 1, "Время вызова", "с"),
           ("dispatch_cpu_self_and_completed_children_seconds", 1, "CPU вызова", "с"),
           ("after_dispatch_memory_rss_peak_kib_self_lifetime", 1024, "Пиковый RSS процесса", "МиБ")]
for ax, (key, divisor, title, unit) in zip(axes, metrics, strict=True):
    before = [r[key] / divisor for r in series["candidate2"]]
    after = [r[key] / divisor for r in series["candidate4"]]
    for a, b in zip(before, after, strict=True):
        ax.plot([0, 1], [a, b], color="#94a3b8", lw=1, alpha=.65, zorder=1)
    for x, values, color in [(0, before, "#3182ce"), (1, after, "#f59e0b")]:
        median = statistics.median(values)
        ax.scatter([x] * 5, values, color=color, s=28, zorder=3)
        ax.plot([x-.09, x+.09], [median, median], color=color, lw=3, zorder=4)
        ax.annotate(f"{median:.3f}" if divisor == 1 else f"{median:.2f}",
                    (x, max(values)), xytext=(0, 10), textcoords="offset points",
                    ha="center", weight="bold")
    ax.set(title=title, ylabel=unit, xlim=(-.3, 1.3), ylim=(0, max(before + after) * 1.18))
    ax.set_xticks([0, 1], ["До", "Исправление"])
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=.18)
fig.savefig(ROOT / "comparison.png", dpi=170)
fig.savefig(ROOT / "comparison.svg")
plt.close(fig)
svg = (ROOT / "comparison.svg").read_text()
svg = svg[svg.index("<svg"): ]
html = """<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{margin:0;padding:24px;background:var(--background,#0b1020);color:var(--foreground,#e8edf7);font:15px/1.5 system-ui,sans-serif}h1{font-size:23px;line-height:1.25;margin:0 0 8px}.muted{opacity:.78}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:20px 0}.stat{padding:14px;border:1px solid var(--border,#334155);border-radius:12px;background:var(--card,#111827)}strong{display:block;font-size:25px}.plot{background:var(--card,#111827);border-radius:12px;padding:8px}svg{width:100%;height:auto}svg text{fill:var(--foreground,#e8edf7)!important}svg [style*="fill: #ffffff"]{fill:transparent!important}p{margin:14px 0 0}.small{font-size:12px;opacity:.7}
</style><h1>CAMI: поиск после изменения исходников</h1><div class="muted">Пять чередующихся пар; одинаковые 329 записей. Локальный вызов инструмента, без модели.</div><div class="stats"><div class="stat">Время вызова<strong>−14,60%</strong>медиана пяти повторов</div><div class="stat">CPU вызова<strong>−16,26%</strong>медиана пяти повторов</div><div class="stat">Пиковый RSS<strong>+4,65 МиБ</strong>+2,57%; память не снизилась</div></div><div class="plot">""" + svg + """</div><p>Вызов быстрее во всех пяти парах. Время остальных четырёх сценариев, подготовки памяти и полного локального процесса — без измеримого выигрыша.</p><p class="muted">Пики cgroup близки; RSS — отдельный счётчик, его нельзя прибавлять к cgroup. Ускорение решения задач OpenCode ещё не установлено.</p><p class="small">Точки — все повторы, горизонтальные отметки — медианы. C2 → C4; одинаковый закреплённый адаптер compact/1. Все 65 вызовов прошли проверку; 15 профильных вызовов не включены в график.</p></html>"""
(ROOT / "comparison.html").write_text(html)
