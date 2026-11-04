# Соответствие конечной модели реальным переходам памяти

На 499 канонических случаях реальные `PeriodicAudit` и `advance_state` совпали
с ожидаемыми переходами конечной модели. Обнаружены обе намеренные ошибки:
пропуск проверки в срок и сохранение доступности после inconclusive validation.
Это ограниченная проверка связи модели с кодом, а не формальная верификация системы.

План закреплён в704da2d, runner — в1a7eeb1. Использованы все403ребра восьми
ранее замороженных графов: exact_binary и sound_positive_only при K=1,2,4,8.
Каждое withheld-состояние реализовано двумя вариантами метаданных — stale/contradicted
и needs_validation/insufficient_evidence. Поэтому64абстрактных состояния дают
76канонических контекстов, а403ребра —499проверяемых переходов.

Вместо Git-истории построена уникальная последовательность синтетических revision ID.
Возраст определяется через last_checked_commit. Произвольный baseline trigger
модели реализован через known_incomplete только у синтетической provenance.
Проверены выбор проверки, причины, доступность, возраст, revision, state, basis,
last verdict, last checked/supported, withheld reason и сохранность provenance.
Исходный MemoryState не должен изменяться на месте.

ValidationResult в этом эксперименте — заданный вход модели. Ни один probe не
исполнялся; число запусков Docker равно нулю. Поэтому результат не подтверждает
правильность реального валидатора и не создаёт независимых truth labels.

Отдельный stdlib-аудитор без импортов CAMI заново проверил все499записей,
покрытие403ребер и76контекстов,5hashes артефактов,10зафиксированных входов и
12артефактов исходной модели. Он отклонил три подмены с пересчитанными hashes:
удаление варианта ребра, ложный last_supported_commit одновременно в actual и
expected, а также подделку passed у отрицательного контроля. Простая проверка
целостности приняла бы эти изменённые hashes; проверки содержания их обнаружили.

Source snapshots до и после совпали.29focused tests проверки переходов и адаптера
прошли перед запуском. Последняя полная проверка всего проекта относится к418f58a;
она не приписывается текущему HEAD.

- [Протокол](../examples/behavior_dependency/translation_protocol.json).
- [Итоги и ограничения](../reports/research-20261104/model-engine-translation-v1/summary.json).
- [Полные записи](../reports/research-20261104/model-engine-translation-v1/translations.json).
- [Независимый аудит](../reports/research-20261104/model-engine-translation-audit-v1.json).

Воспроизведение: `python -m scripts.check_model_translation --protocol
examples/behavior_dependency/translation_protocol.json --out NEW_DIRECTORY`.
Аудит: `python scripts/audit_model_translation.py --report REPORT_DIRECTORY
--out NEW_JSON --tamper-controls`.
