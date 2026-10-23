# CAMI. Отчёт о развитии продукта за 23 октября 2026 года

CAMI ищет определения Python, JavaScript, JSX, TypeScript и TSX в рабочем дереве и Git revisions, сохраняет индекс между процессами и ведёт память о структуре проекта. Агент получает определения, доступные статические связи, происхождение сведений и их текущий статус через CLI. После правок watcher обновляет индекс и память в фоне.

Все пять продуктовых этапов приняты независимыми проверками в согласованном объёме. Последний exact-MAIN review дал PASS без замечаний для `43edac89d8a38ed1551195048e6383ced1479399`, включая WATCH и OPT. Это завершение начатого объёма работ, а не всей [концепции продукта](final_product_vision.md). Поиск обычных переменных и классов, полноценное подключение агента на реальном Next.js-проекте и MCP остаются дальнейшей работой.

Этот отчёт подготовлен чтением исходников, документации и сохранённых проверок. Его подготовка не запускала продуктовые команды, тесты, сборки или бенчмарки. Финализация включает только документы и обычную публикацию текущей `main` в существующий `origin/main`.

## Что пользователь может делать

### Установить окружение и найти код

Нужны Python 3.12 и uv. Для анализа JS и TS нужны Node.js 24, npm 11 и доверенный compiler TypeScript 6.0.3. Из корня клона CAMI выполните:

```bash
uv sync --locked --extra dev
source .venv/bin/activate
cami setup-typescript
cami find run_experiment --repo . --format json
cami find src/cami/engine.py:run_experiment --repo . --revision HEAD --format json
```

`setup-typescript` устанавливает закреплённый compiler в пользовательский cache по lockfile CAMI. Для чисто Python-поиска этот шаг не нужен. Во время `find` CAMI не запускает npm, скрипты проекта или сам код проекта.

Без `--revision` поиск читает текущие bytes, включая unstaged и untracked исходники. `--revision HEAD` или полный SHA читает Git objects. Поиск не меняет Git index. Короткое имя может дать несколько совпадений. Для точного результата используйте `path:qualname`, например `src/cami/engine.py:run_experiment`.

Для своего Next.js-проекта замените путь и имя на существующее определение:

```bash
cami find createUser --repo /absolute/path/to/next-app --format json
cami find createUser --repo /absolute/path/to/next-app --revision HEAD --format json
```

JSON различает `found`, `not_found` и `ambiguous`, показывает сигнатуру, позиции, связи и ограничения. `not_found` при неполном покрытии не доказывает отсутствие символа. Повторяемые `--source-root` и `--exclude` задают область worktree-поиска. Полные правила и exit codes описаны в [контракте поиска](symbol_search_ru.md), [контракте индекса](worktree_index_ru.md) и [контракте TypeScript](typescript_analyzer_ru.md).

### Сохранить структурное ожидание и ручную заметку

Следующий пример использует существующую функцию CAMI. `REPO` должен указывать на клон CAMI, а `EVIDENCE` на отдельный каталог вне исходников. Для другого проекта замените subject на его точный путь и символ.

```bash
REPO=/absolute/path/to/change-aware-memory-invalidation
EVIDENCE=/absolute/path/outside/repository/cami-session
mkdir -p "$EVIDENCE"

cami memory context src/cami/engine.py:run_experiment --repo "$REPO" --format json \
  > "$EVIDENCE/context.json"
cami memory remember symbol_exists src/cami/engine.py:run_experiment --repo "$REPO" \
  --from-context "$EVIDENCE/context.json" --request-id session-exists-1 --format json
cami memory remember signature_equals src/cami/engine.py:run_experiment --repo "$REPO" \
  --from-context "$EVIDENCE/context.json" --request-id session-signature-1 --format json
cami memory remember note src/cami/engine.py:run_experiment --repo "$REPO" \
  --from-context "$EVIDENCE/context.json" --note-key engine-review \
  --text 'Точка входа исследовательского запуска. Заметка требует ручной проверки.' \
  --request-id session-note-1 --format json
cami memory context src/cami/engine.py:run_experiment --repo "$REPO" --format json
```

`symbol_exists` проверяет структурную идентичность определения. `signature_equals` сравнивает поддерживаемую синтаксическую сигнатуру. `note` остаётся `manual_assertion`, даже если выглядит убедительно. После изменения исходника заметка требует явного review. Возврат прежних bytes сам по себе это требование не снимает.

