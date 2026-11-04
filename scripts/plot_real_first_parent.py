#!/usr/bin/env python3
"""Reproduce the two-panel research figure from one verified saved run; no Git access."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

EXPECTED_MANIFEST = "2a57c6b2b71b95d40141422ef23aacac933fd64a248144f9ea9083d867848bf2"
VARIANTS = ("symbol_anchor", "file_anchor", "known_incomplete", "all_validate")
LABELS = ("Символьный якорь", "Файловый якорь", "Известная неполнота", "Проверять всё")
COLORS = ("#0f766e", "#2563eb", "#8793a6", "#334155")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def collect(run):
    manifest_path = run / "manifest.json"
    if sha(manifest_path) != EXPECTED_MANIFEST:
        raise ValueError("requires the exact completed real-first-parent-replay-v1 manifest")
    manifest = json.loads(manifest_path.read_text())
    if manifest["status"] != "complete" or manifest["source_before"] != manifest["source_after"]:
        raise ValueError("run is not complete with unchanged implementation")
    inputs = {"manifest.json": EXPECTED_MANIFEST}
    def read(name, jsonl=False):
        path = run / name
        actual = sha(path)
        if actual != manifest["artifact_hashes"][name]:
            raise ValueError(f"saved artifact hash mismatch: {name}")
        inputs[name] = actual
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if jsonl else json.loads(path.read_text())
    report = read("report.json")
    rows, parents, costs = read("observations.jsonl", True), read("parents.jsonl", True), read("costs.jsonl", True)
    overlap = read("overlap-check.json")
    if overlap["status"] != "matched" or not all(item["matched"] for item in overlap["observations"] + overlap["parents"]):
        raise ValueError("old overlap is not semantically matched")
    groups = {row["claim"]["claim_id"]: row["claim"] for row in parents}
    if len(groups) != 24 or len(rows) != 1152:
        raise ValueError("fixed claim/observation inventory changed")
    series = {}
    subsets = {"full": rows, "new": [row for row in rows if row["trajectory"]["coverage_stratum"] == "new_added"],
               "old": [row for row in rows if row["trajectory"]["coverage_stratum"] == "old_overlap"],
               "merge": [row for row in rows if row["trajectory"]["is_merge"]]}
    reports = {"full": report["variants"], "new": report["primary_new_coverage"]["variants"],
               "old": report["old_overlap"]["variants"], "merge": report["topology_strata"]["merge"]["variants"]}
    for name, subset in subsets.items():
        values = []
        for variant in VARIANTS:
            selected = [row for row in subset if row["variant"] == variant]
            actual = sum(row["validation"] is not None for row in selected)
            if actual != reports[name][variant]["actual_validation_calls"] or len(selected) != reports[name][variant]["candidate_observations"]:
                raise ValueError("report/actual observation accounting mismatch")
            values.append(actual)
        series[name] = values
    if series != {"full": [8, 17, 288, 288], "new": [0, 4, 176, 176], "old": [8, 13, 112, 112], "merge": [0, 1, 80, 80]}:
        raise ValueError("unexpected frozen-study series")
    new = reports["new"]["symbol_anchor"]
    if (new["reference_supported"], new["reference_contradicted"], new["reference_unknown"], new["false_available_per_contradicted"]) != (176, 0, 0, None):
        raise ValueError("new-coverage interpretation changed")
    parent_calls = sum(row.get("actual_calls", 0) for row in costs if row["phase"] == "parent_production_validation")
    reference_calls = sum(row.get("reference_calls", 0) for row in costs)
    indexes = sum(row.get("index_builds", 0) for row in costs)
    if (parent_calls, reference_calls, indexes) != (96, 312, 39):
        raise ValueError("separate-cost accounting mismatch")
    extras = []
    for number, row in enumerate(rows, 1):
        if row["variant"] != "file_anchor" or row["trajectory"]["coverage_stratum"] != "new_added" or not row["selection"]["selected"]:
            continue
        name = f"changes/{row['group_id']}/{row['commit']}.json"
        changes = read(name)
        subject = groups[row["claim_id"]]["subject"]
        symbol_changed = (subject["path"], subject["qualname"]) in {(node["path"], node["qualname"]) for node in changes["symbols"]}
        extras.append({"observation_line": number, "claim_id": row["claim_id"], "kind": groups[row["claim_id"]]["kind"],
            "subject": subject, "commit": row["commit"], "step": row["trajectory"]["step"], "is_merge": row["trajectory"]["is_merge"],
            "parents": row["trajectory"]["parent_commits"], "selection_reasons": row["selection"]["reasons"],
            "production_verdict": row["validation"]["verdict"], "reference_verdict": row["reference"]["verdict"],
            "changed_files": changes["files"], "subject_in_changed_symbols": symbol_changed, "changes_source": name})
    if len(extras) != 4 or sum(row["is_merge"] for row in extras) != 1 or any(row["subject_in_changed_symbols"] for row in extras):
        raise ValueError("additional file selections changed")
    contradicted = [row for row in subsets["full"] if row["variant"] == "symbol_anchor" and row["reference"]["verdict"] == "contradicted"]
    if len(contradicted) != 8 or len({row["claim_id"] for row in contradicted}) != 1 or any(row["trajectory"]["coverage_stratum"] != "old_overlap" for row in contradicted):
        raise ValueError("contradiction concentration changed")
    return {"run": str(run), "source_commit": manifest["source_before"]["git_head"], "input_hashes": inputs,
            "variants": list(VARIANTS), "series": series, "claim_count": 24, "full_denominator": 288,
            "new_denominator": 176, "old_denominator": 112, "parent_actual_validations": parent_calls,
            "reference_calls": reference_calls, "shared_indexes": indexes, "additional_file_selections": extras,
            "contradicted_unique_claims": sorted({row["claim_id"] for row in contradicted}),
            "contradicted_old_observations": 8, "new_reference_supported": 176, "new_reference_contradicted": 0,
            "conditional_false_availability_rate_new": None}


def render(data, output):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "svg.fonttype": "none", "svg.hashsalt": "real-first-parent-v1"})
    fig, axes = plt.subplots(1, 2, figsize=(13.8, 5.8), sharex=True, sharey=True)
    fig.subplots_adjust(left=.185, right=.965, top=.73, bottom=.27, wspace=.16)
    for ax, key, denominator, title in zip(axes, ("full", "new"), (288, 176),
            ("Все 36 переходов", "Только 22 добавленных перехода"), strict=True):
        ax.barh(range(4), [denominator] * 4, height=.62, color="#eef1f5", zorder=1)
        ax.barh(range(4), data["series"][key], height=.62, color=COLORS, zorder=2)
        for position, value in enumerate(data["series"][key]):
            ax.text(value + 4, position, f"{value} / {denominator}", va="center", fontsize=11, color="#172033")
        ax.set_title(f"{title}\n{denominator} наблюдений на вариант", fontsize=12, loc="left", pad=15)
        ax.set_xlim(0, 342)
        ax.set_xticks([0, 80, 160, 240, 320])
        ax.grid(axis="x", color="#dfe4eb", linewidth=.7, zorder=0)
        ax.set_axisbelow(True)
        ax.tick_params(axis="y", length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
    axes[0].set_yticks(range(4), LABELS)
    axes[0].invert_yaxis()
    fig.text(.185, .94, "Выполненные проверки дочерних утверждений", fontsize=18, weight="bold", color="#172033")
    fig.text(.185, .875, "Те же 24 утверждения Click. Старое перекрытие: 112 наблюдений на вариант.", color="#475569")
    fig.text(.185, .19, "Число фактических вызовов production-валидатора; общая шкала двух панелей.", color="#475569", fontsize=10)
    fig.text(.185, .12, "Добавленные 176 наблюдений все supported. Новых contradicted нет;\nоценить обнаружение нарушений по добавленной части нельзя.", color="#8f2f26", fontsize=11)
    fig.text(.185, .035, "Отдельно: 96 родительских проверок · 312 вызовов reference v2 · 39 индексов. Время не сравнивается.", fontsize=9, color="#475569")
    fig.savefig(output / "validation_calls.png", dpi=180, facecolor="white", metadata={"Software": "verified first-parent research plot"})
    fig.savefig(output / "validation_calls.svg", facecolor="white", metadata={"Date": None, "Creator": "plot_real_first_parent.py"})
    plt.close(fig)
    svg = (output / "validation_calls.svg").read_text()
    svg = svg[svg.index("<svg "):]
    table = "".join(f"<tr><td>{html.escape(label)}</td><td>{data['series']['full'][i]}</td><td>{data['series']['new'][i]}</td><td>{data['series']['merge'][i]}</td></tr>" for i, label in enumerate(LABELS))
    extra = "".join(f"<tr><td>{html.escape(row['claim_id'])}<br><code>{html.escape(row['subject']['qualname'])}</code></td><td>{row['step']}<br>{row['commit'][:12]}{' (merge)' if row['is_merge'] else ''}</td><td><code>{html.escape(', '.join(row['changed_files']))}</code></td></tr>" for row in data["additional_file_selections"])
    report_link = html.escape(os.path.relpath(Path(data["run"]) / "report.json", output))
    page = f'''<!doctype html><html lang="ru"><meta charset="utf-8"><title>Click: расширение first-parent replay</title>
<style>body{{max-width:1180px;margin:32px auto;padding:0 20px;font:16px/1.5 system-ui;color:#172033}}svg{{width:100%;height:auto}}table{{border-collapse:collapse;width:100%;margin:20px 0}}th,td{{padding:10px;text-align:left;border-bottom:1px solid #ddd}}code{{overflow-wrap:anywhere}}.limit{{background:#fff4ef;padding:16px}}small{{color:#475569}}</style>
<h1>Проверки на тех же 24 утверждениях Click</h1>{svg}
<p class="limit">Добавленная часть содержит 176 reference-supported наблюдений и ноль contradicted. Условная частота ложной доступности на contradicted не определена. Это зависимые повторные наблюдения, а не 288 независимых примеров. Ускорение не измерялось.</p>
<table><thead><tr><th>Вариант</th><th>Все 288</th><th>Добавленные 176</th><th>Merge: 80</th></tr></thead><tbody>{table}</tbody></table>
<h2>Четыре дополнительные файловые проверки</h2><p>Все завершились supported. Причины в каждой строке: <code>anchor_file_changed</code> и <code>subject_file_changed</code>. Соответствующих subject нет в changed-symbols; символьный вариант не выбирает эти строки.</p>
<table><thead><tr><th>Claim и функция</th><th>Шаг и commit</th><th>Изменённые файлы</th></tr></thead><tbody>{extra}</tbody></table>
<p>Старые 448 строк четырёх вариантов и 24 parent-записи семантически совпали. Восемь contradicted относятся к одному claim в старом перекрытии. Отдельные затраты: 96 parent-валидаций, 24 parent + 288 child вызовов reference и 39 общих индексов.</p>
<small>Источник: <a href="{report_link}">сохранённый report.json</a>, commit {data['source_commit'][:7]}. Хеши входов и детали строк: <a href="plot-data.json">plot-data.json</a>. График: <a href="validation_calls.png">PNG</a> / <a href="validation_calls.svg">SVG</a>. Helper проверяет целостность артефактов; независимый аудит оформляется отдельно.</small></html>'''
    (output / "index.html").write_text(page)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    data = collect(args.run.resolve())
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    dump(output / "plot-data.json", data)
    render(data, output)
    dump(output / "manifest.json", {"status": "complete", "helper_sha256": sha(Path(__file__)), "python": sys.version,
        "matplotlib": matplotlib.__version__, "input_hashes": data["input_hashes"],
        "artifact_hashes": {path.name: sha(path) for path in output.iterdir() if path.is_file()}})


if __name__ == "__main__":
    main()
