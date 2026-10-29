# CAMI: пакет независимой разметки

Это восстановленный черновой пакет от 29 октября 2026, не допущенный
исследовательский cohort и не завершённая разметка. Все формы намеренно пусты.
Утверждения совпадают побайтно с историческими hashes подготовки 1 октября.

В каталоге annotation находятся packets.jsonl, исходники sources, frozen probes
и формы. Пути evidence_path в packets.jsonl отсчитываются от каталога annotation.
В архив не включены policy runs, configurations, receipts, labels или selection
metadata. Repository IDs и parent/child commit identities остаются видимыми.

Порядок работы:

1. Координатор назначает двух разных людей. Первый заполняет primary_form.jsonl,
   второй независимо заполняет second_form.jsonl. Люди не видят ответы друг друга
   до завершения независимого этапа. Не пересылайте заполненные primary ответы
   второму человеку вместе с исходным пакетом.
2. parent_confirmation_form.jsonl — выделенная форма тех же parent-заданий;
   child_form.jsonl — выделенные child-задания. Не импортируйте дубли одной
   аннотации одновременно из общей и выделенной формы.
3. Каждый читает claim, predicate, scope и исходник на указанном commit. Generator
   signature JSON — кандидат, не независимое доказательство. Не используйте
   verdict CAMI в качестве эталона. Прочтите annotation_guide.md.
4. Укажите настоящий annotator_id, уникальный annotation_id, annotator_kind,
   independent, label, evidence, confirmation_type и фактическое annotation_minutes.
   Не заполняйте неизвестные ответы положительными значениями по умолчанию.
5. Behavior probes требуют отдельной проверенной исторической среды. Ошибка
   среды не означает опровержение. Prose исключён из offline evaluation.
6. Передайте заполненные формы координатору для импорта, проверки независимости
   и adjudication. Не меняйте исходные claims или тесты по увиденным child данным.

В пакете 630 parent-заданий, 600 main child-заданий и 300 replay child-заданий.
306 назначений second review пока означают только назначения, а не их выполнение.
Main и replay оцениваются отдельно. Полный metadata seal и допуск cohort ещё не
сформированы. Никакие независимые подтверждения в этом архиве не заявлены.
