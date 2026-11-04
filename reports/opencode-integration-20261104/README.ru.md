# Изолированный OpenCode + CAMI: authored smoke

Выполнены три no-model проверки и ровно две модельные сессии OpenCode 2.2.5. Это проверка интеграционных интерфейсов, не benchmark, не подбор задач и не held-out результат. Использован `openai/gpt-6.1-sol#high`; fixture — собственная функция `stable_value`, возвращающая 7. Другие исследовательские задачи и gold не читались.

## Итог и сохранённая неудача

| Попытка | Результат |
| --- | --- |
| `no-model-01` | Частный сервер, изолированный config и MCP initialize/tools-list работают; без сессии генерации |
| `model-sentinel-01` | **Failed**: OAuth, модель и MCP работают, но default session location оказался основным каталогом; read fixture дважды завершился ошибкой, ответ native_value=null |
| `no-model-location-02` | Явный `POST /api/session` закрепил location своего authored Git; prompt не отправлялся |
| `no-model-cami-03` | Настоящий CAMI adapter подготовил existence-claim; OpenCode подключил MCP; location пустой сессии проверен; prompt не отправлялся |
| `model-cami-02` | **Passed**: native read completed, CAMI memory_lookup completed, точный ответ `{"native_value":7,"memory_supported":true,"memory_type":"symbol_exists"}` |

Первоначальный gate ошибочно считал сам вызов read достаточным. В первой модельной попытке это дало неверный `passed`. Исходный manifest сохранён как `manifest.original-incorrect-status.json`; `postcheck.json` раскрывает ошибку, текущий manifest имеет failed. Трассы и ответ не изменены. Вторая попытка требует successful read, exact answer, exact session ID/location и model/variant; третьей модельной попытки не было.

## Воспроизводимый интерфейс

Исходники: `smoke_harness.py`, `run_smoke.py`, `tiny_memory_mcp.py`, `mcp_recorder.py`. Финальные версии исполненного успешного runner и utilities закреплены в `executed-success-source-pins.json`. CAMI adapter — отдельные staged исходники с проверенными хешами в `model-cami-02/adapter-source-pins.json`; они не копировались и не изменялись этим harness.

Формы вызова (реальные результаты уже сохранены; **модельный лимит исчерпан**, следующие model-запуски запрещены встроенным gate):

```text
.venv/bin/python runs/opencode-isolated-smoke-20261104/run_smoke.py --phase no-model --name NEW_NAME --memory-backend cami
.venv/bin/python runs/opencode-isolated-smoke-20261104/run_smoke.py --phase model --name model-cami-02 --memory-backend cami
```

Для работы через явный server URL одного `cwd` клиента недостаточно. Исправленный порядок:

1. `POST /api/session` с `location:{directory:ABSOLUTE_OWN_WORKSPACE}`, agent `research`, model `{providerID:"openai",id:"gpt-6.1-sol",variant:"high"}` и явным title.
2. Проверить возвращённые session ID и точный location **до** prompt admission.
3. `opencode run --server URL --session EXACT_ID --model openai/gpt-6.1-sol#high --agent research --format json PROMPT`.
4. Снова проверить session ID, location, model/variant, successful tools и ожидаемый ответ.

В `effective-input-config.json` каждой попытки сохранён input config; в `observed-config.json`, `observed-agents.json`, `observed-plugins.json` и `observed-model.json` — runtime evidence. В успешной попытке зафиксированы warming=false, share=disabled, update=disable, project config disabled, compaction.auto=false, отдельные XDG/DB/config/tmp/test-home. Shell/subagent/web/mutation plugins отключены, external_directory denied. Сам `$HOME` не менялся. Встроенный MCP client запросил протокол 2025-11-25 и принял JSONL fallback 2025-06-18.

Existence-payload CAMI не содержит текущий код и не доказывает возвращаемое число. Агент прочитал код отдельным общим native read, затем отдельно использовал stored `symbol_exists` с availability=supported. Сырой MCP transport — `mcp-trace.jsonl`; внутренние затраты backend — `adapter-backend-trace.jsonl`; подготовка памяти и её внешний процесс учтены отдельно.

## Credentials и exposure

Только OpenAI credential экспортирован через явный существующий loopback server напрямую в stdin изолированного `auth import --standalone`. Тела export не проходили через Python decoding и не записывались. Import stdout/stderr, потенциально содержащие labels/email, сохранены только как byte counts и exit codes. Полная пользовательская DB не копировалась. Export-клиент тоже использовал изолированные локальные XDG paths. Config/auth/shared-server mutation commands не выполнялись.

Изолированный credential DB, server log и прочий private state удалены после остановки каждого собственного сервера. В evidence остались redacted диагностика и authored CAMI memory DB без OAuth credentials. `private/` пуст. Пользовательский сервер не останавливался и не перенастраивался; абсолютное отсутствие фоновых изменений shared DB независимо не доказывалось.

Оба модельных smoke выполнены на host. Процесс технически мог обращаться к host filesystem при обходе framework permissions: это **не OS sandbox**. В первой попытке location оказался основным репозиторием, но записаны только failed reads отсутствующего fixture; успешного чтения исследовательских файлов не зафиксировано. Для benchmark root отдельно готовит контейнерную mount/network boundary; переносить этот host exposure в held-out опыт нельзя.

## Трассы, usage и внешние ресурсы

`results.json` связывает обе модельные попытки с raw source manifest hashes и содержит агрегаты без пересчёта стоимости подписки. Успешная попытка: три assistant steps; session counters input=3412, output=61, reasoning=0, cache-read=5248, cache-write=0. Input/output/reasoning совпадают с суммой CLI step-finish. Cost field равен 0 — это client metadata, не доказанная стоимость или отсутствие списания по Codex подписке. Нулевой reasoning usage не отменяет подтверждённый variant high.

В failed попытке session totals превышают CLI step sums на 487 input и 9 output. Title был автоматически сгенерирован; возможна дополнительная title-работа, но причинное разложение не установлено. Явный title закреплён перед успешной попыткой; там необъяснённой разницы нет. Session totals и суммы steps хранятся раздельно, не складываются.

Успешная попытка имеет полный SSE след: 30 событий, три step-ended, два tool-success, execution-succeeded, без collector errors/truncation. В первом smoke пятисекундный SSE timeout потерял поздние события; дефект сохранён в event-collector.json и исправлен на длительный timeout с остановкой после собственного server shutdown. Первую SSE трассу считать полной нельзя.

Для успешной попытки сохранены: полный attempt wall до cleanup/inventory snapshot 10.629 s; model-client wall 6.184 s; server-lifetime wall 7.624 s; reaped-child CPU всего 4.596 s; sampled peak server-tree RSS 346464 KiB. CAMI prepare отдельно: 0.637 s wall, 0.369 s child CPU. Это единичные smoke-измерения, не оценки ускорения. Client interval вложен в server lifetime; CPU подфаз также вложены в общий счётчик — повторно не складывать.

Storage snapshot включает public outputs и private DB; private state перед удалением около 18.9 MB. Ограничения: в исходном runner wall snapshot делается до удаления private state и final artifact hashing; собственного Python CPU нет в child CPU; unreaped orphan descendants могут не попасть в rusage; RSS sampling не равен cgroup peak и может дважды считать shared pages. Не измерялись network wire bytes, серверный compute, фактическая subscription billing и provider-side cache reset. Для benchmark нужны cgroup/Docker counters, полная message pagination и отдельная политика auxiliary/background model usage. Оснований для Rust-оптимизации этот smoke не даёт.

Все результаты smoke сохранены; benchmark и новая модельная сессия здесь не запускаются автоматически.
