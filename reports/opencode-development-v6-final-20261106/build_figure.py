"""Render all frozen v6 blocks, with wall-time ineligibility visible."""
from pathlib import Path
import hashlib
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "report.json"
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == "632953c9879fb1f4f05c059d2dde747e0d4d8ead7724a13c1d7d7805faa1100b"
report = json.loads(SOURCE.read_bytes())
summary = report["summary"]
assert summary["primary_superiority"] == "not_established"
assert summary["primary_metric_eligibility"] == {"charged_wall": False, "token_work": True}
assert summary["all_trials_operational_quality_pass"]
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "svg.fonttype": "none"})
fig, axes = plt.subplots(2, 1, figsize=(8.5, 7.4))
arms = (("plain", "OpenCode", "#64748b"),
        ("static", "+ Память", "#6366f1"), ("cami", "+ Память и CAMI", "#059669"))
panels = (("token_work", 1000, "Токены: устойчивого выигрыша CAMI нет", "Тысячи нормализованных токенов"),
          ("charged_wall", 1, "Время: только описание, вывод об ускорении запрещён", "Секунды за последовательность"))
for ax, (metric, divisor, title, ylabel) in zip(axes, panels, strict=True):
    for offset, (arm, label, color) in enumerate(arms):
        rows = sorted((r for r in summary["blocks"] if r["arm"] == arm), key=lambda r: r["repetition"])
        assert [r["repetition"] for r in rows] == [1, 2, 3]
        values = [r[metric]["total"] / divisor for r in rows]
        bars = ax.bar([r["repetition"] + (offset - 1) * .25 for r in rows], values,
                      width=.23, color=color, label=label,
                      hatch="//" if metric == "charged_wall" else None,
                      alpha=.7 if metric == "charged_wall" else 1)
        ax.bar_label(bars, fmt="%.1f" if divisor == 1000 else "%.0f", padding=3, fontsize=9)
    ax.set_title(title, loc="left", fontsize=11)
    ax.set_xticks([1, 2, 3], ["Повтор 1", "Повтор 2", "Повтор 3"])
    ax.set_ylim(0, ax.get_ylim()[1] * (1.3 if metric == "token_work" else 1.12))
    ax.set_ylabel(ylabel, fontsize=9)
    ax.grid(axis="y", alpha=.2)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
axes[0].legend(loc="upper center", ncol=3, fontsize=9)
fig.suptitle("OpenCode + CAMI · v6 · 36 успешных запусков", fontsize=13, y=.99)
fig.tight_layout(rect=(0, .075, 1, .96), h_pad=2)
fig.text(.02, .035, "Каждый столбец — полная последовательность из 4 задач. Все 3 повтора сохранены.", fontsize=9)
fig.text(.02, .012, "Очистка диска во время серии исключает вывод по времени. Токены — не денежный счёт.", fontsize=9)
fig.savefig(HERE / "comparison.png", dpi=180, facecolor="white")
fig.savefig(HERE / "comparison.svg", transparent=True)
plt.close(fig)
svg = (HERE / "comparison.svg").read_text()
svg = svg[svg.index("<svg"):].replace("#000000", "var(--foreground)")
html = ("<!doctype html><html lang='ru'><meta charset='utf-8'><style>"
        "body{margin:0;color:var(--foreground);font-family:var(--font-sans)}"
        "figure{margin:0}svg{width:100%;height:auto;display:block}p{font-size:14px;line-height:1.5}"
        "</style><body><figure>" + svg + "</figure><p>"
        "CAMI использовал меньше токенов, чем обычный OpenCode, в 1 из 3 повторов, "
        "и меньше, чем обычная память, в 2 из 3. Заранее заданный критерий требует "
        "выигрыша по одной метрике во всех шести сравнениях. Он не выполнен. "
        "Во всех 469 ответах провайдер сообщил default при запрошенном priority. "
        "Это разработочный набор; итоговый отложенный набор ещё не запускался.</p></body></html>")
(HERE / "comparison.html").write_text(html)
