# Продолжение исследования — 4 ноября 2026

Работа возобновлена по прямому поручению пользователя. Изучены Git history,
остановка d25d28c, отчёт предыдущего дня работы и восстановленный пакет.
Независимые parent receipts и child labels пока отсутствуют. Существующие
неотслеживаемые отчёты и архивы сохранены. На старте доступно 17 GiB; очистка
не требовалась.

## Переносимый просмотр parent-свидетельств

Экспорт теперь создаёт автономную `review.html` и дедуплицированные страницы
с исходниками. Полный claim, scope, predicate, parent commit, SHA-256,
назначение второго review и frozen probe доступны без разбора JSONL вручную.
Ответы остаются отдельными пустыми формами. Изменение не допускает cohort
и не запускает основной эксперимент.

На реальном восстановленном пакете: 630 parent-заданий, 126 вторых назначений,
306 HTML-страниц, 761 хешируемый артефакт, 198605 проверенных локальных ссылок
(включая построчные anchors; это не число независимых свидетельств).
Аудит: `reports/research-20261104/parent-viewer-audit-v2.json`;
воспроизводимый проверяющий скрипт: `scripts/check_parent_review.py`.
Архив `output/parent-review-20261104.zip` занимает около 6.5 MiB.
HTML проверен парсером; визуальный браузерный просмотр не проводился.

Дополнительно запрещены пути свидетельств, способные перезаписать формы,
manifest или HTML экспорта. Тесты покрывают такое пересечение, HTML в исходнике,
пропущенные исходники, frozen probe и сохранение оригинальных байтов.
Профильные проверки: 121 passed. Ruff и mypy (53 файла) прошли.

Общий запуск `.venv/bin/pytest -q` выявил существующую проблему сбора трёх
поздних исследовательских тестов: `ModuleNotFoundError: scripts`.
Журнал сохранён как `pytest-full.log`; этот запуск не является успешной
полной проверкой. Следующий этап — восстановить стандартную команду проверки
и выполнить полный набор, не маскируя ошибки через отдельный ручной PYTHONPATH.

## Восстановление стандартного pytest и следующий план

Корень репозитория явно добавлен в pytest `pythonpath`: исследовательские тесты
импортируют namespace `scripts`, который console entrypoint ранее не находил.
Полный collection теперь проходит; полный runtime-прогон выполняется отдельно.

До реализации нового запуска закреплён `examples/behavior_dependency/recovery_protocol.json`.
Предыдущий эксперимент не изолировал успешное восстановление, вызванное только
`previously_unavailable`. Новый synthetic development план задаёт четыре перехода:
прямое нарушение, восстановление вызова при ещё ложной зависимости, восстановление
скрытой зависимости, постороннее изменение. Предсказание для hidden_missing:
на третьем переходе единственная причина отбора — previously_unavailable;
повторная проверка должна восстановить доступность. План: 54 исполнения probe,
16 child states; никаких новых человеческих labels или held-out результатов.

Новый recovery-эксперимент завершён на e32e63e: 54 Docker executions,
16 состояний, единственный trigger восстановления в hidden_missing —
previously_unavailable. Снимки исходников совпали, inputs и артефакты проверены.
Подробности: [отчёт](behavior_hidden_recovery_2026-11-04.md).

## Проверка распространения по графу

После закрепления отдельного плана выполнены 208896 конечных случаев impacted():
все графы на трёх узлах с петлями и все графы на четырёх узлах без петель,
все множества изменений и глубины 0/1/2. Независимый по алгоритму shortest-path
oracle не выявил расхождений. Контроль неправильного направления ребра сработал.
[Подробный отчёт и ограничения](impact_graph_verification_2026-11-04.md).
Свободно около 17 GiB; удаление данных не требовалось.

## Проверки текущего этапа

Стандартная `.venv/bin/pytest -q` завершилась: 1108 passed, 4 skipped за449.88s.
Все четыре пропуска — Docker tests без CAMI_TEST_IMAGE; отдельный запуск с
закреплённым digest завершился 4 passed (1109 deselected). Во время общего
прогона добавлен один recovery parameter case: он отдельно прошёл в наборе
19 профильных tests. Общий прогон не является sealed проверкой одного Git HEAD:
параллельно добавлялись research drivers, поэтому для них сохранены отдельные
checks и снимки до/после фактических экспериментов. Production-код во время
общего прогона не менялся. Ruff и mypy прошли после последних additions.

Push 7a0cafa получил временный remote Internal Server Error от GitHub;
повторная отправка выполняется отдельно. Это не потеря локальных коммитов.

## Реальные Requests-parent: отдельная проекция исходников

План57f01f6, выполнениеe0c0c3f. Все22parent-группы успешно выполнили прежний frozen
probe в package-only проекции:66passed. Включены396file records/144unique Git blobs,
хеши отдельно сверены с Git. Обе исключённые symlinks находятся вне пакета.
Проекция и каждый исключённый путь сохранены; full-tree production отказ не менялся.
Это восстановление отдельного execution context, не admission или human labels.
[Отчёт с ограничениями](requests_package_projection_2026-11-04.md).
15профильных tests и статические проверки прошли; свободно17GiB.
Повторный push после ошибки GitHub завершился успешно до7a0cafa.

## Научное позиционирование

По первоисточникам проверены Anand v1, EA-Graph v1, A-MEM v11 и ChangeGuard v2.
В proposal добавлен пропущенный близкий предшественник EA-Graph и явно ограничена
заявка на новизну. [Сопоставление](research_positioning_2026-11-04_ru.md) связывает
новые результаты с последовательной памятью, стоимостью и неполнотой provenance.
Нового систематического обзора или сравнительного превосходства не заявлено.
Правки документации не входят в source scope текущего sealed suite; коммиты
отложены до завершения его снимков.

## Полная sealed проверка

На неизменном2329d7b завершён `scripts/verify_cami.py`:1115passed,0skipped,
pytest457.59s; Ruff и mypy прошли. Проверены совпадение source snapshots и hashes
всех трёх logs. Свидетельства:`reports/research-20261104/sealed-verification-v1/`.
Это итоговая полная проверка кода до следующей небольшой правки source viewer.

