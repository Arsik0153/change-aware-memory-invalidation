# Исследовательская работа 29 октября 2026

Текущий режим: непрерывная самостоятельная работа до явной остановки пользователем.
Пользователь удалил автоматизацию и отменил прежнее ограничение19:00UTC.
Новые таймеры не создаются. Ранее действовавшее окно до19:00 и остановка новых этапов
в18:45 относятся только к исходной постановке; ниже сохранена история работы.

## Краткая контрольная точка

- Последний завершённый полный suite: **1046 passed, без пропусков**, на `44c77d3`;
  Ruff и mypy прошли. Source snapshots до и после совпали; hashes журналов проверены.
  Позднейшие diagnostic/watch drivers проверены профильными suites и реальными
  запусками; новый полный suite для этих commits пока не заявляется.
- Синтетическая проверка смешанных историй: 36 запусков политик, 15 552 проверенных
  состояния памяти, без расхождений с отдельным oracle. Число вызовов валидатора:
  5184 / 5184 / 1736. Сокращение на 66,5123% относится только к этим fixtures,
  не к общему времени работы или результатам на реальных репозиториях.
- Bootstrap: 600 synthetic trials с известной истиной; доступность интервалов
  отделена от условного покрытия. Отдельный точный расчёт объясняет отказы из-за
  пустых resamples и влияние числа bootstrap-повторов.
- Product memory проверена через CLI на закреплённых Click, Requests и локальном
  TypeScript-репозитории. Контролируемые изменения и восстановление файлов прошли.
- Восстановлены материалы независимого review: 630 candidate claims, пустые формы
  parent/provenance review и проверенные source archives. Реальных независимых
  ответов пока нет; основной cohort не допущен.
- В дополнительном pytest-профиле v2 все 63 прямых вызова на 21 parent завершились
  успешно. Это иной способ исполнения frozen probe; production pytest runner
  не изменён. Результат не создаёт независимых подтверждений или научного допуска.

Подробности, ограничения и доказательства приведены в этапах ниже.
Журнал решений: `reports/research-20261029/decisions.tsv` (append-only).

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

## Первый этап: исходная проверка и manifest

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

## Двенадцатый этап: точная механика доступности bootstrap CI

Post-pilot план зафиксирован до расчёта в f87015d, реализация с19tests — d205f08.
Для прежних шести сценариев и B50/100/500/2000/10000 вычислены30 точных конечных
вероятностных выражений, без новой Monte Carlo выборки. При фиксированном Z
вероятность available=(1−(Z/K)^K)^B; интегрирование по Binomial(K,1−q) даёт
безусловную вероятность. Предел при B→∞ равен q^K. Итерации считают failed draw,
а исходный zero denominator означает0iterations.

Reviewer gpt-6.1-sol независимо подтвердил формулы,19tests,все hashes и30строк
100-digit Decimal (максимальная scaled разница2.12e-15). K2/B2/q.5 проверен точным
перебором: availability17/32,iterations11/8. Для K50/q.1 availability снижается
с60.75% приB50 до14.32% приB2000 и5.57% приB10000. Это не рекомендация менять B
и не оценка coverage. У сохранённых100 datasets K50 conditional expected count21.319,
observed20; generator expected count14.322. Ожидания разделены явно.

Научный текст и ограничения: bootstrap_availability_mechanism_2026-10-29.md.
График проверен по PNG и показан через html_render. html_preview не смог запустить
headless Chrome (exit1); это ограничение preview среды, не ошибка численного расчёта.
Артефакты и review record сохранены отдельно, исходный pilot не изменён.

## Тринадцатый этап: confirmation boundaries и честный environment pilot

Прямой check-inputs принимал synthetic_manual parent receipt в dataset_kind=real;
scorer аналогично принимал synthetic reference labels для real run. Оба случая
воспроизведены synthetic fixtures до исправления (real-confirmation-boundary-before.log,
real-label-boundary-before.log). Теперь real input принимает объявленные independent
methods, с independent_test для behavior и human_review для prose. Старый tokenizer
oracle разрешён только для symbol_exists. Real scoring проверяет методы child labels,
которые действительно входят в метрики; посторонние строки общего файла не используются.
Synthetic workflows сохранены. Эти metadata checks не доказывают реальное авторство.

