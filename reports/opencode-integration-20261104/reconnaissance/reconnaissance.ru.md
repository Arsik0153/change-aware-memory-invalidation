# OpenCode 2.2.5: локальная разведка интерфейсов

Проверена установленная версия, без вызовов модели, изменения конфигурации, credentials или работающего сервера. Бинарник `/root/.opencode/bin/opencode`: версия `2.2.5`, SHA-256 `8d060e1d2fbb9bb44cf09ae6ed1f3f6a7cff070b5227e2f90970132b23a92050`. Версия существующего loopback-сервера также `2.2.5`. Help/version выполнены непосредственно этим бинарником; команды и выводы сохранены в `help-commands.json` и `help-*.txt`. Пять HTTP GET к уже работающему серверу перечислены в `http-read-commands.json`; POST/PATCH/PUT/DELETE не выполнялись.

## Подходящая первая граница интеграции

Практический первый вариант — локальный stdio MCP-сервер с одинаковыми именами и JSON schemas инструментов памяти в двух memory-режимах. Plain не получает память; memory без CAMI и memory с CAMI используют один внешний контракт, разные реализации обслуживания. Нативные инструменты чтения, поиска и изменения кода остаются общими. Их фактический каталог зависит от модели: встроенный OpenAI plugin может убирать edit/write в пользу patch. Список активных tool plugins ещё не равен каталогу конкретного model request. CAMI exact selector не следует выдавать за полноценный regex grep. Специфика CAMI-операций исследуется отдельным агентом root.

Установленная схема `Config.InfoEncoded` содержит `mcp.servers`, а `Mcp.LocalConfigEncoded` — `type:"local"`, `command:string[]`, `cwd`, `environment`, `disabled`, `codemode` и `timeout.{startup,catalog,execution}`. Для прозрачного отдельного memory tool полезно явно задать `codemode:false`; фактическое имя и описание инструмента проверяются в следующем authored smoke test. Конфигурация в `proposed-isolated-config.json` — черновой интерфейс для будущей проверки, не установленная настройка. Ни MCP-процесс, ни OpenCode-сессия здесь не запускались.

## Native plugins и возможная замена поиска

В v2 есть native plugin API, отличный от старых примеров OpenCode v1. Встроенный loader требует default export с `id` и `effect` либо `setup`. Promise-адаптер делает доступными:

- `api.tool.transform(editor => ...)`, где editor имеет `list/get/add/update/remove/namespace`;
- `api.tool.hook("execute.before", callback)` и `api.tool.hook("execute.after", callback)`;
- `api.session.hook(...)`, включая используемые встроенными plugins `context`, `compaction`, `generate`, `retry`;
- `api.session.instructions.entry.put/list/remove` и `api.session.synthetic`.

Это подтверждено встроенным кодом, а не запуском нашего plugin. Точные фрагменты: `embedded-03.js.txt`, `embedded-tool-hooks-and-edit.js.txt`, `embedded-plugin-loader.js.txt`; byte offsets исходного бинарника записаны в `embedded-source-index.json`. Для local package loader ищет `server` entrypoint, затем корневой; `package.json` exports может направить `./server` на локальный JS-файл. Loader умеет читать auto-discovered `plugin/` и `plugins/` под config directories. В явном `plugins` поле локальный путь должен быть каталогом, одиночный файл там отбрасывается. Не нужно устанавливать npm-пакет или обновлять OpenCode ради первого локального plugin.

Обёртка существующего grep через `tool.transform(...update...)` технически возможна. Это ещё не доказательство совместимости CAMI-поиска с grep: нужно сохранить input/output schema, regex/path/line semantics, ограничения, cancellation, fallback и permissions. Поэтому прямую замену следует считать отдельным необязательным вариантом после contract tests. Для добавления нового native tool также нужно проверить конкретный schema codec v2; считать произвольный JSON Schema автоматически подходящим для native `input/output` нельзя. MCP устраняет эту неопределённость первой интеграции.

## Изоляция сессий и состояния

Help подтверждает:

