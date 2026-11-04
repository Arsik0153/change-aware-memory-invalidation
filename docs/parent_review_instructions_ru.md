# Независимый parent-review до просмотра child

Этот пакет содержит только parent-исходники, frozen claims/probes и пустые формы.
Он не содержит child_commits, child evidence, policy outputs, готовых ответов или
результатов автоматических environment diagnostics. Идентичность репозитория
и parent commit остаётся видимой. Claims являются кандидатами, не доказанной истиной.

Координатор выдаёт каждому человеку отдельную неизменённую копию пакета.
Первый reviewer заполняет primary_form.jsonl; второй — second_form.jsonl независимо
от первого. В second_form сохранены ранее назначенные 126 parent-заданий, новая
случайная выборка не проводилась. Не показывайте чужие ответы или child-пакет
до завершения parent-review. Наличие формы не означает выполненную разметку.

Для каждой строки найдите claim_id в packets.jsonl, прочитайте text, predicate и
scope. Посмотрите source_evidence на parent_commit. Пути evidence_path считаются
от корня этого пакета. Сравните утверждение с исходником независимо от нормализатора
CAMI. Для behavior нужно отдельно проверенное исполнение frozen probe; не меняйте
его assertion по результату. Автоматическое наблюдение CAMI не является независимым
подтверждением. Ошибка среды не доказывает, что утверждение ложно.

Заполните реальные annotation_id, annotator_id, annotator_kind, independent, label,
evidence, confirmation_type и annotation_minutes. Не оставляйте пустое evidence;
не выдумывайте фактическое время. Разрешённые label — supported, contradicted,
uncertain. Полные типы описаны в annotation_guide.md. Верните исходные ответы
координатору без слияния с ответами второго человека.

Координатор сохраняет обе исходные формы. Для их совместного импорта используйте
`import-parent-batch`: он сохраняет каждый ответ и всю историю adjudication.
Старый `import-parent` по-прежнему принимает одно решение на claim. Нельзя удалять
один ответ для создания видимости согласия. Неразрешённое разногласие не создаёт
receipt. Поведенческие положительные подтверждения, включая adjudication,
требуют independent_test; простой human_review их не допускает.

Если человек самостоятельно исполнил frozen probe, укажите annotator_kind=human
и confirmation_type=independent_test. Тип метода не меняет авторство. Если среду
восстановить не удалось, сохраните uncertain с evidence и фактическим методом
review. Такой ответ сохраняется без receipt; ошибка среды не означает contradicted.

Импорт parent reviews сам по себе не завершает cohort admission, provenance review
или final protocol freeze. Child-разметка и evaluation остаются следующими этапами.

## Импорт координатором

После получения настоящих ответов сформируйте JSON с `schema_version: 1`, массивом
`annotations` из всех исходных ответов и массивом `adjudications` (пустым, если
согласование не проводилось). Формат каждой записи и цепочки описан в
annotation_guide.md. Импортировать пустые формы нельзя. Сохраните оригинальные
файлы от каждого человека отдельно; importer дополнительно сохраняет точные bytes
совместного входного JSON и нормализованные записи, но не получает исходные файлы
от каждого человека автоматически.

```bash
.venv/bin/python scripts/prepare_main.py import-parent-batch \
  --dataset runs/main-restored-20261029/ready/dataset.json \
  --reviews /path/to/actual-parent-reviews.json \
  --out runs/parent-reviewed-NEW
```

Output должен быть новым каталогом. Для добавления ответов или нового adjudication
используйте исходный unreviewed dataset и новый полный batch, включающий все прежние
ответы и всю цепочку adjudication. Повторный импорт поверх reviewed dataset запрещён,
включая наборы, где были только uncertain ответы и не появилось ни одного receipt.

Importer проверяет parent commits, preview, неизменность claims, probes и экспортированных
parent source files относительно подготовленного packet. Передача child decisions,
synthetic confirmations, повторного ответа того же автора или неполной цепочки
adjudication отклоняется до создания output. Эти проверки сохраняют согласованность
локальных материалов; они не удостоверяют личность человека или независимость review.

Полный denominator выводится из всех candidate parent claims, а не из полученных
ответов. Если передан annotation_population, он должен точно совпасть с этим набором.
Отчёт содержит отдельно общий охват второго human-review и выполнение назначенных
126 parent-заданий: два произвольных ответа на другие claims не закрывают назначение.
Agreement считается до adjudication; unresolved и annotation/adjudication minutes
сохраняются отдельно. Новые файлы:

- `parent_raw_annotations.jsonl` — все исходные решения;
- `parent_adjudications.jsonl` — полная история согласования;
- `parent_resolved_decisions.jsonl` — только разрешённые parent decisions;
- `parent_review_status.json` — coverage, unresolved, hashes и ограничения;
- `groups/*/parent_review/*.json` — evidence разрешённого решения и его источники.

Наличие supported receipts или достижение coverage не меняет preview и не разрешает
held-out execution. Cohort admission, provenance и protocol freeze остаются отдельными.

## Автономный просмотр свидетельств

Новый экспорт содержит `review.html`: откройте файл после распаковки ZIP.
Сервер, сеть и установка CAMI разметчику не нужны. Найдите claim_id через Ctrl+F;
страница показывает полный claim, назначение второго review и ссылки на parent
исходники с номерами строк, исходные байты и frozen probe. Ограничения отсутствующих
свидетельств показаны явно. Исходники отображаются как текст, а не исполняются.
UTF-8 display заменяет недекодируемые байты; оригинальные файлы сохраняются побайтно.
Это средство чтения: ответы по-прежнему заполняются отдельно в JSONL.

Воспроизводимое создание и техническая проверка нового пакета:

```bash
.venv/bin/python scripts/export_parent_review.py \
  --prepared runs/main-restored-20261029/ready \
  --out runs/parent-review-NEW
.venv/bin/python scripts/check_parent_review.py \
  --package runs/parent-review-NEW \
  --out reports/parent-review-NEW-audit.json
```

Проверка контролирует хеши, локальные ссылки и HTML anchors, отсутствие активных
элементов, соответствие заданий и пустоту ответов. Она не проверяет истинность
утверждений или независимость людей. Результат запуска 4 ноября:
`reports/research-20261104/parent-viewer-audit-v2.json`.
Готовый локальный архив: `output/parent-review-20261104.zip`.