Reviewer gpt-6.1-sol нашёл старый producer, несовместимый с честной границей:
pilot-environments автоматически создавал receipt из текста smoke probe и вызывал
research run. Метод не добавлен в allowlist. Команда переведена на execute_probe
только для pinned parents; теперь это automated observations, без receipts, labels,
admission и child execution. Report schema2 отдельно фиксирует eligibility=false.
Сохранены probe и pinned Docker profile; поддерживаются root/src layouts Click.

Независимый review новой orchestration подтвердил authority boundary, но указал,
что fatal exception оставлял status=running. Исправлено: после каждого parent
сохраняется progress; исключение записывает failed, run ID, причину и prefix artifacts.
При failed общий test_executions=null, отдельно известны completed-parent attempts.
Тест с успешным первым parent и ошибкой второго сохраняет правильный partial report.

Focused suite после migration:129 passed; тесты используют mocked execute_probe и
проверяют orchestration, не контейнеры. Более ранний набор core/input/scoring/aggregate:
166 passed. Подготовлен отдельный byte-identical config view20Click parents без изменения
исходного prepared dataset. Следующие проверки — настоящий CLI с Docker и полный suite
на неизменном HEAD. Ни один реальный child не будет исполнен.

Реальный CLI после migration завершён на всех 20 Click parents. Выполнено 60
контейнерных повторов frozen smoke probe: все passed. Все 200 artifact hashes
environment_report.json проверены; receipts, labels и child execution отсутствуют.
В отдельных 20 контейнерах с тем же image/profile после загрузки pytest проверено,
что образ сам не содержит Click, а click/click.core/click.testing загружены из /repo
и совпадают по SHA-256 с соответствующими Git blobs. Это отдельная проверка origins,
не telemetry из исходных 60 повторов. Все raw outputs и воспроизводимый audit driver
сохранены в reports/research-20261029/click-parent-{smoke,origins}-v1.

Полная проверка HEAD 042de36: 982 passed за 450.09 s, без skipped; ruff/mypy passed.
Source snapshots совпали, scoped source status пустой, все hashes logs проверены.
Read-only check_dataset на restored real dataset также прошёл: 63 runs, 630 candidates,
0 supplied receipts, 63 preview runs, 630 known_incomplete provenance, labels_path=null.
Это проверка согласованности входов, без policy execution и без научного admission.
Evidence: confirmation-boundary-full-verification и restored-input-integrity-v2.json.

## Четырнадцатый этап: product memory на настоящем TypeScript-репозитории

В отдельном clone локального seo-articles (HEAD 85070f607449b32dc3d039a81a5951749ec2aa34)
выбран format-count.ts:formatCount. После исходного context и до мутаций профиль
зафиксирован коммитом 64b280f. Шесть authored mutations проверяют те же predicates,
что Python checks: unrelated/body carry, signature contradiction, parse uncertainty,
delete contradiction, restored facts и sticky manual-review. Target code не исполняется.

Driver получил frozen profile с HEAD/source hash/unique anchors, source roots и явный
compiler cache; output/cache не могут оказаться внутри repo, traversal/symlinks запрещены.
Оба TypeScript прогона прошли по18CLI commands. Reviewer независимо проверил v1,
36stream hashes,21source objects и все actual verdicts. Найденная потеря executable
mode при delete/recreate воспроизведена отдельным failing test и исправлена;14tests pass.
Повтор v2 также passed,36hashes verified,исходные bytes/mode восстановлены.
Оригинальная рабочая копия пользователя осталась чистой. Реальных labels/receipts нет.

Подробнее: product_memory_real_repositories_2026-10-29.md. Raw contexts приватного
локального приложения остаются в ignored runs; committed manifests содержат hashes.
Следующий шаг — проверить полную совместимость и продолжить аудит исследовательских
границ/готовности независимой разметки; эта product проверка не снимает main admission.

Полный suite на неизменном HEAD 98f6dbe: 992 passed, 4 skipped за447.00s;
ruff/mypy passed. Scoped source snapshots совпали и были clean, все log hashes
проверены. В этой invocation не был задан CAMI_TEST_IMAGE, поэтому четыре Docker
checks запущены отдельно с ранее подготовленным pinned image; результат будет
записан после завершения. Результат 992 не включает пропущенные Docker checks.

## Пятнадцатый этап: восстановление независимого provenance-review пакета

