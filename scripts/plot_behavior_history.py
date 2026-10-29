"""Plot the saved authored behavior history without rerunning the experiment."""
from __future__ import annotations

import argparse
import csv
from html import escape
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Rectangle

from cami.artifacts import file_hash, reserve, write_json


def plot(source: Path, out: Path) -> None:
    data = json.loads(source.read_text())
    reserve(out)
    names = [row["variant"] for row in data]
    steps = [row["step"] for row in data[0]["states"]]
    assert len(data) == 4 and len(steps) == 6
    assert all([row["step"] for row in variant["states"]] == steps for variant in data)
    colors = {"available_supported": "#157d87", "withheld_contradicted": "#dce5ec",
              "available_contradicted": "#c04c45"}

    def category(row):
        if row["available"]:
            return "available_supported" if row["truth"] == "supported" else "available_contradicted"
        assert row["truth"] == "contradicted"
        return "withheld_contradicted"

    figure, (states, counts) = plt.subplots(1, 2, figsize=(12.5, 4.2),
                                          gridspec_kw={"width_ratios": [3, 1.35]})
    for i, variant in enumerate(data):
        for j, row in enumerate(variant["states"]):
            key = category(row)
            states.add_patch(Rectangle((j, i), 1, 1, facecolor=colors[key], edgecolor="white", linewidth=2))
            states.text(j + .5, i + .5, "checked" if row["selected"] else "carried",
                        ha="center", va="center", color="#17324d" if key == "withheld_contradicted" else "white", fontsize=9)
    states.set(xlim=(0, 6), ylim=(4, 0), yticks=[i + .5 for i in range(4)], yticklabels=names,
               xticks=[i + .5 for i in range(6)],
               xticklabels=["dependency\nbreak", "unrelated\nwhile false", "dependency\nrestore",
                            "direct\nbreak", "direct\nrestore", "unrelated\nwhile true"],
               title="Persisted memory after each transition")
    states.tick_params(length=0, axis="both", labelsize=9)
    for spine in states.spines.values():
        spine.set_visible(False)
    values = [row["maintenance_validations"] for row in data]
    counts.barh(range(4), values, color=["#617887"] * 3 + ["#c04c45"], height=.68)
    counts.set(ylim=(3.5, -.5), xlim=(0, 6.8), yticks=[], xticks=[0, 2, 4, 6],
               xlabel="Maintenance validations", title="Counts, not elapsed time")
    for i, value in enumerate(values):
        counts.text(value + .12, i, str(value), va="center")
    counts.spines[["top", "right", "left"]].set_visible(False)
    figure.suptitle("Synthetic behavior history: one claim, six transitions, four variants", fontsize=13)
    figure.legend(handles=[Patch(color=colors[key], label=label) for key, label in [
        ("available_supported", "Supported and available"),
        ("withheld_contradicted", "Contradicted and withheld"),
        ("available_contradicted", "Contradicted but available")]], loc="lower center", ncol=3,
        bbox_to_anchor=(.5, .04), frameon=False, fontsize=9)
    figure.text(.5, .015, "Each validation runs the probe three times. Each variant also has one parent validation. No population inference.",
                ha="center", fontsize=9)
    figure.tight_layout(rect=(0, .15, 1, .95))
    for extension in ("png", "svg"):
        figure.savefig(out / f"behavior-history.{extension}", dpi=160)
    plt.close(figure)
    rows = [{"variant": variant["variant"], **row} for variant in data for row in variant["states"]]
    fields = ["variant", "step", "truth", "selected", "available", "mismatch", "commit", "last_checked_commit"]
    with (out / "states.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    table = "<table><tr><th>Вариант</th>" + "".join(f"<th>{i + 1}</th>" for i in range(6)) + "<th>Проверки</th></tr>"
    for variant in data:
        table += "<tr><th>" + escape(variant["variant"]) + "</th>"
        for row in variant["states"]:
            key = category(row)
            title = f"{row['step']}; truth={row['truth']}; available={row['available']}; last_checked={row['last_checked_commit']}"
            color = "#17324d" if key == "withheld_contradicted" else "white"
            table += f'<td style="background:{colors[key]};color:{color}" title="{escape(title, quote=True)}">' + ("проверено" if row["selected"] else "перенос") + "</td>"
        table += f"<td>{variant['maintenance_validations']}</td></tr>"
    table += "</table>"
    html = '''<!doctype html><html lang="ru"><meta charset="utf-8"><title>CAMI: поведенческая история</title>
<style>body{font:14px system-ui;background:#f7fafb;color:#17324d;margin:24px}h1{font-size:23px}p{line-height:1.5}
table{border-collapse:collapse;width:100%;font-size:12px}td,th{border:3px solid #f7fafb;padding:9px 5px;text-align:center}
th:first-child{text-align:left}small{color:#4e6473}.legend{display:flex;gap:14px;flex-wrap:wrap}</style>
<h1>Как скрытая зависимость сохраняет ложное утверждение</h1>
<p>Одна искусственная история: 6 переходов, 4 варианта. Наведите курсор на ячейку для деталей.</p>''' + table + '''
<p class="legend"><span style="color:#157d87">■ Подтверждено и доступно</span><span>■ Опровергнуто и скрыто</span>
<span style="color:#c04c45">■ Опровергнуто, но доступно</span></p>
<p>1: изменение зависимости; 2: постороннее изменение при ложном утверждении; 3: восстановление зависимости;
4: прямое изменение функции; 5: восстановление функции; 6: постороннее изменение при верном утверждении.</p>
<p>В hidden_missing два ложных состояния остались доступны. Меньшее число проверок здесь сопровождается ошибкой.
У остальных вариантов таких расхождений нет.</p><small>Каждая проверка — три запуска probe в Docker.
Дополнительно у каждого варианта одна parent-проверка. Это не оценка ускорения или эффективности на реальных данных.</small></html>'''
    (out / "behavior-history.html").write_text(html)
    write_json(out / "manifest.json", {"source": str(source), "source_sha256": file_hash(source),
        "states": len(rows), "status": "rendered_pending_visual_review",
        "artifact_hashes": {p.name: file_hash(p) for p in sorted(out.iterdir()) if p.is_file()}})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    plot(args.source, args.out)