Дополнительная проверка обнаружила ошибку отображения: str.splitlines считал
form-feed отдельной строкой, хотя Python считает его пробельным символом внутри
строки. Минимальный пример показывал def f на строке3 вместо2. Среди фактических
экспортированных parent sources затронутых файлов0; существующий архив сохраняется.

Исправление viewer нормализует только CRLF/CR/LF, сохраняя form-feed внутри строки.
17focused tests прошли, включая соответствие Python AST line number для всех
трёх видов newline. Ruff/mypy прошли. Повторный экспорт всех630заданий дал
побайтно одинаковый manifest и761artifact hash относительно первого пакета:
существующий ZIP остаётся актуальным. Новое исправление проверено профильным
набором; полный1115-test результат выше относится к2329d7b.

## Воспроизводимый аудит Requests

Добавлен отдельный stdlib/Git verifier без Docker. На фактическом прогоне он
сверил22полных parent trees,144unique package blobs,66raw stdout payloads,
claim/probe identity и summary. Четыре отрицательных контроля отклонены, в том
числе три с пересчитанными artifact hashes. Отключение assertions через-O
отклоняется до выдачи отчёта. Случайный пересчёт checksum не маскирует подмену
подлежащих проверке данных; криптографическая аттестация исполнения не заявлена.

## Применимость критерия closure на реальных parent-данных

Read-only gate diagnostic:30/504structural candidates проходят только binding gate,
474отклоняются. На уровне distinct parent/module:23/345pass,322reject. Ни один
real claim не закрыт и не допущен. Основные первые причины — indirect writes и
dynamic namespace на уровне всего модуля. Это существенное ограничение переноса
fixture-критерия на реальные данные, а не ошибка truth labels.
[Отчёт](structural_closure_feasibility_2026-11-04.md).112focused tests прошли;
input/source/output hashes сверены; семь файлов preparation seal сохранили hashes.
Этот seal не является полным рекурсивным inventory всего каталога подготовки.

## Найден и исправлен дефект кэша при смене mode

Три regression cases сначала упали: symbol_validate сохранил доступность на
symlink, all/file_validate не восстановили обычный файл. Причина — одинаковый
blob ID при смене mode и reuse Module без учёта limitation. Ограниченные blobs
теперь обходят AST-кэш; INDEX_VERSION3, VALIDATOR_VERSION4. Реальный before/after
запуск с прежним дисковым кэшем подтвердил его неприменение и восстановление.
132focused tests, Ruff/mypy прошли. [Разбор](ast_cache_mode_fix_2026-11-04.md).
После коммита запускается новая полная sealed проверка, поскольку изменён основной
индексатор и versioning validator cache, а не только исследовательский driver.

Начат [разбор условия переноса структурного predicate](structural_carry_argument_2026-11-04.md).
Он объясняет, почему необходима проверка относительной эквивалентности с полным
валидатором, и явно отделяет её от независимой истины. Именно проверка предпосылки
корректного индекса выявила same-blob/mode cache bug. Нового разрешения closure
или изменения основных labels из этого рассуждения не следует.

## Полная проверка после исправления кэша

На неизменном e810a09276639510e1dc608f64c2ce518fd31476 прошли 1124 теста
за 456.56 s, без skips; Ruff и mypy также прошли. Source snapshots до и после
совпали, три SHA-256 логов сверены. Свидетельство:
`reports/research-20261104/sealed-verification-v2/checks.json`.
[Краткий обзор новых результатов](research_findings_2026-11-04_ru.md).

## Ограниченная проверка структурного переноса

План закреплён в2895ac2, runner вf4eeab9. На168случаях:136selected,
32carried; все32пропуска supported у свежего полного валидатора. Из всех
child verdicts:64supported,40contradicted,64insufficient_evidence.
Нарушений carry и расхождений warm/fresh index нет. Отрицательный контроль
со скрытым изменением сигнатуры обнаружен. Сверены6artifact hashes и
неизменность source snapshot.42focused tests прошли.

Первый запуск прямым путём script завершился до выполнения опыта из-за
импорта namespace scripts; правильная команда — `python -m scripts.check_structural_carry`.
Новый output не был создан до исправления команды.

Это168авторских случаев, а не независимые наблюдения и не оценка real-data
экономии.8size-limit cases дополнительно меняют внешнее ограничение чтения
и лежат вне аргумента с фиксированной конфигурацией.

## Обновлённый отчёт для обсуждения исследования

Собран четырёхстраничный отчёт на4ноября вMarkdown/DOCX/PDF и ZIP
с36компактными evidence files.55paragraphs/cells совпали сPDF extraction;
все4страницы визуально проверены основным ассистентом (не independent review).
Рисунок построен изsummary, первоначальное наложение подписей исправлено
до включения вPDF. Hashes всех файлов и ZIP contents сверены.

Сборщик теперь принимает отдельный dated spec вместо обязательной привязки
к29октября; прежний default сохранён. Current source/schemas совпадают
сe810a09, на котором прошёл полный набор1124тестов.
`reports/research-20261104/report-delivery/` содержитPDF/DOCX иdelivery records;
полный переносимый компактный пакет — `output/research-progress-20261104-v1.zip`.
Этот пакет не заменяет сохранённые полные raw runs.

## Уточнение ограничения binding gate

Post-hoc prerequisite profile: все504 кандидата проходят наблюдаемые технические
условия вне binding gate. Все условия вместе проходят30. Фактических сравнений
сигнатуры252; ещё252symbol_exists не требуют сравнения. Это не независимое
подтверждение и не изменение полномочий closure. Сверены189input hashes,
3artifact hashes и504строки с прежним gate diagnostic, включаяsourceblob hashes.
[Подробности](structural_prerequisites_2026-11-04.md).

## Проект пересмотра критерия и отдельные измерения времени

Подготовлен проект `docs/proposal_structural_closure_v2_2026-11-04.md`.
Он не меняет действующий addendum. Предлагается обсуждать поддержку точного
синтаксического predicate отдельно от blanket namespace gate, сохраняя
независимое parent-подтверждение и явное закрытие каждой review-ремарки.

