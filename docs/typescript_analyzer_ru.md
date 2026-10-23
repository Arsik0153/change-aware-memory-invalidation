# Контракт compiler analysis для захваченного JS и TypeScript

Этот компонент предоставляет `cami.typescript_analyzer.analyze_typescript` для адаптера продуктового индекса.
Он подключён к `cami find` и persistent generations через `cami.product.ecma`.
Neutral EcmaAnalysis schema v1 независима от research Record и product JSON v3.
Watcher и product memory пока отсутствуют.

## Вход и запуск

Caller передаёт полную mapping `repo-relative path -> str | bytes`.
Байты декодируются как UTF-8. Caller также передаёт JSONC configs и нужные resolver inputs.
Пути должны быть каноническими, относительными, с `/`. Traversal, control characters и `node_modules` запрещены.
Анализатор не читает target checkout и не выбирает tracked, ignored или untracked файлы.
Состав capture и согласованность его чтения остаются обязанностью caller.

```python
from cami.typescript_analyzer import analyze_typescript

analysis = analyze_typescript(
    {
        "src/users.ts": "export async function createUser(name: string) { return name }",
        "route.ts": "import {createUser} from './src/users'; function POST(){createUser('Ada')}",
        "tsconfig.json": '{"compilerOptions":{"moduleResolution":"bundler","module":"esnext"}}',
    },
    request_id="captured-generation-42",
)
json_text = analysis.model_dump_json(by_alias=True)
```

`root_config=None` выбирает захваченный root `tsconfig.json`, затем `jsconfig.json`.
При отсутствии обоих CAMI явно сообщает `default_module_mode` и использует ESNext с bundler resolution.
`root_config` может явно выбрать другой захваченный JSON config.
Root config задаёт compiler options для всех переданных source files.
`files`, `include`, `exclude` не фильтруют capture. Nested config contexts и project references не поддерживаются.

Каждый вызов запускает один trusted Node process. Кешей и daemon нет.
Лимиты составляют 10 000 captured files, 16 MiB UTF-8 JSON request и 32 MiB JSON response.
Timeout по умолчанию равен 30 секундам, допустимый диапазон больше нуля и не больше 300 секунд.
Bridge использует временные streams и ограниченное чтение результата.
Sidecar ограничивает размер ответа до записи в stdout.
`NODE_OPTIONS` и `NODE_PATH` удаляются из окружения process.
Загружается только абсолютный путь к проверенному compiler в собственном user cache CAMI.
Target scripts, loaders, Next runtime, `npx` и target npm не запускаются.

`TypeScriptAnalyzerUnavailable` означает отсутствие Node executable или trusted compiler dependency.
`TypeScriptAnalyzerError` означает timeout, сбой process или недопустимый ответ.
Оба исключения запрещено преобразовывать в успешный пустой индекс.
Некорректные capture inputs дают `ValueError`.

## Результат schema version 1

`EcmaAnalysis` и вложенные Pydantic models находятся в `ecma_models.py`.
Модели strict, frozen и запрещают неизвестные поля.
Версии analyzer `1.0.0` и compiler `6.0.3` проверяются отдельно от research и future CLI schemas.
`request_id` возвращается без изменений. Результаты сортируются детерминированно.

`definitions` хранит отдельные declaration occurrences, включая дубликаты.
`id` состоит из path, UTF-16 start и kind. Он идентифицирует occurrence внутри capture.
`key` содержит path, lexical qualname и declaration kind.
После правки source offsets ID может измениться. Адаптер сопоставляет snapshots по уникальному key.
`ambiguous` запрещает выбор одного определения среди дубликатов, conditional declarations или reassignment.
Overload signatures сохраняются с `implementation=false` и не выбираются как targets.
Класс целиком не является function definition. Его методы доступны как `Class.method`.

`signature` хранит binding patterns параметров, optional, rest, default expression, annotation,
type parameters, return annotation, async и generator.
Это исходный синтаксис. Type inference, overload selection и проверка корректности аргументов не выполняются.
`syntax_hash` хеширует текст declaration без ведущего trivia.
`ast_hash` хеширует AST kinds и тексты leaf nodes без whitespace и comments между nodes.
Ни один hash не обещает семантическую эквивалентность.

`site.start` и `site.end` задают полуоткрытый диапазон в UTF-16 code units от начала файла.
`line`, `column`, `end_line`, `end_column` начинаются с 1. Columns также измеряются в UTF-16 code units.
Это единицы TypeScript API, а не Python code points и не UTF-8 bytes.
Bridge проверяет пути, диапазоны, line/column, IDs и ссылки на occurrences по captured contents.

`relations` содержит `imports`, `reexports`, `calls`, `uses` с target occurrence и evidence site.
`source` содержит ближайшее именованное function definition либо `null`.
`scope` сохраняет отдельную lexical identity даже для anonymous callback.
Вызовы внутри callback не приписываются внешней функции.
Передача function reference как callback или JSX prop создаёт `uses`.
JSX component reference также не доказывает вызов.

`unresolved` хранит kind, owner, scope, site, reason и известные candidate IDs.
`type_only` отделяет type syntax и type-only imports от value relations.
Type references не разрешаются в inferred types и не создают value calls.
`exports` содержит export name, site, target либо reason/candidates.
Поиск incoming и outgoing выполняет адаптер над relations и target/source IDs.

`diagnostics` содержит severity, code, message и при наличии site.
`analyzed_files` и `excluded_files` различают healthy source, syntax errors, case collisions и `.d.ts`.
Syntactic diagnostics получаются через публичный `Program.getSyntacticDiagnostics`.
Checker, semantic diagnostics, emit и внутренний `parseDiagnostics` не используются.
При syntax error definitions и relations повреждённого файла исключаются.
Исчезновение definition в таком файле не доказывает удаление. Адаптер обязан учитывать exclusion reason.

