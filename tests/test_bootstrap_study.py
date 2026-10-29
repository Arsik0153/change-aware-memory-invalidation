from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from cami.artifacts import file_hash, load, read_json, read_jsonl, write_json
from cami.errors import InputError

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('bootstrap_study', ROOT / 'scripts/bootstrap_study.py')
assert SPEC and SPEC.loader
study = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = study
SPEC.loader.exec_module(study)


def protocol(**changes):
    data = read_json(ROOT / 'examples/bootstrap_study/protocol.json')
    data.update(changes)
    return study.Protocol.model_validate_json(json.dumps(data))


def test_analytical_undefined_probability():
    assert study.undefined_probability(0, 2, 10) == 0
    assert study.undefined_probability(2, 2, 10) == 1
    assert study.undefined_probability(1, 2, 2) == pytest.approx(7 / 16)
    assert study.undefined_probability(1, 50, 2000) > 0


def test_generator_truth_and_paired_counts():
    config = protocol(bootstrap_repetitions=30)
    assert config.truth == pytest.approx(0.1)
    row = study.generate_trial(config, 0, 0)
    assert row == study.generate_trial(config, 0, 0)
    assert row.left != study.generate_trial(config, 0, 1).left
    for key, (numerator, denominator) in row.left.items():
        other, other_denominator = row.right[key]
        assert 0 <= other <= numerator <= denominator
        assert denominator == other_denominator
    assert row.empty_clusters == 0


def test_null_scenario_has_exact_zero_interval():
    config = protocol(right_probability_multiplier=1.0, bootstrap_repetitions=30)
    row = study.generate_trial(config, 0, 0)
    assert row.left == row.right
    assert row.interval.lower == row.interval.upper == row.interval.estimate == 0
    assert row.covered is True


def test_summary_keeps_unavailable_trials_in_denominator():
    config = protocol(bootstrap_repetitions=30)
    valid = study.generate_trial(config, 0, 0)
    available = valid.model_copy(update={'covered': True})
    missing = valid.model_copy(update={
        'covered': None,
        'interval': valid.interval.model_copy(update={'lower': None, 'upper': None,
                                                      'reason': 'zero_denominator_in_resample'}),
    })
    result = study.summarize([available, missing], config.truth)
    assert result['availability'] == result['joint_available_and_covered'] == 0.5
    assert result['conditional_coverage'] == 1
    assert result['unavailable_reasons'] == {'zero_denominator_in_resample': 1}
    assert study.summarize([missing], config.truth)['conditional_coverage'] is None


def test_runner_artifacts_and_no_overwrite(tmp_path):
    config = protocol(trials_per_scenario=2, bootstrap_repetitions=20)
    path = tmp_path / 'protocol.json'
    write_json(path, config)
    output = tmp_path / 'results'
    study.run(path, output)
    manifest = read_json(output / 'manifest.json')
    assert manifest['status'] == 'complete'
    assert load(output / 'protocol.json', study.Protocol) == config
    for name, expected_hash in manifest['artifact_hashes'].items():
        assert file_hash(output / name) == expected_hash
    rows = read_jsonl(output / 'trials.jsonl')
    assert len(rows) == 12
    assert len({(row['scenario'], row['trial']) for row in rows}) == 12
    for summary in read_json(output / 'summary.json')['scenarios'].values():
        assert summary['trials'] == 2
    with pytest.raises(InputError, match='output already exists'):
        study.run(path, output)


@pytest.mark.parametrize('changes', [
    {'trials_per_scenario': 0}, {'bootstrap_repetitions': 0},
    {'cluster_sizes': []}, {'left_probabilities': [1.5]},
    {'scenarios': [{'id': 'bad', 'clusters': 5, 'active_probability': 0.0}]},
])
def test_invalid_protocol_rejected(changes):
    with pytest.raises(ValidationError):
        protocol(**changes)


def test_report_rechecks_counts_even_if_summary_hash_updated(tmp_path):
    spec = importlib.util.spec_from_file_location(
        'report_bootstrap_study', ROOT / 'scripts/report_bootstrap_study.py')
    assert spec and spec.loader
    reporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reporter)
    path = tmp_path / 'protocol.json'
    write_json(path, protocol(trials_per_scenario=2, bootstrap_repetitions=20))
    source = tmp_path / 'source'
    study.run(path, source)
    reporter.report(source, tmp_path / 'report')
    assert read_json(tmp_path / 'report/validation.json')['validated_trials'] == 12
    assert (tmp_path / 'report/coverage.png').stat().st_size > 0
    summary = read_json(source / 'summary.json')
    summary['scenarios']['dense-k5']['available'] = 0
    write_json(source / 'summary.json', summary)
    manifest = read_json(source / 'manifest.json')
    manifest['artifact_hashes']['summary.json'] = file_hash(source / 'summary.json')
    write_json(source / 'manifest.json', manifest)
    with pytest.raises(ValueError, match='summary disagrees'):
        reporter.report(source, tmp_path / 'rejected')
    assert not (tmp_path / 'rejected').exists()
