# Восстановление материалов независимой разметки

На VPS отсутствовали `runs/next-stage-20261001/` и `data/corpora/`. Исторические
отчёты и manifests сохранились, но ссылались на абсолютные пути прежней машины.
Восстановление завершено 29 октября 2026 без новой выборки переходов.

## Что доступно

- Локальные bare репозитории Click, Requests и pytest в `data/corpora/`.
- Восстановленная подготовка в `runs/main-restored-20261029/ready/`.
- Пакет для передачи разметчикам: `output/annotation-restored-20261029.zip`.
- SHA-256, размер и состав архива: `reports/research-20261029/annotation-package.json`.
- Подробная проверка материалов: `reports/research-20261029/restoration-readiness.json`.

Архив содержит только annotation tree и инструкции. Полный ready tree не подходит
для слепой передачи: там есть policy configuration и selection metadata. Архив
не содержит policy runs, configs, labels или receipts; repository IDs и точные
parent/child commits остаются видимыми. Это ограниченная слепота относительно
результатов политик, а не сокрытие всех особенностей исходных данных.

Локальные корпуса, подготовка и архив не включены в Git. В Git сохранены инструменты,
исходные manifests, hashes, журналы и этот отчёт. Архив доступен на текущей машине;
после переноса клона подготовку можно воспроизвести командами ниже.

## Что проверено

1. Все три тега разрешаются в сохранённые end commits. Все 63 цепочки переходов
   существуют и сохраняют ожидаемые parent/child отношения.
2. Производные manifests отличаются только локальными путями. Исходные файлы
   `data/manifests/main-20261001.*` не изменены. Seed, revisions, strata, clusters,
   replay sequences и порядок сохранены.
3. Все 63 файла claims.jsonl, содержащие 630 claims, совпадают побайтно с hashes
   `reports/next-stage-20261001/final-generation-hashes.json`. Реализация генератора
   изменилась после октября, поэтому совпадение проверено, а не предположено.
4. Проверены 895 уникальных source files и 63 probes. Независимый reviewer также
   сопоставил source bytes и object IDs с Git objects.
5. Формы содержат 1530 primary items, 306 second items, 630 parent items и 900
   child items. Main child population — 600, replay child population — 300.
6. Все формы пусты, все 63 parent receipt files пусты, все 630 provenance rows
   остаются known_incomplete=true. Независимые ответы не генерировались.
7. ZIP содержит 970 файлов; проверка CRC прошла. Архив не содержит forbidden
   policy output/config/label/receipt filenames. SHA-256 записан отдельно.

Это проверка восстановления материалов. Допущенных claims, подтверждённых
поведенческих результатов и завершённого final protocol seal нет.

## Воспроизведение

Не повторяйте `select`: используйте сохранённую выборку. В чистом клоне с пустым
`data/corpora` получите исходники; команды не запускают код репозиториев:

```sh
git clone --bare --single-branch --branch 8.1.8 https://github.com/pallets/click.git data/corpora/click
git clone --bare --single-branch --branch v2.32.3 https://github.com/psf/requests.git data/corpora/requests
git clone --bare --single-branch --branch 8.3.5 https://github.com/pytest-dev/pytest.git data/corpora/pytest
.venv/bin/python scripts/restore_preparation.py \
  --selection data/manifests/main-20261001.selection.json \
  --parents data/manifests/main-20261001.parents.jsonl \
  --corpora data/corpora --out runs/restored-reproduction-001
.venv/bin/python scripts/prepare_main.py generate \
  --parents runs/restored-reproduction-001/parent_inputs.jsonl \
  --out runs/restored-reproduction-001/candidates
.venv/bin/python scripts/prepare_main.py assemble \
  --selection runs/restored-reproduction-001/selection.json \
  --candidates runs/restored-reproduction-001/candidates \
  --out runs/restored-reproduction-001/ready
```

Скрипт переноса проверяет origin, неизменность pinned end commit, согласованность
parent inputs и selection, существование и последовательность ревизий до записи.
Изменившийся tag или неправильный corpus отклоняется. При существующем output
команда отказывает. Сеть нужна только для восстановления корпусов; генерация
и сборка используют локальные Git objects с отключённой lazy fetch.