## Разрешение bindings и modules

Два AST прохода собирают declarations, parameters, catch, block, loop и destructuring bindings,
а также syntactic assignments, updates и delete. Затем ссылки ищутся в ближайшем lexical scope.
Default expressions и computed expressions в binding patterns собираются до разрешения ссылок.
Parameter defaults видят parameter environment, но не bindings из function body.
Anonymous functions имеют отдельный scope и `source=null`; calls не приписываются outer function.
Неизвестный local binding заслоняет внешний import.
Function declarations hoisted. Variable initializer до textual call даёт conservative initialization check.
Саморекурсия variable function разрешена внутри её body. Для других deferred execution orders возможны unresolved.
Direct eval и with блокируют lexical resolution в затронутом scope.

Поддерживаются function declarations, async functions, simple variable arrows и function expressions,
вложенные named functions, class methods, named/default exports и явные named reexports.
Прямой identifier call разрешается только в единственный поддержанный binding.
Namespace member разрешается только для неизменённого namespace import и известного unique export.
Reexport cycles и duplicate exports остаются unresolved.

`ts.resolveModuleName` получает host только над captured mapping.
Отсутствующие файлы не дополняются с диска. Поддерживаются compiler extension substitution,
relative index resolution, `paths`, `baseUrl` и явный module resolution mode.
Для Node16 и NodeNext format файла определяется публичным `getImpliedNodeFormatForFile`
по captured `package.json`. Import mode передаётся из `getModeForUsageLocation` в resolver.
JSONC и relative config extends разбирает TypeScript API после проверки захваченной extends цепочки.
Максимальная глубина extends равна 16. Циклы, внешние extends, missing configs,
project references и ошибочные compiler options дают diagnostics и отключают module resolution.
Relative options унаследованного config считаются относительно файла этого config по правилам TypeScript.
Config fingerprint включает captured JSON inputs, compiler version и итоговые options.
Изменение config приводит к полному повторному разрешению всех связей.
Literal relative extends захватываются даже под исключёнными source directories, например `build/`.
Читаются только выбранные metadata paths; source files в этих каталогах остаются исключёнными.
`paths` описывает compiler resolution, а не доказанное runtime поведение Next или bundler.

External imports без captured mapping, declaration-only modules и side-effect imports сохраняются явно.
`export *`, произвольный member dispatch, computed access, `.call`, `.apply`, `.bind`,
CommonJS, dynamic imports, aliases и higher-order return values не превращаются в угаданные calls.
Alias chain не прослеживается. Произвольные runtime effects и reflection не моделируются.
Анализатор не является proof of execution, security sandbox или полной моделью JavaScript semantics.
Namespaces, enums и accessors не индексируются как implementations.
Semantic errors могут оставаться в syntactically healthy файле.

## Установка compiler dependency для wheel

Wheel содержит bridge, models, sidecar, exact manifest, lockfile и dependency notice.
Он не содержит Node или TypeScript npm distribution.
`pip install` не запускает npm. До bootstrap запрос завершается explicit unavailable error.
Нужны Node 24 и npm 11. Из активного Python environment выполните:

```bash
cami setup-typescript
cami find createUser --repo /path/to/app --format json
```

Setup использует собственные manifest и exact lockfile CAMI, а не target package.
Compiler cache находится под XDG_CACHE_HOME либо ~/.cache и версионируется
compiler version и SHA-256 обоих manifest files. Temporary installation проходит
`npm ci --ignore-scripts` и version check до atomic rename. Повторная команда
проверяет уже опубликованный cache, manifest bytes и checksum compiler из `ready.json`.
Setup lock сериализует установку одной версии. Повреждённый owned cache переносится в
`.invalid-<unique>` только после проверки fresh installation. Quarantine сохраняется для восстановления.
При ошибке установки прежний cache остаётся на месте; ошибка publication восстанавливает quarantine.
Запрос не ремонтирует cache и не следует symlinks в compiler cache. Во время замены повреждённого
cache запрос может вернуть unavailable; такой результат не публикуется как ready generation.
Failed setup не удаляет предыдущий usable cache. Старый marker без checksum требует повторного setup.
Read-only site-packages и relocation venv не меняют этот cache path.
Lockfile фиксирует `typescript@6.0.3`, официальный tarball и SHA-512 integrity.
Compiler distribution сохраняет свои Apache-2.0 `LICENSE.txt` и `ThirdPartyNoticeText.txt`.
Bridge не ищет dependency в target `node_modules` и не устанавливает её во время запроса.

## Адаптер worktree index

Передавайте одному `analyze_typescript` полный captured mapping со source и config inputs.
Сопоставляйте definition по уникальному key, а внутри одного поколения стройте incoming/outgoing по occurrence IDs.
Сохраняйте configuration fingerprint, diagnostics, exclusions и unresolved вместе с поколением.
При unavailable/error не публикуйте успешное empty generation.
При syntax error не объявляйте excluded definition доказанно удалённым.
Product capture/query contracts описаны в [поиске символов](symbol_search_ru.md)
и [worktree index](worktree_index_ru.md).

Для следующего memory worker `ProductAnalysis` является persisted typed contract.
`python` содержит прежний CodeIndex, `typescript` является discriminated state.
`EcmaReady.analysis` хранит оригинальные compiler values. Между generations
сопоставляйте только уникальные EcmaSymbolKey; occurrence ID не является
устойчивым symbol identity. При unavailable или syntax exclusion переход
к отсутствию definition не доказан. `graph_complete` остаётся false.
