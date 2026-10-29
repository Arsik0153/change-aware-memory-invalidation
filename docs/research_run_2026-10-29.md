# Исследовательская работа 29 октября 2026

Рабочее окно: до 19:00 UTC. Автоматическое продолжение в этом же чате каждые
15 минут, завершение новых этапов после 18:45. Это механизм продолжения работы,
а не обещание непрерывного исполнения при недоступном приложении.

## Цель и критерии

Продвинуть проверяемость научного контура CAMI и подготовку следующего эксперимента.
Каждый законченный этап должен иметь отдельный commit, воспроизводимую команду,
сохранённый результат и явное описание ограничений. Строго отделять synthetic
и development результаты от независимого held-out исследования.

Исходный commit: `28d7288`. Незакоммиченные `artifacts/` и
`output/intermediate_report*` существовали до начала работы и не включаются в этапы.

## План

1. Сохранить исходные pytest, ruff и mypy без перезаписи прежних результатов.
2. Усилить идентификацию проверяемого исходного кода в verification manifest.
   Сейчас checks.json не связывает PASS с commit или bytes файлов и не отмечает
   изменение исходников во время проверок. Проверить поведение на временном Git repo.
3. Аудировать статистику и границы experimental scoring. Исправлять доказанные
   ошибки с тестами; не менять протокол задним числом под желаемый результат.
4. Расширить synthetic development проверки и/или готовность разметки, выбирая
   конкретный следующий этап по результатам аудита.
5. Подготовить русский отчёт с командами, commits, фактическими результатами,
   ограничениями и следующими необходимыми действиями человека.

## Научные ограничения

Независимые parent receipts и child labels основного исследования отсутствуют.
Автоматические наблюдения не считаются человеческой разметкой. M6 и платные API
не запускаются. Предыдущие пилоты и продуктовая приёмка не доказывают исследовательскую
гипотезу. Времена текущих проверок не используются для утверждений об ускорении.

## Текущий этап

Исходная проверка запущена командой:

```sh
.venv/bin/python scripts/verify_cami.py --out reports/research-20261029/baseline
```

Журнал решений: `reports/research-20261029/decisions.tsv`.
Следующим запускам следует читать этот файл, журнал и git log до выбора задачи.

### Контракт нового verification manifest

Schema 2 записывает Git HEAD, scoped Git status, SHA-256 каждого исходника,
совокупный digest, SHA-256 журналов и статус running/passed/failed. Scope включает
src, tests, scripts, schemas, docker, lockfile и корневые конфигурации проверок.
Добавленные untracked исходники и удалённые tracked исходники учитываются.
Разные снимки до и после проверок запрещают итоговый PASS.

`source_snapshots_match` означает совпадение двух наблюдений, а не непрерывный
мониторинг. Изменение с последующим возвратом bytes между снимками не обнаруживается.
Для приёмки нельзя редактировать исходники во время запуска; для строгой изоляции
нужен отдельный неизменяемый checkout. Manifest не закрепляет полное состояние
операционной системы или установленных пакетов. Времена проверок не benchmark.

Первый baseline запуск пересёкся с редактированием verification script и новым
тестовым файлом. Его результат используется только как диагностический, не как
доказательство проверки точного исходного commit. После завершения нужен стабильный
запуск новым script в новом каталоге.

### Контрольная точка первого этапа

Commit `ba3b711` содержит manifest schema 2 и пять focused tests. Focused pytest,
ruff и mypy прошли; журналы сохранены рядом с decisions.tsv. Независимый review
и внесённые по нему исправления описаны в review-verification.md.

Полный новый запуск начат после commit:

```sh
.venv/bin/python scripts/verify_cami.py --out reports/research-20261029/stable-verification
```

На этой контрольной точке он ещё выполняется. **Следующему продолжению сначала
прочитать checks.json и журналы; не редактировать исходники и не коммитить, пока
этот запуск не завершён.** Рабочие session IDs harness: baseline 69254,
stable-verification 84680. Если sessions недоступны, проверить процессы и файлы,
не предполагать успех. После завершения сохранить результат отдельным commit.
Исходный legacy baseline тоже ещё выполняется. Параллельность этих двух запусков
исключает любые выводы об их сравнительной производительности.

