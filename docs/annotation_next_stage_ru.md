# Независимая разметка подготовленного набора

Исторический пакет находился в `runs/next-stage-20261001/main-ready/`. На текущей машине восстановленный пакет находится в `runs/main-restored-20261029/ready/`; [отчёт и архив для разметчиков](annotation_restoration_2026-10-29.md). В командах ниже заменяйте исторический путь на восстановленный. Это кандидаты, а не допущенный cohort. В нём нет labels и parent receipts. CAMI не запускал held-out policies.

## Что передать разметчикам

Для первого этапа используйте [parent-only пакет и инструкцию](parent_review_instructions_ru.md),
чтобы parent reviewer не видел child revisions. После завершения parent-review
передайте `annotation/packets.jsonl`, каталог `annotation/sources/`, `annotation/probes/` и пустые формы. Не передавайте каталоги policy runs, selections, validations или сравнение политик.

- `primary_form.jsonl` содержит 1530 заданий. Из них 630 относятся к parent, 600 к child основных пар и 300 к child replay.
- `parent_confirmation_form.jsonl` содержит только 630 parent-заданий.
- `child_form.jsonl` содержит 900 child-заданий.
- `second_form.jsonl` содержит 306 заданий для второго человека. Среди них 126 parent, 120 main child и 60 replay child.
- `main_population.jsonl` фиксирует знаменатель 600 child-заданий основного набора.
- `replay_population.jsonl` фиксирует 300 child-заданий replay.
- `population.jsonl` содержит объединение только child-заданий, без parent. Не используйте общий объём 1530 как знаменатель покрытия child-разметки.

Второй человек получает свою копию исходного пакета и не видит ответы первого до завершения независимой работы. Назначение 20% заданий ещё не означает, что два человека их выполнили. `assignments.json` фиксирует seed и выбранные claims. Все ревизии выбранного replay claim входят в задание второго человека.

## Как заполнить одну строку

Прочитайте неизменяемые claim, predicate и scope. Проверьте точный path и qualname на указанном commit. Структурная сигнатура включает defaults, annotations, decorators и async. Она не является `inspect.signature` работающей программы.

Для `symbol_exists` и `signature_equals` независимо проверьте исходник. Генератор использовал общую с CAMI нормализацию сигнатур, поэтому его JSON не является доказательством своей правильности. Не используйте ответ CAMI как эталон.

Для behavior утверждается только один замороженный вход и ожидаемый выход. Не изменяйте assertion после просмотра child. Сохраните команду, digest контейнера и журналы повторений. Ошибка импорта, timeout или несовместимая среда дают uncertain, а не contradicted. Для pytest стандартный runner сейчас отказывает при конфликте с уже загруженным `_pytest`; нельзя заменить исторический код установленным pytest. Нужен отдельно проверенный способ запуска исторического пакета.

Для prose проверьте ровно заявленную строку docstring, без предположения о поведении функции. Такие claims исключаются из текущего offline cohort, поскольку M6 не выполняется.

Заполните настоящий `annotator_id`, уникальный `annotation_id`, `annotator_kind`, `independent`, `label`, ссылки `evidence`, `confirmation_type` и фактически потраченное `annotation_minutes`. Разрешённые child labels: supported, contradicted, uncertain. Пустые `null` в форме намеренно не проходят импорт. Не заполняйте их автоматически положительными ответами. Типы и формат приведены также в `docs/annotation_guide.md`.

## Импорт подтверждений parent

После независимого подтверждения импортируйте завершённые parent-строки в новый каталог:

```bash
.venv/bin/python scripts/prepare_main.py import-parent-batch \
  --dataset runs/main-restored-20261029/ready/dataset.json \
  --reviews /absolute/path/to/completed-parent-review-batch.json \
  --out runs/main-parent-reviewed-001
```

Batch содержит JSON с annotations всех ответивших и adjudications всей истории
согласования. Importer сохраняет каждый исходный ответ; нельзя удалять несогласный
ответ или подменять двух авторов одним окончательным reviewer. Неразрешённое
разногласие не создаёт receipt. Полный denominator берётся из candidate population;
отдельно проверяется выполнение назначенных вторых reviews. Подробный формат и
способ повторного импорта — в parent_review_instructions_ru.md. Неподтверждённый
parent не становится примером устаревания. Для supported behavior нужен независимый
test, для prose — человеческий review. Контейнерный preflight остаётся отдельной
проверкой допуска.

