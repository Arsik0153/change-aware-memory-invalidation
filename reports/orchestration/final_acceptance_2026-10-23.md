# Итоговая приёмка CAMI за 23 октября 2026 года

Это выжимка уже завершённого независимого read-only review, а не новое ревью автора публикации. Оригинал имеет заголовок `PASS for exact MAIN WATCH + OPT integration` и идентификатор `stage5-main-review/20261023T1800Z-r1`. Его verdict равен PASS, findings `[]`, для точного MAIN commit `43edac89d8a38ed1551195048e6383ced1479399` в согласованном объёме Stage 5 WATCH и OPT. Stage 1, 2, 3 и 4 сохраняют прежнюю scoped acceptance. Вся product vision не объявлена завершённой.

## Привязка к принятому артефакту

| Объект | Значение |
| --- | --- |
| Commit | `43edac89d8a38ed1551195048e6383ced1479399` |
| MAIN TREE этого commit | `677f32b64de7a3919464dd76c655eb51cdfa1f84` |
| Source TREE | `ac78ecf07326cfaa666c15367d54d70fe23ba4d0` |
| Tests TREE | `53d2876ad78fed4a507cf5a7e184a431c828af3a` |
| Feature patch SHA-256 | `84e1d10bd513da67d97c8b7d6353765808d8682b6a0b3d81edc3864073801937` |

Reviewer сравнил реальные bytes всех 361 tracked inputs, Git blob IDs, index и executable modes. Все 21 feature path совпали с независимо проверенным union artifact. Четыре различия с union относились только к program docs. До и после review HEAD, index, tracked bytes и чистый status не изменились. Проверка toolchain связала Python, Node, зависимости и 146 trusted compiler files. Все 58 assets сохранённого wheel совпали с MAIN при неизменном packaging config.

## Свежие проверки на exact MAIN

Сохранённая команда использовала MAIN `.venv/bin/python -B -m pytest -q -p no:cacheprovider`, отдельные внешние `--basetemp` и `--junitxml` и следующие семь selectors. Воспроизведение требует отдельной задачи и бюджета. При финальной публикации команда не запускалась.

```text
tests/watch/test_cleanup.py::test_failed_start_reaps_child_and_preserves_error[write]
tests/watch/test_cleanup.py::test_endpoint_cleanup_preserves_replacement[publication-True]
tests/watch/test_cleanup.py::test_watch_stop_reaps_real_node
tests/memory/test_identity_scopes.py::test_covered_deletion_and_recovery_keep_immutable_check_history
tests/memory/test_hybrid.py::test_nested_identity_gap_is_scoped_to_its_source_file
tests/test_symbol_search.py::test_relative_import_overflow_never_calls_root_init_target
tests/test_symbol_search.py::test_valid_relative_local_import_keeps_call
```

| Проверка | Свежий результат |
| --- | --- |
| Семь selectors выше с параметризацией | 18 passes, 0 failures. Pytest сообщил 13,92 s. |
| Независимый lifecycle driver | 20 CLI-команд или запусков процессов, четыре persisted phases. |
| Отдельные import и `watch --help` probes | MAIN import без `PYTHONPATH`, ожидаемые watch options. В число 20 не входят. |

CLI lifecycle использовал настоящий MAIN `.venv/bin/cami` вне checkout без `PYTHONPATH`. Основные формы команд перечислены ниже. Subjects fixture были `members.ts:A.owner.arrow` и Python signature claim, own-project subject был `src/cami/engine.py:run_experiment`.

```text
cami memory context SUBJECT --repo REPO --format json
cami memory remember KIND SUBJECT --repo REPO --from-context CONTEXT --request-id ID --format json
cami watch --repo REPO
cami watch status --repo REPO --format json
cami watch stop --repo REPO --format json
cami watch restart --repo REPO
cami find run_experiment --repo CAMI_REPO --format json
```

Driver записывал изменения passive fixtures, не выполняя код приложения. До refresh-capable context независимые SQLite/CAS reads подтвердили `binding_unresolved` для неизвестного TS owner. Python body edit сохранил прежний check ID и timestamp. Same-canonical context не создал переход. Возврат известного owner дал новый supported check. После удаления при остановленном watcher restart опубликовал `contradicted / subject_absent` с absence witness. Проверены duplicate start, configuration conflict exit 2, stop и repeated stop. Множества hashes immutable rows только расширялись, прежние source CAS bytes сохранились.

Три watcher regression cases подтвердили cleanup после неудачной записи запроса, сохранение чужого replacement socket и завершение реального Node к моменту stopped confirmation. Reviewer проверил отсутствие собственных controller, worker, Node, endpoint и temp roots. Общие MAIN environment и compiler сохранены.

## Переиспользованные проверки

| Источник | Сохранённый результат | Граница заявления |
| --- | --- | --- |
| Writer corrected union | 819 full passes, четыре Docker deselections, 497 focused passes, Ruff, strict mypy и Node syntax checks. | `FROM_IDENTICAL_ARTIFACT`, не новый запуск на MAIN. |
| Independent isolated union | 79 focused passes, installed Node-stop, 38 CLI/process launches, 12 persisted phases, old62 upgrade и ownership/crash probes. | Переиспользованы после byte/toolchain binding. |
| MAIN integrator | 11 CLI-команд и три persisted phases, ещё четыре postcommit CLI checks. | Отдельные delivery checks, не fresh reviewer count. |

Counts пересекаются и не складываются. Reviewer не повторял full suite, benchmark, compiler setup, install или UID65534 run. Научный held-out и Docker не проверялись. Прежние FAIL сохраняются в журнале.

## Исходные доказательства

Оригинал и подробные receipts являются дополнительными server-local материалами, которые не поставляются с клоном:

```text
/root/.claude/orchestrate/change-aware-memory-invalidation/outputs/stage5-main-review/20261023T1800Z-r1/REPORT.md
```

SHA-256 прочитанного оригинала равен `a9ab307b5c1e5f95f3dacd8a3fd049265f82f54188edb8b84c2dc1302efdf216`.

Основной [отчёт с командами, этапами, ограничениями и следующими шагами](../../docs/session_report_2026-10-23_ru.md) и [план развития](../../docs/product_development_plan_ru.md) доступны после клонирования. Финальный docs commit сохраняет принятые source и tests TREE. Его SHA определяется через `git log -1 -- reports/orchestration/final_acceptance_2026-10-23.md`.
