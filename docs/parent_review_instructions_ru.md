# Независимый parent-review до просмотра child

Этот пакет содержит только parent-исходники, frozen claims/probes и пустые формы.
Он не содержит child_commits, child evidence, policy outputs, готовых ответов или
результатов автоматических environment diagnostics. Идентичность репозитория
и parent commit остаётся видимой. Claims являются кандидатами, не доказанной истиной.

Координатор выдаёт каждому человеку отдельную неизменённую копию пакета.
Первый reviewer заполняет primary_form.jsonl; второй — second_form.jsonl независимо
от первого. В second_form сохранены ранее назначенные 126 parent-заданий, новая
случайная выборка не проводилась. Не показывайте чужие ответы или child-пакет
до завершения parent-review. Наличие формы не означает выполненную разметку.

Для каждой строки найдите claim_id в packets.jsonl, прочитайте text, predicate и
scope. Посмотрите source_evidence на parent_commit. Пути evidence_path считаются
от корня этого пакета. Сравните утверждение с исходником независимо от нормализатора
CAMI. Для behavior нужно отдельно проверенное исполнение frozen probe; не меняйте
его assertion по результату. Автоматическое наблюдение CAMI не является независимым
подтверждением. Ошибка среды не доказывает, что утверждение ложно.

Заполните реальные annotation_id, annotator_id, annotator_kind, independent, label,
evidence, confirmation_type и annotation_minutes. Не оставляйте пустое evidence;
не выдумывайте фактическое время. Разрешённые label — supported, contradicted,
uncertain. Полные типы описаны в annotation_guide.md. Верните исходные ответы
координатору без слияния с ответами второго человека.

Координатор сохраняет обе исходные формы. Текущая команда import-parent принимает
одно решение на claim и отвергает повторные claim IDs; передача объединённых
двойных ответов напрямую не поддерживается. Нельзя удалять один ответ для создания
видимости согласия. Согласование и сохранение происхождения итоговых решений
должно быть отдельным явным шагом. Поведенческие положительные подтверждения
требуют independent_test; простой human_review их не допускает.

Если человек самостоятельно исполнил frozen probe, укажите annotator_kind=human
и confirmation_type=independent_test. Тип метода не меняет авторство. Если среду
восстановить не удалось, сохраните uncertain с evidence и фактическим методом
review. Такой ответ сохраняется без receipt; ошибка среды не означает contradicted.

Импорт parent reviews сам по себе не завершает cohort admission, provenance review
или final protocol freeze. Child-разметка и evaluation остаются следующими этапами.
