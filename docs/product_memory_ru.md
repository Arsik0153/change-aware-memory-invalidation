# Рабочая память для CLI-агента

`cami memory` сохраняет структурные ожидания и ручные заметки между процессами.
SQLite хранит immutable revisions, проверки, состояния, историю и product head.
Состояние находится в `$XDG_STATE_HOME/cami/repos/<worktree-key>` или
`~/.local/state/cami/repos/<worktree-key>`. Capture исключает этот каталог,
если он находится внутри repository. Команды не импортируют код target repository.

## Сохраните ожидание из закреплённого контекста

Сохраните JSON вне source roots. Команды `context`, `remember`, `update` и `refresh`
повторно согласуют текущий worktree.

```bash
cami memory context src/api.py:create_user --repo "$REPO" --format json > /tmp/context.json
cami memory remember symbol_exists src/api.py:create_user --repo "$REPO" \
  --from-context /tmp/context.json --request-id agent-exists-1 --format json
cami memory remember signature_equals src/api.py:create_user --repo "$REPO" \
  --from-context /tmp/context.json --request-id agent-signature-1 --format json
cami memory remember note src/api.py:create_user --repo "$REPO" \
  --note-key api-return-contract --text 'Returns the input name unchanged.' \
  --from-context /tmp/context.json --request-id agent-note-1 --format json
cami memory context src/api.py:create_user --repo "$REPO" --format json
```

`context` разрешает короткое имя. Registration требует ровно один однозначный subject.
Backend проверяет `index`, `code` и привязку memory generation к immutable сохранённому view.
Переданные агентом signature или hashes не становятся evidence без этой проверки.
Старый корректный context сохраняет старый origin. Текущая проверка может сразу
скрыть зарегистрированное ожидание из-за несовпадения с новым кодом.

`symbol_exists` проверяет exact language/path/qualname/kind. `signature_equals`
сравнивает versioned structural syntax, без display signature и inferred types.
Python canonical form содержит AST параметров, annotations, defaults, decorators,
return, type parameters и async. Отсутствующий default отличается от `None`.
Формат привязан к версии Python через analyzer fingerprint.

## Используйте доступные сведения

Ответ содержит `index`, `memory_generation_id`, `observation`, `code`, `facts`,
`notes`, `withheld` и ограничения. `verified_readset` описывает проверенный интервал
чтения. Правка после проверки остаётся возможной.

`facts` содержит только supported structural predicates. Состояние `carried`
сохраняет исходные check ID, timestamp и snapshot. Dependency equivalence относится
к текущему index, но не создаёт validation event. Изменение тела может сохранить
existence и signature, если их структурные входы не изменились.

`notes` всегда имеет label `manual_assertion`. Текст и поведение автоматически
не проверяются. По умолчанию source заметки охватывает полный captured файл.
После изменения bytes заметка получает sticky `needs_review`. Даже возврат bytes
не снимает review. `withheld` сообщает машинную причину и `required_action`.

```bash
cami memory context src/api.py:create_user --repo "$REPO" --format json > /tmp/review.json
cami memory update "$NOTE_ID" --repo "$REPO" --if-revision 1 \
  --from-context /tmp/review.json --text 'Reviewed against this source.' \
  --request-id agent-note-review-2 --format json
cami memory history "$NOTE_ID" --repo "$REPO" --format json
cami memory refresh --repo "$REPO" --format json
```

Update сохраняет subject, создаёт revision и требует CAS `--if-revision`.
Для двух конкурентных update одной revision проходит только один.
Одинаковый request ID с одинаковым запросом возвращает прежний mutation receipt.
Другой запрос с тем же ID даёт conflict. Receipt описывает мутацию.
Перед использованием сведений запрашивайте новый context.
Разные request IDs для одинакового structural identity не создают копий.
Новая expectation для существующей записи требует update.

## Различайте отсутствие и недостаток evidence

Deletion считается contradicted только с captured witness отсутствия пути или
символа в успешно разобранном файле. Capture запоминает перечисленные каталоги
и scoped path probes в том же readset. Отсутствия записи в manifest недостаточно.
Ignored, excluded, symlink, unavailable, parse error и ambiguity не доказывают deletion.
При неизвестном языке или форме predicate возвращает insufficient evidence.
Contradiction и insufficient evidence являются результатами с exit 0.
Input и conflict дают exit 2, отсутствующий ресурс даёт 3, незавершённый refresh даёт 4.

`--source-root` и `--exclude` доступны во всех memory commands. Смена policy
может убрать evidence и потребовать проверки. История доступна без live refresh
и остаётся явно historical. Повреждённые SQLite/schema/source objects дают ошибку.
Автоматической подмены повреждённой базы пустой памятью нет.

