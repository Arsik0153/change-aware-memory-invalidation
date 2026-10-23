# Контракт поиска символов CAMI

`cami find SYMBOL --repo PATH` по умолчанию ищет определения Python в текущем
рабочем дереве, включая незакоммиченные изменения и untracked-файлы.
Явный `--revision HEAD` или SHA выбирает Git objects независимо от dirty checkout.
Формат по умолчанию `text` содержит пути, строки, читаемую сигнатуру, связи и
ограничения. Поиск не импортирует репозиторий и не меняет checkout или Git index.
Разрешение Git revision не требует сетевого доступа.

[Контракт worktree index](worktree_index_ru.md) описывает проверяемый capture,
исключения и постоянные поколения. Git-режим не использует product state.

## Аргументы и matching

`SYMBOL` и `--repo` обязательны. Отсутствие `--revision` выбирает worktree.
Повторяемый `--exclude PATH` исключает путь и его потомков только в worktree-режиме.
`--format` принимает `text` и `json`. Повторяемый `--source-root` задаёт
репозиторные POSIX-пути корней Python. Без этого аргумента корни равны `src`, `.`,
если snapshot содержит Python-файлы под `src/`, иначе `.`. Более глубокий корень
имеет приоритет. Явный `--source-root .` отключает автоматическое снятие `src/`.
Корни и имена модулей выводятся в JSON.

Matching чувствителен к регистру и не использует подстроки или fuzzy search.
Поддерживаются следующие идентификаторы:

- Простое имя `run_experiment` совпадает с последним компонентом qualname.
  Оно также находит методы и вложенные функции с таким именем.
- Qualname `C.method` и `outer.<locals>.inner` совпадает целиком внутри модуля.
- Полное имя `cami.engine.run_experiment` содержит имя модуля и qualname.
- `src/cami/engine.py:run_experiment` содержит точный путь и qualname.

Если строка совпадает с несколькими допустимыми идентификаторами, возвращаются
все определения. Путь с пробелами поддерживается при обычном shell quoting.
Путь в идентификаторе должен совпадать с репозиторным POSIX-путём без `./`.
Суффиксы вроде `engine.run_experiment` не сокращают `cami.engine.run_experiment`.

Индекс содержит функции, async-функции и методы. Классы, переменные, импортированные
re-export имена и TypeScript не являются результатами поиска этого этапа.
`not_found` означает отсутствие определения в поддерживаемой части выбранного
индекса. Ошибка разбора файла остаётся видна в `limitations` даже при `not_found`.

## JSON версии 2

Stdout содержит ровно один JSON document. Объекты сериализуются с отсортированными
ключами, списки matches, limitations и связей имеют стабильный семантический порядок.
Operational warnings и ошибки идут в stderr. Git-ответ воспроизводится побайтово.
Worktree-ответ воспроизводится без верхнего поля `observation`, которое содержит
интервал проверки и факт reuse. Эти значения не участвуют в content identity.

Поля верхнего уровня имеют следующий смысл:

- `schema_version` равен целому числу `2`. Research Record v1 не меняется.
- `query` сохраняет исходный запрос. `requested_revision` равен исходной строке
  revision в Git-режиме или `null` в worktree-режиме.
- `snapshot.kind` различает `git` и `worktree`. Git snapshot содержит `revision`
  с полным commit ID и `tree` с Git tree ID. Длина зависит от формата Git.
  Worktree snapshot содержит `snapshot_id`, `generation_id`, `base_commit`,
  `consistency: verified_readset`, capture `policy` и analyzer `fingerprint`.
  `base_commit` может быть `null` у нового репозитория без коммитов.
- `snapshot.source_roots` фиксирует корни индекса. `index_version`,
  `search_version` и `python_version` различают версии AST-индекса,
  продуктового поиска и Python. Search version равен `2`.
- `coverage` равен `complete` для успешно прочитанных и разобранных включённых
  Python-входов или `partial` при файловом ограничении. Исключённые пути и
  неподдерживаемые языки не входят в эту область покрытия.