Штатный parent-only audit повторён на restored dataset в новый каталог. Все630claims,
63groups и summary main/replay совпали с историческими counts. Проверены643hashes,
точное равенство root/group rows и source copies,389parentGitblobs;1739исходных файлов
не изменились. Новых semantic labels нет, ни один known_incomplete не снят.

Архив output/provenance-review-20261029.zip содержит645entries и630пустых forms;
включена инструкция, явно отделяющая automated verified от независимого решения.
Архив проверен после записи; source/raw evidence остаются локально. Свежий пакет
убирает зависимость review от отсутствовавших путей прежней машины. Подробнее в
provenance_audit_report_ru.md и reports/research-20261029/provenance-restoration-v1.

Отдельный Docker suite завершён:4passed,992deselected за15.84s на том же HEAD98f6dbe
и pinned original image. Таким образом все996тестов выполнены успешно двумя
запусками; не следует называть это одним full run без skipped. Evidence отдельно
в typescript-product-docker-tests.{json,log}.

Независимый reviewer provenance подтвердил hashes,630digest bindings,ZIP CRC/inventory,
389Gitblobs и1260subject/anchor observations. Замечание о неполных parent trees
устранено в новом ZIPv2: добавлены URLs,local paths,63parent IDs и инструкция
исследования пропущенной поддержки вне сохранённых файлов. V1 не перезаписан.
Все643evidence hashes v2 проверены. Целостность не является semantic review,
а source-before остаётся локальной записью, не внешним сертификатом.

Далее: расширить synthetic development проверку селективного engine на заранее
описанные истории с отдельным oracle. Это позволит проверять carried states при
смешанных изменениях, не подменяя отсутствующую независимую real-разметку.

## Шестнадцатый этап: mixed-history synthetic structural stress

План12seeds×18transitions×24claims зафиксирован в16e539f до генерации;
реализация и проверки —0242dfd. Авторские ожидания generator сверяются отдельным
stdlib tokenize/compile-only oracle на actual Git blobs. Closure выполняется до
child commits и только под automatic_fixture independent=false. Human labels нет.

Design review выявил недостаточный контроль config/hash inventories и state metadata,
смешение planned/effective mutations и пропуск variants после verifier exception.
Все четыре исправлены до полного запуска;24focused tests passed. Hash-inventory
обход сначала воспроизведён failing regression. Tests с обновлёнными hashes также
ловят подмену policy/provenance/state/cost. Ошибка одного verifier не скрывает остальные
variants. Ошибочный strict dict compare optional provenance fields исправлен нормализацией;
исходные bytes отдельно hash-bound. Все промежуточные test logs сохранены.

Полный запуск на0242dfd:12seeds,36completed CLI runs,5184child items наvariant,
15552проверенных memory states,5472oracle observations;0mismatches. Maintenance calls:
all_validate5184,original_incomplete5184,closed_structural1736. Разность3448(66.5123%)
относится к этому authored fixture и не включает closure/oracle/index/Git costs.
Из216scheduled events185меняют Git tree. Supported/contradicted/uncertain:3761/751/672.

Независимый reviewer gpt-6.1-sol заново проверил actual Git blobs tokenizer+AST,
всеstates/selectedverdicts/lineage,CSV rows,36configs/input inventories/provenance,
12closure packages и13153raw hashes. Материальных расхождений нет. Все151source files
snapshot совпали с clean scopedHEAD. Общий parent и частично общие history prefixes
исключают трактовку15552rows как независимых samples. Synthetic evaluation_eligible=true
не является real admission;real_experiment_eligible остаётсяfalse.

Evidence: reports/research-20261029/structural-stress-v1;raw runs отдельно ignored.
Текст и повторение: structural_closure_demo_ru.md. График показан через html_render;
PNG inspected,headless html_preview снова exit1. Full suite с Docker ещё выполняется
на том же unchangedHEAD; итог будет добавлен после проверки snapshots/log hashes.

Полный suite этапа16 завершён на0242dfd:1020passed,0skipped за466.94s, включая Docker;
ruff/mypy passed. Source snapshots clean и совпали; hashes каждого журнала проверены.
Следующий этап — отдельная parent-only диагностика frozen pytest probe без заранее
импортированного pytest runner. Она не изменит production validator, protocol admission
или claim/probe bytes; сначала будет зафиксирован самостоятельный diagnostic plan.

## Семнадцатый этап: отдельная диагностика frozen pytest function