Для измерений времени план закреплён в9f5f519, runner вb95ce4f.
40запусков идут последовательно с чередованием вариантов, пять повторений
на каждую комбинацию истории и варианта. Непосредственно перед ними выполняется
отдельный профиль all_validate, не включаемый в итоговое сравнение. CLI startup,
preflight и persistence входят втаймер; подготовка fixtures и проверка выходов — нет.
23focused tests прошли, в том числе четыре подмены raw probe output.
Действующие фоновые сервисы сохранены; нагрузка и их наличие фиксируются.

Измерения завершены:40CLI runs,615probe executions (345passed,270ожидаемых
assertion failures), без технических ошибок. Отдельный профиль добавляет21probe
и исключён из timing summary. Все40run outcomes совпали с ожиданиями истории.
Сверены2160outer artifacts,136inputs,1853nested artifacts; snapshots совпали.
МедианыCLI intact/all:9.24/10.73s и6.20/7.69s. Все5paired deltas intact
отрицательны в каждой истории; known_missing не даёт устойчивого различия.
Hidden_missing exposure быстрее, но оставляет2ложных доступности на историю.
[Полный разбор и ограничения](behavior_timing_2026-11-04.md).

Отчёт обновлён доv2:5страниц,2рисунка,49компактных evidence files.
Проверены63текстовых блока и все5страниц; ZIP hashes сверены.
Новая версия включает timings и post-hoc prerequisite profile. Предыдущийv1
сохранён вoutput и Git history; текущиеPDF/DOCX обновлены вreport-delivery.
Архив: `output/research-progress-20261104-v2.zip`.

## Конечная достижимость и реальный свидетель повторяющейся ошибки

План f339152, runtime64d0f19:12программ,50достижимых состояний,600переходов.
All/intact/known не имеют расхождений доступности; hidden имеет2ложно доступных
состояния и source-changing цикл без проверки. Отдельная stdlib-формула сверила
все600переходов и полноту графа. Два model negative controls и пять подмен
выходных артефактов отклонены.49focused tests прошли.

Извлечённый witness закреплён и исполнен вb8a804d:5Git commits,48Docker
executions (21passed,27assertion failures), всеожидаемые состояния подтверждены.
Две стороны цикла меняют только unrelated.py, дерево после оборота совпадает
сначалом. Hidden не выполняет maintenance validations и имеет3ложные доступности.
[Разбор модели, аудита и реального воспроизведения](behavior_reachability_2026-11-04.md).

Отчёт v3 включает конечный цикл и его Git/Docker-воспроизведение:
6 страниц, 3 рисунка, 66 компактных evidence files. Все 69 текстовых блоков
сохранились, шесть страниц визуально проверены. Новый finalizer связывает
visual review с SHA-256 именно этого PDF, проверяет точный inventory и ZIP.
Три отрицательных контроля отклонили review старого PDF, подменённый artifact
и лишний незапечатанный файл до создания archive/delivery.
`output/research-progress-20261104-v3.zip` — текущий переносимый пакет.

Исправление записи выше: первая упаковка v3 НЕ завершилась. Строгий finalizer
обнаружил пропуск вложенных manifest.json в inventory сборщика: старый фильтр
исключал любой basename manifest.json вместо единственного корневого файла.
Архив v3 не создан, опубликованная delivery оставалась v2. Первая тройка
отрицательных контролей отклонялась по этому общему дефекту, поэтому не считалась
изолированной проверкой трёх заявленных причин. Неудачная попытка и список
пропущенных файлов сохранены в report-packaging-first-attempt.json.
Сборщик исправлен; создаётся новая v4, затем контроли выполнятся заново
с проверкой ожидаемой причины отказа каждого.

Упаковка v4 успешно завершена после исправления: точный исходный inventory
содержит78artifacts; с привязанным кPDF visual review проверены79файлов ZIP.
Все шесть render pages побайтно совпали с ранее просмотренными страницами v3;
69текстовых блоков совпали с текущимPDF. Три изолированных отрицательных контроля
теперь отвергнуты по разным ожидаемым причинам, а не по общему дефекту inventory.
Текущий архив: `output/research-progress-20261104-v4.zip`, SHA-256
`2978a41818ca54396297c93eabe1e58b9095127dad69df03b914198e4bd1b5a2`.
PDF/DOCX иdelivery records действительно обновлены. Неудачнаяv3 сохранена как
незавершённый build, опубликованного ZIPv3 нет.

## Периодический аудит как ограничение длительности ошибки

План 1118604, runtime 7ab2d2c. Расширение конечной модели для K=1,2,4,8
дало 136 достижимых состояний и 1632 перехода. Максимальные серии ложной
доступности равны 0,1,3,7; все границы достигаются. Два дефектных правила
(сброс возраста при изменении исходника и срок с ошибкой на единицу) нарушают
границу и обнаружены. Проверены 15 фиксированных 40-шаговых workloads; это
логические счётчики, фактических Docker executions нет. Семь focused tests прошли.
Дополнительный аудит сверил явную формулу всех переходов и полноту графов.

[Разбор и условный аргумент](periodic_audit_bound_2026-11-04.md).
Production policy, основной протокол и реальные labels не изменены.
Этот результат выпущен отдельным дополнением, в шестистраничный PDF v4 не входит.
PNG визуально просмотрен; HTML preview снова завершился Chrome exit 1,
html_render успешно показал рисунок. Свободно 17 GiB, очистка не потребовалась.

Полная проверка на 61a04bf завершена: 1140 passed, 0 skipped, 459.80 s;
ruff и mypy также прошли. Начальный и конечный source snapshots совпали,
все три хеша логов сверены. Запись и логи сохранены в
reports/research-20261104/full-verification-61a04bf/.

Следующий опыт: временная исследовательская обёртка engine selector с K=2 и K=4,
12 реальных Git children и 93 ожидаемые Docker executions. Прототип подготовлен
в отдельном runs-каталоге во время полной проверки; 14 его проверок прошли.
Протокол фиксируется до Docker-исполнения, не заявляется как предваряющий
само проектирование прототипа. Production source и основной протокол не меняются.

