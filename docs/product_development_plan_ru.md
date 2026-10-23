# План развития CAMI до продукта

План задаёт пять последовательных этапов по [vision](final_product_vision.md).
Статусы относятся к продуктовой работе, а не к исследовательским M0–M5.

## Исходное состояние

На чтении 2026-10-23 HEAD равен `dcd67fa`, ветка `main`, рабочее дерево чистое.
Ветка опережает `origin/main` на два коммита. Это наблюдение до параллельной работы.
Это исторический baseline. Реализация stage1 завершена коммитом
`dea30002cdce4aa5e859d0a3ff6a5124c32bdbe4`. Независимый acceptance этого SHA получил `FAIL`. Fix завершён на
`499acfad48b2d62e37b0f57a3b051bc09eaf847b`; независимый review r2 дал `PASS`, stage1 принят в согласованном scope Git Python find.
[Research status](implementation_status.md) описывает исследовательский прототип.
[Синтетическая демонстрация](structural_closure_demo_ru.md) описывает отдельную проверку structural closure.

Существующий `cami run --config ... --out ...` выполняет research experiment.
Его контракт сохраняется. Имя `cami run` для фонового процесса в vision является примером.
Имя watcher-команды определяется на этапе 5 без переопределения research CLI.
MCP остаётся возможным расширением. Первый агентский интерфейс использует CLI.

## Последовательность и acceptance

Planned порядок теперь ведёт к полезному TS/TSX Next.js path до product memory и watcher.
Stage1 принят после независимого review r2 на exact SHA ниже. По явному решению родителя
параллельная implementation допускается в изолированных app-owned worktrees БЕЗ КОММИТОВ
(standing order 13). Stage2 уже `in_progress`, `not_accepted`. Read-only design work
может идти заранее. Интеграция stage2 в исходную main выполняется после acceptance stage1:
свежий parent-assigned integrator переносит проверенный patch, сохраняет fix stage1,
повторяет acceptance и последовательно коммитит main.
Архитектурные evidence могут уточнить задачи и контракты. Причина и новый acceptance
попадают в [журнал решений](../reports/orchestration/decisions.tsv) до реализации изменения.
Контракты этапов задают целевое поведение. Точные флаги подтверждает writer.

### 1. Git symbol search через `cami find`

