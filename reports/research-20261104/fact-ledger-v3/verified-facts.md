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

Неизменный commit 418f58a; после него добавлено расширение с неполными вердиктами.

| Факт | Значение | Единица | Источник |
| --- | ---: | --- | --- |
| Прошедшие тесты | 1163 | test | [research-20261104/full-verification-418f58a/pytest.log](<../full-verification-418f58a/pytest.log>) |

Ограничения: Более поздние research scripts проверялись профильными тестами.

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
