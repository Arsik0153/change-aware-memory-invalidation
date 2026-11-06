"""Tier configuration/identity controls; no auth, Docker, model or benchmark calls."""
import copy
import json
from pathlib import Path
import shutil
import sys

import pytest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / 'harness'), str(HERE)]
import container_common as common  # noqa: E402
import container_session as harness  # noqa: E402
import study_controller as controller  # noqa: E402
import study_runtime as runtime  # noqa: E402
import study_schema as schema  # noqa: E402


@pytest.mark.parametrize('arm', ['plain', 'static', 'cami'])
def test_legacy_default_configuration_is_byte_value_equal(arm):
    old = json.loads((HERE / 'fixtures/legacy-full-configurations.json').read_bytes())[arm]
    assert harness.configuration(arm, 'prepared/binding.json') == old
    assert schema.service_tier_value({}) is None


@pytest.mark.parametrize('tier', ['auto', 'priority'])
@pytest.mark.parametrize('arm', ['plain', 'static', 'cami'])
def test_tier_is_same_common_model_setting_all_arms(tier, arm):
    old = harness.configuration(arm, 'prepared/binding.json', 'compact')
    new = harness.configuration(arm, 'prepared/binding.json', 'compact', tier)
    assert new.pop('providers') == {'openai': {'models': {'gpt-6.1-sol': {'settings': {'serviceTier': tier}}}}}
    assert new == old
    assert new['model'] == 'openai/gpt-6.1-sol#high'


@pytest.mark.parametrize('bad', [True, False, 1, [], {}, '', 'fast', 'default', 'flex', 'PRIORITY'])
def test_unverified_or_wrong_type_tier_rejected(bad):
    with pytest.raises(ValueError):
        harness.configuration('plain', None, service_tier=bad)
    with pytest.raises(ValueError):
        schema.service_tier_value({'service_tier': bad})


@pytest.mark.parametrize('tier', [None, 'auto', 'priority'])
def test_new_study_pins_tier_only_when_explicit(monkeypatch, tmp_path, tier):
    monkeypatch.setattr(schema, 'normalize', lambda *a: {})
    monkeypatch.setattr(schema, 'digest', lambda *a: 'a' * 64)
    for name in ['harness_files', 'controller_files', 'runtime_files']:
        monkeypatch.setattr(schema, name, lambda *a: {})
    study = schema.make_study(tmp_path, 'development', tmp_path / 'h.py', 'image', tmp_path, tmp_path, tmp_path, service_tier=tier)
    assert ('service_tier' in study) == (tier is not None)
    assert schema.service_tier_value(study) == tier
    assert study['model'] == schema.MODEL and study['max_steps'] == 20


def test_loaded_study_tier_cannot_be_overridden(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, 'argv', ['controller', '--study', 'not-read.json', '--out', str(tmp_path / 'out'), '--service-tier', 'priority'])
    with pytest.raises(SystemExit) as result:
        controller.main()
    assert result.value.code == 2 and 'frozen in --study' in capsys.readouterr().err
    assert not (tmp_path / 'out').exists()


def model(tier='priority', effort='high'):
    return {'settings': {'serviceTier': tier}, 'variants': [{'id': 'high', 'settings': {'reasoningEffort': effort}}]}


def test_requested_configured_is_never_mislabelled_actual_served():
    evidence = common.service_tier_evidence('priority', model(), model_requested=False)
    assert evidence['requested'] == evidence['configured'] == 'priority'
    assert evidence['reasoning_effort'] == 'high'
    assert evidence['actual_served'] is None and evidence['actual_served_status'] == 'unavailable'
    assert not evidence['request_on_wire_observed_for_this_session']


def test_variant_override_or_changed_reasoning_fails_closed():
    override = model()
    override['variants'][0]['settings']['serviceTier'] = 'auto'
    with pytest.raises(ValueError, match='effective service tier'):
        common.service_tier_evidence('priority', override, model_requested=True)
    with pytest.raises(ValueError, match='reasoning'):
        common.service_tier_evidence('priority', model(effort='medium'), model_requested=True)


def test_response_tier_only_comes_from_known_native_scalar_not_text_or_config():
    observations = {}
    common.observe_service_tier({'id': 'a', 'type': 'assistant', 'time': {'completed': 3},
        'metadata': {'serviceTier': 'priority'}, 'content': [{'type': 'text', 'text': 'service_tier priority'}]}, observations)
    assert observations['a']['provider_reported'] is None
    evidence = common.service_tier_evidence('priority', model(), model_requested=True, observations=list(observations.values()), export_complete=True, assistant_ids=['a'])
    assert evidence['actual_served'] is None and evidence['actual_served_status'] == 'unavailable'
    common.observe_service_tier({'id': 'a', 'type': 'assistant', 'time': {'completed': 4}, 'native': {'serviceTier': 'default', 'encrypted_content': 'never-project-this'}}, observations)
    evidence = common.service_tier_evidence('priority', model(), model_requested=True, observations=list(observations.values()), export_complete=True, assistant_ids=['a'])
    assert evidence['actual_served'] == 'default' and evidence['actual_served_status'] == 'provider_reported_complete'
    assert 'never-project-this' not in json.dumps(evidence)
    common.observe_service_tier({'id': 'b', 'type': 'assistant'}, observations)
    evidence = common.service_tier_evidence('priority', model(), model_requested=True, observations=list(observations.values()))
    assert evidence['actual_served'] is None and evidence['actual_served_status'] == 'partially_reported'
    assert evidence['provider_reported_values'] == ['default']