Периодический Git/Docker опыт завершён: 93 executions (33 passed,
60 ожидаемых assertion failures), технических ошибок нет. Без аудита — 8
ложно доступных состояний; K=2 — 1 при 9 проверках; K=4 — 3 при 6 проверках;
all_validate — 0 при 12 проверках. Все 48 состояний и lineage совпали с планом.
Сверены 429 outer artifacts, 159 inputs, 253 nested artifacts и отдельная
deadline-формула. Snapshot неизменен. Все manifests явно research-only.

Рисунок прошёл визуальную проверку. Первый lint обнаружил однострочный цикл
в новом plot script; исправлен до генерации. HTML preview по-прежнему Chrome
exit 1; используется уже проверенный PNG и html_render.
[Разбор модели и реального исполнения](periodic_audit_bound_2026-11-04.md).

Отчёт v5 собран и опубликован: семь страниц, четыре рисунка, 86 компактных
файлов свидетельств. Все 77 текстовых блоков совпали с извлечением PDF;
все семь страниц визуально проверены. Finalizer проверил 100 payload files
архива, включая вложенные manifests и привязанный к этому PDF visual review.
PDF/DOCX в report-delivery обновлены. Текущий архив:
`output/research-progress-20261104-v5.zip`, 1827237 bytes, SHA-256
`e154662f9958621fabf0ce0d723546a571a065ca55b2b8ee1e294070483f3663`.
Модель периодического аудита и его реальное исполнение теперь входят в PDF.

Полный raw-пакет периодического опыта создан: 17104407 bytes, 490 payload files,
оба raw runs и точные исходники runtime. Stdlib-аудитор запущен системным Python
вне .venv: проверены 600 исходных hash references, 253 nested hashes и 384 source
files. Три rehashed tamper controls отвергнуты по ожидаемым разным причинам.
Первая подготовка контролей ошиблась в суффиксе stdout-файла (.stdout.log вместо
.log) и остановилась до создания повреждённого архива; после исправления все
три контроля действительно выполнены. Исходный пакет не менялся.

Архив: output/periodic-audit-raw-20261104-v1.zip. Docker image не включён;
его pinned identity сохранена. Свободно 16 GiB, удаление не требуется.

## Parent-only графы на реальных данных

План a04464b, runtime 5c1deca; первая попытка остановилась до graph construction:
ошибочно ожидались 126 behavior claims, фактически 63 behavior + 63 prose.
Исправление в 1714dee сохранило тот же набор. Успешный v2 охватывает 63 parents,
630 claims, 2131 module occurrences. Все 63 warm/fresh индекса совпали.

Во всех 63 behavior-кандидатах присутствуют subject, module и global unresolved.
2070 module flags добавлены linker; post-hoc простые import triggers объясняют
1912 из них (категории пересекаются). Сверены 1098 уникальных Git blobs,
68 output hashes, 190 inputs и все claim/graph flags. Child-данные не читались.
[Разбор и условное следствие для отбора](parent_graph_fallback_2026-11-04.md).
PNG просмотрен; HTML preview завершился Chrome exit 1, html_render используется
для показа. Дополнение пока не входит в семистраничный PDF v5.

## Проверяемый реестр ключевых чисел

Добавлен реестр из 41 scalar fact по 11 исследованиям/разрезам с hash каждого
источника, точным JSON pointer либо строгим извлечением pytest summary,
единицей измерения, scope и limits. Generated Markdown и TSV собираются из
фактических значений. Шесть тестов проверяют неверное число 126 вместо 63,
подмену источника, bool/int, escaped JSON pointer, неоднозначный лог и обязательные
units/limits. Первые lint-ошибки тестового файла исправлены до запуска тестов.

Первая генерация v1 содержала 33 facts; v2 добавила восемь counts/errors четырёх
вариантов реального периодического опыта. Источники экспериментов не менялись.
Реестр защищает перенос чисел, а не научную интерпретацию, независимость или
полноту исследования. Команда: scripts/check_research_facts.py --out NEW_DIR.

Полный набор на 418f58a прошёл: 1163 passed, 0 skipped, 460.07 s;
ruff/mypy прошли. Source snapshots идентичны; все три log hashes сверены.

Следующее расширение модели различает точный двоичный validator и validator
с корректными только положительными подтверждениями. Во втором допускаются
insufficient_evidence и отрицательные ответы даже на истинном predicate.
Условный аргумент K−1 сохраняется, отсутствие ложного скрытия — уже нет.
Протокол фиксируется до полного обхода; проектирование и четыре малых теста
выполнены в отдельном runs-каталоге во время предыдущей полной проверки.

Расширение с неполными вердиктами завершено: 64 состояния, 403 перехода для
двух моделей и K=1,2,4,8. В обеих максимум false availability равен K−1;
ложное скрытие отсутствует только у точного двоичного validator. Отдельная
формула сверила все допустимые переходы, достижимость, ранговые условия и
свидетели точной границы. Два дефектных правила дали unsafe self-loops:
ложный supported и перенос доступности при insufficient_evidence со сбросом
возраста. Проверены 12 output hashes, snapshots совпали, actual probes=0.
[Условные утверждения и результаты](availability_invariants_2026-11-04_ru.md).
PNG просмотрен; preview Chrome exit 1, html_render используется для показа.

Реестр v3 обновлён до 44 facts/12 разрезов: добавлены расширенные invariants,
полный pytest count обновлён до 1163 с явным commit 418f58a. Теперь каждый
generated ledger сохраняет байтовую копию использованного registry.json внутри
своего inventory; изменение или удаление исходного registry не теряет правила
проверки старой версии. Семь тестов прошли, включая восстановление проверки
из сохранённого registry после удаления исходного. v1/v2 оставлены как история;
текущая ссылка README указывает на v3.

## Символические условия для произвольного K

План 2052627, runtime e5ee97e. В изолированном Z3 4.16.0.0 выполнены 18 проверок:
6 UNSAT отрицаний целей, 6 SAT предпосылок, 6 SAT примеров/контрпримеров.
QF_LIA использует неограниченные Int; K не ограничивается четырьмя значениями
предыдущего конечного обхода. Proof objects сохранены, независимым kernel
не проверялись; это обязательства перехода плюс отдельный индуктивный аргумент.