Статус реализации `implementation_completed`. Исторический acceptance исходного SHA — `failed`.
Fix завершён (`completed`) на `499acfad48b2d62e37b0f57a3b051bc09eaf847b`;
acceptance этого SHA `accepted` после независимого `PASS` r2. Это принятие Git Python find, а не всего продукта из vision.
Writer доставил итоговый отчёт для `dea30002cdce4aa5e859d0a3ff6a5124c32bdbe4`.
Его [implementation evidence](implementation_status.md#2026-10-23-first-product-stage-git-symbol-search)
фиксирует `345 passed, 4 deselected`, Ruff и strict mypy. Эти результаты не означают acceptance.
Независимый reviewer той же `gpt-6.1-sol` завершил проверку этого SHA с `FAIL`.
Исторический finding P2 относится к `dea30002cdce4aa5e859d0a3ff6a5124c32bdbe4:src/cami/symbol_search.py:120`.
Некорректный relative import выше package root создавал две ложные входящие связи в корневой `__init__.py`.
Legacy graph их не содержал, product adapter добавлял обе.
Evidence сохранены в `/tmp/cami-independent-review/verify.py`, `output.txt` и `results.json`.
Runtime handles и exact-SHA verdict указаны во внешнем store в `runtime-handles.json`
и `stage1-review.json`; прежний FAIL на `dea30002cdce4aa5e859d0a3ff6a5124c32bdbe4` сохранён.
По переданному terminal fix receipt исходный repro изменился с 2 ложных incoming до 0,
`unresolved` и `limitations` не изменились; full `372 passed, 4 deselected`, Ruff и mypy прошли.
Это результаты writer, не независимый повтор полной suite. Свежий reviewer r2 той же настроенной модели
дал `PASS` для exact `499acfad48b2d62e37b0f57a3b051bc09eaf847b`, actionable findings нет.
Он выполнил 27 CLI-вызовов, включая старый baseline, 59 targeted tests и 3 doc CLI.
Исходный repro независимо дал 2 ложных incoming до исправления и 0 после.
`unresolved`, `limitations`, `global_unresolved` сохранены; `graph_complete=false`.
Проверен собственный `run_experiment` с incoming от `cli.main`, в согласованном scope.
Evidence: `/tmp/cami-independent-review-r2/{verify.py,results.json,targeted.txt,cli.txt}`.
Exact-SHA receipt `stage1-review-r2.json` во внешнем store связывает verdict с прямым terminal T3 report.
Этот docs drain читает evidence и не повторяет продуктовые проверки. Полнота графа и всё vision не приняты.

Задачи этапа:

- Новый subcommand ищет точное имя символа в выбранной Git revision реального репозитория.
- Результат содержит идентичность символа, путь, диапазон строк, revision и доступные связи.
- Версионируемый JSON имеет стабильную структуру и детерминированный порядок результатов.
- Контракт различает отсутствие совпадений, неоднозначность, неподдерживаемый анализ и ошибку входа.
- Поддерживаемое подмножество Python описано явно. Неполные связи не объявляются полными.

Acceptance этапа:

- Установленный `cami find` вызывается отдельным CLI-процессом на временном Git-репозитории.
- Поиск существующего символа возвращает ожидаемые определения из выбранной revision.
  Проверка диапазонов использует фактические Git blobs.
- Повторный запрос даёт тот же JSON. В нём есть версия схемы и разрешённый commit ID.
- Случаи одинакового имени в разных модулях, отсутствующего имени, неверной revision
  и parse error имеют документированные результаты и коды завершения.
- stdout в JSON-режиме содержит только JSON. Диагностика идёт в stderr.
- Поиск не меняет checkout, HEAD или Git index. Старые research-команды сохраняют свой контракт.
- Отдельный read-only reviewer проверяет diff и CLI evidence после окончания записи writer.

### 2. Worktree snapshots и persistent index

Статус реализации `in_progress`, acceptance `not_accepted`. Зависимость интеграции от acceptance этапа 1.
Implementation запущена параллельно в T3 isolation worktree, БЕЗ КОММИТОВ.
Проверенный patch и evidence передаются свежему parent-assigned main integrator; он сохраняет
исправление stage1, повторяет acceptance после переноса и коммитит в исходной main.

Задачи этапа:

- Модель snapshot описывает repository, worktree, базовый HEAD, фактическое содержимое файлов
  и версию индексатора. Сохранённый index привязан к конкретному snapshot.
- Snapshot включает новые незакоммиченные файлы, modified и deleted.
  Контракт явно различает staged и unstaged изменения и задаёт правила ignore и symlink.
- Persistent index переиспользует неизменившееся содержимое и пересчитывает затронутые части.
- Незавершённая сборка остаётся отдельным поколением. Публикация готового поколения атомарна.
- Изменение файла во время чтения обнаруживается. Несогласованный snapshot повторяется
  или даёт явную ошибку вместо публикации смеси разных состояний.

Acceptance этапа:

- Реальный CLI на временном worktree видит добавленный символ, изменённую сигнатуру
  и удалённый файл без commit. Рабочие файлы и Git index остаются неизменными.
- Два worktree одного repository имеют отдельную идентичность и не подменяют результаты друг друга.
- После перезапуска процесса поиск читает сохранённый index и возвращает то же поколение.
- Прерывание до публикации оставляет предыдущее поколение читаемым.
  Параллельный читатель получает целое старое или целое новое поколение.
- Повреждённый cache, неподдерживаемая версия и недоступный файл дают явный результат.
  Они не превращаются в пустой успешный index.
- Изменение исходника во время сборки не публикует поколение с ложной идентичностью содержимого.

### 3. JS, TS, TSX и полезный сценарий Next.js

Статус core `in_progress`, acceptance `not_accepted`; CLI integration `pending` после этапа 2.
Trusted compiler core для JS, JSX, TS и TSX и Python bridge запущены в отдельном app-owned worktree
БЕЗ КОММИТОВ. Scope ограничен новыми модулями и component handoff. Полный Next.js-сценарий
через `cami find`, worktree snapshots и persistent index остаётся отдельной задачей после интеграции этапа 2.

Задачи этапа:

- Отдельный архитектурный разбор выбирает parser и модель модулей для JS, TS и TSX.
  При необходимости он уточняет ранние контракты с записью evidence в журнале.
- Поддержка охватывает определения, imports, exports и re-exports в заявленном подмножестве.
  Конфигурация path aliases учитывается явно. Dynamic resolution сохраняет неопределённость.
- Зафиксированный небольшой Next.js-проект содержит route, компонент TSX и общую функцию.
  Fixture не использует held-out research inputs.

Acceptance этапа:

- Агент через shell находит `createUser` в Next.js-сценарии и получает определения,
  известные зависимости, места использования и ограничения анализа в JSON.
- Незакоммиченная правка общей функции обновляет поиск через worktree snapshot и persistent index.
  Результат указывает фактический snapshot и ограничения анализа.
- Rename, re-export, TS path alias и TSX имеют проверяемые результаты.
  Unsupported dynamic import и parse error не дают заявления о полном графе.
- Сценарный драйвер показывает реальные CLI-команды, их JSON-ответы и соответствие файлам Next.js fixture.
- Сценарий воспроизводится по зафиксированным версиям инструментов.
  Он демонстрирует работоспособность, но не доказывает ускорение агента на любых проектах.

### 4. Product memory и lifecycle structural claims

Статус `pending`. Зависимость от этапа 3.

Задачи этапа:

- Product memory хранит structural claims о существовании символа и синтаксической сигнатуре.
  Схема отделяет состояние знания от свежести index и от доступности проверки.
- Каждая запись имеет claim ID, точный subject, provenance, исходный snapshot,
  evidence и последний действительно проверенный snapshot.
- Переход snapshot выбирает затронутые claims по subject, известным связям и неопределённости.
  Неизменившееся знание может переноситься с прежним `last_checked`, без фиктивной перепроверки.
- Поддерживаемая проверка различает `supported`, `contradicted` и `insufficient_evidence`.
  Жизненный цикл сохраняет историю, причину недоступности и восстановление после возврата кода.
- Product storage и его миграции не изменяют research datasets, protocols и seals.

Acceptance этапа:

- Последовательность реальных CLI-запусков создаёт claim, меняет код и читает обновлённую memory.
- Посторонняя правка сохраняет подходящий claim и его прежний `last_checked`.
  Смена сигнатуры опровергает signature claim при сохранении существования символа.
- Удаление символа опровергает existence claim. Неоднозначный binding или parse error
  даёт неопределённость. Возврат поддерживаемого определения допускает восстановление.
- Ответ CLI объясняет выбор или перенос и указывает snapshot и provenance.
  После перезапуска история и состояния сохраняются.
- Пропущенная dependency или неполная provenance вызывает консервативную обработку.
  Синтаксический verdict не выдаётся за поведенческую гарантию или независимый human review.

### 5. Watch и интеграция агента

Статус `pending`. Зависимость от этапа 4.

Задачи этапа:

- Отдельная CLI-команда следит за worktree, объединяет всплески событий через debounce
  и запускает обновление index и memory.
- Идентичность поколения связывает завершённый snapshot, index и состояние memory.
  Новый запрос видит согласованные данные одного поколения.
- Обнаруженная правка меняет freshness до завершения обновления.
  Ошибка сохраняет последнее целое поколение и явный статус устаревания.
- Перезапуск сверяет фактические файлы с сохранённым snapshot и восстанавливает пропущенные изменения.
- Параллельный запуск watcher имеет явный отказ или согласованный single-writer механизм.

- Пример инструкции для AGENTS.md направляет агента в CAMI CLI и объясняет freshness,
  provenance и поведение при неполном анализе.

Acceptance этапа:

- Настоящий фоновый CLI видит burst правок, atomic-save rename, добавление и удаление файла.
  После стабилизации поиск и memory соответствуют окончательному содержимому.
- При pending update ответ сообщает, что snapshot устарел. Ошибка разбора, права доступа
  или сбой обновления не маркируют прежний ответ как свежий.
- Kill и последующий restart восстанавливают пропущенные правки без ручной очистки index.
- Прерывание обновления не публикует частичный index или несогласованную memory.
- Проверка фиксирует фактическую задержку обновления и число поколений для заданного burst.
  Измерение не объявляется общим доказательством производительности.
- Старый `cami run --config ... --out ...` продолжает обозначать research execution.
- Незакоммиченная правка общей функции в Next.js-сценарии обновляет поиск и затронутую structural memory.
  Посторонняя правка сохраняет подходящее знание без фиктивной проверки.
- Watcher restart сохраняет идентичность worktree и восстанавливает свежий ответ.
- Сохранённый transcript или сценарный драйвер показывает реальные команды агента,
  их JSON-ответы и соответствие файлам. Наличие примера AGENTS.md само по себе не считается интеграцией.

## Ограничения research

Исходные protocols, datasets, seals и исторические evidence остаются без изменений.
Held-out Requests и pytest, их policies и behavior probes, а также финальный научный
`freeze` не запускаются в этой продуктовой программе без отдельного разрешения.
Обычные тесты нового CLI на самостоятельных fixtures не являются held-out evaluation.

Synthetic 24/24/10 отражает число выбранных проверок в ограниченной демонстрации.
Это не доказательство качества на реальных проектах, полноты графа или ускорения.
M0–M5 описывают исследовательские инструменты и не составляют весь продукт из vision.
Независимые parent receipts, child labels, human review и scientific freeze
не появляются автоматически из product memory или synthetic closure.

## Оркестрация и бюджет

Один code-writer работает в каждом checkout. По прямому поручению пользователя текущий docs integrator
единолично владеет Git index и commit в исходной `main`. Fixworker и reviewer r2 завершены.
Stage2 и TS core работают в отдельных app-owned worktrees БЕЗ КОММИТОВ по standing rule 13.
Все фактические интеграции и коммиты выполняются последовательно в исходной `main`.
Этот drain меняет только план, canonical trail, компактный аудит trail и external store.
Source, tests, README, pyproject, protocols, datasets и seals остаются прежними.

Модель оркестрации и отдельного reviewer задана как `codex:gpt-6.1-sol`,
`reasoningEffort=high`, `serviceTier=default`. Это отдельные проверки одной моделью.
Разнообразие моделей и независимость научной разметки здесь не заявляются.
Прямой выбор пользователя заменяет требование разных семейств в pstack.
Маршрут вызова и точные options проверяет родительский оркестратор по live capabilities T3.

Условие автономного продолжения задано пользователем как недельный остаток Codex `>10%`.
Источник указанного снимка бюджета находится в `/root/.codex/sessions`,
structured `event_msg` с `token_count.rate_limits`, `limit_id=codex`, окно `10080` минут.
Последний transferred snapshot на `2026-10-23 11:40:54.145 UTC` даёт remaining `84%`.
Предыдущий docs snapshot: `84%` на `2026-10-23 11:28:38.016 UTC`.
Receipts: `quota-transferred.json` и `quota-docs.json` во внешнем store.
Reset указан как `2026-10-29 18:36:49 UTC`. Эти значения переданы оркестратором,
здесь они не представлены как новое измерение или текущий остаток.
Перед продолжением волн и после крупного этапа оркестратор обновляет quota evidence.
При остатке `<=10%` новая автономная работа не начинается, состояние передаётся для продолжения.
Без свежей доступной telemetry условие продолжения остаётся неподтверждённым.

## Продолжение после compaction

Точка продолжения задаётся этим планом и append-only [decisions.tsv](../reports/orchestration/decisions.tsv).
Stage1 `accepted` после независимого `PASS` r2 для `499acfad48b2d62e37b0f57a3b051bc09eaf847b`.
Stage2 implementation `in_progress`, `not_accepted`. Stage3 core `in_progress`, integration `pending`, `not_accepted`.
Этапы 4 и 5 `pending`. Итого пять продуктовых этапов: один принят, два в работе, два ожидают.
Runtime units включают отдельные implementation, design, review и docs runs. Их число не означает число готовых этапов.
Исторический независимый `FAIL` сохранён для `dea30002cdce4aa5e859d0a3ff6a5124c32bdbe4`.
Stage2 worktree начат от docs commit `60d631ffd89cb447eb2f530cb74fc27e22d8ab7a`, до fix stage1.
Интегратор сохраняет fix при переносе patch и повторяет acceptance в main.
После stage2 требуется отдельная полная TS find integration и независимый acceptance Next.js-сценария.
Только подтверждённый acceptance меняет статус этапа на принятый.

Долговечный orchestration store находится в `/root/.claude/orchestrate/change-aware-memory-invalidation/`.
Standing orders хранятся в `preferences.md`; runtime handles и источники статусов указаны в `runtime-handles.json`.
`status.md` выводится из `units.tsv` и `ledger.tsv`. Терминальный design run не означает acceptance этапа.
Canonical decision trail остаётся `reports/orchestration/decisions.tsv`; store содержит только ссылку на него.
Исходные plugin paths перечислены в `references.md` внешнего store. Временная vendor-копия удалена.
PR frontier seed пропущен: пользователь выбрал локальные коммиты на main без PR.
Текущий docs integrator коммитит только разрешённые документы в main, без push и PR. Новых агентов не запускает.
[Аудит журнала](../reports/orchestration/trail_audit_ru.md) указывает проверенный диапазон, слабые pointers и пределы проверки.
Полный SHA этого docs commit сохраняется после коммита в external receipt `docs-drain-20261023-receipt.json`.

Docs-only commit `60d631ffd89cb447eb2f530cb74fc27e22d8ab7a` завершён: terminal clean,
2 files, +255; receipt `docs-integration.json` во внешнем store. Это исторический
переданный snapshot, не утверждение о текущем состоянии main.
