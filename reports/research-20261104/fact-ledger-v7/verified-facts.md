# Проверяемый реестр чисел исследования

Сгенерировано из закреплённых артефактов. Проверка предотвращает ошибки переноса чисел; она не подтверждает научную интерпретацию или независимость данных.

## Реальные parent-графы

63 фиксированных parent-группы; child-данные не читались.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| Все кандидаты | 630 | claim | [research-20261104/parent-graph-profile-v2/summary.json](<../parent-graph-profile-v2/summary.json>) |
| Behavior-кандидаты | 63 | claim | [research-20261104/parent-graph-profile-v2/summary.json](<../parent-graph-profile-v2/summary.json>) |
| Prose-кандидаты | 63 | claim | [research-20261104/parent-graph-profile-v2/summary.json](<../parent-graph-profile-v2/summary.json>) |
| Модули | 2131 | parent/module | [research-20261104/parent-graph-profile-v2/summary.json](<../parent-graph-profile-v2/summary.json>) |
| Module unresolved добавлен linker | 2070 | parent/module | [research-20261104/parent-graph-profile-v2/summary.json](<../parent-graph-profile-v2/summary.json>) |
| Behavior с global flag | 63 | claim | [research-20261104/parent-graph-profile-v2/summary.json](<../parent-graph-profile-v2/summary.json>) |
| Behavior с subject flag | 63 | claim | [research-20261104/parent-graph-profile-v2/summary.json](<../parent-graph-profile-v2/summary.json>) |

Ограничения: Флаги анализатора не являются truth labels. Модули повторяются между версиями.

## Binding gate

Parent-only проверка структурных кандидатов.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| Структурные кандидаты | 504 | claim | [research-20261104/binding-gate-v1/summary.json](<../binding-gate-v1/summary.json>) |
| Прошли gate | 30 | claim | [research-20261104/binding-gate-v1/summary.json](<../binding-gate-v1/summary.json>) |
| Отклонены gate | 474 | claim | [research-20261104/binding-gate-v1/summary.json](<../binding-gate-v1/summary.json>) |

Ограничения: Gate pass не является admission или независимым подтверждением.

## Структурный перенос

Авторский конечный набор; сравнение с тем же свежим валидатором.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| Всего случаев | 168 | case | [research-20261104/structural-carry-v1/summary.json](<../structural-carry-v1/summary.json>) |
| Перенесены | 32 | case | [research-20261104/structural-carry-v1/summary.json](<../structural-carry-v1/summary.json>) |
| Нарушения условного переноса | 0 | case | [research-20261104/structural-carry-v1/summary.json](<../structural-carry-v1/summary.json>) |

Ограничения: Не независимая истина. Восемь случаев изменения лимита чтения вне аргумента фиксированной конфигурации.

## Обход графа

Конечные пространства трёх- и четырёхвершинных графов.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| Входные случаи | 208896 | input case | [research-20261104/impact-graphs-v1/results.json](<../impact-graphs-v1/results.json>) |
| Расхождения | 0 | case | [research-20261104/impact-graphs-v1/results.json](<../impact-graphs-v1/results.json>) |

Ограничения: Счётчик включает совпадающие эффективные seed sets. Не проверяет полноту parser.

## Requests package-only projection

Отдельный pinned execution context на реальных parents.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| Parent-группы | 22 | group | [research-20261104/requests-projection-v1/summary.json](<../requests-projection-v1/summary.json>) |
| Успешные исполнения | 66 | Docker execution | [research-20261104/requests-projection-v1/summary.json](<../requests-projection-v1/summary.json>) |

Ограничения: Не full-tree execution и не admission.

## Время синтетических историй