Возьмите `memory_id` и `revision` заметки из mutation receipt. После ручной проверки получите новый context и обновите заметку:

```bash
cami memory context src/cami/engine.py:run_experiment --repo "$REPO" --format json \
  > "$EVIDENCE/review-context.json"
cami memory update "$NOTE_ID" --repo "$REPO" --if-revision "$NOTE_REV" \
  --from-context "$EVIDENCE/review-context.json" --text 'Проверено по текущему исходнику.' \
  --request-id session-note-review-2 --format json
cami memory history "$NOTE_ID" --repo "$REPO" --format json
cami memory refresh --repo "$REPO" --format json
```

`NOTE_ID` и `NOTE_REV` здесь обозначают полученные значения. `--if-revision` защищает от конкурентного обновления. Повтор того же request ID с тем же запросом возвращает прежний receipt. Изменённый запрос с тем же ID даёт conflict. History читает сохранённую историю без live refresh. Перед использованием знания нужен новый context с проверкой `facts`, `notes`, `withheld`, coverage и limitations. Подробности находятся в [руководстве по памяти](product_memory_ru.md).

### Обновлять память в фоне

`cami watch` работает в foreground. Фон создаёт обычная оболочка. С теми же `REPO` и внешним `EVIDENCE` выполните:

```bash
cami watch --repo "$REPO" > "$EVIDENCE/watch.log" 2> "$EVIDENCE/watch.err" &
WATCH_PID=$!
cami watch status --repo "$REPO" --format json

cami find run_experiment --repo "$REPO" --format json
cami memory context src/cami/engine.py:run_experiment --repo "$REPO" --format json

cami watch stop --repo "$REPO"
wait "$WATCH_PID"
```

`WATCH_PID` нужен оболочке. Управление CAMI проверяет собственную session и lease. `cami watch restart --repo "$REPO"` останавливает совпавшую session и запускает замену в foreground. Для фонового restart снова используйте оболочку. `status` и `stop` используют настройки запущенной session. Намеренные source roots и exclusions передавайте одинаково watcher и запросам.

Watcher обновляет память до запроса агента, однако каждый `find` и `memory context` всё равно проверяет собственный набор входов. `latest_successful` в status является историческим результатом. При ошибке или незавершённой работе свежесть может быть `unknown`. Polling 500 ms и debounce 250 ms задают расписание попыток, а не гарантированную задержку публикации.

Готовый текст для проектного AGENTS.md, lifecycle и ограничения управления описаны в [руководстве watch и agent workflow](watch.md). Команда `cami run --config ... --out ...` по-прежнему запускает research experiment. Это отдельный контракт.

## Что реализовано и принято

Точные commits ниже задают объём acceptance. Все они сохранены в истории текущей main.

| Этап | Результат | Принятый exact commit | Статус |
| --- | --- | --- | --- |
| 1. Git search | Поиск Python functions и methods в Git revisions, сигнатуры, позиции, доступные связи, JSON и неоднозначность. | `499acfad48b2d62e37b0f57a3b051bc09eaf847b` | Accepted после исправления relative imports и независимого R2. |
| 2. Worktree и persistent index | Текущие исходники, untracked и unstaged edits, проверяемый readset, immutable generations, reuse и восстановление cache. | `6037294831fc0cde5525986cab043ea21af27dd3` | Accepted после независимого R3. |
| 3. JS, TS и TSX | Trusted compiler bridge, синтаксические definitions и relations, captured configuration и интеграция с поиском и generations. | `c9a94f7effeb6033f2cea5233e9f5f06fb7ab838` | Accepted независимым exact-MAIN review. |
| 4. Product memory | Общий Python и ECMA context, structural predicates, notes, provenance, carry, immutable history, request/revision CAS и durable SQLite publication. | `83f6aea2178b7ace167102b668cedb78c04dca17` | Accepted независимым exact-MAIN R3. |
| 5. WATCH и OPT | Фоновый refresh, status/stop/restart, ownership и cleanup. Группировка identity gaps по точному пути уменьшает лишние проверки. | `43edac89d8a38ed1551195048e6383ced1479399` | Accepted свежим независимым exact-MAIN review без findings. |

