# План развития CAMI до продукта

План задаёт пять последовательных этапов по [vision](final_product_vision.md).
Статусы относятся к продуктовой работе, а не к исследовательским M0–M5.

Актуальный снимок на 2026-10-23T15:10:29.819Z: Stage1 принят на
`499acfad48b2d62e37b0f57a3b051bc09eaf847b`, Stage2 на
`6037294831fc0cde5525986cab043ea21af27dd3`, Stage3 на
`c9a94f7effeb6033f2cea5233e9f5f06fb7ab838`.
Три этапа приняты, Stage4 и Stage5 `in_progress`, оба `not_accepted`.
Исходники main остаются на принятом Stage3. Memory и watch ещё не интегрированы.
Storage component получил R4 PASS. Hybrid memory получил R1 FAIL с одним P1.
Изолированные исправление имён и watcher implementation активны без коммитов.
Исторические snapshots ниже не описывают текущее состояние.
Task counts не являются числом принятых этапов.

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

Порядок ведёт от принятого TS/TSX Next.js path к product memory и watcher.
По явному решению родителя параллельная implementation допускается в изолированных
app-owned worktrees БЕЗ КОММИТОВ, standing order 13. Один writer работает в каждом checkout.
Интеграции и коммиты выполняются последовательно в исходной main.
Read-only design work может идти заранее и не означает acceptance реализации.
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

Статус реализации `implementation_completed`, acceptance `accepted` на exact
`6037294831fc0cde5525986cab043ea21af27dd3` после независимого R3 PASS.
Report: `/tmp/cami-stage2-review-r3-ncph5p29/review-report.json`.
Исторический launch до интеграции описан следующим абзацем.
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

Статус реализации `implementation_completed`, acceptance `accepted` после независимого
MAIN PASS для exact `c9a94f7effeb6033f2cea5233e9f5f06fb7ab838`.
[Независимый отчёт Stage3](/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/stage3-main-review/review-20261023T142134Z/review.json)
подтверждает 188 focused tests, включая все 53 cache/ignore и 27 relative-import regressions.
Все 103 CLI/package/cache-команды прошли, включая relocated read-only wheel под uid65534.
Три исходных findings закрыты: destructuring default scopes, active config capture/invalidation,
repair непустого повреждённого compiler cache. Новых actionable findings нет.

Scope включает Python, JS, JSX, TS и TSX search через worktree и Git, compiler setup и cache.
Поддерживается один root config с captured relative extends. Граф синтаксический и неполный,
`graph_complete=false`. Typechecking, inference и general member/dynamic dispatch не приняты.
Writer отдельно сообщил 569 full tests и 4 deselected. Независимый reviewer не повторял full suite.
Исторический artifact R2 PASS для patch SHA-256
`741ef6de1b68519354f73259b25731d5c37c1735d0cfeaa443786decafa9e145` сохранён отдельно.
Exact-SHA local receipt: `stage3-main-review.json` во внешнем orchestration store.

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

Статус `in_progress`, acceptance `not_accepted`. Этап 3 принят.
[Storage component R4 PASS](/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/stage4-memory-review/t3-42ee661d-20261023T1452Z-r4/REVIEW.md)
привязан к full feature SHA-256
`98f131ac10a9e54a12c205d4d3b13d9cc180daf4b405c6e520aafa71958ee8e2`
и fix-only `2b0e04c595d42d2287a37b73ca7c0f86e72e502bf695fef4226123ad8f7f3586`.
Независимо прошли 97 memory tests, 21 publication crash/failure case и 18 damaged inputs.
Source, index и patches не изменились за review. Writer отдельно сообщил 608 full и 4 deselected.
Это PASS компонента хранения, а не всего Stage4 или main.
Исторический [f0bb R3 FAIL](/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/stage4-memory-review/t3-2a8e7cd2-20261023T1400-r3/REVIEW.md)
сохранён. Его hot-journal boundary finding закрыт новым storage artifact.