```text
opencode run --standalone --model openai/gpt-6.1-sol#high --agent research --format json MESSAGE
opencode serve --hostname 127.0.0.1 --port PORT
opencode run --server http://127.0.0.1:PORT --session SESSION --model openai/gpt-6.1-sol#high --agent research --format json MESSAGE
```

Это формы будущего вызова, не выполненные команды. `research`, `PORT`, `SESSION`, `MESSAGE` здесь placeholders. Custom agent нужно сначала объявить в изолированной конфигурации. `--standalone` запускает частный сервер; `--server` соединяет с явно указанным. Вместе они запрещены. Сам по себе `--standalone` не изолирует SQLite, config, credentials или filesystem caches.

Встроенный код подтверждает `OPENCODE_DB` — абсолютный/относительный путь к DB либо `:memory:`, XDG data/config/cache/state paths, `OPENCODE_CONFIG_DIR`, `OPENCODE_CONFIG`, `OPENCODE_CONFIG_CONTENT`, `OPENCODE_CONFIG_PROJECT_DISABLE` и alias `OPENCODE_DISABLE_PROJECT_CONFIG`. `OPENCODE_TEST_HOME` меняет OpenCode `Global.home`, но не обещает заменить home во всех сторонних библиотеках. Для будущего trial нужны отдельные DB, XDG directories, config directory и root-owned workspace; глобальный `$HOME` здесь не изменялся и в командах не переопределяется. Пины и источники: `embedded-00.js.txt`, `embedded-01.js.txt`, `embedded-02.js.txt`.

Для cold trial — новый local state и новый процесс; для repeated/post-change sequence — явно выбранные DB/session и один частный сервер на всю последовательность, если протокол требует сохранять process caches. Новый `run --standalone` на каждом шаге сохраняет DB при том же пути, но перезапускает process caches. Transcript continuation и повторный запрос с чистым transcript — разные условия; их нужно закрепить отдельно и одинаково во всех режимах. Provider-side prompt cache локально очистить не доказано; cold здесь может означать только local-cold. Фактический cache token usage нужно сохранять.

Один OpenAI OAuth credential уже есть. Никакие токены, email, account IDs, credential bodies или их хеши не сохранены. DB прочитана в SQLite `mode=ro&immutable=1` только для schema и allowlisted metadata; такой snapshot может не содержать свежий WAL. Полная пользовательская DB в trial не копируется: она содержит чужие sessions и account material. Help поддерживает `auth export openai` и `auth import` из stdin. Будущий узкий перенос только OpenAI credential в изолированный DB можно сделать приватным pipe без вывода/логирования его содержимого; он здесь не выполнялся. Нужна последующая проверка изолированного provider settlement, refresh и доступности выбранного model. Наличие OAuth не доказывает текущую валидность, квоту или успешность будущего model request.

## Модель и явные настройки

Локальный `GET /api/model` вернул 19 активных OpenAI chat model IDs; полный allowlisted snapshot — `active-openai-model-metadata.json`. В нём есть `openai/gpt-6.1-sol`, backend `modelID` и варианты `low/medium/high/xhigh/max`. У `#high` настройки `reasoningEffort:"high"`, `reasoningSummary:"auto"`, `include:["reasoning.encrypted_content"]`. Backend URL — Codex endpoint `https://chatgpt.com/backend-api/codex`; temperature capability равна false. Значит общий temperature=0 нельзя молча навязать этой модели. Не подтверждены seed и детерминированное воспроизведение ответа.

Для сравнения нужно закрепить полную model/variant identity и эффективные settings, один agent/system prompt, tools, permissions, compaction и resource limits. `local-openai-model-ids.json` отдельно содержит public cached catalog: это более широкий список и не равно текущей доступности. Snapshot активного сервера сильнее cached catalog, но всё ещё не является успешной модельной пробой. Другие fast/ultrafast IDs не подменяют выбранный обычный ID.