`memory.initialized` сохраняет durable доказательство инициализации вне SQLite.
Первый запуск создаёт полную schema во временной базе, публикует её через hard link
без перезаписи существующего пути,
затем синхронизирует доказательство до любой записи knowledge. Retry после аварии
до публикации начинает инициализацию заново. После публикации проверяет готовую базу.
Существующая корректная база предыдущей версии получает доказательство без удаления
истории. Отсутствующая база при сохранённом доказательстве или `source-objects`
даёт exit 4, `memory_database_unavailable`. Пустой ответ вместо потерянной истории
не возвращается. Если удалить весь каталог состояния вместе с доказательством,
инструмент не может отличить это от первого запуска. Восстановление знаний не заявляется.

SQLite открывает только частную копию базы. До открытия инструмент захватывает
main file и rollback journal через bounded descriptor I/O. Общий worktree lock
сохраняется на всю операцию. Exclusive POSIX byte locks основного файла исключают
одновременный доступ SQLite из другого процесса. Занятый файл даёт exit 4,
`memory_database_busy`. Прямые SQLite-соединения в том же процессе не поддерживаются:
POSIX locks принадлежат процессу и снимаются при закрытии любого descriptor этого inode.

Восстановление hot journal меняет только частную копию. После восстановления
инструмент проверяет schema, integrity, scope, head и соответствие
`Connection.serialize()` частному файлу. Исходные descriptor identity и journal bytes
проверяются повторно до доступа к knowledge и публикации. Подмена частного файла
на время SQLite open даёт exit 4 и сохраняет исходную пару DB и journal побайтно.
Следующая обычная команда может восстановить её. Quoted URI `mode=rw`,
`foreign_keys=ON` и `synchronous=FULL` применяются к частной базе.

Публикация использует каталог `memory.pending`. Он содержит `next.sqlite3`,
typed manifest `commit.json` с hashes старого и нового main file и journal,
а при наличии journal также его точную копию `original-journal`.
Файлы и каталог синхронизируются до атомарной публикации `memory.pending`.
После синхронизации родительского каталога новая транзакция считается durable.
Только затем удаляется проверенный live journal. Его удаление синхронизируется
до замены main file. Поэтому новый main file не остаётся рядом со старым journal.
Новый inode также блокируется до завершения публикации.

После аварии следующая команда проверяет hashes и частную копию `next.sqlite3`,
завершает замену main file и удаление journal. Она принимает старый main file
или уже установленный новый. Несовпадение evidence даёт явную ошибку без перезаписи.
После синхронизации main file инструмент атомарно переименовывает весь
`memory.pending`, синхронизирует родительский каталог и удаляет временные файлы.
Авария во время cleanup не оставляет частично удалённый действующий commit.
Повтор мутации сохраняет один receipt и revision.

Schema version 1, `memory.sqlite3`, `memory.initialized`, revisions и старые
expectations сохраняются. Миграция SQLite не требуется. Новый формат публикации
используется при следующей записи или восстановлении journal. Старые binaries
не умеют завершать `memory.pending`; downgrade во время незавершённой публикации
не поддерживается. SIGKILL может оставить частные временные каталоги. Они не
становятся evidence и не используются для восстановления вместо `memory.pending`.

Основной файл и каждый recovery artifact ограничены 256 MiB. Поддерживается
single-database rollback journal с корректным SQLite header и bounded размером
восстановленной базы. WAL, SHM, attached-database super-journal, неизвестный header
или неподдерживаемые размеры дают exit 4 до открытия SQLite и сохраняют bytes.
Автоматического удаления таких artifacts или сброса базы нет. Гарантии против
замены всех доказательств или удаления всего scope не заявляются.

Source CAS и `--from-context` читаются через bounded descriptor I/O с `O_NOFOLLOW`
и `O_NONBLOCK`. Перед чтением проверяются regular file и размер. Чтение ограничено
исходным размером плюс один byte, CAS дополнительно проверяет expected size и SHA-256.
Изменение файла во время чтения, FIFO, symlink, directory и oversized artifacts
дают явную ошибку. Повреждённое историческое evidence не подменяется live reread.

## Подключите нейтральный index port

`ProductMemory(..., port=...)` принимает `ProductIndexPort` из
`product/memory/adapters.py`. `prepare_locked` вызывается под общим worktree lock,
до SQLite transaction. Он возвращает `PreparedIndex` с immutable `CodeView`,
captured bytes, observation и base commit. `verify` повторно проверяет тот же readset
перед DB commit. Port не должен повторно брать flock. Порядок всегда lock, затем DB.

Default `HybridIndexPort` использует общий `refresh_locked`. Один `IndexedWorktree`
передаёт Python index и `EcmaReady` analysis в единый `CodeView`; повторного TS analysis нет.
Captured blobs дают общие `SourceRef`, signature normalization выполняется одним batch. Index/source objects сохраняются
до DB commit. SQLite product head закрепляет composite generation. Index pointer
остаётся cache hint. После аварии между публикацией index и commit следующий
current query согласует оба слоя. No-change refresh сохраняет memory generation.
Старые и новые dependencies и relation scopes участвуют в invalidation explanations,
поэтому deletion и rename не теряют старое основание.

