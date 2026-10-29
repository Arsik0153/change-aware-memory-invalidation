from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
oracle = importlib.import_module('scripts.structural_fixture_oracle')
stress = importlib.import_module('scripts.stress_structural_memory')


@pytest.mark.parametrize('source,kind,expected', [
    (None, 'symbol_exists', 'contradicted'),
    ('', 'symbol_exists', 'contradicted'),
    ('def f0(x):\n    return x\n', 'signature_equals', 'supported'),
    ('def f0(x):\n    raise RuntimeError("must never execute")\n', 'symbol_exists', 'supported'),
    ('def f0(x, extra=None):\n    return x\n', 'signature_equals', 'contradicted'),
    ('def f0(x, extra=None):\n    return x\n', 'symbol_exists', 'supported'),
    ('def f0(x):\n    return x\n\ndef f0(x):\n    return x\n', 'symbol_exists', 'insufficient_evidence'),
    ('def f0(x):\n    return x\n\ndef broken(:\n', 'symbol_exists', 'insufficient_evidence'),
])
def test_oracle_observable_frozen_grammar(source, kind, expected):
    assert oracle.observe(source, 'f0', kind) == expected


@pytest.mark.parametrize('source', ['f0 = 1\n', 'def f0(y):\n    return y\n',
                                   'class f0:\n    pass\n', 'import os\n'])
def test_oracle_refuses_unsupported_grammar(source):
    with pytest.raises(ValueError, match='grammar'):
        oracle.observe(source, 'f0', 'symbol_exists')


def test_generation_is_reproducible_and_preserves_required_event_coverage():
    spec = stress.read_json(stress.PROTOCOL)
    for seed in spec['seeds']:
        first = stress.history(spec, seed)
        assert first == stress.history(spec, seed)
        assert len(first) == 19
        assert {r['event'] for r in first[1:]} >= set(spec['fixed_events'])
        for record in first:
            for mode, functions in zip(record['modes'], record['functions'], strict=True):
                source = stress.render(functions, mode)
                for number, state in enumerate(functions):
                    for kind in spec['predicates']:
                        assert oracle.observe(source, f'f{number}', kind) == stress.generator_verdict(mode, state, kind)