Архитектура разделяет входы, индекс, память и наблюдение за процессом. Snapshot идентифицирует captured содержимое и policy. Generation дополнительно учитывает analyzer и реализацию. Memory хранит исходное evidence, результаты проверок и историю отдельно от текущего индекса. При допустимом carry прежние check ID и timestamp сохраняются. Новая generation не изображает новую проверку каждого знания.

Общий индекс объединяет Python AST и ECMA analysis одного capture. TypeScript compiler читает переданные captured bytes и metadata. SQLite product head закрепляет memory generation, а index pointer остаётся cache hint. Watcher вызывает тот же ProductMemory, поэтому foreground и background используют общие правила доказательств.

История реализации и подробные acceptance описаны в [плане развития](product_development_plan_ru.md), [implementation status](implementation_status.md) и [журнале решений](../reports/orchestration/decisions.tsv). Их ранние pending-снимки исторические. Свежий Stage 5 PASS и точные команды сохранены в [переносимой выжимке приёмки](../reports/orchestration/final_acceptance_2026-10-23.md).

### Исправления, которые защищают достоверность результата

- Некорректный relative import выше package root ошибочно превращался в пустое имя модуля и создавал ложные incoming calls в корневой `__init__.py`. Теперь неразрешимый import остаётся неразрешимым. Независимый исходный repro изменился с двух ложных связей до нуля.
- Cache и ignore-boundaries проверяются как входы. Повреждённые artifacts, symlinks, FIFO и UNIX sockets не превращаются в успешный stale result. Действующие ignore rules и compiler metadata входят в идентичность capture. Ошибка чтения отличается от отсутствия файла.
- SQLite больше не открывает live database для recovery. CAMI захватывает ограниченную по размеру пару database/journal, работает с частной копией и публикует durable intent перед заменой. Подмена во время SQLite open сохраняет исходные bytes и даёт явную ошибку. Потерянная установленная база не подменяется пустой историей.
- Неподдерживаемое или неизвестное computed-имя владельца могло дать ложное отсутствие вложенного определения. Coverage теперь удерживает все затронутые descendant kinds в `insufficient_evidence / binding_unresolved`, сохраняя точные границы пути и qualname. Изменение validator fingerprint заставляет перепроверить старый catalog без удаления истории.
- Нормализация quoted, numeric, escaped, private и direct literal-computed member names согласована между definitions и coverage gaps. Совпадение идентичностей остаётся ambiguity.
- Watcher исправляет ownership на неудачной передаче запроса, orphan Node при остановке и cleanup заменённого socket. Подтверждённый stop требует завершения собственной работы. PID из discovery metadata не является разрешением послать signal. Чужой replacement endpoint сохраняется.

Эти исправления приняты по воспроизводимым случаям. Прежние FAIL и причины сохраняются в evidence, а не переписываются как успешные проверки.

## Что действительно проверено

Подготовка этого отчёта читала сохранённые результаты. Ни один результат ниже не является новым тестовым прогоном автора отчёта. Проверки разных этапов пересекаются, поэтому их количества не складываются в общий итог.

| Источник | Реальное свидетельство | Как его трактовать |
| --- | --- | --- |
| Stage 1 независимый R2 | 27 CLI-вызовов, 59 targeted tests, исходный relative-import repro до и после исправления. | Scoped acceptance exact `499acfad`. |
| Stage 2 независимый R3 | 148 targeted tests и 76 CLI checks. | Scoped acceptance exact `6037294831fc0cde5525986cab043ea21af27dd3`. |
| Stage 3 exact-MAIN review | 188 focused tests и 103 CLI/package/cache-команды. | Scoped acceptance exact `c9a94f7`. |
| Stage 4 exact-MAIN R3 | 111 distinct targeted cases. Отдельный новый 49-call installed driver проверил genuine old62 upgrade, immediate SQLite state, историю и source CAS. | Scoped acceptance exact `83f6aea`. Первоначальные cache-collision failures сохранены, затронутые cases перепроверены. |
| Writer corrected WATCH+OPT | 819 full passes с четырьмя Docker tests deselected и 497 focused passes, Ruff, strict mypy и Node syntax checks. | `FROM_IDENTICAL_ARTIFACT`. На MAIN полная suite не повторялась. Focused cases пересекаются с full. |
| Независимый review isolated union | 79 focused passes, отдельный installed Node-stop, 38 CLI/process launches и 12 persisted phases, ownership/crash и old62 background upgrade. | PASS изолированного artifact. При приёмке MAIN эти проверки переиспользованы после сравнения bytes, а не посчитаны как новые. |
| MAIN integrator | 11 CLI-команд, запуск watcher и три persisted phases. Ещё четыре postcommit CLI-проверки. | Новые проверки доставки на MAIN, включая состояние памяти до refresh-capable context и own-project find/context. |
| Свежий exact-MAIN Stage 5 review | 18 passing tests, 20 CLI/process launches и четыре persisted phases. Отдельные import и help probes не входят в число 20. | Новый независимый PASS exact `43edac89`, findings `[]`. Full suite, benchmark, setup и install не повторялись. |

