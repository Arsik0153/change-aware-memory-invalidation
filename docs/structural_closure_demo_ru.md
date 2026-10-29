# Выборочная перепроверка структурных claims на development-fixtures

23 октября 2026 года. Это синтетическая демонстрация, не независимый эксперимент.

CAMI теперь готовит производную provenance после проверяемого закрытия конкретного
замечания. Раньше протокол 1.1 оставлял все такие записи под fallback
`known_incomplete`. Новое [development-дополнение версии 1](protocol_1_1_structural_closure_v1.md)
задаёт узкий критерий и отдельный [подготовительный модуль](../src/cami/structural_closure.py).
Оригинальные правила отбора, аудита и импорта review сохранены.

Для `symbol_exists` достаточно полного parent blob и проверки единственного
безусловного определения с точной идентичностью, без конкурирующего binding в
поддерживаемом статическом подмножестве. Для `signature_equals` дополнительно
нужно равенство всей нормализованной синтаксической сигнатуры, включая defaults,
annotations, decorators и async. Разрешать значения вызовов и импортов для этих
синтаксических предикатов не требуется. Body-вызовы и наблюдения анализатора
сохраняются в evidence. Неопределённость binding и ограничения анализа приводят
к отказу. Это отсутствие известных незакрытых обязательств в принятой области,
а не доказательство полноты зависимости от всех возможных факторов.

Каждое закрытие связано hashes с parent, полным claim, исходной provenance,
полным исходником, дополнением и evidence. Записываются новая provenance,
точные dispositions замечания, история, версия Python и hashes реализации.
Незапрошенные записи сохраняются. Неизвестное замечание, явная dependency,
неподходящий тип или scope, неподдерживаемый текст, неоднозначность, ограничение
анализа или несовпадение hashes не позволяют опубликовать результат.
Подготовка читает только parent и строгий отдельный вход. В демонстрации
она завершается до создания child-коммитов. Behavior и prose не допускаются.

## Воспроизведение

Из корня репозитория с Python 3.12 и uv:

```bash
uv sync --locked --extra dev
uv run python scripts/demo_structural_closure.py --out runs/structural-closure-dev-003
```

Нужен новый несуществующий каталог. Фактический измеренный запуск использовал
`runs/structural-closure-dev-002`; [точная команда и код завершения](../reports/structural-closure-20261023-002/demo_invocation.json)
сохранены отдельно. Результат можно проверить по
[summary.json](../reports/structural-closure-20261023-002/summary.json),
[журналу CLI](../reports/structural-closure-20261023-002/demo.log),
[истории закрытий](../reports/structural-closure-20261023-002/derived/closure_history.jsonl)
и [manifest подготовки](../reports/structural-closure-20261023-002/derived/closure_manifest.json).
Полные артефакты 15 запусков находятся в `runs/structural-closure-dev-002/runs/`.
В каталоге отчёта сохранён полный переносимый пакет производной provenance с evidence.
Серия `001` предшествует исправлению отказа при alias динамического namespace
и заменена окончательной серией `002`.

## Фактическое сравнение

Четыре claim заданы в [scenario.json](../examples/structural_closure/scenario.json)
до запуска CAMI. Для `f` и `stable` проверяются существование и сигнатура `(x)`.
Ожидания не извлекались из ответов CAMI. Отдельный tokenizer проверяет реальные
Git blobs без вызова индексатора, нормализации или валидатора CAMI. Все 28
parent и child наблюдений совпали с заранее заданными ответами.

Число выбранных claims на каждом переходе одинаково во всех пяти повторениях:

