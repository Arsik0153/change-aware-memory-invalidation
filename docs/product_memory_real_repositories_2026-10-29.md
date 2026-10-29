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