Следует явно отключить `warming`: встроенный plugin способен после сессии отправлять дополнительные keep-alive model requests. Его код сохранён в `embedded-warming.js.txt`. Аналогично для контролируемого теста закрепляются `update:"disable"`, `share:"disabled"`, отсутствие лишних plugins/skills/MCP, запрет project-config discovery, одна политика compaction, schedules/media/subagent tools и web access. `OPENCODE_DISABLE_MODELS_FETCH` и `OPENCODE_MODELS_PATH` подтверждены кодом для models-dev; не доказано, что они запрещают все account-specific metadata/refresh запросы. Отключение background-механизмов ещё нужно проверить в изолированном no-model smoke test.

## API, трассы и стоимость

`installed-openapi.json` — фактическая OpenAPI-схема работающего v2.2.5 сервера (138 paths). Компактная выборка сохранена в `interface-evidence.json`.

| Операция | Подтверждённый интерфейс |
| --- | --- |
| Создать session | `POST /api/session`: location `{directory}`, model `{providerID,id,variant}`, agent, permissions, metadata |
| Передать input | `POST /api/session/{sessionID}/prompt`: text/files/agents/skills/metadata/delivery/resume |
| Читать результат | `GET /api/session/{sessionID}`, `GET .../message`, `GET /api/experimental/session/{sessionID}/export` |
| События | `GET /api/event`, SSE; фильтр types; session/tool/step/execution/usage события |
| Permissions | rules `{action,resource,effect}`; effect allow/deny/ask; отдельный reply endpoint |
| Инструкции памяти | experimental instructions entry PUT/GET/DELETE и synthetic message; альтернативный механизм, не смешивать с tool-only arm без объявления |

CLI `--format json` пишет JSONL с `type,timestamp,sessionID,...`; код содержит `step_start`, `step_finish`, `text`, `reasoning`, `tool_use`, `error`. Step-finish несёт cost и tokens. Reasoning-текст выводится при `--thinking`; его сохранение не требуется для основных metrics. Код CLI сохранён в `embedded-cli-json-trace.js.txt`. SSE и session export богаче CLI-вывода и лучше подходят для raw trace.

Schemas `Session.Info` и `Session.Message.Assistant` содержат tokens `{input,output,reasoning,cache:{read,write}}`, cost, model, agent и timestamps; tool parts содержат state с input/content/status/metadata и `time.{created,ran,completed}`. Нельзя складывать session totals с message totals или автоматически прибавлять reasoning/cache к другим token fields: сначала проверить семантику provider usage на smoke test. Cost — поле клиента, а не доказанная сумма списания с подписочного Codex аккаунта. Missing/нулевые поля учитывать явно, не заменять собственной оценкой без маркировки.

Для полного wall time нужны внешние monotonic timestamps от старта setup до завершения maintenance/ответа, отдельно startup/warm phase. Инструментальный trace не включает автоматически все затраты CAMI, сборки памяти, SQLite, MCP startup или дочерних CLI-процессов. Их CPU, RSS, disk, elapsed time и stdout/stderr нужно измерять harness-ом и включать в maintenance total. Профилировать можно после закрепления нагрузки; оснований переносить что-либо в Rust из этой разведки нет.

## Permissions и ограничения вывода

`--auto` одобряет то, что явно не запрещено. Без него noninteractive run отклоняет запросы permissions; это может менять качество и завершение задач. Нужен одинаковый заранее проверенный allow/deny contract всех трёх режимов. OpenCode rules — не доказанный OS sandbox: они не заменяют process/container filesystem/network/resource isolation и не делают произвольный plugin безопасным. Не следует применять `--auto` к пользовательскому shared server.

Не проверены модельным вызовом: OAuth refresh/entitlement, tool registration/schema compatibility, JSON usage completeness, cancellation, actual cache isolation, выбранный native plugin и весь benchmark harness. Ни одна задача, oracle, held-out split или оценка качества здесь не выбраны. Следующая конкретная единица — изолированный authored tool/config/permission smoke test без модели; затем закреплённая короткая модельная проверка интерфейсов до разработки held-out набора. Пользователь уже разрешил OpenCode test sessions; эта разведка не использовала это разрешение для новых модельных запросов.
