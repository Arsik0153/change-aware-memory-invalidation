"""Reproduce the standalone descriptive research figure from frozen analysis."""
from pathlib import Path
import json
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator

root = Path(__file__).resolve().parent
blocks = json.loads((root / "analysis.json").read_text())["summary"]["blocks"]
labels = ["No memory (context)", "CAMI lexical", "CAMI identifier"]
fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), layout="constrained")
for ax, key, label in zip(axes, ("token_work", "native_read_bytes"),
                         ("Normalized noncached token work", "Native read result text / UTF8 bytes")):
    values = [b[key]["total"] for b in blocks]
    ax.barh(labels, values, color=["#6b7280", "#2563eb", "#a855f7"])
    ax.invert_yaxis()
    ax.set_xlim(0, max(values) * 1.23)
    for i, value in enumerate(values):
        ax.text(value + max(values) * 0.025, i, f"{value:,}", va="center", fontsize=9)
    ax.set_xlabel(label)
    ax.xaxis.set_major_locator(MaxNLocator(4))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1000:g}k" if value else "0"))
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.grid(axis="x", alpha=0.15)
    ax.set_axisbelow(True)
fig.suptitle("Ranking-only development block: no resource reduction\n12/12 quality passed; complete telemetry; one dependent four-stage sequence per condition", fontsize=11)
fig.savefig(root / "comparison.png", dpi=180)
fig.savefig(root / "comparison.pdf")