## Импорт child labels

Соберите JSON следующей формы из реально заполненных строк:

```json
{
  "schema_version": 1,
  "annotations": [],
  "adjudications": [],
  "annotation_population": []
}
```

Пустой пример не является готовым импортом. В `annotations` поместите ответы обоих людей с разными ID. В `annotation_population` поместите строки `main_population.jsonl` для отдельного main-импорта или `replay_population.jsonl` для replay. Parent-строки сюда не входят. При разногласиях используйте формат Adjudication из `schemas/AnnotationImport.json`. Не удаляйте первичные ответы.

```bash
.venv/bin/cami annotate-import \
  --input /absolute/path/to/completed-main-child-import.json \
  --out runs/main-labels-import-001
.venv/bin/cami annotate-import \
  --input /absolute/path/to/completed-replay-child-import.json \
  --out runs/replay-labels-import-001
```

Импорт сохранит original_import, raw_annotations, adjudications, labels и отчёт о согласии до adjudication. Проверяйте фактическую долю двух независимых человеческих ответов, а не размер второй формы.

## Что требуется перед freeze

1. Подтвердите parent и окончательный cohort. Опубликуйте исключения с причинами до запуска политик. Не заменяйте исключённые claims после просмотра child labels.
2. Проверьте provenance на parent. Сейчас она честно помечена `known_incomplete=true`; оставление этого флага может снова привести к проверке всего cohort.
3. Подготовьте закреплённые образы для исторических behavior-проверок. Click smoke-пилот не доказывает работоспособность новых probe на всех выбранных историях Requests и pytest.
4. Оставьте prose вне offline cohort. Без prose основной набор имеет не более 540 кандидатов, а при недоступных behavior не более 480. Это меньше исходного плана около 600. Не дополняйте его после результатов ради значимости; любое расширение требует заранее записанного exploratory протокола.
5. Зафиксируйте окончательные конфигурации семи policies, глубины и варианты provenance. Уберите `preview=true` только после проверки допуска и сред. Все variants одного cohort используют те же claims и receipts.
6. Выполните `cami freeze --dataset FINAL_DATASET --out NEW_PROTOCOL_DIR`. Только этот финальный seal используйте как `frozen_protocol_path`. `preparation_hashes.json` является записью подготовки, не разрешением held-out evaluation.
7. Выполните заранее объявленные held-out запуски и отдельный scorer. Не меняйте отбор после просмотра их ответов. Chronological, enriched и каждая replay-последовательность анализируются отдельно.

## Аудит provenance до независимого эксперимента

Аудит выполняется на parent snapshot и пишет отдельный каталог. Он не читает child revisions,
labels, receipts, selections или результаты policies и не меняет исходные claims/provenance:

```bash
.venv/bin/python scripts/prepare_main.py audit-provenance \
  --dataset runs/next-stage-20261001/main-ready/dataset.json \
  --out runs/main-provenance-audit-001
```

`provenance_audit.jsonl` содержит полный неизменённый claim с текстом, predicate и scope,
subject, исходную provenance, записанные anchors и явные зависимости. `automatic_checks`
отделены от `independent_review`. Для зависимости проверяются оба конца, включая точные
qualname. Существование концов не подтверждает саму связь. Пустой список зависимостей
фиксируется как исходный факт и сам по себе не считается дефектом structural claim 1.1.

Проверки используют production parser CAMI и не являются независимым oracle. Аудит
сохраняет конкретные unresolved nodes, ограничения parser и global unresolved для parent
в `groups[].snapshot_index` манифеста. Для claim отдельно указаны ограничения и unresolved
в его записанной поддержке. Эти наблюдения не добавляются автоматически в явные зависимости
и не меняют правило отбора 1.1.