40 CLI runs; пять повторов каждого варианта двух authored histories.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| Измеренные CLI runs | 40 | run | [research-20261104/behavior-timing-v1/summary.json](<../behavior-timing-v1/summary.json>) |
| Измеренные пробы | 615 | Docker execution | [research-20261104/behavior-timing-v1/summary.json](<../behavior-timing-v1/summary.json>) |
| Exposure all: медиана | 10.731269817100838 | second | [research-20261104/behavior-timing-v1/summary.json](<../behavior-timing-v1/summary.json>) |
| Exposure intact: медиана | 9.24319527996704 | second | [research-20261104/behavior-timing-v1/summary.json](<../behavior-timing-v1/summary.json>) |
| Recovery all: медиана | 7.69090930884704 | second | [research-20261104/behavior-timing-v1/summary.json](<../behavior-timing-v1/summary.json>) |
| Recovery intact: медиана | 6.201838667970151 | second | [research-20261104/behavior-timing-v1/summary.json](<../behavior-timing-v1/summary.json>) |

Ограничения: Общая машина. Повторы не являются независимыми новыми историями. Отдельный cProfile исключён.

## Конечная достижимость

Две функции и конечная грамматика; точный oracle.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| Программы | 12 | program | [research-20261104/behavior-reachability-v1/summary.json](<../behavior-reachability-v1/summary.json>) |
| Hidden: состояния | 14 | state | [research-20261104/behavior-reachability-v1/summary.json](<../behavior-reachability-v1/summary.json>) |
| Hidden: ложная доступность | 2 | state | [research-20261104/behavior-reachability-v1/summary.json](<../behavior-reachability-v1/summary.json>) |

Ограничения: Нулевое число Docker executions в этом обходе. Не произвольный Python.

## Периодический аудит: модель

K обработанных child commits; корректная завершённая validation.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| K=2: максимум подряд | 1 | false-available state | [research-20261104/periodic-audit-bound-v1/summary.json](<../periodic-audit-bound-v1/summary.json>) |
| K=4: максимум подряд | 3 | false-available state | [research-20261104/periodic-audit-bound-v1/summary.json](<../periodic-audit-bound-v1/summary.json>) |
| K=8: максимум подряд | 7 | false-available state | [research-20261104/periodic-audit-bound-v1/summary.json](<../periodic-audit-bound-v1/summary.json>) |

Ограничения: Граница не в секундах. Production policy не изменена.

## Периодический аудит: engine

Одна авторская история из 12 Git children; исследовательская обёртка.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| Фактические исполнения | 93 | Docker execution | [research-20261104/periodic-audit-docker-v1/manifest.json](<../periodic-audit-docker-v1/manifest.json>) |
| Успешные пробы | 33 | Docker execution | [research-20261104/periodic-audit-docker-v1/manifest.json](<../periodic-audit-docker-v1/manifest.json>) |
| Ожидаемые assertion failures | 60 | Docker execution | [research-20261104/periodic-audit-docker-v1/manifest.json](<../periodic-audit-docker-v1/manifest.json>) |

Ограничения: Не population effect или timing benchmark. Parent confirmations включены в executions.

## Полная проверка

Неизменный commit 49dc9c2; production fix, AI pilot, translation и real replay driver включены.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| Прошедшие тесты | 1259 | test | [research-20261104/full-verification-49dc9c2/pytest.log](<../full-verification-49dc9c2/pytest.log>) |

Ограничения: Полная проверка относится к указанному HEAD; поздние отдельные auditors не приписываются этому прогону.

## Политики в периодическом Git/Docker опыте

Одна фиксированная 12-шаговая история; восстановление на child9.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| hidden_missing: Перепроверки child | 0 | logical validation | [research-20261104/periodic-audit-docker-v1/results.json](<../periodic-audit-docker-v1/results.json>) |
| hidden_missing: Ложно доступные состояния | 8 | child state | [research-20261104/periodic-audit-docker-v1/results.json](<../periodic-audit-docker-v1/results.json>) |
| periodic_2: Перепроверки child | 9 | logical validation | [research-20261104/periodic-audit-docker-v1/results.json](<../periodic-audit-docker-v1/results.json>) |
| periodic_2: Ложно доступные состояния | 1 | child state | [research-20261104/periodic-audit-docker-v1/results.json](<../periodic-audit-docker-v1/results.json>) |
| periodic_4: Перепроверки child | 6 | logical validation | [research-20261104/periodic-audit-docker-v1/results.json](<../periodic-audit-docker-v1/results.json>) |
| periodic_4: Ложно доступные состояния | 3 | child state | [research-20261104/periodic-audit-docker-v1/results.json](<../periodic-audit-docker-v1/results.json>) |
| all_validate: Перепроверки child | 12 | logical validation | [research-20261104/periodic-audit-docker-v1/results.json](<../periodic-audit-docker-v1/results.json>) |
| all_validate: Ложно доступные состояния | 0 | child state | [research-20261104/periodic-audit-docker-v1/results.json](<../periodic-audit-docker-v1/results.json>) |