def test_real_cli_history_matches_oracle_and_detects_corrupt_states(tmp_path):
    spec = stress.read_json(stress.PROTOCOL)
    spec.update(seeds=[1], files=1, functions_per_file=2, random_events_per_history=0)
    protocol = tmp_path / 'test-protocol.json'
    stress.write_json(protocol, spec)
    out = tmp_path / 'study'
    result = stress.run_study(out, protocol)
    assert result['status'] == 'passed'
    seed = result['seeds'][0]
    assert len(seed['variants']) == 3
    assert all(v['states_checked'] == 48 for v in seed['variants'])
    assert all(v['actual_validations'] == 48 for v in seed['variants'] if v['variant'] != 'closed_structural')
    assert next(v['actual_validations'] for v in seed['variants'] if v['variant'] == 'closed_structural') < 48
    # Stored artifacts are verified before the outcome can be trusted.
    run = out / 'seed-01/runs/closed_structural'
    original_states = (run / 'states.jsonl').read_bytes()
    manifest = stress.read_json(run / 'manifest.json')
    with (run / 'states.jsonl').open('a') as stream:
        stream.write('\n')
    claims = [stress.Claim.model_validate_json(stress.canonical(r)) for r in stress.read_jsonl(out / 'seed-01/parent/claims.jsonl')]
    history = stress.read_json(out / 'seed-01/history.json')
    with pytest.raises(ValueError, match='Artifact hash mismatch'):
        stress.verify_run(out / 'seed-01', 'closed_structural', claims, history['records'],
                          history['revisions'], stress.read_jsonl(out / 'seed-01/oracle.jsonl'))

    (run / 'states.jsonl').write_bytes(original_states)
    broken_manifest = dict(manifest, artifact_hashes={}, input_hashes={})
    stress.write_json(run / 'manifest.json', broken_manifest)
    with pytest.raises(ValueError, match='hash|inventory'):
        stress.verify_run(out / 'seed-01', 'closed_structural', claims, history['records'],
                          history['revisions'], stress.read_jsonl(out / 'seed-01/oracle.jsonl'))
    stress.write_json(run / 'manifest.json', manifest)
    original_policy = manifest['config']['policy']
    manifest['config']['policy'] = {'id': 'all_validate', 'dependency_depth': 1}
    stress.write_json(run / 'manifest.json', manifest)
    with pytest.raises(ValueError, match='Configuration'):
        stress.verify_run(out / 'seed-01', 'closed_structural', claims, history['records'],
                          history['revisions'], stress.read_jsonl(out / 'seed-01/oracle.jsonl'))
    manifest['config']['policy'] = original_policy
    stress.write_json(run / 'manifest.json', manifest)
    original_provenance = (run / 'provenance.jsonl').read_bytes()
    changed_provenance = stress.read_jsonl(run / 'provenance.jsonl')
    changed_provenance[0]['known_incomplete'] = True
    stress.write_jsonl(run / 'provenance.jsonl', changed_provenance)
    manifest['artifact_hashes']['provenance.jsonl'] = stress.file_hash(run / 'provenance.jsonl')
    stress.write_json(run / 'manifest.json', manifest)
    with pytest.raises(ValueError, match='provenance'):
        stress.verify_run(out / 'seed-01', 'closed_structural', claims, history['records'],
                          history['revisions'], stress.read_jsonl(out / 'seed-01/oracle.jsonl'))
    (run / 'provenance.jsonl').write_bytes(original_provenance)
    manifest['artifact_hashes']['provenance.jsonl'] = stress.file_hash(run / 'provenance.jsonl')
    stress.write_json(run / 'manifest.json', manifest)
    actual = stress.read_jsonl(run / 'states.jsonl')
    actual[0]['available'] = not actual[0]['available']
    actual[0]['state'] = 'retired'
    actual[0]['last_verdict'] = 'insufficient_evidence'
    stress.write_jsonl(run / 'states.jsonl', actual)
    manifest['artifact_hashes']['states.jsonl'] = stress.file_hash(run / 'states.jsonl')
    stress.write_json(run / 'manifest.json', manifest)
    verified = stress.verify_run(out / 'seed-01', 'closed_structural', claims, history['records'],
                                 history['revisions'], stress.read_jsonl(out / 'seed-01/oracle.jsonl'))
    assert verified['status'] == 'failed'
    assert {'available', 'state', 'last_verdict'} <= {r['field'] for r in verified['mismatches']}
    stress.write_jsonl(run / 'states.jsonl', [*actual, actual[0]])
    manifest['artifact_hashes']['states.jsonl'] = stress.file_hash(run / 'states.jsonl')
    stress.write_json(run / 'manifest.json', manifest)
    with pytest.raises(ValueError, match='Duplicate'):
        stress.verify_run(out / 'seed-01', 'closed_structural', claims, history['records'],
                          history['revisions'], stress.read_jsonl(out / 'seed-01/oracle.jsonl'))

    (run / 'states.jsonl').write_bytes(original_states)
    manifest['artifact_hashes']['states.jsonl'] = stress.file_hash(run / 'states.jsonl')
    changed_costs = stress.read_jsonl(run / 'costs.jsonl')
    next(r for r in changed_costs if r['phase'] == 'maintenance')['actual_validations'] += 1
    stress.write_jsonl(run / 'costs.jsonl', changed_costs)
    manifest['artifact_hashes']['costs.jsonl'] = stress.file_hash(run / 'costs.jsonl')
    stress.write_json(run / 'manifest.json', manifest)
    with pytest.raises(ValueError, match='accounting'):
        stress.verify_run(out / 'seed-01', 'closed_structural', claims, history['records'],
                          history['revisions'], stress.read_jsonl(out / 'seed-01/oracle.jsonl'))


@pytest.mark.parametrize('field,value', [('seeds', []), ('seeds', [1, 1]), ('seeds', [True]),
    ('files', 0), ('functions_per_file', -1), ('dataset_kind', 'real'), ('split', 'heldout'),
    ('variants', []), ('random_event_choices', ['unknown'])])
def test_invalid_protocol_rejected_before_output(tmp_path, field, value):
    spec = stress.read_json(stress.PROTOCOL)
    spec[field] = value
    protocol = tmp_path / 'bad.json'
    stress.write_json(protocol, spec)
    with pytest.raises(ValueError):
        stress.run_study(tmp_path / 'out', protocol)
    assert not (tmp_path / 'out').exists()


def test_verifier_failure_is_reported_and_other_variants_still_execute(tmp_path, monkeypatch):
    spec = stress.read_json(stress.PROTOCOL)
    spec.update(seeds=[1], files=1, functions_per_file=1, fixed_events=['body'], random_events_per_history=0)
    protocol = tmp_path / 'protocol.json'
    stress.write_json(protocol, spec)
    verify = stress.verify_run

    def fail_first(base, variant, *args):
        if variant == 'original_incomplete':
            raise ValueError('injected verifier failure')
        return verify(base, variant, *args)

    monkeypatch.setattr(stress, 'verify_run', fail_first)
    result = stress.run_study(tmp_path / 'study', protocol)
    assert result['status'] == 'failed'
    variants = result['seeds'][0]['variants']
    assert len(variants) == 3 and all(r['exit_code'] == 0 for r in variants)
    assert {r['variant']: r['status'] for r in variants} == {
        'original_incomplete': 'failed', 'all_validate': 'passed', 'closed_structural': 'passed'}
    assert 'injected verifier failure' in next(r['error'] for r in variants if r['status'] == 'failed')
