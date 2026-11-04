# CAMI

CAMI finds Python, JavaScript, and TypeScript definitions in working trees and Git revisions without importing target code. Its research engine maintains a fixed cohort of repository claims and measures how Git-aware selection changes validation cost and memory availability. Synthetic demonstrations are separate from real datasets.

## Find definitions in the worktree or a Git revision

```bash
uv run cami find run_experiment --repo .
uv run cami find cami.engine.run_experiment --repo . --format json
uv run cami find run_experiment --repo . --revision HEAD --format json
uv run cami find src/cami/engine.py:run_experiment --repo . --source-root src --exclude vendor --format json
```

Without `--revision`, `find` reads live working tree bytes, including unstaged
changes and untracked source files. Explicit `--revision HEAD` or a commit ID
reads Git objects even in a dirty checkout. Neither mode imports target code or
changes the Git index.

`find` returns definitions, signatures, and incoming and outgoing static relations.
JSON schema version 3 reports `found`, `not_found`, or `ambiguous`, preserves
duplicate definitions, and distinguishes complete from partial input coverage.
Worktree content IDs are separate from commits. Persistent immutable generations
are reused across processes after fresh capture verification. The worktree
consistency contract is `verified_readset` over an interval, not an atomic
filesystem snapshot. Runtime observations are separate from the deterministic
search payload. The static graph remains partial.

For `.js`, `.jsx`, `.ts`, and `.tsx`, install Node.js 24 and npm 11, then run
`cami setup-typescript` once in the active Python environment. Setup installs the
pinned TypeScript 6.0.3 compiler from CAMI's own lockfile into your user cache.
It supports read-only packages and relocated environments. `find` never runs npm
or project scripts.

```bash
cami setup-typescript
cami find createUser --repo /path/to/next-app --format json
cami find registerUser --repo /path/to/next-app --revision HEAD
```

The compiler returns syntax signatures, evidence sites, imports, named reexports,
calls, JSX uses, diagnostics, and unresolved references. It does not typecheck or
infer types. Missing compiler resources return an actionable error. Healthy
Python matches remain available with partial coverage in a mixed repository.
See the [TypeScript contract](docs/typescript_analyzer_ru.md) for supported resolution and limits.

See the [symbol search contract](docs/symbol_search_ru.md) for matching and exit
codes and the [worktree index contract](docs/worktree_index_ru.md) for capture,
exclusions, persistence, and failure behavior. The research `run` command keeps
its existing contract.

## Install and run the offline demo

Use Python 3.12 and uv. If uv is missing, install it into a local tool directory:

```bash
python3 -m pip install --target .tools uv==0.12.21
export PATH="$PWD/.tools/bin:$PATH"
uv sync --locked --extra dev
uv run cami demo --out runs/demo-new
uv run pytest
uv run ruff check .
uv run mypy src/cami
```

`demo` creates a real synthetic Git history, executes all seven policies, and writes `runs/demo-new/report/`. No Docker, API key, or network is used by the demo. An existing output directory is always rejected. Choose a new output path for another run.

The small checked-in example uses a bundled synthetic Git history. Restore it once in a fresh clone, then run the command contract:

```bash
git clone examples/demo/repo.bundle examples/demo/repo
uv run cami check-inputs --config examples/demo/run.json
uv run cami run --config examples/demo/run.json --out runs/example-new
uv run cami score --run runs/example-new --labels examples/demo/labels.jsonl --out reports/example-new
uv run cami compare --runs runs/demo-new/keep_all runs/demo-new/all_validate runs/demo-new/file_validate runs/demo-new/symbol_validate --labels runs/demo-new/dataset/labels.jsonl --out reports/comparison-new
```

## Run isolated behavior probes

Build the image outside measured probe execution. Record its full repository digest from the inspect output.

```bash
docker build -f docker/Dockerfile.probes -t cami-probes:py312-pytest842 .
docker image inspect cami-probes:py312-pytest842 --format '{{json .RepoDigests}}'
export CAMI_TEST_IMAGE='docker.io/library/cami-probes@sha256:YOUR_ACTUAL_DIGEST'
uv run pytest -m docker
```

The locally verified digest is recorded in [implementation_status.md](docs/implementation_status.md). Build attestations can change the derived image digest. Always use the actual digest, never a floating tag in run configurations.

A behavior claim supplies an immutable probe hash, exact pytest node ID and environment profile. CAMI performs three parent repeats before admission and three repeats per selected child. Only three matching assertion failures contradict a claim. Collection, import, crash, timeout and inconsistent outcomes yield insufficient evidence. Repository and probe mounts are read-only; the container has no network, no capabilities, a non-root user and fixed resource limits. Probes must contain their own fixtures; repository conftest and automatic pytest plugins are disabled.

