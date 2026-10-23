# Проверка CAMI, 1 октября 2026

- [x] Read the Principles section of poteto-mode.
- [x] Phase A: Frame. Проверяем шесть этапов пользовательского задания. Успех требует повторяемого baseline, объяснения 120/120, воспроизведённых дефектов и тестов, сравнения на том же cohort, материалов основного эксперимента и честного отчёта об ограничениях.
- [x] Phase B: Design the workflow. Сохраняем исходный код для сравнения. Аудит отбора и аудит экспериментальной границы выполняются независимыми read-only агентами Sol high. Изменения делает основной агент.
- [x] Phase C: Run the loop.
- [x] 1. Baseline. Тесты, Ruff, mypy, demo и 84 Click-запуска в новых каталогах.
- [x] 2. Количественная диагностика причин, пересечений и границ fallback.
- [x] 3. Воспроизведение дефектов, минимальные исправления и регрессии.
- [x] 4. Три повторения времени с seed 42. Отдельные некешированные и кешированные серии. Те же claims и commits до и после.
- [x] 5. Фиксируем правила нового сбора, готовим parent-only данные и пакеты независимой разметки. Held-out не используется для настройки.
- [x] Phase D: Keep the audit trail. decisions.tsv в этом каталоге.
- [x] Phase E: Verify and hand back. Полные проверки и русский отчёт.

Throughput checkpoint. Наибольшие неизвестные находятся в fallback и доступности исторических сред. Сначала измеряем существующие данные. Затем исправляем подтверждённые дефекты. Подготовку новых данных отделяем от настройки на Click. Не запускаем платные API и M6.

Model the Domain. Сохраняем раздельные Claim, Selection и ValidationResult. Точное синтаксическое утверждение не получает неявный смысл утверждения о поведении.

Prove It Works. Сравнение строится по новым реальным запускам и проверяется через сохранённые selections, validations и costs. Старые отчёты не считаются доказательством.

Completed available work: 182 passing tests; 1188 successful paired timing jobs;
600 main and 30 replay candidates; independent forms prepared but unanswered.
Scientific admission, independent labels and heldout execution remain outside the
completed technical preparation, as detailed in docs/next_stage_report_ru.md.