Ограничения: Research-only adapter. Число ошибок не является популяционной частотой. Parent-проверки исключены из logical validation counts.

## Неполные вердикты и условия гарантии

Полный конечный обход для K=1,2,4,8; точная двоичная и только положительно корректная модели.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| Состояния двух моделей | 64 | state | [research-20261104/ternary-audit-invariants-v1/audit.json](<../ternary-audit-invariants-v1/audit.json>) |
| Переходы двух моделей | 403 | transition | [research-20261104/ternary-audit-invariants-v1/audit.json](<../ternary-audit-invariants-v1/audit.json>) |
| Циклические отрицательные контроли | 2 | control | [research-20261104/ternary-audit-invariants-v1/audit.json](<../ternary-audit-invariants-v1/audit.json>) |

Ограничения: Не проверяет soundness реального валидатора. Нет Docker executions. Граница для всех K опирается на отдельный аргумент возраста.

## Символические условия для произвольного K

QF_LIA, K>=1, неограниченные Int; один закреплённый Z3 4.16.0.0.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| Все solver checks | 18 | solver check | [research-20261104/symbolic-audit-v1/manifest.json](<../symbolic-audit-v1/manifest.json>) |
| UNSAT отрицаний целей | 6 | obligation | [research-20261104/symbolic-audit-v1/manifest.json](<../symbolic-audit-v1/manifest.json>) |
| SAT предпосылок | 6 | obligation | [research-20261104/symbolic-audit-v1/manifest.json](<../symbolic-audit-v1/manifest.json>) |
| SAT примеров и контрпримеров | 6 | witness | [research-20261104/symbolic-audit-v1/manifest.json](<../symbolic-audit-v1/manifest.json>) |

Ограничения: Ручная формализация перехода, не production verification. Proof objects не проверены независимым kernel. Непротиворечивость предпосылок не доказывает их выполнение на реальных данных.

## Слепой AI development-пилот

Три Click parent-группы; исходные claims и авторские контролы; раздельные AI-контексты.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| Все случаи | 36 | case | [research-20261104/ai-parent-pilot-v1/summary.json](<../ai-parent-pilot-v1/summary.json>) |
| Исходные утверждения | 24 | claim | [research-20261104/ai-parent-pilot-v1/summary.json](<../ai-parent-pilot-v1/summary.json>) |
| Авторские контролы | 12 | case | [research-20261104/ai-parent-pilot-v1/summary.json](<../ai-parent-pilot-v1/summary.json>) |
| Расхождения двух AI | 0 | case | [research-20261104/ai-parent-pilot-v1/summary.json](<../ai-parent-pilot-v1/summary.json>) |
| Расхождения reference и AI A | 0 | case | [research-20261104/ai-parent-pilot-v1/summary.json](<../ai-parent-pilot-v1/summary.json>) |
| Расхождения reference и AI B | 0 | case | [research-20261104/ai-parent-pilot-v1/summary.json](<../ai-parent-pilot-v1/summary.json>) |
| Человеческие reviews | 0 | review | [research-20261104/ai-parent-pilot-v1/summary.json](<../ai-parent-pilot-v1/summary.json>) |
| Уникальные source hashes | 21 | hash | [research-20261104/ai-parent-pilot-v1/summary.json](<../ai-parent-pilot-v1/summary.json>) |

Ограничения: AI agreement не является truth или человеческой разметкой. Общий CPython и модель; зависимые строки и простые искусственные контролы. Известный nested-class-global gap v1 отдельно раскрыт; целевых global в этих исходниках нет.

## Связь модели с engine