Сверены 57 hashes, snapshots совпали; stdlib-аудитор повторно вычислил все 12 SAT
переходов. Две rehashed подмены отвергнуты. Wheel SHA совпал с официальным PyPI,
релиз не yanked. Первая попытка python -m venv не смогла вызвать ensurepip;
использовано новое окружение uv --seed, основной .venv не изменён.
[Подробный разбор](symbolic_availability_verification_2026-11-04_ru.md).

Консолидированный отчёт v6 опубликован: 9 страниц, 6 рисунков, 245 компактных
evidence files. В него включены real-parent graph profile, неполные вердикты,
символические условия для произвольного K и реестр 48 чисел. Все 92 текстовых
блока совпали с PDF extraction. Первые две страницы побайтно совпали с ранее
просмотренными v5 PNGs; страницы 3–9 просмотрены заново. Finalizer проверил
261 payload file архива. PDF/DOCX и delivery records обновлены.

Текущий архив: output/research-progress-20261104-v6.zip, 4113510 bytes, SHA-256
0b9286c58508373d6ae407ad95580e1d73419b628fbdaab52b2742ec1b7103b8.
Полный raw ZIP периодического опыта остаётся отдельным пакетом и не подменяется
компактными данными отчёта.

## Слепой AI development pilot и связь модели с кодом

Пакет36случаев зафиксирован вa738e58, анализатор в7b9f1de. Два свежих AI-контекста
и отдельно реализованный reference совпали:24supported,9contradicted,3uncertain.
Все12контролей дали ожидаемые ответы. Исходные ответы и helpers сохранены;
людей, новых labels, receipts и admission нет. Последующий аудит выявил
nested-class-global gap reference; отдельный screen не обнаружил ни одного
целевого global в36случаях. Дополнительный аудит подтвердил обязательные facts
и methodology обоих reviewer. Подробности: `ai_parent_pilot_2026-11-04_ru.md`.
При интеграции два теста сначала не нашли перемещённые CLI/schema; пути исправлены,
35тестов прошли. Это ошибки расположения тестовых ресурсов, не изменения решений.

Проверка переходов на1a7eeb1 дала499/499совпадений для403ребер и76канонических
контекстов. Оба отрицательных контроля обнаружены. Независимый stdlib-аудит
повторно вычислил записи и отклонил три подмены с обновлёнными hashes.
Подробности: `model_engine_translation_2026-11-04_ru.md`.

Перед новым transition challenge закреплены21синтетическая мутация и42claim-пары
(126policy states). Nested-class-global добавлен до запуска после независимой
находки reviewer; frozen reference остаётся неизменным. На диске свободно16GiB,
очистка не требовалась.

## Дефект class-global и исправление700ebf2

Исходныйchallenge наab9bd6e подтвердил разногласие production/reference для прямого
class-global и общий пропуск nested-class-global. Referencev2 зафиксирован в5ed6844;
его42ответа совпали с authored controls. При прежнем production четыре случая
оставались доступными при reference uncertain. После production-фикса700ebf2
таких случаев ноль, полные ответы совпали42/42, symbol selections выросли28→32.
Исходные before-v1, before-v2 и after-v2 сохранены раздельно. Утверждение uncertain
не переименовывается в доказанно false. См. `class_global_binding_fix_2026-11-04_ru.md`.

До исправления7regression failures и4passing controls. После —161связанный test,
Ruff/mypy; затем29engine+bindingtests, включая6реальныхGit-историй иотклонение
прежнего validation cache. Текущий файл содержит18регрессий. Полная sealed проверка
запущена на700ebf2; до её завершения source иHEAD не меняются.

График PNG/SVG просмотрен локально. html_preview снова завершился ошибкой
Headless Chrome exited unexpectedly (exit code1); html_render успешно показал
тот же локальный PNG. На диске свободно16GiB(78%занято), очистка не нужна.

Полная sealed проверка700ebf2 завершена:1248passed,0skipped,463.75s;Ruff иmypy
прошли. Source snapshots совпали, три log hashes сверены. Реестрv5 содержит
69показателей,17разрезов и17источников; старые реестры сохранены.

## Сводная поставкаv7

Сборка7d304ef включает11страниц,7рисунков и437компактных evidence-файлов.
Все11страниц визуально просмотрены после pdftoppm; текстовая проверка прошла.
PDF/DOCX и ZIPv7 опубликованы отдельно от прежних версий. Новый раздел описывает
AI-пилот с ограничениями,499переходов model/engine и раздельное исправление
reference/production class-global. Реестрv5 связывает69чисел с17источниками.

## Реальный структурный replay Click

На56750dd закреплены117входов и runtime sources до доступа к дочерним исходникам.
Реальный прогон завершён на том жеHEAD с одинаковыми source snapshots:24claims,
три истории длины1/12/1,112observations на вариант,448записей. Symbol/file/known/all
выполнили8/13/112/112дочерних validations, у всех0false_available,
0available_unknown и0withheld_supported. Родительские24проверки на вариант,
136reference calls и17sharedindexbuilds учтены отдельно.
Восемь contradicted observations — одинclaim shell_complete:ctx_args,
t.Dict→t.MutableMapping на пятом шаге длинной истории. После первой проверки
семь повторов вызваны previously_unavailable. Это точное синтаксическое изменение,
не установленный behavioralbreak. Независимый raw-аудит идёт отдельно.

График PNG/SVG сохранён и просмотрен. Первоначальный запуск renderer вreport-tools
не нашёлmatplotlib; запуск восновном.venv сзакреплённой зависимостью успешен.
html_preview снова завершился Headless Chrome exit1; html_render показал тот жеPNG.
Свободно около16GiB, очистка не нужна. Подробности:real_structural_replay_2026-11-04_ru.md.

Полная проверка49dc9c2 завершена:1259passed,0skipped,469.85s;Ruff иmypy53files
прошли. Источники до/после неизменны, три log hashes проверены. Свободно15GiB,
занято80%; очистка пока не требуется.