Следующий научный этап: проверить paired cluster bootstrap и aggregate scoring
на независимых малых примерах (размеры кластеров неодинаковы, нулевые знаменатели,
общая парная перестановка, повторяемость seed). Сначала установить ожидаемые
результаты независимо от реализации. При отсутствии ошибки добавить только
содержательные недостающие проверки и протокол synthetic эксперимента.

Стабильный прогон завершён: **824 passed, 4 skipped**, ruff passed, mypy passed
(52 source files). Проверены status=passed, source_snapshots_match=true и SHA-256
всех трёх журналов. Начальный HEAD `ba3b71194284410a5e87d6b27c8837789f8a1fcb`,
source digest `52fe5524bf6bf4afdb75c1138dbf176f2d5787d68a1263b5099172606e122762`.
Ограничение на изменения source/HEAD снято после завершения этого запуска.

## Второй этап: статистический контракт

Гипотеза проверки: paired cluster bootstrap должен оценивать разность micro rates,
переносить целый кластер для обеих политик одновременно и не скрывать неопределённые
resamples. Добавлены семь случаев в `tests/test_bootstrap_contract.py`.

Для двух кластеров left=(1/1, 0/3), right=(0/1, 3/3) ожидаемая micro-разность
равна 1/4−3/4=−1/2. Среднее двух кластерных разностей равно нулю и было бы другой
оценкой. Полный набор из четырёх равновероятных ordered resamples даёт разности
1, −1/2, −1/2, −1; точные percentile endpoints распределения равны −1 и 1.
Фиксированный запуск с 2000 повторов и seed 42 воспроизводит эти endpoints.
Ожидания получены из этих дробей до исполнения проверяемой функции.

Дополнительные проверки: одинаковые политики дают нулевую разность при любых
выбранных кластерах; перестановка политик меняет знак оценки и отражает интервал;
порядок ключей не влияет на результат; нулевой знаменатель в resample оставляет
интервал недоступным; три вида некорректных counters отклоняются.

Команда и результат:

```sh
.venv/bin/pytest -q tests/test_bootstrap_contract.py tests/test_evaluation.py tests/test_aggregate.py
# 32 passed
```

Журнал: `reports/research-20261029/statistics-contract-tests.log`. Ruff нового
файла также прошёл. Production алгоритм не изменён: эти случаи не выявили ошибки.
Полный suite после добавления только этих tests не повторялся; перед следующим
кодовым этапом использовать завершённый stable-verification как предыдущую точку.

Это проверка арифметики и контракта, не simulation study покрытия интервалов.
Два кластера выбраны для ручной проверяемости; пример не разрешает делать надёжные
популяционные выводы из двух реальных наблюдений. Частота отказа при нулевых
знаменателях и покрытие на редких противоречиях требуют отдельного заранее
описанного synthetic исследования.

Следующий полезный этап: спроектировать и исполнить такое synthetic исследование
без доступа к held-out labels, с фиксированными seed, размерами кластеров и частотой
противоречий. Сохранить raw результаты и явно разделить coverage среди доступных
интервалов и долю недоступных интервалов. Не менять оцениватель по результату без
отдельного development протокола. Альтернатива при обнаружении более важного
дефекта: сначала воспроизвести и исправить его.

Независимый source review второго этапа выполнил gpt-6.1-sol. Блокирующих замечаний
нет. Ревьюер подтвердил арифметику и смысл проверок, но сам тесты не повторял.
Он отметил оставшиеся пробелы: точность внутренних percentile и редкие
неопределённые resamples. Эти ограничения включаются в следующий synthetic этап.

## Третий этап: synthetic bootstrap pilot завершён

Протокол `db63bff` сохранён до запуска; runner `d3d133d`. Выполнены 600 trials
в шести заранее заданных сценариях. Результаты и воспроизведение:
[bootstrap study](bootstrap_study_2026-10-29.md).