План зафиксирован в c717dbb: 21 исторический parent, один неизменённый probe,
три прямых вызова на parent. В контейнере нет установленного pytest framework;
исполняется функция без fixtures, conftest, plugins и assertion rewriting.
Это дополнительный способ наблюдения, не изменение production validator.
Происхождение загруженных pytest-модулей проверяется в том же процессе по parent
Git blobs. Claims, frozen probes и основной admission protocol сохранены.

V1: 60 returned, 3 technical errors. Единственный проблемный parent требует
packaging при импорте. Ошибка сохранена; v2-план с добавлением packaging26.0
зафиксирован в92a3564 до повторного прогона. Все21parents повторены, без исключения
неудобного случая. V2 на44c77d3: 63 returned, 0 technical errors. Это восстановление
среды после наблюдаемого сбоя, а не подтверждающий эксперимент по исходному профилю.

Проверены147artifact hashes,65input hashes и366same-process origin records,
соответствующих122distinct parent Git blobs. Числа origin records не являются
числом независимых тестовых случаев. Независимый reviewer gpt-6.1-sol проверил
оба результата, stdout/payload equality, Git blobs, frozen plans, неизменность
общих inputs и происхождение Docker layers; материальных расхождений не обнаружил.
Его review завершился до полного suite; итог suite проверен отдельно ниже.

Полный suite:1046passed,0skipped за459.98s, Ruff/mypy passed. Проверяемый HEAD44c77d3
оставался неизменным, scoped source status чистый; оба snapshots и hashes всех
трёх журналов сверены. Evidence: parent-function-full-verification,
parent-functions-v1/v2 и parent-function-results-review.json. Подробности
в annotation_restoration_2026-10-29.md. Независимых реальных labels/receipts нет,
основной cohort по-прежнему не допущен.

Далее: исправить сохранение частичного прогресса старого parent-environment
диагностического driver при исключении между группами. Сейчас завершённые
observations могут остаться без сводки, а manifest — со статусом running.

## Восемнадцатый этап: сохранение незавершённых parent diagnostics

В старом check_parent_environments.py исключение между группами оставляло manifest
running и не публиковало накопленные observations/summary. Семь новых проверок
сначала упали: snapshot failure, probe failure, KeyboardInterrupt и четыре случая
output внутри исходных данных/репозитория, включая symlink. После исправления
51 профильный тест прошёл. Реализация в a217a3b; production validator не изменён.

Теперь каждая завершённая группа сохраняется до начала следующей. Обрабатываемое
исключение сохраняет failed status, группу и тип ошибки, hashes накопленных файлов.
В failed/running summary test_executions=null: внутри незавершённой группы могли
исполняться контейнеры. Отдельный completed_group_test_executions описывает только
законченные наблюдения. Output проверяется до Docker и не может быть внутри inputs,
candidates или репозиториев. Это не гарантия восстановления после SIGKILL/сбоя диска.

Реальный smoke на a217a3b: frozen probe первого Click parent выполнен в трёх Docker
контейнерах, supported. Затем driver намеренно прерывает чтение второго parent.
Сохранён failed manifest, одно завершённое observation, все artifact hashes сходятся,
inputs и clean source snapshots до/после совпали. Это инъекция сбоя, а не естественное
падение исторического parent. Evidence: parent-environment-progress-v1 и docker.log.

Независимое ревью gpt-6.1-sol не выявило существенных дефектов; reviewer отдельно
выполнил13tests. Предыдущий полный1046suite относится к44c77d3; после a217a3b выполнены
51focused tests и реальный Docker smoke, а не новый полный suite. Ни labels,
ни parent receipts, ни child executions не создавались.

Далее: связать полученные development результаты с вопросами исследования и явно
отделить инженерную проверку, synthetic cost observations и недостающую независимую
оценку качества на реальных переходах.

## Девятнадцатый этап: научный разбор накопленных результатов

Добавлен research_findings_2026-10-29_ru.md: вопросы исследования, определения
exposure/retention, synthetic structural результаты, статистические ограничения,
product checks, исторические environments и условия допуска основного cohort.
Это development synthesis, не заявление о подтверждении основной гипотезы.
Исходное исследовательское предложение и submission documents не переписаны.

