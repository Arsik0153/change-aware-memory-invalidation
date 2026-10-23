# Независимая разметка подготовленного набора

Готовый пакет находится в `runs/next-stage-20261001/main-ready/`. Это кандидаты, а не допущенный cohort. В нём нет labels и parent receipts. CAMI не запускал held-out policies.

## Что передать разметчикам

Передайте `annotation/packets.jsonl`, каталог `annotation/sources/`, `annotation/probes/` и пустые формы. Не передавайте каталоги policy runs, selections, validations или сравнение политик.

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
.venv/bin/python scripts/prepare_main.py import-parent \
  --dataset runs/next-stage-20261001/main-ready/dataset.json \
  --annotations /absolute/path/to/completed-parent-reviews.jsonl \
  --out runs/main-parent-reviewed-001
```

Команда принимает один окончательный независимый ответ на claim. Сохраните ответы второго человека и протокол разрешения разногласий отдельно до выбора окончательного parent-подтверждения. Импорт не заменяет adjudication. Неподтверждённый parent не становится примером устаревания. Команда сохраняет все переданные исходные строки, но создаёт receipt только для supported. Для behavior нужен независимый test receipt, для prose человеческий review. Контейнерный preflight остаётся отдельной проверкой допуска.

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

Труд разметчиков, минуты adjudication, расходы подготовки provenance и восстановления образов записываются отдельно. Никаких независимых человеческих ответов в текущем пакете ещё нет.