Независимый reviewer gpt-6.1-sol проверил hashes и агрегаты по всем raw данным.
Профильный набор после добавления report validator: 43 passed; ruff и mypy passed.
Product и research production код не изменялся. Вывод ограничен synthetic pilot:
редкие активные кластеры дают много недоступных интервалов; высокое условное coverage
без количества доступных интервалов может вводить в заблуждение.

Следующий этап: проверить диагностику bootstrap в aggregate reports. Для каждой
метрики полезны число кластеров с ненулевыми знаменателями и причина отсутствия
интервала. Сначала прочитать действующие schemas и reporting, установить пробел
на реальном CLI артефакте, затем добавить минимальную диагностику без изменения
оценивателя и held-out правил. Это полезнее немедленного подбора другого estimator
по уже увиденным synthetic результатам.

## Четвёртый этап: диагностика bootstrap в отчётах

На реальном `cami analyze` для authored synthetic fixture подтверждён пробел:
старый JSON показывал общее число кластеров, а число ненулевых знаменателей
отсутствовало; отдельного intervals.csv не было. Артефакт до изменения:
`reports/research-20261029/diagnostics-before/`.

В `BootstrapInterval` добавлено optional `denominator_support` с числами кластеров
с положительным знаменателем слева, справа и одновременно с обеих сторон.
Это характеристика исходной парной выборки, не число resamples, не эффективный
размер выборки и не критерий допуска. Общие пустые кластеры остаются в выборке.
Диагностика вычисляется и при недоступной оценке или интервале.

`cami analyze` теперь пишет `intervals.csv` с dimensions, направлением сравнения,
оценкой, границами, причиной недоступности и support counts. Summary объясняет
значения и ссылается на CSV. Для replay и not_applicable bootstrap не запускается,
поэтому support остаётся null в JSON и пустым в CSV. Исторические JSON без поля
читаются новым кодом как unknown; из общего количества кластеров support не
выдумывается. Чтение новых расширенных JSON старой strict-версией не гарантируется.

Не менялись estimator, RNG, правила resampling, допуска и held-out. Проверено:

- Все прежние поля 600 сохранённых synthetic интервалов совпадают точно с
  результатом нового кода. Воспроизводимая команда:
  `.venv/bin/python scripts/verify_bootstrap_equivalence.py --study reports/research-20261029/bootstrap-study-v1 --out NEW_DIRECTORY`.
- Полный CLI metrics.json совпал после удаления только новых diagnostic fields
  при одинаковых входах и порядке runs. Артефакты `diagnostics-before/` и
  `diagnostics-after-ordered/`, результат `diagnostics-cli-equivalence.json`.
- Первая проверка CLI использовала сортировку runs вместо прежнего порядка.
  Отличался только порядок run_directories. Этот запуск сохранён в diagnostics-after;
  для строгого сравнения выполнен отдельный запуск с исходным порядком.
- Тест sparse metric сохраняет 2 общих кластера при 1 ненулевом и показывает
  zero_denominator_in_resample; пустой кластер не удаляется.
- Тесты проверяют разделение сторон, legacy JSON, replay и публичный CLI export.

Независимый reviewer gpt-6.1-sol не нашёл блокирующих замечаний и выполнил
22 focused tests. По его предложению дополнительно закреплён null support для
replay. Итоговый расширенный профильный набор и static checks записаны в
`diagnostics-tests-final-reviewed.log`, `diagnostics-ruff.log`, `diagnostics-mypy.log`.
Полный прогон будет запущен после commit; до его завершения не менять source/HEAD.

Следующий этап после полного прогона: аудит готовности независимой разметки.
Проверить существующие main/replay пакеты, наличие независимых parent receipts,
неизменность seal и реальные ограничения historical behavior environments.
Результат должен быть проверяемым readiness-отчётом, не выдуманной разметкой.

Четвёртый этап сохранён commit `29dcd56`. Итоговый профильный набор: **48 passed**.
Полный прогон запущен новым verifier в `reports/research-20261029/diagnostics-full-verification/`,
harness session 67150. На этой контрольной точке он ещё выполняется.
До завершения не менять source и HEAD. Следующее продолжение сначала читает
checks.json и проверяет журналы; при отсутствии завершения выполняет только
чтение существующих annotation пакетов. После завершения фиксирует результат.