Машинная проверка сверяет арифметику, шесть строк bootstrap-таблицы, counts
product CLI/parent functions/cohort, привязку полного suite к44c77d3 и13локальных
ссылок. Сохранены hashes16источников. Первая попытка checker предположила одинаковую
схему v1/v2 audit и остановилась на KeyError attempts; исправлен путь к существующему
v1 summary.container_attempts, log ошибки сохранён. Данные не менялись.

Независимый reviewer повторил checker и проверил математическую интерпретацию,
границы oracle independence, единицы измерения, admission и хронологию: существенных
замечаний нет. Проверка текста не повторяет исходные эксперименты и quantiles.
Evidence: reports/research-20261029/research-synthesis-v1. В docs/README.md добавлена
ссылка на связный разбор, чтобы важные выводы не требовали чтения всей хронологии.

Далее: проверить фоновое обслуживание product memory на настоящем локальном
TypeScript repository, читая persisted state до любого foreground context,
который сам мог бы обновить память. План мутаций и границы проверки будут
зафиксированы до запуска; это engineering development, не real-label experiment.

## Двадцатый этап: фоновое обновление на реальном TypeScript source tree

План891bec9 расширил предыдущий foreground memory check до watcher со scope src
в pinned seo-articles clone. Ключевой критерий: persisted SQLite state читается
независимым stdlib reader до context, который сам мог бы обновить память. После
context head/counts не должны меняться. Frozen expected mutations сохранены.

До запуска независимый reviewer обнаружил ownership bug драйвера: watch stop после
проигранного launch мог остановить чужую сессию. Исправлено: свободный lease до
старта, привязка к started event собственной сессии, cleanup только через SIGTERM
owned Popen. Tests покрыли уже занятую копию и проигранную гонку. Protocol stop
не вызывается даже после предварительной проверки, чтобы убрать race смены session.

V1 на61f0ca0 сохранил восемь background source-mutation phases, но завершился failed:
после успешного foreground note CAS driver ошибочно требовал эту generation в
historical latest_successful watcher. Failure и integrity audit сохранены;
owned process остановлен, clone восстановлен. В c4a55e2 зафиксирован v2-план до
повтора: все phases сохранены, меняется только явная атрибуция note publication.
Реализация892695e,27focused tests passed, Ruff passed.

V2 на892695e прошёл12phases:11persisted-before-query proofs, из них8source mutations,
2начальное/стабильное состояние и1foreground note update; последний этап — stop.
35foregroundCLI exit0,492initial source references. Проверены85raw hashes, Git bytes,
context/persisted equality, session attribution, inputs, runtime и clean source
snapshots. Nodev24.15.0, прежний доверенный compiler. Исходный repo и clone чистые.
Ruff всего проекта и mypy52files passed; full suite повторно не заявляется.

Подробности: product_watch_real_repository_2026-10-29.md. Evidence: product-watch-v2,
failed-v1 и invocation logs. Это authored engineering check, не performance или
real-label experiment. Historical JSON/DB hashes сохранены; raw SQLite bytes
каждой промежуточной phase отдельно не архивировались. Независимый reviewer
подтвердил85v2/339v1 artifact hashes,158source files,496source objects,все11phase
states/context outputs и исторические поколения в конечной SQLite. Существенных
замечаний нет; старое время публикаций опирается на logs и frozen driver.

Следующий научный вопрос: как различие и пересечение denominator support двух
политик влияет на доступность paired bootstrap. Предыдущая точная формула
охватывала совпадающие знаменатели. Новый условный разбор не будет менять estimator
или использовать реальную разметку; план фиксируется до расчёта таблиц.

## Двадцать первый этап: разные denominator support sets в paired bootstrap

Планea263dd зафиксировал15support configurations×4B до расчёта. Формула недопустимого
resample выведена включением-исключением: ((K-L)/K)^K+((K-R)/K)^K-
((K-L-R+J)/K)^K. При ненулевых исходных знаменателях availability=(1-r)^B.
Это условный анализ фиксированных support sets, не новый Monte Carlo dataset.

Реализация600d379: exact Fraction для одного resample и Decimal100 для конечного B.
23tests прошли: полный перебор masks/draws K2..4,144production sequences,
shared-support reduction, границы, симметрия, монотонность и сохранение tiny values.
Рассчитаны все60rows; минимальная положительная вероятность8.709809816e-603.
Основной estimator не менялся, real labels/admission не использовались.