Независимый stdlib-аудитор интегрирован после полной проверки. Проверены562artifact,
117sealed,228historicalsource,136Gitpacket,24exactAIclaimbinding,448states и494costrows.
Десять групп контролей прошли, включая пять полностью перехешированных подмен.
Первоначальный staged код имел60Ruffstyle замечаний; новый вариант отформатирован,
привязка ROOT исправлена дляscripts/, outputs создаются эксклюзивно. Установленная
версия повторно прошла аудит иконтроли; прежние rawresults сохранены. Реестрv6:
82факта,18разрезов,19источников. Измерения не объявляются ускорением всегоrun.

## Сводная поставкаv8

Сборка5f0065f включает12страниц,8рисунков и1017evidence-файлов. Добавлены полные
rawpackets реальногоClick replay, независимый аудит, полная1259-test проверка
и82-фактныйреестрv6. Все12PNG-страниц визуально просмотрены; новыйPDF иZIPv8
проверены finalizer. Предыдущие версии сохранены. Частотаfalse_available
не интерпретируется как популяционная оценка, восьмикратное повторение одного
claim явно указано.

## Цена переноса отрицательного результата

Наcbfbe28 закреплены80файлов,17авторскихисторий31переход,три стратегии,21парный
повтор иотдельныеprofiles.14installedtests иRuff прошли до измерений. Результат:
29/21/22validations заодиннабор; CPUmedian223.799/477.429/481.752ms за100наборов.
Оба кандидата медленнее во всех21парахCPU иwall. Сохранены93correctnessrecords,
63timingsamples,отдельныеwarmup/profilecosts и151artifacthash. Все15suppressed
states остаютсяcontradicted/predicate_mismatch. Триintentionalkeep_all состояния
оставляют восстановленнуюистину скрытой, затемвсе вариантыеёперепроверяют.

Полныйrawtar508667bytes сохраняет17Gitfixtures,symlink и80runtimefiles; 151payload
и80sourcehash перепроверены внутриархива. ДляGit создана151-filemirror безвложенных
.git; исходныйrun сохранён. На диске15GiB(80%),очистка не требуется. Графикпросмотрен;
html_preview сноваexit1,html_render показалPNG. Независимыйаудитидётотдельно.

Независимый аудит отрицательногоcarry завершён:151artifact,80sealed,237historical
source,48Git snapshots,31referencepacket,93correctnessrecords и63timingsamples.
Пять перехешированныхподменотклонены,7контрольныхгрупппрошли. Установленныйаудитор
повторилпроверкуmirror сGitбазами израспакованного опубликованногоrawtar. 90обычных
записей дают0FA/AU/FW,триkeep_allcontrolsотделены. Профилисверенысполными.prof;
коллизииbasenameпослеstrip_dirs учитываются безложнойатрибуциизависимостей.
Первоначальныенеудачныеитерацииаудиторасохраненывruns. Реестрv7:95фактов,
19разрезов,23источника. GitHubpusha48e5b1 завершилсяHTTPSconnecttimeout;
локальныеcommitsиартефактысохранены,повторнаяотправкапредстоит.

Push4a8ee5f успешно повторён после временногоHTTPSconnecttimeout;remoteиlocalHEAD
совпали. Экспериментregistered-inputs закреплён8e4241c:88sealedfiles,тотже17/31
workload,4варианта,21x100paired. Rootдобавилgetter/pendingkeep_all guardsпослеreview;
17новых+14старыхтестовпрошли. Получены124correctnessrecords,84timingrows;
registeredCPUmedian544.743msпротив222.551msbaseline,все21pairedCPU/wallхуже.
Создание22регистрацийи17ingresschecksучтено. Источникидо/посленеизменны.

Применёнpstack:principle-attack-the-premise: записанаипроверенаобщаяпредпосылка
окупаемостидешёвыхvalidation. Отдельныйprofile даёт1.925ms всехbaselinevalidations
против4.704msregister и1.730msingress; этиinstrumented интервалы не смешаны
сCPUtiming samples. check_negative_carry_premise.py сохраняетповторяемыйдиагноз.
Дальнейшие варианты на той же предпосылке не добавляются; следующийопыт — реальные
first-parent траекториисmerges. Графикпросмотрен,html_previewexit1,html_renderуспешен.
Rawregisteredtar546134bytes сохраняет153payload,88runtimefiles,17Gitfixtures иsymlink.
Независимыйаудитвыполняетсяотдельно.


## Проверка регистрации и расширение реальной истории

На неизменном a1dc53c полный suite дал 1290 passed за 472.00 секунды, Ruff и
mypy прошли. Source snapshots до и после совпали; хеши трёх логов проверены.
В этот прогон входят 31 тест negative carry, но ещё не входят first-parent tests.

Независимый аудитор регистрации установлен и проверен на опубликованном mirror
с Git fixtures, извлечёнными из raw-архива. Подтверждены 124 correctness records,
84 timing samples, 153 артефакта, 88 закреплённых входов и 244 исторических файла.
Восемь подмен с пересчитанными хешами отклонены; прошли десять групп контролей.
Commit 8624996 сохраняет аудит и полный suite.

На 02fcd4a закреплены отдельный first-parent протокол и 134 файла до чтения
добавленных child-исходников. Установленные 11 авторских тестов прошли; независимый
review проверил 15 семантических подмен и сохранение всех старых production sources.
Все метаданные проверяются до чтения первого снимка. Side-parent trees не читаются.

Реальный запуск завершился на том же 02fcd4a с неизменными исходниками: 36 переходов,
10 merges, 1152 записи четырёх вариантов и 1290 хешированных файлов результата.
Семантически совпали 448 старых записей и 24 parent records. Добавленные 176 пар
на вариант все supported; новых опровержений нет. В полном наборе дочерние вызовы
составили 8/17/288/288, в добавленной части 0/4/176/176. Родительские 96 вызовов,
312 reference calls и 39 общих индексов выделены отдельно. Выигрыш во времени
не измерялся. Результат сохранён и отправлен в Git на c4a2b32.

