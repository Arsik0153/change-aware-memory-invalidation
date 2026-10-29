# Независимая проверка восстановления

Ревьюер: gpt-6.1-sol, отдельный read-only agent review_restored_annotation.
Ошибок целостности восстановления не найдено.

Независимо проверены:

- Исходные manifests совпадают с HEAD. Менялись только 3 repository paths и
  63 repo_path в производных файлах parent inputs.
- 63 файла candidates и 63 файла assembled claims соответствуют историческим
  hashes. Всего 630 утверждений. Проверены pinned tags и все цепочки ревизий.
- Семь preparation hashes корректны. Все 895 исходных файлов совпадают с Git
  object IDs, bytes и SHA-256. Все 63 копии probes соответствуют hashes.
- Формы пусты: 1530 primary, 306 second, 630 parent, 900 child. Все 63 receipt
  files пусты; admitted claims отсутствуют. Все 630 provenance known_incomplete.

Ограничения: annotation packet скрывает policy outputs/configurations, receipts
и labels, но сохраняет repository/run IDs и parent/child identities. Полный ready
каталог нельзя выдавать за blinded пакет: в нём есть configs и selection metadata.
Reviewer identities null; назначения не означают реально выполненную независимую
разметку. Проверка целостности не подтверждает гипотезу или истинность claims.
