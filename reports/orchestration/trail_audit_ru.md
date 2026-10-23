# Аудит orchestration trail

Проверены все 29 записей, существовавших в начале этого run: строки 2–30 `decisions.tsv`, от 11:12:26 до 11:40:10 UTC 2026-10-23.
Проверка включает схему TSV, сохранность префикса, доступность pointers и согласованность claims с последующими событиями.
Это отдельное чтение прежнего журнала текущим docs integrator той же настроенной `codex:gpt-6.1-sol` high/default.
Cross-model diversity и независимый review этого docs drain другим агентом не заявляются.

Для ключевых событий прочитаны прямые T3 reports: r1, fix, r2, прежний docs commit, state drain, stage2 и TS core.
Их thread/run IDs, terminal item IDs и тексты сохранены в external store `docs-drain-direct-t3.json`.
Parent thread `6348e19a-2cfe-4781-b3c5-6d7c056c06e3` целиком не исследовался.
Не читались все исторические чаты или `/root/.codex/logs`. Продуктовые CLI, tests и benchmarks не запускались.

## Подтверждённые события

Строки 20 и 24 сохраняют независимый r1 `FAIL` exact `dea30002cdce4aa5e859d0a3ff6a5124c32bdbe4`.
Прямой terminal report и `stage1-review.json` совпадают: P2, две ложные incoming от некорректных relative imports.
Строка 26 подтверждается terminal fix report для `499acfad48b2d62e37b0f57a3b051bc09eaf847b`.
Writer сообщил 372 passed, 4 deselected, Ruff и mypy. Это не независимый повтор полной suite.

Строка 27 отражает прежнее ожидание r2. Более новый terminal r2 дал `PASS` exact `499acfad48b2d62e37b0f57a3b051bc09eaf847b`.
Прочитаны драйвер и результаты `/tmp/cami-independent-review-r2`: JSON содержит 27 CLI-вызовов с одним старым baseline.
`targeted.txt` содержит 59 passed, `cli.txt` подтверждает исходный repro 2→0 и контракт поиска.
Ещё три doc CLI подтверждены terminal report. Они не пересчитывались как отдельные 27 результатов.
Before/after receipts содержат одинаковые 297 tracked hashes вне docs scope, exact HEAD и index hash.
Actionable findings нет, `graph_complete=false`, прежние limitations и unresolved сохранены.
`stage1-review-r2.json` связывает PASS с SHA, terminal item и хэшами evidence. Принят только согласованный Git Python find scope.

Прямые T3 thread reports подтверждают stage2 и TS core как `running` в разных app-owned worktrees.
Их HEAD прочитаны: stage2 `60d631ffd89cb447eb2f530cb74fc27e22d8ab7a`, TS core `499acfad48b2d62e37b0f57a3b051bc09eaf847b`.
Поэтому будущая интеграция stage2 должна сохранить stage1 fix. Патчи и завершение workers здесь не проверены.
TS launch ограничен trusted compiler core и Python bridge, без CLI integration. Полный TS find после stage2 остаётся задачей.

## Слабые и устаревшие evidence

- Строки 9 и 11 ссылаются на удалённый `reports/orchestration/pstack_sources.md`. Строка 16 уже supersedes эти pointers.
  Отсутствие файла подтверждено. Canonical plugin paths из `references.md` существуют. Историческое дословное совпадение удалённой копии сейчас непроверяемо.
- Строка 4 содержит изменяемые номера строк CLI. Строка 10 уже исправляет evidence на `dcd67fa:src/cami/cli.py:17,94-96`.
  Этот Git blob прочитан. На exact `499acfad…` research `run` по-прежнему вызывает `run_experiment`, строки 109–110.
- Строки 19–30 частично используют `runtime-handles.json#stage1ReviewTask`, `#stage2Task` и аналогичные fragments.
  Это поисковые указатели на элементы массива `units`, не JSON Pointer и не гарантированные renderer anchors.
  `preferences.md#13` в строке 25 указывает на numbered standing rule, не Markdown heading. Само правило прочитано полностью.
- Строки 22, 27 и 30 больше не описывают текущий acceptance: `under_review` и `still_not_verified` предшествуют независимому r2 PASS.
  Строка 28 также называет прежнего владельца main index. Новый run явно передаёт index текущему docs integrator.
- Агрегированные claims строк 11, 18 и 30 о проверке ссылок, схем и всех evidence сильнее одной доступности файлов.
  Старые receipts существуют, их префиксные хэши совпадают с началом текущего trail. Это не повтор всех исторических проверок.
  Файлы `/tmp` и external store доступны сейчас, но не входят в Git docs commit. Хэши не гарантируют их будущую доступность.

Superseding-строки нового run добавлены в конец canonical trail. Старые строки не переписаны.
Исторические quota, initial status и design claims проверены по имеющимся pointers и последовательности записей.
Все ранние runtime runs, исходные telemetry и научные claims независимо заново не воспроизводились.
Таким образом, аудит диапазона не означает полную независимую перепроверку каждого исторического утверждения.

Sibling `task_status` вернул `task_not_found`: задачи принадлежат parent thread.
Использованы прямые `t3_thread_read`; свежие task-level `workState` и pending children должен сверить parent.
Runtime units отдельно учитывают design, implementation, review и docs. Пять продуктовых этапов: один принят, два в работе, два pending.
PR отсутствует, PR ledger не пополняется. Exact-SHA PASS хранится в local receipt без выдуманного PR.
Quota 84% на 11:40:54.145Z, reset 2026-10-29T18:36:49Z передана пользователем и reviewer report, здесь не измерена.

Фактические docs checks и full SHA нового коммита записываются после commit в external `docs-drain-20261023-receipt.json`.