[Hybrid memory R1 FAIL](/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/stage4-hybrid-review/t3-149a13ec-20261023T145431Z-r1/REVIEW.md)
относится к exact patch `7ca9534027645c03c6bcfd216f6b7f860c5bc4a2818dc20cbafd0a886d3ec5db`.
Один P1: quoted method names и quoted unsupported fields дают ложные `subject_absent` witnesses.
Runtime prototype и dynamic-scope observations не блокируют принятый static/syntax contract.
Независимо прошли 326 focused tests, 254 installed CLI-команды и 51 additional probe.
Writer 648 full и 4 deselected остаются отдельным evidence.

`hybridNameFixTask` активен isolated без коммитов. Он восстанавливает hybrid feature
с принятым storage fix и готовит full patch и fix-only patch. Эти patches ещё ожидаются.
Main integration не начата. После исправления нужны combined TS/TSX memory CLI на main
и свежий независимый Stage4 MAIN review.
Полная [карта memory/TS integration](/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/references/memory-ts-merge-map-20261023-v1.md)
хранится вне репозитория.

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

Статус `in_progress`, acceptance `not_accepted`. `watchImplementationTask` уже
работает в изолированном worktree без коммитов, на собственной сборке hybrid и storage fix.
[Design proposal](/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/references/watcher-design-20261023-v1.md)
остаётся reference. Задача охватывает foreground polling, status, stop и restart.
Acceptance требует доказать обновление persisted state до запроса, который сам мог бы обновить данные.
Позже нужны upstream name fix, Stage4 MAIN PASS и свежий watcher review.
Финальная поставка ещё не подтверждена.

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

Один code-writer работает в каждом checkout. По прямому поручению пользователя текущий docs worker
единолично владеет Git index и docs commit в исходной `main`.
Активные name-fix и watcher workers работают в отдельных app-owned worktrees БЕЗ КОММИТОВ по standing rule 13.
Все фактические интеграции и коммиты выполняются последовательно в исходной `main`.
Этот recorder меняет только план, canonical trail и external store. Исторический аудит не расширяется.
Source, tests, README, pyproject, protocols, datasets и seals остаются прежними.

Модель оркестрации и отдельного reviewer задана как `codex:gpt-6.1-sol`,
`reasoningEffort=high`, `serviceTier=default`. Это отдельные проверки одной моделью.
Разнообразие моделей и независимость научной разметки здесь не заявляются.
Прямой выбор пользователя заменяет требование разных семейств в pstack.
Маршрут вызова и точные options проверяет родительский оркестратор по live capabilities T3.

Условие автономного продолжения задано пользователем как недельный остаток Codex `>10%`.
Источник указанного снимка бюджета находится в `/root/.codex/sessions`,
structured `event_msg` с `token_count.rate_limits`, `limit_id=codex`, окно `10080` минут.
Hybrid R1 передал remaining `70%` на `2026-10-23T15:06:40.103Z`, до review было `71%`.
Этот recorder отдельно прочитал свежую локальную structured telemetry: remaining `70%`
на `2026-10-23T15:09:38.514Z`, reset `2026-10-29T18:36:49+00:00`.
Измерения начала и конца run сохраняются во внешнем receipt
`outputs/milestone-docs/run-20261023T1510Z-storage-hybrid-watch/receipt.json`.
Остаток не вычисляется по tokens. Работа продолжается до фактического недельного остатка `<=10%`.
Перед продолжением волн и после крупного этапа оркестратор обновляет quota evidence.
При остатке `<=10%` новая автономная работа не начинается, состояние передаётся для продолжения.
Без свежей доступной telemetry условие продолжения остаётся неподтверждённым.

## Продолжение после compaction

