# Фоновая память на настоящем TypeScript репозитории

Цель development-проверки — установить, что watcher самостоятельно публикует
обновлённую память после изменений настоящих исходных файлов. Обычный
`memory context` тоже обновляет память, поэтому успешного ответа этой команды
недостаточно для доказательства фоновой работы.

## План и область проверки

План зафиксирован в `891bec9` до реализации драйвера и запуска мутаций:
[seo_articles_protocol.json](../examples/product_watch/seo_articles_protocol.json).
Используется отдельный clone локального проекта `seo-articles` на revision
`85070f607449b32dc3d039a81a5951749ec2aa34`. Исходная рабочая копия не изменяется.
Subject — `src/shared/lib/format-count.ts:formatCount`; scope watcher и запросов —
весь `src`, включая остальные поддерживаемые исходники проекта.

Для subject регистрируются `symbol_exists`, `signature_equals` и ручная заметка.
Проверяются неизменённое состояние, создание/переименование/удаление другого файла,
изменения тела и сигнатуры, синтаксическая ошибка, удаление subject-файла,
возврат исходных bytes и явный review заметки. Ожидания задаются заранее:
структурные проверки переносятся при эквивалентных изменениях; signature mismatch
отличается от parse uncertainty; состояние заметки `needs_review` сохраняется
после revert до явного обновления с ожидаемой revision.

Это один выбранный subject и авторские мутации. Проверка не оценивает
естественную частоту ошибок, эффективность политики на исторических изменениях,
latency SLA или пользовательскую пользу. Код целевого приложения не исполняется.

## Как подтверждается фоновая работа

Драйвер читает bounded bytes опубликованной SQLite и загружает их в независимую
in-memory SQLite connection. Он использует stdlib-reader из
`tests/watch/cli_driver.py`, без вызовов CAMI ProductMemory. Reader проверяет
согласованность product head, record states, index view, source references,
сохранённых source objects и checksum индекса. Чтение повторяется при незавершённой
публикации; live SQLite не открывается на запись.

После каждого изменения исходников сначала сохраняется persisted proof с ожидаемыми
source hashes и состояниями. Затем status должен связать эту generation
с успешным обновлением запущенного watcher. Явное CAS-обновление заметки имеет
другой источник публикации: foreground-команду update. Его persisted result
проверяется отдельно и не приписывается watcher. После этого вызывается
`memory context`. Его generation/index и содержимое должны совпасть с уже
сохранённой памятью; повторное чтение head/counts исключает незаметную публикацию
нового состояния самим foreground-запросом.

Источник ожидаемых verdicts — явно заданные мутации, не результат CAMI.
При этом reader использует контракт продуктового хранилища и общий SQLite runtime:
это независимый способ чтения, не независимое человеческое авторство и не
доказательство корректности всех возможных состояний базы.

## Владение процессом и восстановление

До регистрации памяти проверяется отсутствие watcher в disposable clone.
Идентичность новой сессии берётся из `started` event собственного дочернего
процесса и сравнивается с authenticated status. В cleanup драйвер отправляет
SIGTERM только своему `Popen` process, дожидается выхода и проверяет статус lease.
Он не использует `watch stop`, который заново обнаруживает текущую сессию:
при гонке это мог бы быть уже другой watcher.

Такой дефект первоначального драйвера был воспроизведён независимым reviewer
до реального запуска и устранён. Regression tests покрывают уже занятый clone
и ситуацию, когда после свободного preflight собственный launch проиграл гонку
и завершился. Частичные stdout/stderr сохраняются и при foreground timeout.

После остановки восстанавливаются исходные bytes и mode subject, удаляются
созданные драйвером файлы и проверяется чистота Git. Ошибка cleanup не допускает
`passed`. Source snapshots CAMI, hashes протокола/мутаций и compiler runtime
проверяются до и после прогона. Жёсткое завершение всего драйвера или сбой файловой
системы не являются проверенной гарантией восстановления.

Драйвер реализован в `61f0ca0`. До реального запуска прошли 10 профильных tests
и Ruff. Более ранний combined run содержал 22 tests, включая 8 ранних tests
драйвера и 14 tests foreground memory driver; это не число tests последней версии.
Независимое review относится к исходному дизайну; исправления проверены родителем.

## Повторение

Из корня CAMI, с установленным окружением и заранее подготовленным доверенным
TypeScript compiler cache, создайте новую отдельную копию закреплённого проекта.
Нужен доступ к тому же локальному репозиторию; его код не публикуется этим отчётом.
`--out` должен быть новым каталогом вне clone, `--cache-dir` — существующим
доверенным cache вне clone. Пример для текущей машины:

