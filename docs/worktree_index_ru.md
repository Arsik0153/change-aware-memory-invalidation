# Контракт рабочего дерева и постоянного индекса

`cami find SYMBOL --repo PATH` читает рабочее дерево. Staged и unstaged версии
не объединяются: анализируются текущие bytes файла на диске. Untracked `.py`
участвуют без `git add`; delete удаляет определения; rename меняет путь и
пересчитывает граф. Явный `--revision HEAD` или SHA читает только Git objects.
Ни один режим не запускает target Python или target-конфигурацию.

## Идентичность и покрытие

Product JSON имеет schema version 2. Research Record v1 остаётся прежним.
`snapshot.kind` различает `worktree` и `git`; поля commit и tree относятся
только к Git. `base_commit` у worktree является контекстом capture и может
быть `null`. Он не служит идентичностью незакоммиченного содержимого.

`snapshot_id` является SHA-256 канонического manifest входов и capture policy.
Manifest содержит пути, типы, режимы, размеры, hashes bytes и ограничения.
Hash вычисляется по полному прочитанному содержимому, включая комментарии,
пустые строки и файлы больше лимита разбора. Изменение только комментария
меняет snapshot и строки результатов. Возврат тех же bytes и policy позволяет
переиспользовать прежнее поколение независимо от staged-состояния и commit.

`generation_id` дополнительно включает fingerprint schema, Python, Pydantic,
AST-индекса и продуктового кода. Корни, исключения и ignore-policy входят в
snapshot identity. Код продукта меняет fingerprint автоматически. Изменение
корней пересчитывает имена модулей и связи, даже если bytes файлов прежние.

`coverage: complete` относится к включённым поддерживаемым Python-входам.
Синтаксическая ошибка, symlink, submodule, специальный или слишком большой
файл дают `partial`. Healthy-файлы доступны. Определения и связи повреждённого
файла из старого поколения не переносятся. `not_found` при `partial` имеет
`absence_confirmed: false`; он не доказывает отсутствие определения.
Статические связи всегда неполны, в том числе при `coverage: complete`.
Неподдерживаемые языки обозначены общим limitation
`python_functions_and_methods_only`. JavaScript и TypeScript пока не индексируются.

## Проверяемый набор прочитанных входов

Consistency равен `verified_readset`. В `observation` отдельно от стабильного
payload находятся UTC-поля `capture_started_at`, `verified_at` и `cache_reused`.
Это интервал чтения и проверки, не атомарный filesystem snapshot. OS lock CAMI
сериализует процессы CAMI, но не блокирует редактор или Git-команды пользователя.
Изменения после проверки возможны; ABA между чтениями не исключается.

Один запрос выполняет следующие действия:

1. Берёт writer lock для canonical корня этого worktree.
2. Перечисляет включённые входы и читает их через descriptors. Все компоненты
   worktree-пути открываются без следования по symlinks. `fstat` до и после
   чтения проверяет замену, тип, размер и метаданные. Чтение ограничено исходным
   размером плюс один byte для обнаружения роста. Directory metadata
   проверяется после обхода. FIFO и устройства не открываются для чтения.
3. Выбирает готовое поколение с проверенными manifest, schema и checksum либо
   строит полный индекс исключительно из captured bytes.
4. Повторно перечисляет и читает входы. Сверяет content identity, policy и HEAD.
5. Публикует только прошедшее проверку поколение и возвращает закреплённый индекс.

При обнаруженном изменении весь capture повторяется до трёх попыток.
Исчерпание даёт `capture_unstable`, exit 4 и пустой stdout. Ошибка чтения или
доступа даёт exit 4 вместо фиктивного delete или `not_found`. Предыдущее
поколение не возвращается как свежее. Ошибка разбора отличается от ошибки
чтения: bytes известны, поэтому parse limitation допускает partial-поколение.

## Политика обхода