- `absence_confirmed` равен `true` только при `not_found` и `coverage: complete`.
  Это отсутствие определения в поддерживаемой области поиска, не доказательство
  отсутствия runtime binding или определения на другом языке.
- `observation` равен `null` в Git-режиме. Для worktree он содержит
  `capture_started_at`, `verified_at` в UTC и `cache_reused`.
- `status` равен `found` при одном однозначном определении, `not_found` при пустом
  `matches`, `ambiguous` при нескольких определениях или неоднозначной привязке.
- `matches` содержит все определения, отсортированные по `path`, `qualname`,
  `start_line`, `end_line`. Повторные определения одного qualname сохраняются
  раздельно со своими строками. Условное определение тоже может дать
  `ambiguous`, даже если синтаксический результат один.
- `graph_complete` всегда равен `false`.
- `limitations` содержит объекты `{code, path}`. Для общего ограничения `path`
  равен `null`. Для пропущенного файла указан его репозиторный путь.
- `unresolved` содержит отсортированные объекты `{path, qualname}` всего выбранного
  индекса. Это консервативные сигналы существующего resolver, включая присваивания,
  внешние импорты и неизвестные вызовы. Это не перечень только проблем найденного
  символа. `qualname: null` обозначает модуль. `global_unresolved` означает наличие
  такого модульного сигнала. Значение `false` не доказывает полноту графа.

Каждое определение содержит `path`, `qualname`, `module`, `qualified_name`,
`node_kind`, `start_line`, `end_line`, `signature`, `signature_text`, `ambiguous`,
`incoming`, `outgoing`. Строки нумеруются с единицы и включают обе границы.
Начало соответствует строке `def`, а не предшествующему декоратору.
`node_kind` равен `function` или `method`. `signature` сохраняет AST-контракт
существующего индекса:

- `parameters` содержит `name`, `kind`, `default_ast`, `annotation_ast`.
  Отсутствующее значение равно `null`. AST default для литерала `None` является
  строкой `Constant(value=None)` и отличается от отсутствующего default.
- Виды параметров равны `positional_only`, `positional_or_keyword`,
  `var_positional`, `keyword_only`, `var_keyword`.
- `returns_ast`, `decorators_ast`, `is_async` сохраняют синтаксическую информацию.
- `signature_text` отображает нормализованный Python-заголовок без тела и
  завершающего двоеточия, включая type parameters Python 3.12.
  Существующий AST-контракт в `signature` не содержит отдельного поля type parameters.

Связь содержит `source`, `target`, `relation`, `origin`. Оба конца используют
`{path, qualname}`. Направление всегда от потребителя к зависимости.
`incoming` содержит связи с найденным определением в `target`, `outgoing`
содержит связи с ним в `source`. `relation` равен `calls` или `imports`, `origin`
равен `static`. Модульный импорт имеет `source.qualname: null`.
Одинаковые связи удаляются. Порядок фиксирован по путям и qualname обоих концов,
затем по relation. У связи нет диапазона call site и идентичности отдельного
повторного определения. При неоднозначном qualname связь относится к этому
идентификатору, а не к доказанному runtime binding.

Код завершения равен `0` для всех трёх search statuses. Отсутствие и неоднозначность
являются результатами запроса. Некорректный repo, revision, корень, пустой запрос
или формат дают `2` и понятный stderr без traceback. Недоступный Git даёт `3`.
Прерванная или неожиданно незавершённая операция даёт `4`.

## Границы статического графа

Поиск использует существующий Python AST-индекс и его связи локальных прямых
вызовов и явных модульных импортов. Продуктовый адаптер дополнительно разрешает
прямой вызов через локальный `from ... import ...`, включая relative import и
`as`, если имя не перекрыто и цель однозначна. Это позволяет показать вызов
`run_experiment` из `cli.main`. Условный импорт даёт возможную статическую связь,
а не гарантию выполнения ветки. Функциональный `imports` edge для этого дополнения
не создаётся. Консервативный `unresolved` исходного индекса сохраняется.
Relative import выше корня пакета не создаёт связь, в том числе с корневым
`__init__.py`. Вызывающая функция остаётся в `unresolved`. Такой импорт также
сохраняет неоднозначность при конкурирующем локальном импорте того же имени.

