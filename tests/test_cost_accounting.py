import time

import pytest

from cami import engine
from cami.artifacts import read_json, read_jsonl


def test_full_run_cost_includes_output_publication(repo, monkeypatch):
    a = repo.commit({'module.py': 'def f(): return 1\n'})
    b = repo.commit({'notes.txt': 'unrelated'})
    config = repo.config(a, [b], policy='keep_all')
    original = engine.write_jsonl

    def slow_publication(*args, **kwargs):
        time.sleep(0.01)
        return original(*args, **kwargs)

    monkeypatch.setattr(engine, 'write_jsonl', slow_publication)
    out = config.parent / 'out'
    engine.run_experiment(config, out)
    manifest = read_json(out / 'manifest.json')
    components = sum(row['wall_seconds'] for row in read_jsonl(out / 'costs.jsonl'))
    assert manifest['end_to_end_seconds'] >= components + 0.045
    assert manifest['overhead_seconds'] >= 0.045


def test_pareto_cost_accounts_for_preflight(repo):
    from cami.artifacts import write_jsonl
    from cami.evaluation import _pareto_values, score_run

    a = repo.commit({'module.py': 'def f(): return 1\n'})
    b = repo.commit({'notes.txt': 'unrelated'})
    config = repo.config(a, [b], policy='keep_all')
    out = config.parent / 'out'
    engine.run_experiment(config, out)
    labels = config.parent / 'labels.jsonl'
    write_jsonl(labels, [{'schema_version': 1, 'claim_id': 'f', 'commit': b,
                         'label': 'contradicted', 'annotator_id': 'synthetic',
                         'evidence': ['manual hypothetical metric case'],
                         'confirmation_type': 'synthetic_manual', 'adjudication_status': 'single_annotator'}])
    report = score_run(out, labels, config.parent / 'score')
    retention = report.overall.metrics['valid_retention'].model_copy(update={'value': 1.0})
    report = report.model_copy(update={'end_to_end_seconds': None,
        'overall': report.overall.model_copy(update={
            'metrics': {**report.overall.metrics, 'valid_retention': retention}})})
    initial = _pareto_values(report)[0]
    preflight = report.costs['preflight']
    changed = report.model_copy(update={'costs': {**report.costs,
        'preflight': preflight.model_copy(update={'totals': {**preflight.totals,
            'wall_seconds': preflight.totals['wall_seconds'] + 100}})}})
    assert abs(_pareto_values(changed)[0] - initial - 100) < 1e-8


@pytest.mark.parametrize("old_version", ["1", "2"])
def test_old_validator_cache_is_not_reused_after_semantic_fix(repo, monkeypatch, old_version):
    from cami.artifacts import write_json

    a = repo.commit({'module.py': 'def f(): return 1\n'})
    b = repo.commit({'notes.txt': 'unrelated'})
    config = repo.config(a, [b], policy='all_validate')
    data = read_json(config)
    data['cache_dir'] = 'cache'
    write_json(config, data)
    with monkeypatch.context() as legacy:
        legacy.setattr(engine, 'VALIDATOR_VERSION', old_version)
        engine.run_experiment(config, config.parent / 'legacy')
    out = config.parent / 'current'
    engine.run_experiment(config, out)
    assert read_jsonl(out / 'costs.jsonl')[-1]['actual_validations'] == 1


def test_initial_index_cost_is_the_cold_parent_build(repo, monkeypatch):
    a = repo.commit({'module.py': 'def f(): return 1\n'})
    b = repo.commit({'module.py': 'def f(): return 2\n'})
    config = repo.config(a, [b])
    clock = [0.0]
    original = engine.build_index

    def measured_build(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] += 20.0 if clock[0] == 0 else 1.0
        return result

    monkeypatch.setattr(engine.time, 'perf_counter', lambda: clock[0])
    monkeypatch.setattr(engine, 'build_index', measured_build)
    out = config.parent / 'out'
    engine.run_experiment(config, out)
    cost = read_jsonl(out / 'costs.jsonl')[-1]
    assert cost['initial_index_seconds'] == 20.0
    assert cost['incremental_index_seconds'] == 1.0