Восемь конечных графов, реальные функции отбора и состояния, канонические synthetic metadata.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| Исходные рёбра | 403 | edge | [research-20261104/model-engine-translation-v1/summary.json](<../model-engine-translation-v1/summary.json>) |
| Канонические контексты | 76 | context | [research-20261104/model-engine-translation-v1/summary.json](<../model-engine-translation-v1/summary.json>) |
| Проверенные переходы | 499 | transition | [research-20261104/model-engine-translation-v1/summary.json](<../model-engine-translation-v1/summary.json>) |
| Совпавшие переходы | 499 | transition | [research-20261104/model-engine-translation-v1/summary.json](<../model-engine-translation-v1/summary.json>) |
| Обнаруженные отрицательные контролы | 2 | control | [research-20261104/model-engine-translation-v1/summary.json](<../model-engine-translation-v1/summary.json>) |

Ограничения: ValidationResult задан моделью; probes не исполнялись. Ограниченное соответствие, не доказательство произвольных production histories.

## Class-global: before

21 authored mutation × 2 predicates; одинаковый reference v2 до и после production fix.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| Claim-переходы | 42 | claim/transition | [research-20261104/reference-alignment-before-v2/summary.json](<../reference-alignment-before-v2/summary.json>) |
| Выбранные symbol-проверки | 28 | validation | [research-20261104/reference-alignment-before-v2/summary.json](<../reference-alignment-before-v2/summary.json>) |
| Доступность при отсутствии поддержки | 4 | claim/transition | [research-20261104/reference-alignment-before-v2/summary.json](<../reference-alignment-before-v2/summary.json>) |
| Полный validator против reference | 4 | claim/transition | [research-20261104/reference-alignment-before-v2/summary.json](<../reference-alignment-before-v2/summary.json>) |

Ограничения: Available при uncertain означает отсутствие поддержки по rubric, не доказанную ложность. Синтетический challenge не измеряет эффект на популяции репозиториев.

## Class-global: after

21 authored mutation × 2 predicates; одинаковый reference v2 до и после production fix.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| Claim-переходы | 42 | claim/transition | [research-20261104/reference-alignment-after-v2/summary.json](<../reference-alignment-after-v2/summary.json>) |
| Выбранные symbol-проверки | 32 | validation | [research-20261104/reference-alignment-after-v2/summary.json](<../reference-alignment-after-v2/summary.json>) |
| Доступность при отсутствии поддержки | 0 | claim/transition | [research-20261104/reference-alignment-after-v2/summary.json](<../reference-alignment-after-v2/summary.json>) |
| Полный validator против reference | 0 | claim/transition | [research-20261104/reference-alignment-after-v2/summary.json](<../reference-alignment-after-v2/summary.json>) |

Ограничения: Available при uncertain означает отсутствие поддержки по rubric, не доказанную ложность. Синтетический challenge не измеряет эффект на популяции репозиториев.

## Реальная история Click, development

24 фиксированных claims; три цепочки длины 1/12/1; 112 наблюдений на вариант; четыре стратегии.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| Исходные parent claims | 24 | claim | [research-20261104/real-structural-replay-v1/report.json](<../real-structural-replay-v1/report.json>) |
| Наблюдения на вариант | 112 | claim/child | [research-20261104/real-structural-replay-v1/report.json](<../real-structural-replay-v1/report.json>) |
| Проверки по символу | 8 | validation call | [research-20261104/real-structural-replay-v1/report.json](<../real-structural-replay-v1/report.json>) |
| Проверки по файлу | 13 | validation call | [research-20261104/real-structural-replay-v1/report.json](<../real-structural-replay-v1/report.json>) |
| Проверки при известной неполноте | 112 | validation call | [research-20261104/real-structural-replay-v1/report.json](<../real-structural-replay-v1/report.json>) |
| Полная перепроверка | 112 | validation call | [research-20261104/real-structural-replay-v1/report.json](<../real-structural-replay-v1/report.json>) |
| Опровергнутые наблюдения на вариант | 8 | claim/child | [research-20261104/real-structural-replay-v1/report.json](<../real-structural-replay-v1/report.json>) |
| Различные опровергнутые claims | 1 | claim | [research-20261104/real-structural-replay-audit-v1/report.json](<../real-structural-replay-audit-v1/report.json>) |
| Ложная доступность, symbol | 0 | claim/child | [research-20261104/real-structural-replay-v1/report.json](<../real-structural-replay-v1/report.json>) |
| Доступность при unknown, symbol | 0 | claim/child | [research-20261104/real-structural-replay-v1/report.json](<../real-structural-replay-v1/report.json>) |
| Скрытые подтверждённые, symbol | 0 | claim/child | [research-20261104/real-structural-replay-v1/report.json](<../real-structural-replay-v1/report.json>) |
| Общие построения индекса | 17 | index build | [research-20261104/real-structural-replay-v1/report.json](<../real-structural-replay-v1/report.json>) |
| Дочерние reference calls | 112 | reference call | [research-20261104/real-structural-replay-v1/report.json](<../real-structural-replay-v1/report.json>) |