Точка продолжения задаётся этим планом и append-only [decisions.tsv](../reports/orchestration/decisions.tsv).
Stage1 `accepted` после независимого `PASS` r2 для `499acfad48b2d62e37b0f57a3b051bc09eaf847b`.
Stage2 `accepted` на `6037294831fc0cde5525986cab043ea21af27dd3`.
Stage3 `accepted` на `c9a94f7effeb6033f2cea5233e9f5f06fb7ab838` после independent MAIN PASS.
Stage4 и Stage5 `in_progress`, оба `not_accepted`.
Итого пять продуктовых этапов: три приняты, два в работе. Main содержит принятый Stage3 source.
Storage R4 PASS не принимает весь Stage4. Hybrid R1 FAIL требует name fix и свежего MAIN review.
Runtime units включают отдельные implementation, design, review и docs runs. Их число не означает число готовых этапов.
Исторический независимый `FAIL` сохранён для `dea30002cdce4aa5e859d0a3ff6a5124c32bdbe4`.
На снимке `2026-10-23T15:10:29.819Z` активны `hybridNameFixTask` и `watchImplementationTask`.
Storage R4 и hybrid R1 review завершены. Полные parent handles сохранены вместе с исходными
running labels и отдельными свежими backing-thread observations. `task_status` недоступен sibling worker.
Активные задачи не ожидались. Этот снимок не обновляет будущие состояния автоматически.
Исторический recorder snapshot завершён в 14:29:18 UTC и не обновляется автоматически.
Только подтверждённый acceptance меняет статус этапа на принятый.

Долговечный orchestration store находится в `/root/.claude/orchestrate/change-aware-memory-invalidation/`.
Standing orders хранятся в `preferences.md`; runtime handles и источники статусов указаны в `runtime-handles.json`.
`status.md` выводится из `units.tsv` и `ledger.tsv`. Терминальный design run не означает acceptance этапа.
Canonical decision trail остаётся `reports/orchestration/decisions.tsv`; store содержит только ссылку на него.
Исходные plugin paths перечислены в `references.md` внешнего store. Временная vendor-копия удалена.
PR frontier seed пропущен: пользователь выбрал локальные коммиты на main без PR.
Текущий docs integrator коммитит только разрешённые документы в main, без push и PR. Новых агентов не запускает.
[Аудит журнала](../reports/orchestration/trail_audit_ru.md) указывает проверенный диапазон, слабые pointers и пределы проверки.
Полный SHA этого docs commit и результаты self-readback сохраняются во внешнем receipt
`outputs/milestone-docs/run-20261023T1510Z-storage-hybrid-watch/receipt.json`.
Независимый docs review в этом bounded run не проводился.

Docs-only commit `60d631ffd89cb447eb2f530cb74fc27e22d8ab7a` завершён: terminal clean,
2 files, +255; receipt `docs-integration.json` во внешнем store. Это исторический
переданный snapshot, не утверждение о текущем состоянии main.

## История интеграций и review до Stage3 MAIN PASS

Следующие snapshots сохранены как история. Текущие acceptance и active tasks указаны выше.

### Проверка интеграции stage2 в main

Patch SHA-256 `9a62a9c4395521eb059071a2fdf517b3dc5fa157364f2fe47e53448d63529294`
проверен перед применением к чистой main `14572ebd470d7c246c52d860b6957635a32a0a64`.
Трёхстороннее применение прошло без конфликтов. P2 resolver helpers не изменились;
все 27 исправляющих регрессий сохранены. Research contracts и inputs не менялись.
Main self-tests дали 95 targeted и 408 non-Docker passed, 4 deselected.
Ruff и strict mypy `src/cami scripts/demo_structural_closure.py` прошли.
Реальные CLI-процессы проверили 15 lifecycle и 13 дополнительных сценариев,
включая исходный P2 repro с нулём ложных incoming в worktree и Git-режимах.
Сортировка limitations в JSON v2 изменилась, их содержимое и unresolved signals сохранены.

Полные commands, драйверы и receipt находятся во внешнем store в
`outputs/stage2-main-integration/run-20261023T1210/`.
Точный commit, source/test tree IDs и postcommit self-query сохранены после commit.
Это implementation verification, не independent review. Свежий reviewer той же
настроенной модели назначается родителем; до его verdict stage2 остаётся `under_review`.
Следующая продуктовая работа требует полной TS find integration и отдельной приемки Next.js.
PR не создавался, PR ledger не заполняется фиктивным номером.