Два скрипта предварительного review сохранены как точные sealed artifacts.
Их стиль не меняется после выполнения опыта: отдельный ruff.toml наследует
pyproject.toml и перечисляет только конкретные нарушения стиля этих двух файлов.
Остальные исходники проверяются по прежним правилам. Ruff и mypy снова прошли.

При планировании расширения выяснено по sealed selection metadata: все 20
исходных development-групп относятся к Click, а Requests и pytest целиком heldout.
Эти проекты не переводятся в development. Рассматривается отдельный новый проект
с выбором parent и claims до просмотра child-исходников. На диске 14 ГБ свободно;
очистка не потребовалась.

Реестр v8 проверяет 119 показателей в 21 разделе по 29 хешированным источникам.
First-parent рисунок повторно сгенерирован установленным helper и просмотрен.
HTML preview снова завершился ошибкой Chrome exit1; html_render успешно показал
HTML с рисунком и таблицами.

First-parent аудит завершён и установлен: 1290 артефактов, 134 sealed inputs,
251 historical source, 1152 observations, 312 Git/AST packets и 1048 cost rows.
После форматирования исходника результат побайтно совпал с независимым отчётом;
10 rehashed controls, семь scope refusals и deferred-body positive прошли.
Новые runtime-скрипты и исходники исследуемого проекта не исполнялись аудитором.

## Сводная поставка v9

На bfc56e1 собран PDF: 14 страниц, 10 рисунков, 193 текстовых блока/ячейки
совпали с извлечённым текстом. Просмотрены все 14 PNG-страниц; таблица first-parent
продолжается на следующей странице с повторённым заголовком и читается полностью.
Внутри 2661 файл evidence. ZIP v9 проверен по 2681 payload hashes, размер
13614385 байт, SHA-256 ccf1ef47cabe8ca420d879f0d2deea58114c300abfb449786dfea7303f1af2f4.
PDF/DOCX и delivery records обновлены; прежние версии сохранены.

## Новый проект: отказ первого плана до чтения исходников

На ac6ac62 закреплён metadata-only протокол packaging 23.2→25.0, 20 файлов.
12 тестов сборщика и независимая проверка 601 длины/11 потоков прошли. Git clone
выполнен с blob:none и no-checkout: 2401 объект, pack594KiB, HEAD соответствует
закреплённому f585376. Исходники, списки файлов и diffs не читались.

Коллектор остановился: в first-parent frame 72 позиции, а для трёх раздельных
24-step окон требовалось 75. Failed manifest и отдельные72OID сохранены в
packaging-topology-v1/ и packaging-frame-infeasibility-v1/. Никакой parent/child
source не прочитан. Исходный протокол не изменён, fallback не активирован.

Отдельно принято решение подготовить metadata-informed v2: горизонт23,
те же endpoints/roots/rank seed, parents0/24/48. Это изменение по результату
проверки выполнимости, до любых source/AI/reference исходов. Оно не выдаётся
за успех исходного плана или полностью неадаптивную пререгистрацию.

### Packaging v2: freeze before parent source access

Installed the reference-free parent collector and explicit parent-blob provisioning helper. The collector passed 12 authored tests and independent review; the installed provisioning helper passed 14 authored local-Git controls, independently rerun. Whole-repository Ruff passed. Both reviews are retained in `reports/research-20261104/packaging-parent-preaccess-review-v2/`.

Separate parent collection and blob protocols seal the exact three parents from the completed metadata v2 result. The acquisition helper requests only missing eligible package blob OIDs, checks committed input bytes, disables implicit lazy fetching, and records all object inventories. Unknown transfer size is explicitly acknowledged: the 2 GiB storage target is observed after fetch, with >5 GiB free-space checks, not a hard network or transient storage quota. No child access is authorized. Collector metadata-only preflight passed before any Packaging source/tree access.

Complete public packets and the checker must be sealed separately before AI/reference decisions. Named o200k_base counts screen the research envelope only; they do not claim actual model context or billing. The original h24 metadata failure remains unchanged; this is the disclosed metadata-informed h23 amendment.

### Packaging: real parent acquisition and packet freeze

At `0826434`, explicit provisioning fetched 37 distinct allowed parent blobs and no unrequested objects. All were below 2 MiB. Offline generation then inspected 42 module occurrences across three parents, found 75/77/79 eligible direct functions, and selected four per parent by the frozen hash rank. It produced 24 new derived claims and 12 controls, with complete modules, inventories, ranks and mappings retained. The three complete research-envelope estimates were 14201, 14576 and 12776 o200k_base tokens. No truncation or replacement was needed.

Commit `81b680f` froze 493 inputs, all public packets and the unchanged v2 reference before any AI/reference decisions. The independent reference then completed 36 decisions: all 24 derived parents supported, all nine negative controls contradicted, all three duplicate controls uncertain. This is still parent-only development evidence, not child replay, human annotation or admission. Six fresh AI contexts are being collected under the separate frozen review protocol.

The installed h23 replay driver passed 28 authored tests in 61.04 seconds and Ruff. Added observed CPU/wall guards include self and completed child CPU from execute entry, parent/child boundaries and the final artifact-hashing step. Tests preserve all 2208 partial rows when a final resource check fails. A single operation may overshoot a boundary; no preemptive hard time guarantee is claimed. Production CAMI and the reference implementation remain unchanged.

### Packaging: global parent gate passed, final child protocol frozen

All six fresh primary AI contexts completed, producing 72 case decisions. Every reviewer supported its eight real cases and matched all four controls. The separate reference completed 36 decisions. All 24 derived claims are eligible; there were no replacements, exclusions or retries. The assembly preserves full reviews, methodology, helpers, independent extracted facts and exact byte copies; helpers are archived as `.py.txt`. Same-tokenizer response estimates range 4353–6174, below 8000 each. Primary review identity is declared invocation, not a model-weight fingerprint.

Installed final-snapshot provisioning passed 10 authored controls against the actual unchanged global gate; whole-repository Ruff passed. The final replay seal binds 578 inputs. Offline `load_inputs` passed before any child access. The protocol authorizes complete trees of exactly 72 frozen snapshots, after the six-review gate, and explicitly separates 36 earlier packet-reference calls from 24 repeated parent plus 552 child reference calls in replay. It also clarifies the inherited `exact24-step` prose typo without changing any amended numeric h23 field or window. No source outcome informed these accounting clarifications.

