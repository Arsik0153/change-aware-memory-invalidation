"""Render verified complete measurements as standalone figures and a report."""

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/practical-complete-20261115"


def main():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    result = json.loads((REPORT / "model-summary.json").read_text())
    assert result["status"] == "completed_and_verified" and result["attempts"] == 72
    tasks = result["task_results"]
    local = json.loads((REPORT / "local-comparison-v3/summary.json").read_text())
    failed_local = [name for name, case in local["cases"].items() if not case["accepted"]]
    local_text = (
        f"Новый локальный опыт local-comparison-v3 выполнил {local['attempts']} сравнительных запусков. "
        + (
            "Все семантические выходы и коды завершения совпали. "
            if all(case["correct"] for case in local["cases"].values())
            else "Есть несовпадения выходов или кодов завершения. "
        )
        + (
            "Критерий ускорения пройден. "
            if local["accepted"]
            else "Общий критерий не пройден в случаях: "
            + ", ".join(failed_local)
            + ". Изменение не включено. "
        )
        + "Исходные версии и оба новых опыта сохранены отдельно."
    )
    labels = [
        ("Packaging" if x["repository"].startswith("packaging") else x["repository"].title())
        + ": "
        + x["task"].replace("-", " ")
        for x in tasks
    ]
    for metric, title, unit, filename in [
        ("time", "Full measured pipeline per task", "seconds", "task-time"),
        (
            "token_work",
            "Token work per task (cache reads separate)",
            "normalized tokens",
            "task-tokens",
        ),
    ]:
        fig, ax = plt.subplots(figsize=(12, 7), layout="constrained")
        for arm, offset, color, label in [
            ("plain", -0.18, "#8493a5", "Plain"),
            ("cami", 0.18, "#258f85", "CAMI"),
        ]:
            for i, row in enumerate(tasks):
                value = row[arm][metric + "_mean"]
                if value is None:
                    ax.text(0, i + offset, "usage incomplete", fontsize=10)
                    continue
                minimum = row[arm][metric + "_min"]
                maximum = row[arm][metric + "_max"]
                ax.barh(
                    i + offset, value, height=0.32, color=color, label=label if i == 0 else None
                )
                ax.errorbar(
                    value,
                    i + offset,
                    xerr=[[value - minimum], [maximum - value]],
                    fmt="none",
                    color="#263238",
                    capsize=3,
                    linewidth=1,
                )
        ax.set_yticks(range(len(tasks)), labels, fontsize=11)
        ax.invert_yaxis()
        ax.set_xlabel(unit, fontsize=12)
        ax.set_title(
            title + "\nMean and observed min–max; 3 fresh sessions per condition", fontsize=13
        )
        ax.legend(loc="lower right")
        ax.grid(axis="x", alpha=0.2)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
        fig.savefig(REPORT / (filename + ".png"), dpi=160)
        fig.savefig(REPORT / (filename + ".pdf"))
        plt.close(fig)
    q = result["quality_passes"]
    time_pct = 100 * (result["median_paired_task_time_ratio"] - 1)
    token_ratio = result["median_paired_task_token_work_ratio"]
    token_text = (
        f"{100 * (token_ratio - 1):+.2f}%" if token_ratio is not None else "нет полного итога"
    )
    decision = (
        "Включение CAMI по умолчанию принято для проверенного набора задач."
        if result["recommend_cami_by_default"]
        else "Включение CAMI по умолчанию отклонено по заранее заданному критерию."
    )
    lines = [
        "# Практическая эффективность CAMI: завершённое сравнение",
        "",
        decision,
        "",
        f"Выполнены все 72 запланированные сессии: 12 исторических задач из Click, Requests и Packaging, по три свежих запуска plain и CAMI на задачу. Проверки качества прошли plain {q['plain']}/36 и CAMI {q['cami']}/36.",
        "",
        f"Медиана отношения средних времён по 12 парным задачам: CAMI {time_pct:+.2f}% относительно plain. Медиана отношения учитываемых токенов: {token_text}. Знак плюс означает увеличение затрат. Это медианы отношений по задачам, а не отношение общих сумм или медиан всех сессий.",
        "",
        "## Решение по критериям",
        "",
        "| Критерий | Пройден |",
        "|---|---|",
    ]
    lines += [f"| {key} | {'да' if value else 'нет'} |" for key, value in result["gates"].items()]
    lines += [
        "",
        "## Результаты по задачам",
        "",
        "| Задача | Качество plain / CAMI | Среднее время plain / CAMI, с | Средние токены plain / CAMI |",
        "|---|---:|---:|---:|",
    ]

    def tok(value):
        return f"{value:,.0f}" if value is not None else "unknown"

    for row in tasks:
        a, b = row["plain"], row["cami"]
        lines.append(
            f"| {row['task']} | {a['quality_passes']}/3 / {b['quality_passes']}/3 | {a['time_mean']:.2f} / {b['time_mean']:.2f} | {tok(a['token_work_mean'])} / {tok(b['token_work_mean'])} |"
        )
    lines += [
        "",
        "![Полное измеряемое время](task-time.png)",
        "",
        "![Учитываемые токены](task-tokens.png)",
        "",
        "## Что именно измерено",
        "",
        "Модель openai/gpt-6.1-sol#high одинакова. Порядок условий чередуется. Каждый запуск получает чистое рабочее дерево и новую модельную сессию. CAMI строит новую общую память префиксов из исходного кода, без ответов на задачи. Кеш готовых решений отключён. Стоимость построения памяти включена. Это проверка холодного начала работы с новым набором памяти, а не измерение её амортизации в долгоживущей пользовательской сессии.",
        "",
        "Время включает подготовку входов, память, контейнерный запуск, авторизацию, работу модели, сохранение исходников и свежую проверку качества. Общая стоимость допуска base/gold распределена поровну между 72 попытками. Подготовка итоговых графиков и отчёта исключена. Хост общий, его нагрузка и ресурсы записаны перед каждой попыткой.",
        "",
        "При аудите обнаружено различие границы таймера и текста протокола: исполнитель остановил таймер непосредственно перед публикацией терминальной записи, после сохранения решения и устойчивой записи оценки качества. Исходный протокол и результаты сохранены. Отдельный [аудит этого интервала](publication-tail-audit.json) ограничивает пропущенный хвост сверху: максимум 0,143 с, медиана 0,010 с. Даже наиболее выгодная для CAMI поправка оставляет отношение времени 1,11236; решение об отклонении также независимо следует из непройденного порога токенов. Текст генератора будущих протоколов исправлен после завершения опыта.",
        "",
        "Качество проверяет отдельный контейнер с фиксированными acceptance-тестами и полным выбранным upstream-модулем регрессионных тестов. Исходная версия провалила проверку каждой задачи, эталонная прошла. Для оценки используются исходники решения и канонические тесты, независимо от правок тестов моделью. Это не полный тестовый набор каждого репозитория.",
        "",
        "Токены разделены на input, output, reasoning, cache read и cache write. Основной token work исключает cache read; все компоненты сохранены отдельно. Неполная попытка не получает выдуманный полный расход. Данные usage являются наблюдаемыми показателями OpenCode, а не фактическим счётом провайдера.",
        "",
        "Три запуска одной задачи не считаются тремя независимыми задачами. Набор состоит из публичных исторических исправлений в уже изучавшихся репозиториях. Он не доказывает отсутствие этих исходников в обучении модели. Min–max на графиках являются наблюдаемым разбросом, а не доверительными интервалами.",
        "",
        "## Локальная оптимизация и Rust",
        "",
        local_text,
        "",
        "Решение по языку: оставить Python. Полная перепись на Rust не является результатом этого эксперимента. Наблюдаемые интервалы backend и числа вызовов инструментов находятся в model-summary.json; они не заменяют полный профиль CPU и транспорта.",
        "",
        "## Журнал обычных задач",
        "",
        "Команда cami task автоматически сохраняет входные файлы, режимы, точный текст задачи, объявленный внешний контекст, ответы и расход. Проверена установленная wheel-сборка и настоящий запуск через существующий OpenCode. Первые две проверки обнаружили неверную неявную привязку каталога в CLI. Исправление создаёт сессию с явным каталогом через API и проверяет привязку до отправки задания. Неудачные проверки и их расходы сохранены.",
        "",
        "[Инструкция обычного запуска и восстановления](../../integrations/opencode/TASK_SESSION.md). Прерывание, тайм-аут и гибель управляющего процесса проверены. При ошибке провайдера известные отдельные компоненты usage сохраняются как нижние границы, без двойного учёта; полный итог остаётся неизвестным. Все модельные admission-попытки, включая неудачные, отделены от основного сравнения в [общем журнале расходов](all-opencode-attempt-accounting.json).",
        "",
        "Историческая проверка ранее нашла 151 кандидатное пользовательское обращение без полного стартового снимка. Из этих записей частоту точных повторов восстановить нельзя. Смоук-проверки и 72 экспериментальные сессии не выдаются за обычный пользовательский поток. Новый сбор создаёт пригодные записи для последующего хронологического подсчёта.",
        "",
        "## Артефакты",
        "",
        "- [Первичный протокол](protocol.json) и [его хеш](protocol-seal.json).",
        "- [Независимая проверка](model-audit.json) и [все результаты](model-summary.json).",
        "- [Допуск задач](task-admission.json), [локальный опыт](local-comparison-v3/summary.json).",
        "- [Команды воспроизведения](REPRODUCE.md).",
        "- [Сверка всех обязательных результатов](completion-manifest.json).",
        "- Архивы runtime, исходников и всех сырых попыток: [output/practical-complete-20261115](../../output/practical-complete-20261115/).",
        "- Исходники, журналы и решения: runs/practical-complete-20261115/.",
        "",
    ]
    if (REPORT / "completion-manifest.json").exists():
        completion = json.loads((REPORT / "completion-manifest.json").read_text())
        checks = completion["checks"]
        lines += [
            "## Финальная проверка реализации",
            "",
            f"Общий прогон без Docker: {checks['general_non_docker']} passed. Отдельная проверка последней версии контура запуска и контрактов: {checks['latest_capture_and_contract']} passed. Docker: {checks['docker']} passed. Эти группы частично пересекаются; числа не складываются. Ruff прошёл, mypy проверил 56 файлов без ошибок. Финальный установленный пакет проверен настоящей модельной задачей; хеш wheel и привязка его исходников находятся в installed-task-accounting-admission.json.",
            "",
            "Изменения учёта и обычного запуска включены. Локальный кандидат отклонён; фактический worktree.py побайтно совпадает с baseline. Исходная версия модельного опыта сохранена отдельно от последующих исправлений команды. Исторические журналы и предыдущие неудачные проверки сохранены.",
            "",
        ]
    (REPORT / "README.md").write_text("\n".join(lines))
    summary = f"<p><b>Plain {q['plain']}/36 · CAMI {q['cami']}/36</b> — решения, прошедшие тесты</p><p>{html.escape(decision)}</p>"
    page = """<!doctype html><html lang="ru"><meta charset="utf-8"><style>
body{margin:0;color:var(--foreground);font:14px var(--font-sans);line-height:1.5}p{margin:8px 0 14px}
select{width:100%;padding:9px;border:1px solid var(--border);border-radius:var(--radius);color:var(--foreground);background:var(--background);font:inherit}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:20px}.plot{height:205px}h3{font-size:16px;margin:0 0 12px}.row{margin:12px 0}.label{display:flex;justify-content:space-between;gap:10px}.track{height:12px;background:var(--secondary);margin:5px 0;position:relative}.bar{height:12px;background:var(--chart-2);transition:width .2s}.cami{background:var(--chart-1)}small,.muted{color:var(--muted-foreground)}small{font-size:12px}.target{position:absolute;top:-3px;height:18px;border-left:2px dashed var(--warning)}@media(max-width:540px){.grid{grid-template-columns:1fr;gap:8px}}@media(prefers-reduced-motion:reduce){.bar{transition:none}}
</style><div id="cami-results">@@SUMMARY@@<label for="task-choice">Показать</label><select id="task-choice"><option value="all">Все 12 задач: основной показатель</option></select><p id="scope" class="muted"></p><div class="grid"><section><h3 id="time-title"></h3><div id="time-plot" class="plot" role="img"></div></section><section><h3 id="token-title"></h3><div id="token-plot" class="plot" role="img"></div></section></div><small>Token work исключает чтение кеша провайдера. Все пять компонентов сохранены отдельно. Проценты не являются фактическим денежным счётом.</small></div>
<script>
const data=@@DATA@@;
const root=document.getElementById('cami-results');
const choice=root.querySelector('#task-choice');
const fmt=n=>n===null?'unknown':new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(n);
for(const row of data.task_results){const o=document.createElement('option');o.value=row.task;o.textContent=row.repository+': '+row.task;choice.appendChild(o);}
function plot(id,values,unit,aggregate){
 const el=root.querySelector('#'+id);el.replaceChildren();
 const max=Math.max(1,...values.flatMap(v=>[v.value??0,v.max??0]));
 el.setAttribute('aria-label',values.map(v=>v.label+' '+fmt(v.value)+' '+unit).join('; '));
 for(const v of values){
  const row=document.createElement('div');row.className='row';
  const label=document.createElement('div');label.className='label';
  const name=document.createElement('span');name.textContent=v.label;
  const value=document.createElement('b');value.textContent=fmt(v.value)+' '+unit;label.append(name,value);
  const track=document.createElement('div');track.className='track';
  const bar=document.createElement('div');bar.className='bar'+(v.label==='CAMI'?' cami':'');bar.style.width=((v.value??0)/max*100)+'%';track.appendChild(bar);
  if(aggregate){const target=document.createElement('div');target.className='target';target.style.left=(90/max*100)+'%';track.appendChild(target);}
  const range=document.createElement('small');range.textContent=aggregate?'Пунктир: порог принятия 90%':v.min===null?'Нет полного расхода':fmt(v.min)+'–'+fmt(v.max)+' '+unit+' · наблюдаемый диапазон';
  row.append(label,track,range);el.appendChild(row);
 }
}
function update(){
 const aggregate=choice.value==='all';
 const row=data.task_results.find(r=>r.task===choice.value);
 root.querySelector('#scope').textContent=aggregate?'Plain = 100%. Для CAMI показана медиана 12 отношений средних по трём запускам. Меньше лучше.':'Среднее трёх свежих запусков каждого условия. Диапазоны не являются доверительными интервалами.';
 root.querySelector('#time-title').textContent=aggregate?'Полное время относительно plain':'Полное измеряемое время';
 root.querySelector('#token-title').textContent=aggregate?'Token work относительно plain':'Учитываемые токены';
 for(const [id,key,ratio,unit] of [['time-plot','time',data.median_paired_task_time_ratio,'с'],['token-plot','token_work',data.median_paired_task_token_work_ratio,'токенов']]){
  const values=['plain','cami'].map(arm=>({label:arm==='plain'?'Plain':'CAMI',value:aggregate?(arm==='plain'?100:ratio===null?null:ratio*100):row[arm][key+'_mean'],min:aggregate?null:row[arm][key+'_min'],max:aggregate?null:row[arm][key+'_max']}));
  plot(id,values,aggregate?'%':unit,aggregate);
 }
}
choice.addEventListener('change',update);update();
</script></html>"""
    page = page.replace("@@SUMMARY@@", summary).replace(
        "@@DATA@@", json.dumps(result, ensure_ascii=False).replace("</", "<\\/")
    )
    (REPORT / "chart.html").write_text(page)


if __name__ == "__main__":
    main()