`ecma_view(EcmaAnalysis, IndexRef, captured, coverage)` адаптирует реальный TS Core v1.
Интегратор передаёт полный captured sources/configs/package readset и включает
compiler/configuration fingerprints в `IndexRef`. Signature использует только
поля `EcmaSignature`, без inference. Для methods core v1 не отдаёт access modifiers,
поэтому signature predicate пока insufficient `unsupported_symbol_kind`.
Declaration groups без доказанной уникальности не объединяются в overloads.

Canonical format `ecma.syntax-signature/2` использует trusted TS 6.0.3 printer
для удаления comments и traversal полного дерева tokens. Operators, keywords,
literals, modifiers и порядок списков сохраняются независимо от display signature.
Whitespace и comments не меняют expectation. Формат `/1` остаётся читаемым в старых
revisions и history, но сравнение с `/2` возвращает insufficient evidence,
`signature_schema_mismatch`. Lost information старого формата не восстанавливается
догадкой и expectation не retargeted. Требуется явный update из нового context.
Validator fingerprint меняется, поэтому current claims проверяются заново.

`ecma_view(..., trusted_compiler=Path(...))` и `ecma_signatures` принимают путь
к compiler module из trusted setup интегратора. Это API для trusted backend,
не CLI option для target repository. По умолчанию используется `compiler_path()`
из user cache после `cami setup-typescript`. И default, и override проходят общую
`trusted_compiler` проверку. Node environment очищается от NODE_OPTIONS/NODE_PATH.
Compiler проверяет точную версию 6.0.3 под Node 24. Target npm и scripts не запускаются.

ECMA unavailable withholds только ECMA claims; Python остаётся доступным.
Typed `identity_gaps` из существующего compiler traversal удерживают unsupported
bindings, namespace bodies и computed members как insufficient evidence.
Unresolved calls сами по себе не отменяют известные local definitions.
Подтверждённое отсутствие пути берётся из captured probes/directories.

Installed CLI acceptance запускается без production imports:

```bash
python3 tests/memory/hybrid_cli_driver.py --cami /installed/bin/cami --out /tmp/new-hybrid-evidence
```

Driver проверяет обе language projections, provenance, receipts, carry timestamps,
review/CAS, history, signature syntax, unavailable/recovery и config/ignore/scope.
Полная приёмка Stage 4 требует отдельного storage R3 исправления и fresh review
окончательной интеграции в main.

## Повторите Python acceptance

Driver использует фиксированные templates и literal expected outcomes. Он не
импортирует production validator или canonicalizer для вычисления ожиданий.
Каждая CLI-команда работает в отдельном процессе. Укажите новый output directory.

```bash
PYTHONPATH=src .venv/bin/python tests/memory/cli_driver.py --out /tmp/cami-memory-evidence
PYTHONPATH=src .venv/bin/python -m pytest tests/memory -q
```

Driver сохраняет command arguments, exit codes, stdout, stderr и result.json.
Дополнительные tests проверяют concurrent mutations, CAS, source evidence после
live edit, crash до и после index publication и DB commit, ошибки refresh и corrupt DB.
`cami find` и research CLI сохраняют свои контракты. Product checks не создают
human receipts, не меняют research known_incomplete и не участвуют в datasets.

### Статические имена ECMA members

Compiler traversal использует один ключ для identifier, string literal (включая
escapes), numeric literal и непосредственно вычисляемого `["name"]` / `[16]`.
Объявления `createUser() {}`, `"createUser"() {}` и `["createUser"]() {}`
внутри `class Users` дают selector `api.ts:Users.createUser`. Числовые spelling `16`,
`0x10` и `"16"` дают один сегмент `16`. Произвольные строки, которые не являются
identifier или целым десятичным сегментом, сохраняются как JSON string: например
`C."a.b"` отличается от вложенного `C.a.b`, а public `C."#x"` — от private `C.#x`.
Static и instance members используют прежний общий namespace; совпадения
нормализованных ключей дают ambiguity, а не выбор одного определения.

Та же нормализация применяется к coverage gaps для неподдерживаемых fields и
accessors. `"createUser" = wrap(...)` удерживает `Users.createUser` как
`binding_unresolved`, а не подтверждает удаление. Динамические computed names,
включая выражения, template literals и дополнительные wrappers, не вычисляются;
они удерживают methods соответствующего scope. Посторонняя top-level function
сохраняет поддержку. Constructors не становятся methods. Нормализация имён
не добавляет canonical signature для methods и не обещает runtime dispatch.