## Пятый этап: восстановлены реальные материалы разметки

Полный прогон `29dcd56` завершён: **847 passed, 4 skipped**, ruff/mypy passed.
Проверены manifest status, source_snapshots_match и hashes всех журналов.
Ограничение на source/HEAD снято до добавления следующего инструмента.

На VPS не было старых corpora и ready пакетов. Восстановлены три pinned bare
репозитория, проверены 63 revision chains, перенесены только пути без reselection.
Все 63 regenerated claim files совпали с историческими hashes. Собраны реальные
материалы для 630 parent и 900 child заданий; все формы остаются пустыми.

[Отчёт восстановления](annotation_restoration_2026-10-29.md) содержит команды,
проверки и ограничения. Пользовательский архив: `output/annotation-restored-20261029.zip`.
Это новый наш файл; старые output/intermediate_report* и artifacts/ не затронуты.
Архив остаётся локальным вне Git; hash и состав сохранены в annotation-package.json.

Независимый reviewer подтвердил hashes, Git object bindings и отсутствие готовых
ответов. Добавлен переносчик fixed manifests, 5 targeted tests passed; ruff и mypy
passed. Он воспроизводит те же relocated bytes. Production код не менялся.

Следующий этап: восстановить Docker fixture environment и запустить четыре
до сих пор пропускавшихся Docker tests на синтетических данных. Это не разрешает
исполнение held-out behavior claims. Сначала изучить Dockerfile.probes и тесты,
использовать реальный digest построенного образа, сохранить журналы. Затем можно
планировать historical environment pilot отдельно от независимой разметки.

## Изменение режима по указанию пользователя

Пользователь сообщил, что удалил автоматизацию, и поручил продолжать работу
до его явной остановки. Прежнее ограничение 19:00 UTC отменено. Новые таймеры
не создаются; работа продолжается в активной сессии. Исторические записи выше
сохраняют прежний план, но не задают текущий срок.

## Шестой этап: Docker восстановлен

Собран docker/Dockerfile.probes с закреплённой Python 3.12.12 base и package
versions. Реальный локальный digest сохранён в docker-image.json. Четыре ранее
пропускавшихся Docker tests теперь прошли: `4 passed, 852 deselected`. Это
интеграционные synthetic tests, не повтор полного suite и не real-data labels.

Run inputs и raw per-repetition evidence сохранены в runs/docker-fixture-20261029,
команда, digest, exit code и hash pytest log — в docker-tests.json. Дополнительно
пересчитаны реальные repeat outcome files в docker-repeat-audit.json.

### Следующий опыт: только parent environments

Добавлен scripts/check_parent_environments.py. Он принимает строгие parent-only
inputs и frozen candidates, проверяет hashes и происхождение claims, выполняет
по одному заранее заданному behavior probe на parent каждой из 63 групп.
Child commits, labels и policy outcomes не являются входом. Child-поля отклоняются.

Весь заранее заданный parent набор проверяется на одном pinned probe image.
Source paths заданы явно `.` и `src`, чтобы поддержать оба исторических layout.
Успех означает только автоматическое наблюдение в данной среде. Script не пишет
parent receipts, child labels, final seal и не меняет claims. Ошибки среды
сохраняются как insufficient_evidence. Никакая группа не заменяется по результату.

Это environment-preparation diagnostic, не admission review и не held-out policy
эксперимент. Независимость будущих reviewers остаётся отдельным требованием.
Тесты runner: 4 passed; проверены parent snapshot вместо HEAD-child, отсутствие
receipts/labels, immutability inputs и отказ при подмене probe/hash или child fields.

### Итог первого parent environment diagnostic

Все 63 группы обработаны; фактических контейнерных попыток 123. Click: 20 supported
после 60 повторений. Requests: 22 environment_error до контейнерного исполнения
(0 попыток), поскольку ext/requests-logo.ai имеет 2189478 bytes при capture limit
2097152. pytest: 21 environment_error после 63 попыток; обнаружен preloaded
pytest/_pytest collision. Это не labels и не опровержения claims.