Независимый reviewer использовал integer four-state DP, exact rational power
и Decimal160. Все60rows согласованы: maxrelative error3.014e-100, максимум0.469
serialized ulp. Перепроверены336support assignments,67328resamples,144production
sequences,7zero-support cases,160source hashes и6artifact hashes. Математических
замечаний нет. Первичная plot autoscale выше1 исправлена в374fb8a; v2таблицы
побайтно равныv1, source snapshots обеих версий clean/equal. PNG inspected и HTML
показан; headless preview вновь Chrome exit1.

При K20,L=R8,B2000 полное пересечение даёт92.948510% availability, отсутствие
пересечения86.394024%. Это не coverage и не unconditional population probability.
При K2,L=R1,J0,B2 availability1/4: отсутствие совместно положительного кластера
само по себе не делает интервал недоступным. Подробности и воспроизведение —
bootstrap_availability_mechanism_2026-10-29.md, evidence paired-support-v1/v2.

Далее: проверить, можно ли использовать уже сохранённые denominator-support
поля отчёта для объяснения отказа CI без повторного исполнения политик. Если
добавляется такой diagnostic, он должен явно сохранять not_applicable/zero_sample
и не переименовывать теоретическую availability в наблюдаемую частоту или coverage.

## Двадцать второй этап: область применимости denominator-support анализа

Прямой аудит compute_metrics и aggregate._intervals показал, что основные exposure
и retention имеют одинаковые label denominators у политик на общем cohort.
Проверены729synthetic scorer combinations:3labels×3states для3claims, set-cardinality
oracle отдельно от scorer loops. Шесть rate denominators фиксированы labels;
contamination,precision,F1 могут иметь зависимую от состояния поддержку. Для F1
D=|P_binary|+|C|, поэтому support меняется только в кластерах с C пустым.

V1audit5995df0 ошибочно ожидал denominator=null при not_applicable и завершился
failed с0completed cases. Scorer сохраняет raw counts, но value=null; aggregate
проверяет reason до bootstrap. Исправлен только auditor в749f01c. V2 прошёл729cases
и14580applicability checks; оба artifact hashes и source snapshots совпали.
Synthetic labels явно authored oracle; policy algorithms не запускались.

Независимый reviewer перепроверил всеcases/counts, source history и прямые aggregate
отказы для not_applicable,raw count,replay. Существенных замечаний нет. Перебор
не охватывает retired/freshness mismatches; это не доказательство всего scorer.
87focused tests passed на5995df0; после двухстрочной коррекции auditor выполнен
v2 и его independent recomputation. Между версиями production не менялась;
фраза source unchanged в прежней строке журнала относилась к проверке сразу
после v1failure, а не к тождеству всего исходного дерева v1/v2.

Таблица знаменателей и научная интерпретация добавлены в
bootstrap_availability_mechanism_2026-10-29.md. Evidence:metric-denominators-v1/v2,
metric-denominators-focused.log. Новый механизм overlap нельзя выдавать за
дополнительный источник различий availability primary exposure/retention,
если их cohort/labels корректно совпадают.

Далее: собрать переносимый научный отчёт из проверенных выводов и графиков,
с сохранившейся границей между development evidence и pending real experiment.
Исходные proposal/submission и старые output/intermediate_report* сохраняются.

## Двадцать третий этап: переносимый научный отчёт

Подготовлен отдельный русский progress report на семь страниц с двумя графиками,
формулами, результатами и ограничениями. Его evidence cutoff — 4e13583; builder
зафиксирован в6a284aa и исправлен в9f071d3. Исходные proposal/submission и старые
output/intermediate_report* не изменялись. Зависимости документов закреплены в
requirements/report.txt и установлены в отдельной среде; production среда сохранена.

Первая сборка корректно создала PDF, но получила failed из-за трёх ложных
пропусков текста: pdftotext -layout перемешивал строки соседних ячеек. Сохранены
её manifest, ошибка и исходная сборка. Во второй сборке semantic check использует
-raw, а layout extraction остаётся для чтения. Все118абзацев/ячеек присутствуют.
Все7страниц v1 осмотрены; PNG всех7страниц v2 побайтово совпадают с ними.

Отдельный reviewer gpt-6.1-sol сверил31artifact hashes,20evidence sources,
118ordered Markdown/DOCX/PDF blocks,162source hashes,72production/schema files
относительно1046-test snapshot44c77d3 и все60paired-support probabilities.
Существенных замечаний нет. Проверка не заменяет human annotation; основная
эмпирическая гипотеза остаётся pending. Текущий полный suite не заявляется.