Последний review проверил реальные MAIN `.venv/bin/cami` и `.venv/bin/python` вне checkout без `PYTHONPATH`. Background refresh сохранил Python check и его timestamp после body edit. Неизвестный TS owner дал `binding_unresolved` до запроса context. Возврат поддерживаемого owner создал новую проверку. Удаление после stop и запуск через restart дали `contradicted / subject_absent` с captured absence witness. Проверены duplicate start, configuration conflict, stop, repeated stop и own-project поиск.

Persisted SQLite/CAS читались независимо до запросов, которые сами могли бы обновить память. Immutable rows и старые source objects сохранились. Fresh Node/request/socket tests подтвердили cleanup на MAIN. Проверка всех 361 tracked inputs, Git blobs и modes связала фактические bytes с HEAD и index. HEAD, index и чистый status остались неизменными после review.

Для отдельного повторного воспроизведения уже существуют drivers. Их запуск создаёт fixtures и evidence, требует собственного бюджета и последующего удаления только созданных ими ресурсов. Они запускались на временных passive fixtures, без выполнения кода проверяемого приложения:

```bash
python3 tests/watch/cli_driver.py --cami /installed/bin/cami --out /absolute/new-watch-evidence
python3 tests/memory/hybrid_cli_driver.py --cami /installed/bin/cami --out /absolute/new-memory-evidence
```

Это справочные команды, не просьба повторить их при публикации отчёта. Точные команды новых проверок и их outcomes сохранены в Stage 5 receipt. Static checks включали Ruff, strict mypy, два Node syntax checks и `git diff --check`. Нет нового заявления о Docker, научном freeze или реальных held-out Requests и pytest.

### Что дала OPT

Оптимизация группирует identity gaps по точному source path перед вызовом прежнего authoritative `covers`. Кандидаты из других файлов всегда давали false. Их исключение сохраняет same-file порядок, исходные gaps, ambiguity и правила uncertainty.

Независимый corrected-composition report измерил пять чередующихся пар на synthetic warm workload из 1000 TS source files. Median owned CPU уменьшилась с 3,67 до 1,69 секунды. Отдельная диагностика насчитала 13 949 045 вызовов `covers` до группировки и 13 968 после. Analysis переиспользовался, analyzer и npm во время этих запросов не запускались.

Это ограниченное измерение данного workload. Host имел два CPU, конкурирующую нагрузку и неконтролируемый page cache. Wall-time ranges пересекались. На 100-file control CPU ranges также пересекались. Вывода об универсальном ускорении, стабильной latency, cold path или больших catalogs нет. Во время финализации benchmark не повторялся. Переносимое описание результата есть в [аудите trail](../reports/orchestration/trail_audit_ru.md). Точный measurement report указан среди server-local evidence ниже.

## Границы текущего продукта