Независимый reviewer gpt-6.1-sol подтвердил соответствие всех 63 planned groups,
проверил 333 artifact hashes и 4 focused runner tests. Полные исходные логи
остаются в runs/parent-environments-20261029-v1; manifest, summary, observations
и по одному полному примеру на repo сохранены в reports/research-20261029/parent-environments-v1.

Следующий диагностический запуск заранее меняет только явно заданный предел
размера Git blob на 4 MiB, сохраняя прежний default 2 MiB. Все 63 parent группы,
образ, probes и assertions сохраняются. Это проверка materialization blocker,
а не исправление показателя путём исключения неудачных групп. Первый опыт сохранён.

Второй parent diagnostic (4 MiB, прежний image) завершён: 63 группы, 186
контейнерных попыток. 21 Requests-группа дошла до collection и выявила отсутствие
urllib3. Ещё одна не материализована из-за symlink tests/certs/mtls/client/ca.
Click остаётся 20 supported, pytest 21 environment_error. Все ограничения
сохраняются; symlink не заменён пустым файлом и не проигнорирован.

Для третьего diagnostic заранее подготовлен отдельный image на Python 3.9.25
с точным digest base. AST-чтение setup.py всех 22 Requests parents подтвердило
совместимость выбранных runtime dependency pins с каждым объявленным constraint.
Setup-код на хосте не исполнялся. Выбран urllib3 1.22 и idna 2.6, чтобы удовлетворить
ограничениям ранних parents; Python 3.9 позволяет сохранить исторические imports
из collections, несовместимые с Python 3.12. Тестовый runner остаётся pytest 8.4.2.
Requests как установленный пакет в image отсутствует; импортируется Git-снимок.

Изменяются сразу Python и installed dependencies. Следовательно, возможное
изменение результата относится к комбинированному environment profile, а не к
отдельной библиотеке. Frozen probes, parent выборка и 4 MiB limit сохраняются.
Точный image и установленный package inventory сохранены в parent-image.json,
проверка pip check прошла. Это finite probe compatibility, не общая пригодность
старых библиотек для production или сети. Контейнеры probe остаются без сети.

Независимый review gpt-6.1-sol не нашёл blockers в capture override и profile;
подтвердил сохранение default2MiB и ограничений symlink/LFS/submodule, проверил
requirements audit. Финальный профильный набор 125 passed, ruff/mypy passed.

Третий parent diagnostic завершён: 63 группы, 186 попыток. Click20 и Requests21
получили supported в новом профиле. Requests1 остаётся symlink_unsupported до
исполнения. pytest21 остаются infrastructure collisions. Независимый reviewer
проверил 438 artifact hashes, одинаковые populations/claim hashes v2 и v3 и
Python3.9.25 в успешных logs. Репрезентативные повторные imports в exact image
подтвердили, что click.utils и requests.utils читаются из /repo, а не site-packages.
Эти повторные imports не были telemetry оригинальных logs. Никаких receipts,
labels или admission из этих результатов не создано.

## Седьмой этап: отдельный parent-only review packet

Добавлен scripts/export_parent_review.py, который отбрасывает child revisions,
child source evidence и child assignments, сохраняя исходный parent population.
В самостоятельном пакете 630 primary и 126 previously assigned secondary rows.
В него не входят automated parent observations или policy metadata.

Reviewer gpt-6.1-sol нашёл недопустимое прохождение неизвестных form/source полей
(потенциальная передача child metadata). Исправлено проверкой точного набора полей
форм, source entries и probes, плюс Claim schema validation. Добавлены regression
tests для неизвестных metadata. При проверке реальных signature claims обнаружено,
что strict Python validation отвергает JSON arrays; исправлено чтением через JSON
schema boundary и закреплено отдельным тестом. Некорректный export не создал output.