Пакет output/research-progress-20261029-v2.zip содержит36files, проверены35hashes
и CRC. Размер592072bytes;SHA256:
d02fd0702937dfaaf4593161b9f6a505d0eed69a97847ab92437c94c85d5eca4.
README объясняет, что компактный пакет не включает все raw runs/corpora/images.
Исходный текст:docs/research_progress_report_2026-10-29_ru.md;
инструкции:docs/research_report_delivery_2026-10-29_ru.md;
доказательства:reports/research-20261029/report-build-v1/ и report-build-v2/.

Далее: проверить, какие поведенческие свойства уже покрыты development fixtures
и есть ли полезный проверяемый пробел за пределами existence/signature stress.
Новый эксперимент, если нужен, сначала фиксирует oracle и протокол; основная
разметка, held-out и платные API остаются вне разрешённого выполнения.

## Двадцать четвёртый этап: поведенческая история со скрытой зависимостью

План1aceb7f зафиксировал6переходов×4варианта для одного synthetic behavior claim
f()==1. Driver и отдельный finite AST oracle запущены на0c2f04d. Oracle прочитал
реальные Git blobs и подтвердил значения1,2,2,1,3,1,1; никакой ответ CAMI не
использовался для truth labels. Parent receipts и labels явно synthetic authored;
реальные человеческие ответы не создавались.

Все4production run CLI и4score CLI завершены. Maintenance validations:
all_validate6,intact5,known_missing6,hidden_missing2; preflight по1накаждыйвариант.
69реальных Docker probe executions:39passed и30assertion failures. Проверены
24states,selection,carry metadata,costs и descriptive metrics. Hidden_missing
сохранил ложную доступность на2из3contradicted items;остальные0/3;retention3/3везде.
Меньше проверок у hidden_missing здесь означает ошибку, не безопасную экономию.

19focused tests иRuffpassed. Независимый gpt-6.1-sol проверил312raw artifact hashes,
74input hashes,197nested artifact hashes,34nested inputs,166runtime source files,
7sourcevalues ивсе69payloads. Source snapshots совпали; blocking findings нет.
Принято ограничениеBH-SCOPE-1: второй переход изолирует revalidation из-за
previously_unavailable, но успешные восстановления имеют и другие change triggers.
Поэтому причинное объяснение recovery одним fallback не заявляется.

Документ:docs/behavior_dependency_history_2026-10-29.md.
Raw:runs/behavior-history-20261029-v1; компактные evidence:behavior-history-v1.
Figure/CSV/HTML:behavior-history-figure-v1;PNG просмотрен,24CSVrows и5hashes сверены.
HTMLshown; headless Chrome preview failedexit1, это не скрыто как successfulpreview.
Никаких populationCI,таймингового ускорения или real-effectiveness conclusions.

Далее: проверить один из оставшихся пробелов реального рабочего процесса —
полноту и пригодность пакета независимой разметки для передачи человеку —
без заполнения форм за разметчика и без запуска основного held-out.

## Остановка по просьбе пользователя

Пользователь остановил самостоятельную работу из-за лимитов. Последний завершённый
исследовательский этап —24, commit c2bf001. Отслеживаемых незакоммиченных изменений
перед этой записью нет. Активных экспериментальных процессов и работающих reviewer
agents нет. Автоматизация ранее удалена пользователем; новые таймеры не создавались.

Предложенный parent-only HTML viewer не реализовывался: выполнено только начало
чтения существующего пакета. Это идея следующего этапа, а не готовая возможность.
Готовые переносимые DOCX/PDF/ZIP находятся в output/research-progress-20261029-v2/ и
output/research-progress-20261029-v2.zip. Бинарные пакеты и локальные raw runs не
добавлялись в Git; исходники, инструкции, manifests, hashes и проверки закоммичены.
Старые artifacts/ и output/intermediate_report* сохранены без изменений.

Последняя полная проверка:1046passed,0skipped на44c77d3; production и schemas
после неё не менялись. Позднейшие drivers проверялись профильными tests и actual
runs, включая19focused tests и69Docker executions последнего этапа. Независимая
человеческая разметка и основной held-out эксперимент остаются невыполненными.