Исходные `build_index`, selector и validator не меняются. Дополнение локальных
импортов используется только поиском. Общие ограничения всегда перечислены
машинными кодами:

- `python_functions_and_methods_only` ограничивает виды определений.
- `static_graph_is_partial` запрещает трактовать пустой список incoming как
  доказательство отсутствия вызовов. Граф не вычисляет все атрибутные вызовы,
  методы через экземпляры, callbacks, re-exports, динамические импорты,
  monkeypatching, runtime dispatch или межъязыковые зависимости.
- `calls_may_include_nested_scopes` отмечает, что исходный индекс может приписать
  вызовы вложенной функции внешнему определению. Связи являются кандидатами.
- `unresolved_is_conservative` объясняет сохранение сигналов исходного resolver.
- `runtime_binding_not_evaluated` отмечает отсутствие исполнения и анализа
  достижимости. Анализ не доказывает порядок импортов и присваиваний.

Граф может содержать как пропущенные, так и ложноположительные связи.
В частности, исходный resolver приближённо учитывает lexical binding при
перекрытии модульного определения локальным импортом. `found` характеризует
результат поиска определения и не подтверждает корректность всех его связей.
Вызовы непосредственно в теле модуля не индексируются.

Файловые ограничения включают `parse_error`, `file_too_large`,
`symlink_unsupported`, `submodule_unsupported`, `lfs_unsupported`. В Git-режиме превышение
лимита 2 MiB и неподдерживаемые объекты не замещаются содержимым рабочего дерева.
Worktree также сообщает `special_file_unsupported` без чтения FIFO или устройств.

## Воспроизводимые acceptance checks

Команды запускаются из корня CAMI после `uv sync --locked --extra dev`:

```bash
uv run cami find run_experiment --repo . --revision HEAD
uv run cami find cami.engine.run_experiment --repo . --revision HEAD --format json > /tmp/cami-find.json
uv run python -m json.tool /tmp/cami-find.json > /tmp/cami-find-pretty.json
uv run cami find missing_cami_symbol --repo . --revision HEAD --format json
uv run cami find run_experiment --repo . --revision invalid-cami-ref --format json
uv run pytest -q tests/test_symbol_search.py tests/test_index.py
```

Первый запрос выводит `found: run_experiment`, путь `src/cami/engine.py` и связь
`src/cami/cli.py:main --calls--> src/cami/engine.py:run_experiment`.
Qualified запрос возвращает `status: found`. Для `missing_cami_symbol` статус
равен `not_found`, `matches` равен `[]`, код завершения равен `0`.
Для invalid revision stdout пуст, stderr содержит `input error`, код равен `2`.

`tests/test_symbol_search.py` запускает настоящий CLI через отдельные процессы.
Тесты создают изолированные Git-истории с путями с пробелами. Сценарии покрывают
точный и qualified поиск, дубликаты в модулях и одном scope, условные определения,
rename и delete на разных revision, сохранность staged и unstaged содержимого,
прямые связи обоих направлений, локальные импорты и перекрытие имён, parse errors,
разные `PYTHONHASHSEED`, ошибочные входы и собственный CLI CAMI.

## Граница продукта и research

`FindResult` и persistent manifest принадлежат `cami.product`. Research records,
selector и протоколы не расширяются продуктовыми типами. `Node(path, qualname)`
остаётся идентификатором графа, а диапазон строк различает повторные определения.
Продуктовый resolver версионируется отдельно. Неизменяемый `CodeIndex` строится из
Git blobs либо из захваченных bytes рабочего дерева через один адаптер.
Worktree token `worktree:<snapshot_id>` остаётся внутри продуктового адаптера и
не подставляется в commit-поля research records.

TypeScript, product memory и watch не входят в этот этап. Отсутствующий Node
или TypeScript toolchain не мешает Python-поиску. Конфигурация target-репозитория
не исполняется. Research `cami run` сохраняет прежний интерфейс.