### Новые component events из parent handoff

TS core завершён как tested component: переданы 50 targeted и 422 full tests.
Это результаты изолированного worker, не проверка `cami find` и не acceptance этапа 3.
Patch находится в
`/root/.t3/worktrees/change-aware-memory-invalidation/t3-b16d8453/outputs/stage3-typescript-core/patch.diff`.
Переданный SHA-256 равен `8b987029866d4b9292f8c81da9395345552f2c34491b9d0589c9fb7dfae9b40c`.
TS product integration запущена в отдельном worktree без коммитов.
Memory architecture завершена с SQLite, provenance и claim freshness design.
Memory core implementation также запущена изолированно без коммитов и пока не принята.
Полная TS/memory CLI-приемка ожидает подключения TS find.
Task/thread handles сохранены в `runtime-handles.json` внешнего store.
Эти parent-transferred события уточняют прежние launch snapshots, не расширяют scope Stage2.

### Stage2 review r1 и исправление четырёх P2

Независимый review r1 дал FAIL точному main SHA
`1adf399f38e38b98b16b405359287e8a28884d8e`. Исторический verdict сохраняется.
Исправлены external ignore capture, блокирующее чтение cache FIFO, persistent
repair неверного типа generation-directory и fingerprint исключённой `.gitignore`.
Source-symlink coverage не расширено. Frozen research inputs и contracts не менялись.

До правок baseline95/full408 прошёл; новые regression tests дали 16 FAIL и 8 PASS.
После правок прошли targeted133/full446, 4 Docker deselected, Ruff, strict mypy32
и diffcheck. CLI подтвердил исходные четыре дефекта до правок и их исправление
с persistent repair/reuse. Дополнительно прошли 15 lifecycle scenarios и 10 CLI
вызовов для исходного relative-import P2, valid imports и запросов к own source.
Это implementation verification. Новый commit остаётся `under_review` до свежего
независимого review r2 от parent. Exact SHA и receipt сохраняются после commit в
`outputs/stage2-storage-fix/run-20261023T123409Z/` внешнего store. PR не создавался.

### Memory component handoff из parent

Memory core завершён как tested component. Parent передал 477 non-Docker tests
и 20 CLI checks. Patch находится в
`/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/stage4-memory-core/t3-2ea4315e-20261023T1220/feature.patch`.
Переданный SHA-256 равен `07a71b84d3c83b0c39a939229f3a1fa0bc32598078326defbfbe489b667ea937`.
Это не main integration и не PASS memory acceptance. Полный TS CLI gate остаётся pending.
Независимый read-only component review r1 запущен для завершённого memory candidate.
Task/thread handles сохранены во внешнем `runtime-handles.json`; verdict пока отсутствует.

### Stage2 review r2 и UNIX socket cache repair

Независимый r2 дал FAIL exact main
`26d9188ab75784ca1c2a9d4a55b1381ab07bbdde`. Все четыре прежних P2 независимо
подтверждены как исправленные, 133 targeted tests и 224 CLI вызова прошли.
Оставшийся P2 касается UNIX socket вместо `current.json`, `manifest.json` или
`index.json`. Два новых CLI-процесса повторяли exit 4 с `ENXIO` без repair.
Полный report сохранён в `/tmp/cami-stage2-review-r2-461q7d91/review-report.json`.

Узкая правка проверяет regular-file invariant до open и descriptor identity перед
bounded read. Ошибка open требует подтверждения неверного фактического типа;
ошибки обычного файла остаются явными. Неверные pointer nodes также quarantined.
Source coverage, Gitignore handling, query semantics и research inputs не менялись.
До правки actual CLI9 подтвердил дефект всех трёх ролей; regression matrix дала
3 FAIL и 2 PASS, corrected boundary tests дали 2 FAIL и 9 PASS. После правки
focused34, targeted148, full461 non-Docker +4deselected, Ruff, strict mypy32 прошли.
Сохранены прежние 38 cache/ignore и 27 relative-import regressions.
Actual CLI15 проверил quarantine, correct query, valid regular JSON, reuse новым
процессом без builder и настоящий kernel EACCES для всех трёх ролей. Ещё CLI10
проверил relative-import P2, valid imports и own-source worktree/HEAD/SHA queries.