Исходные claims/provenance сохраняются побайтно в `groups/RUN/source_inputs/`. Прочитанные
parent blobs сохраняются без перекодирования в `groups/RUN/sources/`; запись наблюдения
содержит путь и SHA-256, относительный к `source_evidence_base`. Для behavior сохраняются
байты и ожидаемый/фактический hash frozen probe в `groups/RUN/probes/`, без исполнения.
Манифест содержит hashes файлов пакета, реализации аудита и индексатора, а также index version.

Проверки существования символа, хеша blob и строкового диапазона подтверждают только
записанные данные. Они не доказывают, что все опорные участки и зависимости перечислены.
Диапазон строк служит отображению, не идентичности anchor. Односторонняя граница или
диапазон, не покрывающий всё определение, допустимы. Выход указанной строки за пределы
parent blob фиксируется как ошибочное наблюдение; фактические строки определения
сохраняются отдельно от указанных границ.
В IMPLEMENTATION_SPEC.md `known_incomplete=false` означает отсутствие известных пропусков,
а не доказанную полноту. Протокол не задаёт процедуру закрытия уже известных пропусков.
Поэтому исходная provenance остаётся неизменной, а консервативный флаг аудита остаётся
`known_incomplete=true`, включая после положительного независимого review. Исходный флаг
и причины отдельно сохранены в `source_known_incomplete` и `source_unresolved_reasons`.

`review_form.jsonl` является пустой формой независимого review. Не меняйте `claim_id`,
`parent_commit`, `claim_sha256` и `provenance_sha256`. Эти поля связывают ответ с точной
версией claim и provenance; ответ на предыдущую версию не принимается. Заполните
`reviewer_id`, установите `independent: true`, укажите `status` (`confirmed`, `incomplete`
или `uncertain`), списки `confirmed_dependencies` и `omitted_dependencies`, evidence и заметки.
Статус `confirmed` означает оценку записанной поддержки человеком и не является ни label
истинности claim, ни разрешением снять флаг неполноты. Parent receipt подтверждает истинность
claim и не заменяет этот отдельный review поддержки.

Оба списка зависимостей используют исходную структуру Dependency с полями `from`, `to`,
`relation`, `origin`. Подтверждённые связи должны присутствовать в исходной provenance.
Пропущенные связи сохраняются в ответе, но не дописываются в исходную provenance автоматически.
При `status=confirmed` список пропущенных связей должен быть пустым. `evidence` содержит
непустой список относительных путей к реальным parent-only файлам, относительно каталога
завершённого JSONL. Абсолютные пути, выход через `..` и свободный текст вместо файлов
не принимаются. Например, `"evidence": ["evidence/parent-review.txt"]`.
Передайте реально полученные строки в JSONL и импортируйте их в новый каталог:

```bash
.venv/bin/python scripts/prepare_main.py import-provenance-review \
  --audit runs/main-provenance-audit-001/audit_manifest.json \
  --reviews /absolute/path/to/completed-provenance-reviews.jsonl \
  --out runs/main-provenance-reviewed-001
```

Импорт сохраняет точные исходные байты ответов в `raw_provenance_reviews.jsonl` и копирует
байты evidence в `review_evidence/` с hashes и исходными ссылками. Root и group audit rows
синхронизируются; оригинальный каталог аудита сохраняется. При частичном импорте остальные
claims остаются `unreviewed`. Пустые формы, ответы без независимого решения, неизвестные
или повторные claims и несовпадающие hashes отклоняются до создания output. Изменённые
файлы исходного пакета аудита также отклоняются. Output не может находиться внутри input.

Для архитектуры рассмотрены расширение `Provenance`/`ParentReceipt` и отдельный пакет
аудита. Выбран отдельный пакет с реализацией в `src/cami/provenance_audit.py`, подключённый
через `scripts/prepare_main.py`. Так автоматические наблюдения и независимые ответы остаются
различимы, а schemas policy inputs, claims, predicates и policies сохраняют прежнее значение.
До утверждения процедуры закрытия пропусков пакет фиксирует оставшуюся блокировку и не
допускает cohort автоматически. Held-out policies, child labels и freeze эти команды не запускают.

Труд разметчиков, минуты adjudication, расходы подготовки provenance и восстановления образов записываются отдельно. Никаких независимых человеческих ответов в текущем пакете ещё нет.