Итог: 9 tests passed. Исправленным exporter создан runs/parent-review-20261029-v2;
все 456 файлов совпали с независимо проверенным чистым исходным export. Пользователю
доступен output/parent-review-20261029.zip; hash и состав в parent-review-package.json.
Это новый локальный архив, в Git сохранены инструмент, инструкции и evidence.
[Инструкция parent-review](parent_review_instructions_ru.md).

Обнаруженное следующее ограничение: import-parent принимает одно решение на claim
и не поддерживает прямой импорт двух parent answers. Нужно проверить путь сохранения
двойной разметки и adjudication перед фактической передачей пакета людям. Кроме того,
проверить, сохраняет ли importer uncertain человеческое решение о behavior при
невозможности выполнить probe, не создавая supported receipt.

## Восьмой этап: сохранение неопределённости и авторства parent-review

Гипотеза аудита: importer смешивает требование к положительному behavior receipt
с требованием к любому ответу и смешивает способ проверки с авторством. Оба дефекта
воспроизведены failing tests до исправления. Теперь uncertain/contradicted behavior
ответ сохраняется без receipt; supported по-прежнему требует independent_test.
Ошибка среды сама по себе не служит основанием contradicted.

RawAnnotation допускает independent_test от human либо independent_oracle, сохраняя
фактический объявленный тип автора. Human double-review coverage считает только
human, включая человека, самостоятельно выполнившего тест. Программная валидация
не доказывает независимость или личность автора. Реальные формы остаются пустыми.

Независимый reviewer gpt-6.1-sol не нашёл blockers, проверил 82 теста. После его
предложения добавлен contradicted case: финальный focused suite 83 passed;
ruff и mypy (52 source files) passed. Все новые ответы — явно synthetic fixtures.
Preview, admission и heldout gates сохранены. Evidence: parent-review-import-reviewed-tests.log,
behavior-uncertainty-before.log, test-authorship-before.log.

Следующие шаги: полная проверка с Docker на неизменном HEAD, затем product memory
на настоящем локальном репозитории с явно авторскими development mutations.
Двойные parent answers/adjudication остаются отдельной незакрытой задачей.

Полная проверка восьмого этапа завершена на HEAD 55be9d6: 876 passed за 446.92 s,
без skipped, ruff и mypy passed. Включён исходный pinned Python3.12 Docker image.
Начальный и конечный source snapshots совпали; source status пустой, hashes всех
logs проверены. Evidence: reports/research-20261029/parent-review-full-verification.

## Девятый этап: product memory на реальных локальных исходниках

Гипотеза проверена через публичный CLI на отдельных clean clones Click8.1.8 и
Requestsv2.32.3: изменение тела сохраняет structural predicates, signature change
скрывает signature expectation, parse error не доказывает отсутствие, deletion
доказывает отсутствие в захваченном view. Ручная заметка остаётся needs_review
после точного byte revert и возвращается только после явного CAS update.

Для каждого repo выполнены 18 команд, включая idempotent registration retries,
шесть authored mutation phases, history и ручное review. Первый результат независимо
проверен reviewer gpt-6.1-sol: реальные verdicts, source-object и log hashes, mutation
bytes и чистые восстановленные clones. Два замечания к driver исправлены: проверка
contradicted verdict и запись passed только после cleanup. Усиленный v2 повторён
на обоих repo, 36 exit0; все log hashes и source restoration проверены.

Воспроизводимый инструмент scripts/check_product_memory.py побайтно совпадает с
проверенным v2 driver. Исходный v1 driver восстановлен из точного текста до исправления
и сверён с hash, записанным в обоих manifests. Evidence и ограничения:
[product_memory_real_repositories_2026-10-29.md](product_memory_real_repositories_2026-10-29.md).
Никаких research labels, child policy runs или API-запросов этот этап не создаёт.

Следующий этап: общий resolver для raw annotations/adjudications и parent batch
import, который сохраняет оба ответа, disagreement и history. Проверять только
synthetic fixtures до получения настоящих ответов; реальный пакет остаётся пустым.

## Десятый этап: двойной parent-review и история adjudication