| Переход | all_validate | Исходная неполная | После закрытия | Результат для f после закрытия |
|---|---:|---:|---:|---|
| Посторонний файл | 4 | 4 | 0 | Оба claim перенесены |
| Тело, прежняя сигнатура | 4 | 4 | 2 | Оба supported |
| Сигнатура | 4 | 4 | 2 | exists supported, signature contradicted |
| Удаление | 4 | 4 | 2 | Оба contradicted, subject_absent |
| Неоднозначный binding | 4 | 4 | 2 | Оба insufficient_evidence, ambiguous_subject |
| Возврат к прежнему коду | 4 | 4 | 2 | Оба supported и снова доступны |
| Всего на одну последовательность | 24 | 24 | 10 | 14 проверок исключены |

`all_validate` всегда указывает `all_claims`. Исходная provenance всегда добавляет
`known_incomplete`. После закрытия посторонний файл не даёт причины выбора.
Остальные переходы дают `subject_changed` и `symbol_or_dependency_changed`.
Удаление дополнительно выбирает ранее недоступный signature claim через
`previously_unavailable`. На неоднозначности и revert эта причина есть у обоих
claims `f`. Полные списки причин и verdicts каждого claim сохранены в summary.

В полном и исходном неполном вариантах получены 19 supported, 3 contradicted
и 2 insufficient_evidence. После закрытия получены 5 supported, те же 3 contradicted
и 2 insufficient_evidence. Ещё 14 состояний перенесены без объявления новой проверки.
Оба claim `stable` на всех переходах сохраняют parent в `last_checked_commit`.
Изменение тела законно выбирает структурные claims по AST протокола 1.1.
Минимальность отбора не заявляется.

Каждый вариант выполнен пять раз отдельным CLI-процессом. Порядок циклически
меняется, [расписание](../reports/structural-closure-20261023-002/schedule.json)
записано до запусков. Общий verdict cache выключен, AST cache локален процессу.
Время включает Python startup, preflight, шесть переходов, Git I/O, запись
артефактов и завершение процесса. Кеш ОС не сбрасывался.

| Вариант | Медиана полного CLI, с | Минимум, с | Максимум, с |
|---|---:|---:|---:|
| all_validate | 0.408130 | 0.350786 | 0.421733 |
| Исходная неполная provenance | 0.401199 | 0.375378 | 0.446467 |
| После закрытия | 0.356212 | 0.340178 | 0.406609 |

Диапазоны пересекаются. Ускорение не установлено. Это небольшое операционное
измерение, включающее накладные расходы процессов, Git и файлов артефактов.
Подготовка provenance заняла ещё 0.293989 с отдельным CLI. Полная команда
демонстрации заняла 6.485037 с, включая все 15 запусков, подготовку, создание
истории, независимые проверки и отчёт.

## Проверки и оставшиеся ограничения

[preservation.json](../reports/structural-closure-20261023-002/preservation.json)
подтверждает неизменность 242 прежних tracked-файлов и hashes всего производного
пакета. Из прежних файлов изменились только README и CLI подготовки. Исходные
протоколы, наборы, seals, `audit-provenance`, `import-provenance-review`, модели
и консервативный selector не изменены. Новые тесты проверяют допуск, отказы,
побайтную сохранность исходников, отсутствие child-чтения, поведение fallback,
причины verdicts и восстановление доступности. Два найденных при интеграции
дефекта сначала воспроизведены падающими тестами, затем исправлены. Финальный
review нашёл alias динамического namespace; три дополнительных регрессии сначала
воспроизвели обход и после исправления прошли. Повторный review замечаний не нашёл.
Итоговые команды и результаты находятся в
[checks.json](../reports/structural-closure-20261023-002/checks.json).
Итоговый прогон дал 322 passed и четыре исключённых Docker-теста. Ruff и mypy
для `src/cami` и демонстрационного скрипта прошли.

Автоматическое закрытие разрешено только для `synthetic/development/fixture`
с `independent=false`. Реальные и held-out входы отклоняются. Оно не выдаёт
себя за человеческий review и не создаёт parent receipts. Демонстрационный
драйвер отдельно создаёт явно синтетические подтверждения parent из своего oracle.

