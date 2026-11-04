# Видимое использование устаревшей информации: проект AI-рубрики

Результат этой стадии — дизайн, а не аннотация исходов. `rubric.json` и `extraction-design.json` нужно закрепить вместе с extractor/packetizer, roster и параметрами AI review **до** чтения reviewers фактических transcripts. В этой стадии изучены только generic source/schema; transcripts, heldout и gold не читались, вызовов моделей не было.

Раздельно отмечаются четыре оси:

1. **Exposure:** устаревший буквальный фрагмент действительно показан trial-agent в tool response. Изменившийся файл сам по себе этого не доказывает; withheld ID/reason без старого текста — другой канал.
2. **Explicit reliance:** публичная фраза принимает либо применяет именно старый факт как текущий или обосновывает им действие. Цитирование для проверки, отрицание старого факта и намерение заглянуть в память не достаточны. «По памяти…» — self-report источника, а не доказательство причинного эффекта.
3. **Observable action consistent with stale information:** в реальном input/diff/call виден старый identifier/signature/context, применённый как текущий. Failed patch и obsolete call сохраняются как attempted actions, отдельно от их результата. Grep старого имени, отрицательный тест и действие, одинаково совместимое с обеими версиями, сами по себе не положительный случай.
4. **Correction after native inspection:** связанная цепочка «раннее положительное свидетельство → native current evidence → явная ретракция или видимое исправление». Ранняя reliance/action не стирается после correction. Одного успешного финала или последующего read недостаточно.

Для каждой оси раздельны positive, отсутствие наблюдаемого свидетельства в полном видимом record, unassessable и not applicable. Последние два никогда не превращаются в zero reliance. Private reasoning/native encrypted data не извлекаются и не используются как окно во внутреннюю chain of thought.

Каждое положительное решение должно ссылаться на короткую **точную** цитату, artifact SHA256, JSON Pointer или JSONL line+pointer, message/tool ID, codepoint offsets и hash parsed string. Нужны origin/current source hashes и область hash; если доступен только partial read, full-file hash остаётся null. Поле «совпадает со старым фактом» отделено от «источник явно назван memory» и от «память вызвала действие»; последнее этой рубрикой не устанавливается.

Временная граница обязательна: canonical reset доказывает source state до первой возможной записи, включая input первого mutation attempt, но не после результата. Shell и неизвестные tools считаются potentially mutating; failed tool не гарантирует отсутствие частичных writes. После записи нужен contemporaneous checkpoint/native evidence. Final candidate source нельзя переносить назад во времени. Overlap или пропущенные timestamps означают unknown, а не удобный порядок JSON.

Extractor сначала фиксирует **весь roster**, затем нормализует все допустимые события и создаёт coverage row для каждого attempted trial, включая setup/model failures и partial exports. Только после этого привязываются stale-fact evidence и AI labels. Нельзя выбрать только static, плохие задачи или эпизоды с exposure. Plain без внешней памяти — not applicable для внешнего канала; это не ноль устаревших внутренних знаний. Non-memory/unattributed stale-looking действия учитываются отдельно.

Основной транспорт — полный `messages.json` из OpenCode API. В установленной 2.2.5 tool time находится в `part.time.{created,ran,completed}`, а text результатов — в `part.state.content`; старый CLI `state.time.start/end` нельзя предполагать без отдельного adapter. Полнота pagination, IDs, terminal hash inventory и compact audit receipt проверяются механически. Повторные API/CLI/SSE представления одного call не дают новые наблюдения. Недоступную или повреждённую после redaction привязку не восстанавливают из private state.

Предложены два fresh AI review contexts на полный trial packet, одинаковые rubric/prompt/model/settings, заранее случайный порядок opaque IDs и сохранение обоих оригиналов до adjudication. Это решение, бюджеты и limits ещё должен закрепить root перед вызовами. Gold, grader outcome и arm rankings в packet не нужны. Backend/trust text нельзя скрывать с искажением evidence, поэтому полного arm blinding может не быть. Oversized transcript нельзя молча обрезать: он остаётся unassessable до отдельного frozen chunking protocol.

Отчёт должен называться AI-annotated visible evidence, не human validation и не ground truth. Показывать coverage/unknowns и каждую ось отдельно по arm/stage; единицы trials и вложенные episodes не независимы. Расходы extraction, packets, AI review и adjudication — отдельная offline evaluation инфраструктура, а не trial model/tool cost. Рубрика не разрешает выводить causal reliance из exposure или failed quality score.

Во время подготовки один generic classifier был изменён параллельным worker. До/после hashes сохранены; analyzer не исполнялся, actual outcomes не читались. Для будущей extraction root должен отдельно закрепить актуальную реализацию и schema adapter; эти справочные source pins не объявляются замороженным runtime.