## Prepare the real Click pilot

Fetch source data before running CAMI. `run` disables Git lazy fetching.

```bash
git clone --no-checkout https://github.com/pallets/click.git data/corpora/click
uv run cami prepare-pilot --repo data/corpora/click --out data/pilot/click-new
uv run cami pilot-run --dataset data/pilot/click-new/dataset.json --out runs/click-new
uv run cami pilot-report --runs runs/click-new --out reports/click-new
uv run cami pilot-environments --dataset data/pilot/click-new/dataset.json --image "$CAMI_TEST_IMAGE" --out runs/click-environments-new
uv run cami annotate-export --dataset data/pilot/click-new/dataset.json --out reports/click-annotation-new
uv run cami freeze --dataset data/pilot/click-new/dataset.json --out runs/click-protocol-new
```

The pilot selects the last 12 non-merge first-parent transitions through Click 8.1.8. Up to ten exact top-level function claims per parent are sampled with seed 42 before reading child source. An independent tokenizer supplies parent structural evidence. No child labels are generated. These adjacent pairs share one episode cluster.

`pilot-environments` checks one finite Click invocation on each parent only. It
writes observations and an `environment_report.json` with schema version 2; it
does not execute children, generate confirmation receipts, or admit claims.
Failed runs retain completed parent observations and a failure record. Earlier
environment reports remain historical artifacts. This smoke check does not
establish full historical test compatibility or independent parent truth.

## Annotate, freeze and analyze

See [annotation_guide.md](docs/annotation_guide.md) for the import format and independent-review procedure. Import retains all original answers and adjudication history:

```bash
uv run cami annotate-import --input annotations.json --out data/annotations/import-001
uv run cami freeze --dataset data/dataset.json --out runs/protocol-001
uv run cami analyze --dataset data/dataset.json --runs RUN_DIR_1 RUN_DIR_2 --labels data/annotations/import-001/labels.jsonl --out reports/analysis-001
uv run cami prepare-scenario --dataset examples/demo/dataset.json --mode hidden_missing --drop 0.50 --seed 42 --out runs/scenario-001
```

`compare` requires one shared cohort and scenario. `analyze` handles explicitly declared multiple populations, checks complete paired policy sets, separates repositories, strata and replay sequences, and uses declared episode clusters for paired bootstrap. It reports micro rates and repository macro rates separately. Reliability remains exploratory with fewer than 50 contradictions or fewer than 20 clusters containing contradictions.

A freeze hashes configs, cohort records, evidence, probes, graph views and available annotations. It never runs a validator. Missing annotations remain explicitly pending. Held-out `run` requires `frozen_protocol_path` pointing to a matching `protocol.json`; add this path after freeze. The reference field is excluded from the sealed configuration digest. Held-out preflight must reproduce the sealed cohort and exclusions; any change fails the run. Execution requires the recorded local Git repository even though the frozen source evidence is portable.

## Read the artifacts

Every completed run contains a manifest, immutable claims and provenance, selections, validations, states, transitions, costs, evidence and logs. `last_checked_commit` changes only after validation. Carried claims remain distinguishable from claims confirmed at the current revision. Direct invalidation withholds memory without declaring it false. Previously withheld claims are rechecked by validating policies, including after reverts.

Only the evaluation and annotation tools read child labels. Policies and validators receive no labels. Scoring rejects incomplete runs, changed artifacts, incompatible cohorts and incomplete label coverage. Zero-denominator metrics are null with a reason.

Costs separate actual validations, logical validations, cache hits, preflight, initial indexing and incremental indexing. Cached durations are reconstructed estimates, not measured end-to-end times. CPU time covers the analyzer process; container and child-process CPU are not measured. Provenance preparation costs and annotation minutes remain separate. The real pilot uses one fixed execution order, so its measured times are operational observations rather than a final timing comparison.

M6 is not enabled or implemented. No paid requests are made. It requires a separate model, API key, explicit budget and frozen protocol. The executable M0–M5 prototype and pilot do not complete independent annotation or establish the research hypothesis.

Exit codes are 0 for a completed operation, 2 for invalid inputs, 3 for a missing required resource and 4 for an interrupted or incomplete operation.

## Demonstrate structural provenance closure

```bash
uv sync --locked --extra dev
uv run python scripts/demo_structural_closure.py --out runs/structural-closure-dev-001
```

Use a new output directory for each invocation. The command creates four fixed synthetic claims,
prepares hash-bound derived provenance from parent inputs before child commits exist, and runs
`all_validate`, `symbol_validate` with original incomplete provenance, and `symbol_validate` with
closed provenance. It checks six authored transitions with an independent tokenizer oracle and
executes each variant five times in rotating order. `summary.json` records selection reasons,
verdicts, carried claims and full CLI wall times. A reduction in validations is not a speedup claim.