Для основного эксперимента по-прежнему нужны реальные независимые
parent-подтверждения и принятие достаточности provenance по этому критерию,
разрешение разногласий reviewers, независимая child-разметка с двойной проверкой,
исторические behavior-среды, решение о cohort и последующий научный freeze.
Импорт независимого разрешения на реальное закрытие в этой версии не реализован.
Методы, вложенные определения и неподдерживаемые конструкции Python остаются
вне автоматического допуска. Синтетическая демонстрация не доказывает качество
на реальных проектах. Held-out Requests и pytest, behavior probes, M6 и финальный
научный freeze не запускались.

При проектировании два отдельных разбора сошлись на производном пакете подготовки.
Runtime overlay и изменение существующего review importer отклонены, поскольку
они переносили бы правила разрешения в исполнение или меняли контракт аудита.
Model the Domain определил строгие записи запроса, evidence и истории.
Prove It Works определил фактические CLI-запуски и проверку их артефактов.
Архитектурные разборы выполнены той же настроенной моделью; они не являются
независимым человеческим подтверждением научного эксперимента.

## Расширенная development-проверка, план от 29 октября 2026

До генерации данных и запуска новых policy runs зафиксирован
`examples/structural_stress/protocol.json`. План расширяет узкую демонстрацию:
12 seeds, по3файла с4функциями,24immutable claims на parent и18последовательных
изменений. В каждом history есть unrelated/body/signature/duplicate/remove/parse/
file_delete/restore/no_change; ещё6событий выбираются из фиксированного списка.
Ожидается5184child claim-revision items на variant, без повторных timing trials.

Три variants остаются all_validate, symbol_validate с исходной known_incomplete
и symbol_validate после автоматического fixture-only closure. Real data и допуски
не используются. Parent receipts явно synthetic; labels человеческой разметки
не создаются. Closed provenance готовится на parent до создания child commits.

Oracle задаётся двумя путями: состоянием генератора и отдельным tokenize обходом
фактических Git blobs с compile-only проверкой синтаксиса. Он не вызывает CAMI
parser/index/validator и проверяет только намеренно узкую грамматику top-level
functions. CPython syntax checking — общая базовая зависимость; это независимость
реализации проверок, не независимость авторов и не доказательство для любого Python.

Будут проверены actual verdicts, availability всех states, carry lineage, неизменность
cohort и учёт validations. Exact selector minimality не предполагается: parser
uncertainty может консервативно расширять selection. Числа savings описывают только
этот authored generator; population confidence intervals и ускорение не заявляются.
Каждый seed сохраняется, включая ошибки. Изменения плана/исправления oracle после
наблюдения результатов отмечаются явно и требуют нового каталога прогона.

### Проверка драйвера до полного запуска

Драйвер `python -m scripts.stress_structural_memory` и отдельный stdlib-only oracle
реализованы. Генератор выбирает file/function равномерно через random.Random(seed);
состояния остальных функций сохраняются. Restore сбрасывает выбранный файл, поэтому
может не затронуть другой ранее повреждённый файл. Операции могут быть no-op.
Для каждого перехода сохраняются Git tree и фактический changed_paths; scheduled
и effective изменения будут посчитаны отдельно. Это уточнение реализации заданного
генератора до полного запуска, не отбор удачных результатов.

Независимый design reviewer нашёл четыре проблемы в verification/reporting, до
основных12seed runs: неполную проверку manifest/config hashes; непроверенные поля
last_verdict/state; смешение scheduled/effective событий; пропуск оставшихся variants
при ошибке verifier. Исправлены все четыре. Пустой hash inventory сначала принят
старым verifier (failing regression), затем отклонён. Tests также намеренно меняют
policy, provenance, availability, state, last_verdict и costs с обновлёнными hashes.
Инъекция verifier exception не мешает выполнению двух остальных variants.