Новый main commit остаётся `under_review` до свежего independent R3 от parent.
Исторические FAIL exact1ad и exact26d сохранены. SHA, commands, hashes и receipt
находятся в external `outputs/stage2-socket-fix/run-20261023T1318Z/`.
По текущему parent handoff TS artifact является read-only candidate under review,
а memory component имеет FAIL с тремя findings и исправляется isolated без
коммитов. Эти события заменяют старые running/no-verdict snapshots, но не означают
TS или memory acceptance. Их интеграция в main этой правкой не выполнялась.

### Parent wave после socket implementation commit

Новый parent handoff уточняет предыдущий snapshot. TS artifact review завершён
с FAIL и тремя новыми P2 по destructuring default scopes, active config during
build и setup cache publication. Fresh TS fix запущен isolated без коммитов.
Memory fix component завершён с переданными 559 full и 63 memory tests.
Patch находится в
`/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/stage4-memory-fix/t3-3ed26adc-20261023T1300/feature.patch`,
переданный SHA-256 равен `9776a6f30a9f7a445d89868eb72d1455929f6d45c567dfaf26238a7f8df2509c`.
Fresh memory component review r2 запущен read-only; verdict ещё отсутствует.
Оба новых task/thread handles сохранены во внешнем `runtime-handles.json`.
TS и memory не имеют PASS; full TS/memory CLI gate остаётся pending.
Это transferred evidence, без новых проверок или code integration в main.

### Stage2 R3 и интеграция TypeScript в MAIN

Независимый Stage2 R3 дал PASS exact
`6037294831fc0cde5525986cab043ea21af27dd3`: 148 targeted tests и 76 CLI checks.
Report сохранён в `/tmp/cami-stage2-review-r3-ncph5p29/review-report.json`.
Этот verdict заменяет pending R3 выше. Исторические FAIL exact1ad и exact26d
сохранены вместе с исходными evidence.

TypeScript artifact R2 дал PASS полному patch SHA-256
`741ef6de1b68519354f73259b25731d5c37c1735d0cfeaa443786decafa9e145`.
Все три R1 P2 закрыты, новых findings нет. Независимый report находится в
`/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/stage3-typescript-review/t3-7e700358-20261023T1343-r2/review.json`.
Это artifact acceptance, не exact-MAIN acceptance.

Patch перенесён трёхсторонне в MAIN с сохранением принятых socket и ignore
исправлений. Конфликт был только в implementation status и разрешён сохранением
обоих исторических разделов. Combined self-checks дали 256 targeted и 569
non-Docker tests, 4 deselected. Сохранены все 53 Stage2 и 27 relative-import cases.
Ruff, strict mypy38, Node, реальные combined CLI и установленный read-only wheel
под uid65534 прошли. Полные команды и receipt находятся в external
`outputs/stage3-main-integration/run-20261023T140732Z/`.
Stage3 остаётся `under_review` до fresh independent review итогового MAIN commit.

Parent сообщил о fresh memory component R3 над candidate f0bb. Переданы self-checks
583 full и 72 memory tests; это не Stage4 acceptance. Memory R2 исторический FAIL
и его database-open-race finding сохраняются. Полная TS/memory CLI integration
ещё pending. Task/thread handles записаны в external runtime-handles.
Watch design завершён как proposal. Точный terminal brief сохранён вне repo в
`/root/.claude/orchestrate/change-aware-memory-invalidation/briefs/stage5-watch-implementation-20261023-v1.txt`.
Stage5 не реализован. PR не создавался, PR ledger не получает фиктивной записи.