- Статический граф частичный даже при `coverage: complete`. Покрытие относится к выбранным поддерживаемым входам, а не ко всей семантике приложения. Runtime dispatch, reflection и произвольные dynamic imports не доказываются.
- TypeScript используется для синтаксического анализа и поддерживаемого module resolution. CAMI не выполняет semantic typechecking, type inference, Next runtime или проверку поведения приложения. Один root config context применяется ко всем captured sources. Nested config contexts и project references не поддерживаются.
- Поиск возвращает functions, methods и поддерживаемые callable definitions. Обычные module-level constants, objects и классы как отдельные symbols пока отсутствуют. Класс может давать методы, но это не поиск самого класса. MCP не реализован.
- Default worktree contract равен `verified_readset` за интервал чтения и повторной проверки. Это не атомарный filesystem snapshot. Внешняя правка после проверки и ABA между чтениями возможны.
- Memory проверяет поддерживаемые structural predicates. Ручные заметки не становятся автоматически истинными. Signature comparison не доказывает runtime поведение. Для неподдерживаемых method signatures возможен `unsupported_symbol_kind`.
- Worktree и watcher используют POSIX descriptors, locks, signals и Unix sockets. Проверен этот объём на Linux. Windows portability, daemon installer и системный service manager не заявлены. Python API и CLI реализованы в описанных границах.
- Watcher один на canonical Git worktree. Повреждённые ownership proofs дают unknown и требуют осмотра. Scheduling ограничивает попытки, а не время coherent publication. Произвольные kernel-I/O задержки и все same-UID interleavings не сертифицированы.
- SQLite recovery ограничен поддерживаемым single-database rollback journal. WAL, SHM и super-journal не принимаются. Удаление всего state вместе с доказательствами неотличимо от первого запуска. Восстановление такой истории не обещано.
- Index generations сохраняются, автоматического GC пока нет. Изменения inventory, config и ряда analyzer inputs могут потребовать полной пересборки generation. Постоянно инкрементальная обработка каждого изменения ещё не доказана.
- Исследовательский engine и его прошлые демонстрации остаются отдельной частью CAMI. Польза для независимых ИИ-агентов и научное качество на real held-out данных текущими продуктовыми проверками не доказаны.

## Ресурсы и очистка

Ранее generated artifacts накопились до дефицита диска. По явной коррекции пользователя очищены 329 подтверждённых generated paths, 19 555 590 144 allocated bytes, или 18,21 GiB. Заполнение всего filesystem снизилось с 96% до 68%. Прирост свободного места всего filesystem не приписывается только CAMI cleanup.

Main, история Git и сохранённые исходники worktrees остались на месте. Cleanup сверил main и 786 сохранённых worktree source files. Общие main `.venv`, trusted compiler и npm/uv caches сохранены. Continuation archive занимает 14 758 369 bytes, около 14,07 MiB. При cleanup были проверены hashes всех 4592 сохранённых файлов. Подготовка отчёта архив не распаковывала и заново его не проверяла.

Повторная коррекция пользователя теперь задаёт рабочее правило. Только один тяжёлый worker/check работает за раз. Он переиспользует main environment и compiler cache, создаёт собственный disposable temp до 512 MiB и очищает свои fixtures, environments и процессы в finally. Остаются компактные manifests, scripts, receipts и logs. Full suite и benchmark на идентичном artifact без новой причины не повторяются.

Последний MAIN review выполнил проверки последовательно, не создавал environment и подтвердил cleanup своих workers, Node, temp roots и endpoints. Измеренные end-of-check scratch объёмы были меньше 512 MiB. Это не непрерывное измерение peak usage. Его final boundary составил 25 282 830 336 bytes свободного диска и MemAvailable 1 028 940 KiB.

Structured Codex quota последнего MAIN reviewer была 99% на `2026-10-23T18:02:21.589Z`, window 10080 минут, reset `2026-10-30T17:41:40+00:00`. Это сохранённое измерение reviewer, не оценка по tokens. Standing limits запрещают новую работу при remaining не выше 10% и тяжёлый прогон при disk free ниже 8 GiB или MemAvailable ниже 512 MiB.

## Публикуемый результат

Принятый код находится в `43edac89d8a38ed1551195048e6383ced1479399`. Финальный коммит документов добавляет этот отчёт и выжимку независимой приёмки, обновляет текущий снимок плана и дополняет журнал. Деревья `src` и `tests` сохраняются без изменений.

