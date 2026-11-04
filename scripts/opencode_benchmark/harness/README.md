# Контейнерный OpenCode session harness

Статус: staged implementation и authored no-model проверки. Модельные вызовы и auth import в этом контейнерном этапе не выполнялись. Предыдущие два host smoke сохранены отдельно в `runs/opencode-isolated-smoke-20261104/`; они не являются результатом этого harness. Benchmark task/gold файлы здесь не читались.

## CLI и стабильные пути

```text
.venv/bin/python container_session.py \
  --workspace OWNED_PREPARED_WORKSPACE \
  --state-dir NEW_PRIVATE_STATE \
  --memory-dir OWNED_PERSISTENT_MEMORY \
  --arm plain|static|cami \
  --out NEW_OUTPUT \
  [--binding-relative prepared/binding.json] \
  [--no-model] \
  [--prompt-file FILE --run-model --runtime-manifest FROZEN_JSON] \
  [--timeout-seconds 900] [--reported-token-budget 250000] \
  [--cami-source PYTHONPATH_ROOT] [--adapter-dir ADAPTER_DIRECTORY]
```

По умолчанию no-model: prompt file не открывается, credential pipe не запускается. `--run-model` требует prompt и frozen runtime manifest; до разрешения root этот режим не запускался. Пути workspace/state/memory/output должны быть раздельными явно переданными owned directories под `runs/`. Создаются только новые state/output. Chown65534 выполняется только в переданных trial workspace/memory/state; никакие пользовательские каталоги вне них не меняются. Existing output не перезаписывается.

В контейнере всегда `/workspace`, `/memory`, `/state`. Root генерирует canonical catalog и готовит static/CAMI память **внутри того же runtime с repo=/workspace и постоянными /memory путями**. Host-path binding не переносится. Plain получает собственный пустой dummy memory directory; конфигурация прочих инструментов и system prompt совпадает со static/CAMI. В двух memory-режимах одинаковый MCP контракт; меняется backend binding. Свежие OpenCode DB/process/transcript создаются для каждого вызова, `/memory` сохраняется между стадиями. Это process-cold + memory/disk-cache reuse, не warm OpenCode и не гарантированный cold provider cache.

Runtime defaults: binary `/root/.opencode/bin/opencode`, CAMI source root `src/`, adapter `integrations/opencode/`. Overrides обязательны для воспроизведения старого runtime после оптимизации. Источник должен содержать `cami/__init__.py`; adapter — `memory_adapter.py`. Инвентарь включает все regular noncache файлы, в том числе JS/package/analyzer inputs, исключая `.git`, `__pycache__`, pytest/Ruff caches и `.pyc/.pyo`.

`runtime-identity.json` задаёт точный формат входного `--runtime-manifest`: `image_id`, `binary_sha256`, `cami_files`, `adapter_files`. В model-режиме полное равенство проверяется до credential export. Image передаётся immutable `sha256:...`; бинарник закреплён на OpenCode2.2.5 SHA8d060e1d…. Все top-level harness Python sources и probe отдельно закреплены в `stable-source-pins.json`; root включает их в общий study seal.

## Isolation и lifecycle

Контейнер запускается с UID65534, cap-dropALL, no-new-privileges, read-only root, 2CPU, 2GiB RAM, pids256, tmpfs/tmp512MiB. RO mounts: бинарник, CAMI runtime, adapter, ровно два worker/common файла, публичный CA bundle и authored RO sentinel. RW: только свой `/workspace`, `/state`, `/memory` и `/tmp`. Host repo, другие trials, gold и Docker socket не монтируются. Image/current source проверяются до auth и после выполнения.

Helper Python имеет trusted-only PYTHONPATH и PYTHONSAFEPATH1. Worker/MCP не импортируют `/workspace/src`. Только native task commands получают обычный workspace-first Python path; target code там исполняется намеренно для тестов. Server config и project-discovery environment заданы явно, наблюдаемые config sources проверяются до prompt. У всех режимов один agent20steps и одинаковое условное указание консультировать memory_lookup, когда он доступен; запросы/число lookup сохраняются из messages.

Сессия создаётся API с exact location=/workspace, explicit model `openai/gpt-6.1-sol#high`, fixed title. Эти поля проверяются до prompt и после; assistant model identity и эффективный high variant тоже проверяются. Warming/share/update/project config, web/subagent/schedule/image tools отключены. Основные native coding tools сохранены. Равенство конфигураций режимов кроме MCP проверяется unit-контролем.

