# Product memory на двух настоящих локальных репозиториях

Цель development-проверки — проверить жизненный цикл памяти через публичный CLI
на реальных исходных файлах. Изменения намеренно внесены автором эксперимента;
они не являются историческими ошибками проекта, независимыми labels или результатом
held-out сравнения политик. Target code не исполняется: CAMI читает и разбирает файлы.

Использованы отдельные локальные clones с закреплёнными revisions:

| Репозиторий | Revision | Subject |
| --- | --- | --- |
| Click | `934813e4d421071a1b3db3973c02fe2721359a6e` | `src/click/utils.py:_posixify` |
| Requests | `0e322af87745eff34caffe4df68456ebc20d9068` | `src/requests/utils.py:get_encoding_from_headers` |

Гипотеза: структурные ожидания зависят от соответствующего predicate, а ручная
заметка требует явного review после изменения её source. Синтаксическая ошибка
не должна превращаться в доказательство отсутствия символа.

В каждом clone driver создаёт `symbol_exists`, `signature_equals` и ручную заметку
из одного context. Повтор регистрации с тем же request ID должен вернуть тот же
receipt. Повтор context без изменений должен сохранить generation и facts.
Далее применяется заранее заданная последовательность, всякий раз из исходных bytes:

| Изменение | Existence | Signature | Ручная заметка |
| --- | --- | --- | --- |
| Другой Python-файл | supported, carried | supported, carried | доступна |
| В начало тела вставлен `return None` | supported, carried | supported, carried | needs_review |
| Добавлен параметр с default | supported | contradicted | needs_review |
| В файл добавлена синтаксическая ошибка | insufficient_evidence | insufficient_evidence | needs_review |
| Файл удалён | contradicted | contradicted | needs_review |
| Исходные bytes возвращены | supported | supported | needs_review |
| Заметка явно обновлена с CAS revision 1 | supported | supported | manual_assertion, revision 2 |

Ожидаемые переходы заданы явно, а не вычислены валидатором CAMI. Для carried facts
проверяются прежние check IDs и timestamps; для signature history — точная
последовательность причин. Перед началом clone должен быть чистым. В finally
восстанавливаются исходные bytes и проверяется чистота Git. State и cache изолированы
в каталоге evidence вне clone, поэтому отдельные процессы проверяют durable memory.

Первый запуск: по 18 CLI-команд на репозиторий, все успешны. Независимый reviewer
проверил stdout/stderr hashes, каждый сохранённый source object, bytes всех мутаций,
реальные verdicts, обе чистые копии и history. В driver усилены две проверки:
явный contradicted verdict при signature/delete и запрет status=passed до проверки
восстановления. Первый driver сохранён с точным исходным hash; результаты v1
не перезаписаны. Итог усиленного повторного запуска будет записан после проверки.

Ограничения: две намеренно выбранные функции, три вида памяти и статические
авторские мутации. Это проверка продукта, не оценка качества на популяции, не
семантическое доказательство поведения кода и не независимая человеческая разметка.

Повтор v2 с усиленным driver завершён: по 18 команд, все exit 0; hashes каждого
stdout/stderr проверены, оба clone восстановлены и чисты. Raw CLI outputs,
manifest обоих запусков и review record сохранены в
`reports/research-20261029/product-memory-real/`. Полные SQLite/state/source-object
каталоги остаются в `runs/product-real-20261029/*-evidence-v2`.

## Повторение

Используйте отдельный disposable clone: driver намеренно меняет и удаляет один
файл, затем восстанавливает его. Не запускайте эксперимент в рабочей копии с
неопубликованными изменениями. `--out` должен быть новым каталогом вне clone.
Команды выполняются из корня CAMI в установленном `.venv`:

```bash
git clone --no-hardlinks data/corpora/click runs/product-click-repeat
git -C runs/product-click-repeat checkout --detach 934813e4d421071a1b3db3973c02fe2721359a6e
.venv/bin/python scripts/check_product_memory.py \
  --repo runs/product-click-repeat \
  --subject src/click/utils.py:_posixify \
  --out runs/product-click-repeat-evidence
```