The [development addendum](docs/protocol_1_1_structural_closure_v1.md) defines the narrow closure
criterion. Fixture automation cannot authorize real or held-out data and does not create independent
human reviews. See the [demonstration report](docs/structural_closure_demo_ru.md) for measured results
and the remaining experiment requirements.

## Аудит и подготовка следующего эксперимента (2026-10-01)

Подробный результат, ограничения и команды: [русский отчёт](docs/next_stage_report_ru.md).
Исходный протокол 1.0 сохранён; [вариант 1.1](docs/protocol_1_1.md) отдельно проверяет
правило отбора для точных структурных утверждений. Это development-абляция, а не
подтверждение качества без независимых labels.

Новые инструменты:

- `scripts/diagnose_selection.py` — причины и пересечения fallback на фиксированном пилоте.
- `scripts/benchmark_pilot.py` — исходный код 1.0, исправленный 1.0 и вариант 1.1;
  три повторения, seed 42, отдельное заполнение и использование кеша.
- `scripts/prepare_main.py` — фиксированная выборка, parent-only генерация, пакеты
  разметки и импорт независимых parent-подтверждений.
- `scripts/verify_cami.py --out NEW_DIRECTORY` — тесты и статический анализ без
  перезаписи прежних журналов.

Подготовлены 600 основных кандидатов и три replay-последовательности; независимые
receipts и labels ещё не получены. Формы и дальнейшие действия описаны в
[инструкции разметчикам](docs/annotation_next_stage_ru.md). Held-out оценка и M6
не запускались.

Product memory commands and the agent consumption flow are described in
[Рабочая память для CLI-агента](docs/product_memory_ru.md).

Product background refresh and agent workflow: [cami watch](docs/watch.md).

`cami analyze` also writes `intervals.csv`: interval estimates and bounds, unavailable
reasons, and counts of original clusters with positive metric denominators for the
left policy, right policy, and both. Comparison names specify left minus right.
The same counts appear as `denominator_support` in JSON. Blank CSV counts (JSON
null) mean diagnostics were not computed, including replay and not-applicable
metrics; they do not mean zero support. These counts do not establish interval
calibration. The [synthetic development study](docs/bootstrap_study_2026-10-29.md)
explains why interval availability must be reported alongside conditional coverage.

## Результаты на 4 ноября 2026 года

[Обзор новых результатов](docs/research_findings_2026-11-04_ru.md) и
[обновлённый исследовательский отчёт](docs/research_progress_report_2026-11-04_ru.md):
применимость binding gate на 504 реальных parent-кандидатах, восстановление
behavior-памяти, ограниченная проверка структурного переноса, Requests package-only
projection и исправление кеша при смене Git mode. Полная проверка исправления:
1124 passed на e810a09. Независимые parent reviews и child labels остаются
незавершёнными; основная held-out оценка ещё не выполнена.

Текущий [PDF-отчёт](reports/research-20261104/report-delivery/CAMI_research_progress_2026-11-04.pdf)
включает измерения времени и [достижимый цикл ложной доступности](docs/behavior_reachability_2026-11-04.md),
подтверждённый конечной моделью и отдельным Git/Docker-свидетелем.
Команды сборки и упаковки: `scripts/build_research_report.py` и
`scripts/finalize_research_report.py`; упаковка требует записи визуальной проверки,
привязанной к SHA-256 конкретного PDF.

PDF v5 также включает
[периодическая перепроверка и граница K−1](docs/periodic_audit_bound_2026-11-04.md).
Конечная модель дополнена опытом на 12 Git children и 93 Docker executions;
исследовательская обёртка подтверждает предсказанные 1 и 3 ошибки для K=2 и K=4.
Производственная политика пока не изменена. Полная проверка накопленных изменений
на 61a04bf: 1140 passed; обёртка дополнительно покрыта профильными тестами.

Для периодического опыта также подготовлен полный raw evidence ZIP:
`output/periodic-audit-raw-20261104-v1.zip`. Он содержит логи, Git fixture и точные
runtime sources; Docker image в него не входит. Хеш и инструкция проверки —
в [разборе опыта](docs/periodic_audit_bound_2026-11-04.md), отдельная запись доставки —
[periodic-raw-delivery.json](reports/research-20261104/periodic-raw-delivery.json).

Дополнение после PDF v5: [графовые ограничения на реальных parent-снимках](docs/parent_graph_fallback_2026-11-04.md).
У всех 63 behavior-кандидатов присутствуют одновременно локальные и глобальные
unresolved-флаги; снятия одного глобального fallback недостаточно для выборочного
отбора. Проверены parent-источники; child-результаты не использовались.