Гипотеза: для реального parent-review недостаточно экспортировать две формы —
importer должен сохранять оба ответа, не скрывать disagreement и не подменять
полный denominator количеством ответивших. Добавлен import-parent-batch с общим
resolver, извлечённым из существующего annotate-import без изменения его правил.
Legacy import-parent сохраняет ограничение одного ответа на claim и использует
тот же core. Все originals, полный adjudication chain и точные bytes batch сохраняются.

Неразрешённое разногласие либо последний unresolved adjudication не создают receipt.
Supported behavior adjudication требует independent_test так же, как первичный ответ.
Coverage human double-review считается по полному candidate population; отдельно
проверяется выполнение ранее назначенных вторых reviews. 20% произвольных двойных
ответов не закрывают невыполненные assigned items. Preview и eligibility не меняются.
Повторный импорт поверх reviewed dataset запрещён, даже когда старые uncertain
ответы не создали receipts: исходные решения нельзя молча перезаписать.

Independent review gpt-6.1-sol подтвердил основную логику, но воспроизвёл пропуск
hash проверки экспортированного source evidence. Дополнительные failing tests
выявили прием preview=false и несовпадающего run parent. Исправлены проверки
preview/parent, claims, обеих копий probes, parent evidence и assignments до output.
Evidence: parent-batch-integrity-before.log (3 failures до исправления).

Финальные focused проверки: 108 passed; ruff и mypy passed. Включены реальный CLI
на synthetic fixture, agreement/disagreement, reopening adjudication, неверные IDs,
child decisions, неполный population, source/probe drift и защита прежних originals.
Никакой synthetic ответ не импортировался в реальную выборку. Read-only аудит её
материалов подтвердил 63 группы, 630 claims, 389 parent source files, 63 probes,
630 пустых parent forms и 0 receipts/admitted. Данные проверки и ограничения
в parent-batch-real-preparation-audit.json; инструкция parent-review обновлена.

Следующие шаги: полный suite на новом неизменном HEAD; обновить локальный ZIP
parent-review актуальной инструкцией, сохраняя все исходные blank assignments.
После этого продолжить научный аудит и воспроизводимость результатов.

Parent review archive обновлён отдельным файлом output/parent-review-20261029-v2.zip.
Все 456 файлов исходного blank packet сохранены побайтно; изменены только две
добавляемые инструкции. В архиве 458 файлов, 630primary/126secondary пустых заданий;
CRC и каждый извлечённый файл сверены с источником. Hash:
25da88d670536e0faf5ae5e7de126c377d7b55ce162d4a7410991bd2d9f49074.
Первый ZIP не изменён. Manifest: parent-review-package-v2.json.

В docs/README.md устранено устаревшее утверждение, что indexer/memory/engine ещё
не реализованы. Submission proposal оставлен историческим источником формы,
а актуальные development evidence и pending empirical requirements теперь
имеют прямые ссылки. Внешний статус подписи и подачи не предполагается.

Полный suite после десятого этапа: HEAD 4fcbdfd, 901 passed за 441.40 s, 0 skipped,
ruff/mypy passed. Source snapshots совпали, исходное scoped дерево было чистым;
hashes всех logs сверены. Evidence: parent-batch-full-verification.

## Одиннадцатый этап: независимая проверка всех bootstrap summaries

Воспроизведена неполнота report validation: на отдельной synthetic fixture bias=999.0
проходил после обновления summary hash. Теперь scripts/report_bootstrap_study.py
независимо пересчитывает все summary fields, проверяет analytic truth, paired counts,
generator support, empty probabilities, interval metadata и denominator diagnostics.
Валидатор не вызывает generator summarize и не использует production estimator.

Reviewer gpt-6.1-sol выявил valid floating-boundary false rejection и acceptance
невозможных endpoint counters. Исправлены verified-saved-truth boundary comparison
и multinomial-category support; regression tests покрывают оба случая. Финально
37 passed, ruff/mypy passed. Намеренно изменённый bias теперь отклоняется до output.
Все оригинальные 600 trials повторно validated без изменения данных/численных выводов.
Report v3 содержит hash validator и явно исключает random-stream/quantile replay
из заявленной области проверки. Подробнее в bootstrap_study_2026-10-29.md.