```bash
git clone --no-hardlinks /root/apps/seo-articles runs/watch-repeat-repo
git -C runs/watch-repeat-repo checkout --detach 85070f607449b32dc3d039a81a5951749ec2aa34
.venv/bin/python -m scripts.check_product_watch \
  --repo runs/watch-repeat-repo \
  --protocol examples/product_watch/seo_articles_protocol_v2.json \
  --out runs/watch-repeat-evidence --cache-dir /root/.cache
```

Протокол связывает конкретные bytes и revision: другая версия проекта требует
нового явно описанного плана. Драйвер отказывает при несовпадении и не подбирает
замены мутаций по результату запуска.

## Первый прогон и уточнение плана

V1 на61f0ca0 завершился с failed status на проверке `note_review`. Все восемь
мутаций исходников были обработаны watcher, а persisted state каждой мутации
проверен до context. Явный update заметки записал revision2 и снял needs_review,
но driver ошибочно потребовал эту foreground generation в historical
`latest_successful` watcher. Контракт status не требует приписывать чужую
публикацию фоновому процессу; ожидание драйвера было чрезмерным.

Failed manifest и журналы сохранены в product-watch-failed-v1, raw evidence —
в runs/product-watch-20261029/evidence-v1. Все hashes сошлись; source snapshots
CAMI и compiler runtime до/после совпали. Owned watcher завершился, clone чистый.
Неуспешный прогон не переименован в passed.

В c4a55e2 до повтора зафиксирован
[план v2](../examples/product_watch/seo_articles_protocol_v2.json). В нём сохранены
все subjects, мутации, порядок и ожидаемые states. Меняется только атрибуция
публикации note_review: foreground_explicit_update. Source-mutation phases
по-прежнему требуют подтверждённой background generation. Драйвер отвергает
попытку отключить эту проверку для других phases. Для note_review сохраняются
как актуальная product generation, так и historical watcher generation.

## Результат полного повторного прогона

V2 завершён на неизменном HEAD `892695e`: все 12 phases выполнены. В 11 phases
persisted state прочитан до запроса context; восемь из них следуют за мутациями
исходников, два проверяют начальное/неизменённое состояние, один относится
к явному foreground update заметки. Двенадцатый этап — завершение owned watcher.

Сохранены 35 foreground CLI-команд с exit0 и отдельный long-lived watcher process.
Это число технических вызовов, не число независимых научных наблюдений.
Начальный snapshot содержит 492 source references. После body mutation обе
структурные проверки сохранили исходные check IDs и timestamps; note требует review.
Signature mutation даёт contradicted для signature, parse — insufficient_evidence,
удаление — contradicted. После revert структурные утверждения снова supported,
а review заметки остаётся обязательным до явного CAS update.

Перепроверены 85 hashes raw artifacts, source inputs и фактические Git bytes subject.
Context generation/index и states совпали с предварительно прочитанным хранилищем.
Все восемь source-mutation generations сопоставлены с successful status собственной
watcher session. Для note update отдельно сохранён исторический watcher head:
он не подменён текущей foreground generation13. Owned process завершился с exit0,
lease свободен, source bytes/mode восстановлены и обе рабочие копии чисты.

Compiler runtime до/после одинаков: Node v24.15.0, SHA-256 compiler
`569177652966bd528c319171c7dd22860dbf72bde116cbc4f644f1d02bb12e39`.
Scoped source snapshots CAMI чистые и совпали. Итоговые профильные tests —27passed;
Ruff всего проекта и mypy52source files прошли. Новый full suite не выполнялся.

Evidence: [product-watch-v2](../reports/research-20261029/product-watch-v2/),
[invocation log](../reports/research-20261029/product-watch-invocation-v2.log).
Полные raw contexts, source objects и SQLite остаются в ignored
`runs/product-watch-20261029/evidence-v2`. Historical persisted JSON содержит
DB hash, но отдельные raw SQLite bytes каждой промежуточной phase не архивировались.
Это ограничивает повторный аудит исторических database pages; текущая конечная
база и сохранённые состояния доступны локально.

Независимый reviewer gpt-6.1-sol проверил все85v2 и339v1 artifact hashes,
158CAMI source files,496unique source objects, состояния/источники всех11phases,
context equality и session attribution. Исторические heads, record states и
source references всех11generations независимо сопоставлены с конечной SQLite
через in-memory query-only connection. Отсутствие отдельных byte snapshots
промежуточных DB остаётся ограничением, но логическая история в конечной базе
проверена. Существенных замечаний нет. Время прежних публикаций подтверждается
сохранёнными журналами и зафиксированным драйвером, не внешней аттестацией.