Focused suite:24passed,ruff passed. Это включает небольшой настоящий CLI prototype
(1file,2functions,12transitions), не полный experiment. При усилении verifier был
исправлен его false positive: отсутствующие optional anchor fields нормализуются
через модель перед сравнением, а исходные bytes отдельно связываются hashes.
Evidence: structural-stress-tests-v1..v5.log, structural-stress-attestation-before.log,
structural-stress-design-review.json. Основной12seed запуск пока не выполнен.

Maintenance validation counts не включают подготовку/проверку provenance, oracle,
Git I/O и индексацию. Их уменьшение не является измерением общего ускорения или
экономии труда при real annotation. Все состояния и результаты остаются synthetic.

### Результаты полного synthetic stress, 29 октября 2026

Полный план выполнен на неизменном HEAD `0242dfd`: все12seeds и36policy runs
завершены. На каждый вариант приходится5184child claim-revision items
(12×18×24). Проверены15552сохранённых состояний и5472parent+child oracle observations.
Выбранные verdicts совпали с oracle; доступность всех состояний, last_checked,
last_supported, last_verdict и basis прошли предусмотренные проверки.
Расхождений не обнаружено. Это не оценка нулевой вероятности ошибки: observations
зависимы, имеют общий parent fixture и местами общие prefixes историй.

| Вариант | Maintenance validator calls | Items без повторной validation |
| --- | ---: | ---: |
| all_validate | 5184 | 0 |
| symbol_validate, исходная неполная provenance | 5184 | 0 |
| symbol_validate, fixture-only closure | 1736 | 3448 |

Разность относительно каждого baseline —3448вызовов, или66.5123% от5184.
Это эффект конкретного сочетания закрытой fixture provenance и выборочной политики,
а не результат для исходной неполной provenance. В каждой истории baseline делает432
проверки, closed variant — от80до195. Затраты closure и oracle не включены в эти
maintenance counts, поэтому сокращение не является оценкой end-to-end ускорения.
Для реальных630claims флаги incomplete по-прежнему сохранены: вывод на них не перенесён.

По oracle имеется3761supported,751contradicted и672uncertain child items. Последние
связаны с неоднозначными или синтаксически повреждёнными определениями; uncertain
не заменён отрицательной истиной. Из216scheduled событий185реально изменили Git tree.
Остальные31 —18явных no_change и13операций, оставивших bytes прежними. В CSV записаны
actual changed_paths для каждого перехода, а не только название запрошенной операции.

Проверены13153hashes raw artifacts, точные variant configs/input hashes и сохранность
исходных inputs. Source snapshots совпали и были clean. Полные артефакты находятся
в `runs/structural-stress-20261029-v1`; compact report, raw manifest, protocol,
seeds.csv, transitions.csv, PNG/SVG и integrity record — в
`reports/research-20261029/structural-stress-v1`. График проверен по PNG и показан
через html_render; headless html_preview завершился exit1, как и ранее в этой среде.

Поле engine evaluation_eligible=true у этих запусков означает возможность оценивать
synthetic development output. Оно не предоставляет real-cohort admission: closure
отдельно фиксирует real_experiment_eligible=false. Независимых человеческих labels,
реального held-out execution и допуска основного исследования здесь нет.

Для повторения из корня установленного проекта используйте новый каталог:

```bash
.venv/bin/python -m scripts.stress_structural_memory \
  --out runs/structural-stress-repeat
```

Ошибочные seeds/variants сохраняются; exit1 означает неуспешное исследование или
изменение implementation/protocol во время запуска. Existing output не перезаписывается.

Независимый empirical reviewer (gpt-6.1-sol) пересчитал все5472oracle observations
непосредственно из Git с tokenizer и отдельной AST-классификацией, проверил все15552
state rows и selected verdicts,36configs и12closure packages. Counts,CSV и13153hashes
совпали; материальных расхождений нет. Full suite с Docker на unchanged0242dfd:
**1020 passed,0skipped за466.94s**,ruff/mypy passed. Source snapshots совпали и
все log hashes проверены. Evidence: structural-stress-full-verification/checks.json.