### Packaging: completed historical replay (independent audit pending)

The real run completed at frozen source `b960218` with identical before/after source snapshots. Explicit acquisition fetched 259 new objects in addition to 37 parent blobs: 296 unique blobs for exactly 72 snapshots, zero oversize objects and no unrequested acquisition. The replay retained 2378 hashed artifacts and 2208 observations.

Raw aggregates report 552 observations per variant, 528 supported and 24 contradicted, with zero unknown. Actual child validation calls are 28/71/552/552 for symbol/file/known-incomplete/all. All variants have zero false availability, unknown availability and withholding of supported claims. The 24 contradicted observations are two signature claims in two episodes: 21 and 3 repeated trajectory positions, not 24 independent failures. Parent initialization adds 96 production validations; replay reference adds 24 parent and 552 child checks, separate from the earlier 36 packet checks; indexes are shared across variants and built 72 times. Observed replay usage was 22.069 CPU seconds and 26.688 wall seconds, a resource observation rather than a speedup benchmark.

These raw findings are retained for a separate implementation/result audit before the synthesis is promoted to the research fact ledger. Production source remains unchanged since `700ebf2`.

### Packaging verification and figure

Full verification at `07cb633` passed: 1361 tests, four skipped, Ruff clean and mypy clean across 53 production files; source snapshots and all three log hashes match. The four skips are the opt-in Docker integration cases because this invocation omitted `CAMI_TEST_IMAGE`. The previously pinned local image remains available, so the four cases will be checked separately with that exact digest; this run is not relabelled as 1365 passed.

Installed the reproducible Packaging figure. PNG/SVG/data remain byte-identical to the independently prepared figure; HTML was adjusted for theme variables and zero outer padding. All five installed output artifacts match a repeat rendering. The PNG was visually inspected and HTML was shown. Browser preview itself failed with the existing Chrome exit1 limitation, which is recorded.

### Four Docker integration skips resolved separately

At `2071f54`, reran only the four skipped Docker integration node IDs with `CAMI_TEST_IMAGE=cami-probes@sha256:17ad59a0efd3a62ede046c70b74213d649940e46a8330ac595ead4d647732bd6`. All four passed in 14.96 seconds. Every pre-existing source file matches the full `07cb633` run; the sole added source file is the reviewed plot script. Before/after snapshots also match within this supplement. The original full-run record stays `1361 passed, 4 skipped`; the supplemental record stays `4 passed`. Together they exercise all 1365 collected cases, without presenting that as a single uninterrupted full-suite result.

### Packaging corpus can be checked without GitHub

Published a file-only mirror of the bounded offline corpus, with a 1,130,413-byte deterministic tar.gz (SHA256 `423fbc71a9fc7a56b346c8dfb065c830f44db64ab1a78708e8db76749a12b81f`). The unchanged installed stdlib verifier independently checked all 72 trees and 296 blob contents in actual `unshare --net` namespaces. A parameterized installed control runner reproduced rejection of wrong archive hash, rehashed injected hook and rehashed missing object pack. All 108 original repository file identities remain unchanged. No extracted repository or Gitlink is committed. This is a bounded snapshot corpus, not complete Git history, the CAMI runtime or a full evidence backup.

### Packaging: independent result audit and v10 publication preparation

The installed stdlib audit reproduced the independently computed report byte-for-byte using the extracted offline corpus. It verified 2378 artifact files, 578 sealed inputs, 272 historical source files, all 53 unchanged production Python files, exact 72 snapshots/69 steps, all 24 parent and 2208 child-policy records, 576 Git/AST packets and 1947 cost rows. Child validation calls independently recompute to 28/71/552/552; 24 contradicted rows are two first observations plus 22 repeats, in runs of 21 and three ranks. All 69 actual transitions are nonmerge.

Installed rehashed controls rejected eight applicable mutations; unknown-as-contradicted is explicitly inapplicable to real data with zero uncertain rows and is exercised by the nine authored controls. Compact installed-control reports and stdout/stderr are published under `packaging-result-audit-v1/`, together with the audit manifest. The first audit and original measured run remain unchanged. The fact registry/ledger v9 separately verifies 152 facts across 24 studies and 36 sources. This is independent reanalysis with prior awareness of preliminary root claims, not a blinded replication.

V10 will package the completed Packaging result, parent/review and acquisition evidence, post-hoc event description, bounded offline corpus, independent audit, full verification at 07cb633 and the separate four-case Docker supplement at 2071f54. The original full run remains 1361 passed/4 skipped; together with the supplement 1365 cases were exercised in two runs. No new experiment or corpus collection is part of publication.

### Completed report delivery v10

Published v10 from clean build HEAD `5681b67434531d3d5a2211f46e0283e35d241b46`, with source/evidence cutoff `a0fac3097594dfe1f6cd5cb7ddee386e0e808ac6`. The unchanged builder rendered 17 PDF pages and 11 figures; all 222 paragraph/table-cell text blocks passed extraction. Every page was individually inspected through `view_image`; tables continuing across pages 1–2 and 12–13 retain repeated headers and readable rows, and all figures fit page bounds. The passed visual-review JSON binds the exact PDF SHA256 `7b570ba94836f98eb254229a6d5c1c059d68042260dc435da271418854ff80c4` and all17 rendered page-image hashes.

The portable archive `output/research-progress-20261104-v10.zip` contains 7005 evidence files and 7026 verified payload hashes (7027 ZIP entries including manifest), totals 23,546,458 bytes and has SHA256 `03a858d7f062b7c1e22328b0586fcc69494bafde7b0ca73b70813ed233c1e532`. Finalizer ZIP integrity and per-file comparisons passed. Current PDF/DOCX and delivery records are under `reports/research-20261104/report-delivery/`; the v9 output/archive remain unchanged. The first v10 render rejected HTML-only fact-marker comments; its output is retained as `output/research-progress-20261104-v10-attempt-1`, and the supported Markdown source was committed before the successful clean build. Scientific facts and the verified 152-fact ledger were unchanged by that formatting fix.