Ограничения: Восемь contradicted observations относятся к одному claim и одному возникновению изменения аннотации. Экспериментальный provenance и AI parent-подтверждения не являются допуском основного held-out протокола. Счётчики дочерних validations не являются wall-time speedup; parent, reference и общий index учитываются отдельно.

## Цена переноса отрицательного ответа

17 авторских Git-историй, 31 переход; 21 парный повтор; блок содержит 100 повторов всего набора, 1700 историй и 3100 переходов.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| Авторские истории | 17 | history | [research-20261104/negative-carry-maintenance-evidence-v1/setup.json](<../negative-carry-maintenance-evidence-v1/setup.json>) |
| Различные переходы в наборе | 31 | transition | [research-20261104/negative-carry-maintenance-evidence-v1/setup.json](<../negative-carry-maintenance-evidence-v1/setup.json>) |
| Baseline validations на набор | 29 | validation call | [research-20261104/negative-carry-maintenance-evidence-v1/expected-work.json](<../negative-carry-maintenance-evidence-v1/expected-work.json>) |
| Signature-witness validations на набор | 21 | validation call | [research-20261104/negative-carry-maintenance-evidence-v1/expected-work.json](<../negative-carry-maintenance-evidence-v1/expected-work.json>) |
| Blob-witness validations на набор | 22 | validation call | [research-20261104/negative-carry-maintenance-evidence-v1/expected-work.json](<../negative-carry-maintenance-evidence-v1/expected-work.json>) |
| Baseline CPU median | 223798710 | ns / 100 history packs | [research-20261104/negative-carry-maintenance-evidence-v1/summary.json](<../negative-carry-maintenance-evidence-v1/summary.json>) |
| Signature-witness CPU median | 477428730 | ns / 100 history packs | [research-20261104/negative-carry-maintenance-evidence-v1/summary.json](<../negative-carry-maintenance-evidence-v1/summary.json>) |
| Blob-witness CPU median | 481752160 | ns / 100 history packs | [research-20261104/negative-carry-maintenance-evidence-v1/summary.json](<../negative-carry-maintenance-evidence-v1/summary.json>) |
| Парные повторы | 21 | paired block | [research-20261104/negative-carry-audit-v1/report.json](<../negative-carry-audit-v1/report.json>) |
| Записи timing | 63 | timing sample | [research-20261104/negative-carry-audit-v1/report.json](<../negative-carry-audit-v1/report.json>) |
| Положительные CPU-разности signature−baseline | 21 | paired block | [research-20261104/negative-carry-audit-v1/report.json](<../negative-carry-audit-v1/report.json>) |
| Положительные CPU-разности blob−baseline | 21 | paired block | [research-20261104/negative-carry-audit-v1/report.json](<../negative-carry-audit-v1/report.json>) |
| Correctness records | 93 | variant/transition | [research-20261104/negative-carry-audit-v1/report.json](<../negative-carry-audit-v1/report.json>) |

Ограничения: Индексы, Git и reference подготовлены заранее; witness creation, eligibility, actual validation и state advance входят в измерение. Все повторы используют тот же набор, а не независимые программы. Общий хост; диапазоны не являются популяционными confidence intervals. Три controlled keep_all состояния intentionally withhold supported claims; обычные 90 переходов анализируются отдельно. Снижение числа validation calls не стало ускорением этих реализаций.