Credential transfer — только OpenAI export из обнаруженного loopback shared service напрямую в stdin `docker exec ... auth import --standalone`. Shared server/config/auth mutation commands не выполняются. Тело credential не декодируется на пути переноса и не логируется; stdout/stderr import сохраняются лишь как размеры и exit codes. Initial credential values держатся только в host RAM для redaction, объединяются с final values после остановки. `/state` затем удаляется; `/memory` не удаляется.

Own-session shell имеет тот же UID и теоретически может читать собственный `/state` OAuth DB. Это не OS secret isolation; запрет external_directory остаётся framework rule. Docker default/proxy network сохранён, HTTPS trust не отключается; native web tools отключены, но OS egress не закрыт строгим allowlist. Эти ограничения известны и не выдаются за более сильную sandbox-гарантию.

## Статусы, metrics и failures

`passed` означает успешное выполнение harness/OpenCode и целостность протокола. Это **не task grade**: качество проверяет отдельный fixed grader root. Session/messages/SSE, все страницы messages, tool calls, lookup queries, model metadata, raw normalized token components и client cost сохраняются раздельно. Fixed title и согласование session totals со всеми assistant messages обнаруживают неожиданную background usage. Client cost не является доказанной подписочной оплатой.

Установленный normalizer2.2.5: input — noncached; output — visible; reasoning и cache-read/write — отдельные компоненты. Порог250000 считает их сумму и прерывает session после наблюдаемого превышения. Возможен overshoot текущего запроса; это не hard provider/billing quota. Missing/nonfinite provider usage нормализуется в0, поэтому сохраняются raw компоненты и соответствующее ограничение. Source excerpts: `runs/opencode-reconnaissance-20261104/token-semantics/`.

Внешний host wall охватывает lifecycle, auth/setup, worker, publication и cleanup. Cgroup v2 cpu.stat/memory.peak покрывают весь контейнер; worker/server/client интервалы вложены, их не складывают с общим. Docker daemon/controller CPU вне cgroup. `cpu.max`, `memory.max`, `pids.max` реально проверяются. Storage измеряется на границах фаз, перед новым trial требуется ≥5GiB free; hard writable-storage quota нет. Model timeout900s и20steps фиксированы; Docker/client setup имеет отдельные bounded deadlines. Setup памяти выполняется root отдельно и должен прибавляться один раз по своему ledger, не исчезать из total maintenance.

При model failure/timeout сохраняются latest reported usage и best-effort все messages **до** shutdown; недоступные значения null, а не нули. In-flight provider usage может не вернуться. Затем удаляется только известный собственный container name, даже если launch не успел вернуть ID. Неподтверждённая остановка блокирует publication.

После остановки host проверяет evidence root и все descendants без symlink following: только single-link regular UTF8 JSON/JSONL/text, суммарно≤128MiB. Private DB/password/sidecars тоже проверяются на тип/размер перед чтением. Known initial+final secrets, server password/Basic и email/JWT очищаются; known secret в имени файла блокирует export. SQLite/binary/FIFO/symlink/hardlink или невозможная проверка не публикуются. Unsafe payload удаляется с private state; сохраняются safe failure metadata и missing-payload reason. Это fail-closed publication, не полная DLP-гарантия против кодирования неизвестного секрета.

## Проверки и сохранённые итерации

22 authored unit controls проходят; Ruff проходит. В них есть fake credential rotation, password/Basic, secret filename, root/leaf symlink, hardlink/binary/FIFO denial, отсутствующий credential, wrong runtime beforeauth, source inventory/Git closure, неудачный worker, неизвестная остановка writers, отсутствующее evidence, частичный/недоступный failure usage и token-component arithmetic. Реальные credentials/model/task data в unit tests не использованы. Часть publication-контролей предоставил независимый reviewer; исходник скопирован без изменения логики.

Финальные `check-{plain,static,cami}-final` прошли на exact pinned helpers: no model/auth, UID/cgroup caps, explicit session path, shell API read, writable own workspace, RO sentinel EROFS30, host repo/gold/socket недоступны, два shell messages прочитаны полностью через три API pages при limit1; private state и собственный контейнер удалены. Для memory-режимов подтверждены OpenCode MCP connection/catalog и реальная container-side preparation. Сам memory_lookup через OpenCode в контейнере ещё не вызывался: его проверяет следующий root-owned authored model smoke.

`check-*-02` сохранены failed: probe ошибочно использовал Path.exists на запрещённом `/root`, получил PermissionError; это ошибка probe, не утечка mount boundary. Исправление явно измеряет unreadability. Первые вызовы memory-arm без обязательного binding отвергнуты CLI до launch; это отдельно указано в verification report. Все более ранние checks сохранены, а финальный набор отмечен явно. Это development verification, не измерение производительности.