Цель публикации равна существующей ветке [origin/main на GitHub](https://github.com/Arsik0153/change-aware-memory-invalidation/tree/main). Пользователь прямо разрешил обычный `git push origin main`. Публикация включает все готовые коммиты текущей main. Перед push проверяется, что свежий удалённый tip является предком локального HEAD. После push отдельные `git ls-remote` и fetch должны подтвердить равенство SHA и чистый checkout.

Фактический итог публикации, время и SHA фиксируются во внешнем `publication-receipt.json` и финальном сообщении пользователю. Этот документ не объявляет push успешным до такой проверки. После клонирования коммит отчёта можно найти без доступа к серверу:

```bash
git log -1 --format=fuller -- docs/session_report_2026-10-23_ru.md
git rev-parse 43edac89d8a38ed1551195048e6383ced1479399:src
git rev-parse 43edac89d8a38ed1551195048e6383ced1479399:tests
git diff 43edac89d8a38ed1551195048e6383ced1479399 HEAD -- src tests
```

Ожидаемые source и tests TREE указаны в конце отчёта. Последняя команда должна дать пустой diff для финального docs commit. Полный MAIN TREE в конце относится к принятому source commit, а не к следующему коммиту документов.

## Дальнейшие шаги по приоритету

1. Отдельной задачей расширить symbol domain на module-level constants и named classes. Добавить consumer references, в том числе чтение `config.feature` из TSX. Сохранить честные границы lexical references и runtime semantics.
2. Подготовить agent onboarding и содержательную демонстрацию на реальном Next.js-проекте. Проверить путь от поиска до memory, edits, watcher и review заметки реальным агентским workflow.
3. Оценить sustained incremental indexing и GC по evidence длительной работы. Сначала измерить reanalysis, capture и рост generations, затем выбрать ограниченный change без ослабления provenance и истории.
4. Вести независимую исследовательскую проверку отдельно. Подготовить annotation, held-out design и scientific evaluation своим согласованным процессом. Продуктовый PASS их не заменяет.

Сессия останавливается после уже разрешённой публикации. Текущая продуктовая база равна accepted main `43edac89`. Интегратор и reviewer завершили свои owned watch/process/temp lifecycle и сохранили cleanup receipts. Автор этого документа не запускал watcher, fixtures или отдельный environment. Новые features в эту финализацию не входят.

## Источники и сохранённые доказательства

Основной переносимый набор ссылок находится в репозитории. Команды сверены с [основным CLI parser](../src/cami/cli.py), [memory CLI parser](../src/cami/product/memory/cli.py) и [watch CLI parser](../src/cami/product/watch/cli.py). Контракты и ограничения связаны выше относительными ссылками, рассчитанными на расположение этого отчёта в `docs/`.

Следующие дополнительные материалы являются server-local evidence. Они не включены в Git этим документом и могут быть недоступны читателю GitHub. Их существенные inputs, outcomes и ограничения изложены выше.

| Материал | Server-local pointer |
| --- | --- |
| Fresh Stage 5 exact-MAIN acceptance | `/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/stage5-main-review/20261023T1800Z-r1/REPORT.md` и `final-receipt.json`. |
| MAIN delivery и новые CLI-проверки интегратора | `/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/stage5-main-integration/20261023T174926Z/HANDOFF.md`, `integration-receipt.json`, `reused-evidence.json`. |
| Независимый accepted Stage 4 | `/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/stage4-main-review/20261023T165329Z-r3/REVIEW.md`. |
| Независимый isolated WATCH+OPT review | `/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/corrected-watch-union-review/20261023T1736Z-r1/REPORT.md`. |
| Точный corrected OPT measurement | `/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/context-gap-review/20261023T164400Z-r1/REPORT.md`, `paired-results.json`, `diagnostic-proof.json`. |
| Cleanup и продолжение | `/root/.claude/orchestrate/change-aware-memory-invalidation/cleanup/20261023-cleanup/REPORT.md` и `RESUME.md`. |
| Исторический read-only remote audit | `/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/final-session-report/20261023T175958Z-draft-8e369c/git-audit-before.json`, `remote-probe.json`, `git-audit-after.json`. |

Финальная привязка продукта сохранена как MAIN TREE `677f32b64de7a3919464dd76c655eb51cdfa1f84`, source TREE `ac78ecf07326cfaa666c15367d54d70fe23ba4d0`, tests TREE `53d2876ad78fed4a507cf5a7e184a431c828af3a`. Feature patch SHA-256 равен `84e1d10bd513da67d97c8b7d6353765808d8682b6a0b3d81edc3864073801937`. Эти значения связывают отчёт с конкретным принятым кодом, независимо от будущего docs commit.