def test_mixed_response_tiers_or_malformed_scalar_cannot_claim_uniform_priority():
    observations = {}
    for ident, value in [('a', 'priority'), ('b', 'default'), ('c', {'value': 'priority'})]:
        common.observe_service_tier({'id': ident, 'type': 'assistant', 'native': {'serviceTier': value}}, observations)
    evidence = common.service_tier_evidence('priority', model(), model_requested=True, observations=list(observations.values()))
    assert evidence['actual_served'] is None and evidence['actual_served_status'] == 'partially_reported'
    assert observations['c']['status'] == 'unsupported_value'


def test_complete_tier_cannot_be_inferred_from_partial_pagination():
    observations = {}
    common.observe_service_tier({'id': 'a', 'type': 'assistant', 'native': {'serviceTier': 'priority'}}, observations)
    for complete, ids in [(False, ['a']), (True, ['a', 'missing-assistant'])]:
        evidence = common.service_tier_evidence('priority', model(), model_requested=True,
            observations=list(observations.values()), export_complete=complete, assistant_ids=ids)
        assert evidence['actual_served'] is None and evidence['actual_served_status'] == 'partially_reported'
    common.observe_service_tier({'id': 'a', 'type': 'assistant', 'time': {'completed': 5}, 'native': {'serviceTier': 'priority'}}, observations)
    assert len(observations) == 1 and observations['a']['completed'] == 5
    evidence = common.service_tier_evidence('priority', model(), model_requested=True,
        observations=list(observations.values()), export_complete=True, assistant_ids=['a'])
    assert evidence['actual_served'] == 'priority'


@pytest.mark.parametrize('tier', [None, 'auto', 'priority'])
def test_controller_forwards_only_frozen_tier_and_checks_effective_identity(monkeypatch, tmp_path, tier):
    out = tmp_path / 'session'
    (out / 'evidence').mkdir(parents=True)
    config = harness.configuration('plain', None, service_tier=tier)
    (out / 'effective-input-config.json').write_text(json.dumps(config))
    (out / 'evidence/messages.json').write_text('[]')
    if tier is not None:
        (out / 'evidence/service-tier.json').write_text(json.dumps(common.service_tier_evidence(tier, model(tier), model_requested=True)))
        (out / 'evidence/observed-model.json').write_text(json.dumps({**model(tier), 'providerID': 'openai',
            'id': 'gpt-6.1-sol', 'modelID': 'gpt-6.1-sol', 'package': '@opencode/ai/providers/openai/responses'}))
    manifest = {'status': 'passed', 'image_id': 'image', 'model_requested': True, 'memory_response_format': 'full',
                'artifact_hashes': {str(p.relative_to(out)): runtime.digest(p) for p in out.rglob('*') if p.is_file()}}
    if tier is not None:
        manifest['service_tier_requested'] = tier
    (out / 'manifest.json').write_text(json.dumps(manifest))
    study = {'harness': 'fake.py', 'runtime_manifest_path': 'fake.json', 'reported_token_budget': 1000000,
             'image': 'image', 'cami_source': 'source', 'adapter': 'adapter', 'model': schema.MODEL}
    if tier is not None:
        study['service_tier'] = tier
    calls = []
    monkeypatch.setattr(runtime, 'command', lambda argv, **kwargs: calls.append(argv) or {'returncode': 0, 'timeout': False})
    runtime.session(study, {'arm': 'plain'}, tmp_path, tmp_path, tmp_path, out)
    assert ('--service-tier' in calls[0]) == (tier is not None)
    if tier is not None:
        assert calls[0][calls[0].index('--service-tier') + 1] == tier
    wrong = copy.deepcopy(config)
    wrong['providers'] = {'openai': {'models': {'gpt-6.1-sol': {'settings': {'serviceTier': 'auto' if tier != 'auto' else 'priority'}}}}}
    (out / 'effective-input-config.json').write_text(json.dumps(wrong))
    rejected = tmp_path / 'negative/session'
    shutil.copytree(out, rejected)
    with pytest.raises(ValueError, match='service tier differs'):
        runtime.session(study, {'arm': 'plain'}, tmp_path, tmp_path, tmp_path, rejected)