Проверка переносчика: `pytest -q tests/test_restore_preparation.py`, 5 passed.
Включены отказы при неправильных origin, pin, parent inputs и child revision,
а также сохранение исходных файлов. Повторная relocation через скрипт дала те же
байты selection и parent_inputs, что использовались при восстановлении.
Ruff и mypy прошли. Полный suite после добавления только переносчика не повторялся.

## Что ещё необходимо

- Реальные независимые parent reviews; назначения второго человека ещё не означают
  выполненную двойную разметку.
- Проверка и утверждение provenance. Известная неполнота не снимается автоматически.
- Независимое подтверждение исторических behavior environments. После восстановления
  подготовлены pinned образы и выполнены parent-only diagnostics: в v3 из63групп
  41дали положительные автоматические observations,21pytest-группа остановлена
  конфликтом runner modules,1Requests-группа — неподдерживаемым snapshot.
  Эти observations не создают receipts; см. research_run_2026-10-29.md и
  reports/research-20261029/parent-environments-v3/summary.json.
- Независимые child labels, adjudication и фактическое время работы разметчиков.
- Окончательное решение о допустимых kinds и cohort, затем final protocol seal.

Нельзя сначала посмотреть результаты held-out policies и затем исправить выборку.
M6 и платные запросы не запускались. Prose остаётся вне offline evaluation.

Независимый review gpt-6.1-sol подтвердил целостность восстановленных материалов
и явно ограничил выводы. Отчёт: `reports/research-20261029/restoration-review.md`.
Переносчик добавлен после этого review, проверен родителем через tests и побайтное
сравнение входов; отдельного независимого code review переносчика не было.

## Дополнительная диагностика pytest: план до запуска

Все21pytest parent-группы имеют одинаковый frozen probe SHA-256
`609844de252a2ed01c153c8862703c6d492376de668033f56cac82b4aaa820f8`.
Он импортирует safe_getattr и проверяет единственный вызов с object(), отсутствующим
атрибутом и fallback. Production runner сначала импортирует свой pytest, поэтому
честно отказывает из-за пересечения `_pytest` modules с целевым репозиторием.
Отключать эту защиту или принимать системный pytest за target нельзя.

Отдельный план `examples/parent_function_diagnostics/pytest_protocol.json`
проверит неизменённую frozen function прямым вызовом в новом процессе, без pytest
framework/fixtures/plugins/assertion rewriting. Будут закреплены Python3.9.25,
attrs23.2.0 иpy1.11.0; целевой код читается только из parent mount. Все loaded
_pytest origins и target source hash проверяются в том же процессе. По3контейнера
на каждый parent, без сети, с readonly mounts и ограничениями ресурсов.

Это иной execution profile для узкой дополнительной диагностики. Даже успешный
вызов не означает, что standard pytest validator стал доступен, не выдаёт independent
receipt и не разрешает real held-out execution. Все failures сохраняются; ошибки
импорта/среды не превращаются в contradicted labels. Claims/probes не меняются.

До21parent запуска реализованы scripts/check_parent_functions.py и отдельный
container runner. Образ:
`cami-parent-function@sha256:434d7f8ef1728a7752fc21bcd6bcabd56e6df8f2daced060f4d36fb9fb7bf8a4`.
Проверенный runtime:Python3.9.25,attrs23.2.0,py1.11.0;pytest/_pytest не установлены.
Runner использует Python -I -B и требует optimize=0, чтобы assert не был отключён.
Host сверяет target source и все loaded_pytest origins с parent Git blobs.

Independent design review обнаружил потерю прогресса при timeout команды очистки
контейнера; отказ воспроизведён и исправлен. Partial stdout/stderr и timeout outcome
сохраняются даже при cleanup error. Сводка отдельно считает завершённые попытки,
полученные function observations и groups с одними техническими ошибками.
Focused suite новых и прежних parent diagnostics:43passed;ruff passed.
Полный21parent опыт ещё не выполнен на этом checkpoint.
