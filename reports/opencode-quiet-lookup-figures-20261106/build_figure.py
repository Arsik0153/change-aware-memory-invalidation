"""Plot the sealed local experiment; no model-task performance inference."""
from pathlib import Path
import hashlib
import json
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / "runs/opencode-quiet-lookup-confirmation-20261106/summary.json"
EXPECTED = "19211a707a267170014298cfa5307f640aa0045208ece6f1c8c2eae86e356870"
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == EXPECTED
data = json.loads(SOURCE.read_bytes())
variants = ("baseline", "candidate1", "candidate2")
labels = ("Исходная версия", "+ Индекс связей", "+ Индекс записей")
colors = ("#64748b", "#6366f1", "#059669")
panels = (
    ("Обращение после изменения кода · основной замер", "lookup_rows", "dispatch_wall_seconds"),
    ("Построение памяти · дополнительный замер", "variant_cost_rows", "preparation_host_inclusive_seconds"),
    ("Построение + пять обращений · весь локальный сценарий", "variant_cost_rows", "host_variant_seconds_inclusive"),
)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "svg.fonttype": "none"})
fig, axes = plt.subplots(3, 1, figsize=(8.3, 7.8))
records = []
for ax, (title, table, metric) in zip(axes, panels, strict=True):
    ax.set_title(title, loc="left", fontsize=11, pad=12)
    for y, (variant, label, color) in enumerate(zip(variants, labels, colors, strict=True)):
        rows = [r for r in data[table] if r["variant"] == variant]
        if table == "lookup_rows":
            rows = [r for r in rows if r["case"] == "changed-new-process"]
        samples = [r[metric] for r in rows]
        assert len(samples) == 5
        median = statistics.median(samples)
        ax.plot([min(samples), max(samples)], [y, y], color=color, linewidth=3)
        ax.scatter(samples, [y] * 5, color=color, alpha=.45, s=30)
        ax.scatter([median], [y], color=color, marker="D", s=55, zorder=4)
        ax.annotate(f"{median:.3f} с", (max(samples), y), xytext=(9, 0),
                    textcoords="offset points", va="center")
        records.append({"metric": metric, "variant": variant, "samples": samples,
                        "median": median, "min": min(samples), "max": max(samples)})
    ax.set_yticks(range(3), labels)
    ax.set_ylim(2.6, -.6)
    ax.set_xlim(left=0, right=ax.get_xlim()[1] * 1.13)
    ax.set_xlabel("Секунды · меньше — лучше")
    ax.grid(axis="x", alpha=.2)
    ax.spines[["top", "right", "left"]].set_visible(False)
fig.suptitle("CAMI: локальная память, 329 записей, 5 повторов", fontsize=13, y=.99)
fig.tight_layout(rect=(0, .035, 1, .97), h_pad=1.8)
fig.text(.02, .012, "Ромб — медиана; линия — минимум–максимум; точки — все повторы. Модель не запускалась.", fontsize=9)
fig.savefig(HERE / "local-memory-comparison.png", dpi=180, facecolor="white")
fig.savefig(HERE / "local-memory-comparison.svg", transparent=True)
plt.close(fig)
svg = (HERE / "local-memory-comparison.svg").read_text()
svg = svg[svg.index("<svg"):].replace("#000000", "var(--foreground)")
html = ("<!doctype html><html lang='ru'><meta charset='utf-8'><style>"
        "body{margin:0;color:var(--foreground);font-family:var(--font-sans)}"
        "figure{margin:0}svg{width:100%;height:auto;display:block}p{font-size:14px;line-height:1.5}"
        "</style><body><figure>" + svg + "</figure><p>"
        "Построение памяти и весь локальный сценарий стали быстрее по заранее выбранному правилу. "
        "Для отдельного обращения преимущество над исходной версией остаётся в пределах разброса. "
        "Это ещё не результат сравнения полных задач OpenCode.</p></body></html>")
(HERE / "comparison.html").write_text(html)
(HERE / "chart-data.json").write_text(json.dumps({"source_sha256": EXPECTED, "rows": records}, indent=2) + "\n")