`--source-root` принимает повторяемые repository-relative POSIX-пути.
Без него корни равны `src`, `.` при наличии включённых `.py` под `src/`, иначе
`.`. Более глубокий корень задаёт имя модуля. `--exclude PATH` исключает точный
путь и его потомков, включая tracked-файлы. Пустые, абсолютные пути и `..`
недопустимы. Эти CLI-параметры не исполняют target-конфигурацию.

Git ignore rules применяются к untracked-входам с обычными Git negation и
nested rules. Tracked-файл остаётся входом, даже если новая `.gitignore`
игнорирует его путь. Учитываются repository `info/exclude`, глобальный
`core.excludesFile` и стандартный global ignore. Их содержимое входит в
ignore fingerprint. Точечное чтение ignore metadata не обходит `.git`.

До спуска исключаются `.git`, `.venv`, `venv`, `node_modules`, `__pycache__`,
`.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.cache`, `.tox`, `.nox`.
Корневые `runs`, `reports`, `output`, `cache` также исключены. Product state
исключён целиком, если находится под target root. Эта политика действует
даже для tracked-файлов. В submodules и directory symlinks обход не входит.
Symlink и special-file limitations видны явно. Лимит разбора равен 2 MiB;
hash слишком большого файла вычисляется потоково по всем bytes.

## Постоянные неизменяемые поколения

State находится в `${XDG_STATE_HOME:-~/.local/state}/cami/repos/<worktree-key>/`.
Ключ включает canonical worktree path, поэтому linked worktrees имеют отдельные
writer lock и current pointer. Запрос из вложенного каталога использует Git root.
Worktree backend использует POSIX descriptors и `flock`. Git-режим не загружает
этот backend и не читает и не пишет product state.

Каталог содержит следующие данные:

```text
writer.lock
current.json
generations/<generation-id>/manifest.json
generations/<generation-id>/index.json
```

Manifest хранит policy и hashes входов. Index содержит неизменяемый `CodeIndex`
со source, определениями, static edges и unresolved signals. Pickle не используется.
Готовое поколение повторно используется между процессами только после нового
capture и его проверки. Это свидетельство reuse, не измерение ускорения.

Writer создаёт `.pending-*`, записывает и синхронизирует index и manifest,
синхронизирует каталог, затем переименовывает его в окончательный generation.
Только после этого заменяет `current.json` через отдельный temporary file.
Файлы и родительские каталоги синхронизируются через `fsync`. Все writers
сериализованы до завершения публикации. Query закрепляет одно поколение;
здоровые опубликованные каталоги не перезаписываются и не удаляются.
Автоматического GC пока нет.

После crash неполные temporary directories игнорируются. Завершённое поколение
без переключённого pointer может быть найдено по content identity и использовано.
Повреждённый или несовместимый manifest/index вызывает stderr diagnostic и
пересборку. Повреждённый каталог переносится в `.corrupt-*`, а восстановленный
кандидат публикуется целиком. Недоступный state даёт явную ошибку, не stale answer.
Повреждённый pointer восстанавливается из проверенного поколения.

## Проверки поведения

Из корня CAMI выполняются следующие команды:

```bash
uv run --locked pytest -q tests/test_worktree_search.py tests/test_symbol_search.py tests/test_index.py
uv run --locked pytest -q -m 'not docker'
uv run --locked ruff check .
uv run --locked mypy src/cami
git diff --check
```

CLI fixtures запускают отдельные процессы для edits, staged/unstaged, untracked,
delete, rename, revert, comment-line changes и HEAD isolation. Дополнительно
проверяются reuse без вызова builder, parse recovery, ignore/exclude rules,
linked worktrees, SHA-256 Git, symlinks, FIFO и paths with spaces. Управляемые
hooks меняют входы между capture и verification, имитируют permission failure
и останавливают процесс до и после atomic rename. Два настоящих процесса
проверяют writer serialization и одинаковый закреплённый generation.

Эти тесты проверяют достижимый readset contract. Они не доказывают атомарность
произвольных внешних изменений файловой системы. Docker, реальные heldout
Requests/pytest и scientific freeze для этого этапа не требуются.