Для Requests используйте соответствующий pinned revision и subject из таблицы.
Driver принимает однозначную top-level функцию с однострочной сигнатурой; общая
поддержка произвольных Python/TypeScript субъектов этой проверкой не заявляется.


## Расширение на TypeScript: план до запуска мутаций

Pinned локальный seo-articles: `85070f607449b32dc3d039a81a5951749ec2aa34`.
Subject: `src/shared/lib/format-count.ts:formatCount`; SHA-256 исходного файла
`dd3827bb67849e1dfa8ed3eb72bf80d618bded1d6266a45b97b5e231cc59fb0d`.
Первичный context уже подтвердил однозначный статический symbol. Это exploratory
выбор функции после Python checks, не предварительная регистрация исследования.

До первого применения мутаций зафиксирован профиль
`examples/product_memory/seo_articles_typescript.json`. Он заменяет return в теле,
расширяет явный тип count до number | string, отдельно добавляет syntax error.
Ожидания шести фаз и ручного review те же, что в таблице выше. TypeScript predicate
проверяет написанную сигнатуру, не inferred types и не поведение runtime.
Область capture — src/shared/lib; unrelated-файл будет создан внутри этой области.
Target code не запускается, зависимости приложения не устанавливаются.

State изолирован; установленный compiler cache используется явно, с фиксацией
Node/TypeScript identity. Исходная рабочая копия пользователя не меняется; опыт
идёт в отдельном disposable clone. Полные локальные contexts остаются в runs,
в Git попадут компактные результаты и hashes, без копирования исходников приложения.

### Результат TypeScript

Оба запуска завершены: по 18 CLI-команд, все exit 0. Независимый reviewer
(gpt-6.1-sol) проверил v1: 36 hashes stdout/stderr, 21 сохранённый source object,
точные bytes всех мутаций, фактические verdicts, carried check IDs, sticky review
заметки и revision 2 после явного обновления. Clone и исходная рабочая копия
чисты. В отдельном executable Python fixture reviewer воспроизвёл потерю mode
после delete/recreate. Driver исправлен: сохраняет и восстанавливает stat mode;
регрессионный тест сначала упал, после исправления весь driver suite — 14 passed.

Повтор TypeScript v2 с исправленным driver также прошёл все 18 команд. Проверены
36 stream hashes и совпадение driver/profile hashes; source SHA и mode восстановлены.
Дополнительно unrelated-файл должен присутствовать в capture coverage: проверяется
реальное изменение захваченной области, а не файл за её пределами. Более широкий
полный suite на этом этапе ещё не запускался; предыдущий результат 982 passed
относится к HEAD 042de36 до расширения driver.

Использован TypeScript 6.0.3 с Node v24.15.0. Manifest сохраняет compiler SHA-256,
lockfile fingerprint, source roots и явный путь cache. Shared cache нужен только
для уже установленного trusted compiler; durable memory state изолирован на запуск.
Это не повторение Python с иным runtime приложения: target TypeScript не исполнялся.

```bash
.venv/bin/python scripts/check_product_memory.py \
  --repo runs/product-typescript-20261029/repo \
  --subject src/shared/lib/format-count.ts:formatCount \
  --mutation-spec examples/product_memory/seo_articles_typescript.json \
  --cache-dir /root/.cache \
  --out runs/product-typescript-repeat-evidence
```

Путь cache заменяется на локальный каталог с подготовленным compiler; установки
по сети driver не выполняет. Mutation profile должен совпасть с Git HEAD, subject,
source hash и уникальными anchors. Без profile сохранён прежний Python сценарий.
Output/cache внутри repo, parent traversal и symlink subjects отклоняются до записи.

Evidence: `reports/research-20261029/product-memory-typescript-{v1,v2}` и
`product-memory-typescript-review.json`. Raw application contexts и state сохранены
только локально в `runs/product-typescript-20261029/evidence-{v1,v2}`; в Git находятся
компактные manifests с hashes. Эта проверка охватывает одну намеренно выбранную
TypeScript функцию и не оценивает точность на популяции репозиториев.
