"""Pure configuration and controller checks, without Docker/auth/model calls."""
import json
from pathlib import Path
import sys

import pytest

STAGE = Path(__file__).resolve().parent
sys.path[:0] = [str(STAGE.parent / 'harness'), str(STAGE)]
import container_session as harness  # noqa: E402
import study_runtime as runtime  # noqa: E402
import study_schema as schema  # noqa: E402
import study_controller as controller  # noqa: E402

def legacy_configuration(arm):
    return json.loads((STAGE / 'fixtures/legacy-full-configurations.json').read_text())[arm]


@pytest.mark.parametrize('arm', ['plain', 'static', 'cami'])
def test_default_full_preserves_configuration(arm):
    assert harness.configuration(arm, 'prepared/binding.json') == legacy_configuration(arm)


@pytest.mark.parametrize('arm', ['plain', 'static', 'cami'])
def test_compact_only_changes_memory_command(arm):
    old = legacy_configuration(arm)
    new = harness.configuration(arm, 'prepared/binding.json', 'compact')
    if arm != 'plain':
        old['mcp']['servers']['research_memory']['command'] += ['--response-format', 'compact']
    assert new == old
    runtime.validate_memory_command(new, arm, 'compact')


@pytest.mark.parametrize('value', [None, True, 1, 'unknown', [], {}])
def test_invalid_format_rejected(value):
    with pytest.raises(ValueError):
        schema.memory_response_format({'memory_response_format': value})
    with pytest.raises(ValueError):
        harness.configuration('static', 'prepared/binding.json', value)


def test_old_study_defaults_to_full():
    assert schema.memory_response_format({}) == 'full'


@pytest.mark.parametrize('selected', ['full', 'compact'])
def test_cli_cannot_override_loaded_study(monkeypatch, tmp_path, capsys, selected):
    monkeypatch.setattr(sys, 'argv', ['study_controller.py', '--study', 'not-read.json',
                                    '--out', str(tmp_path / 'unused'),
                                    '--memory-response-format', selected])
    with pytest.raises(SystemExit) as caught:
        controller.main()
    assert caught.value.code == 2
    assert 'frozen in --study' in capsys.readouterr().err
    assert not (tmp_path / 'unused').exists()


@pytest.mark.parametrize('selected', ['full', 'compact'])
def test_mismatched_effective_command_rejected(selected):
    other = 'compact' if selected == 'full' else 'full'
    config = harness.configuration('static', 'prepared/binding.json', other)
    with pytest.raises(ValueError, match='differs from frozen'):
        runtime.validate_memory_command(config, 'static', selected)
    with pytest.raises(ValueError, match='unexpectedly configured'):
        runtime.validate_memory_command(config, 'plain', selected)
    with pytest.raises(ValueError, match='differs from frozen'):
        runtime.validate_memory_command({}, 'cami', selected)


@pytest.mark.parametrize('selected', ['full', 'compact'])
def test_make_study_records_one_common_frozen_format(monkeypatch, tmp_path, selected):
    monkeypatch.setattr(schema, 'normalize', lambda *args: {})
    monkeypatch.setattr(schema, 'digest', lambda *args: 'a' * 64)
    for name in ('harness_files', 'controller_files', 'runtime_files'):
        monkeypatch.setattr(schema, name, lambda *args: {})
    study = schema.make_study(tmp_path, 'development', tmp_path / 'harness.py', 'image',
                             tmp_path, tmp_path, tmp_path, memory_response_format=selected)
    assert study['memory_response_format'] == selected
    assert study['arms'] == ['plain', 'static', 'cami']
    assert study['execution_authorized'] is False


@pytest.mark.parametrize('arm', ['plain', 'static', 'cami'])
@pytest.mark.parametrize('selected', ['full', 'compact'])
def test_session_passes_frozen_format_and_verifies_effective_command(monkeypatch, tmp_path, arm, selected):
    out = tmp_path / 'session'
    out.mkdir()
    manifest = {'status': 'passed', 'image_id': 'image', 'model_requested': True,
                'memory_response_format': selected, 'artifact_hashes': {}}
    (out / 'evidence').mkdir()
    (out / 'evidence/messages.json').write_text('[]')
    manifest['artifact_hashes']['evidence/messages.json'] = runtime.digest(out / 'evidence/messages.json')
    if arm != 'plain':
        (out / 'evidence/memory-backend-trace.jsonl').write_text('')
        manifest['artifact_hashes']['evidence/memory-backend-trace.jsonl'] = runtime.digest(out / 'evidence/memory-backend-trace.jsonl')
    (out / 'manifest.json').write_text(json.dumps(manifest))
    config = harness.configuration(arm, 'prepared/binding.json', selected)
    (out / 'effective-input-config.json').write_text(json.dumps(config))
    calls = []

    def fake_command(argv, timeout):
        calls.append(argv)
        return {'returncode': 0, 'stdout': '', 'stderr': '', 'timeout': False}

    monkeypatch.setattr(runtime, 'command', fake_command)
    study = {'harness': 'fake.py', 'runtime_manifest_path': 'fake.json',
             'reported_token_budget': 1000000, 'image': 'image', 'cami_source': 'source',
             'adapter': 'adapter', 'model': 'openai/gpt-6.1-sol#high',
             'memory_response_format': selected}
    assert runtime.session(study, {'arm': arm}, tmp_path, tmp_path, tmp_path, out) == manifest
    argv = calls[0]
    assert argv[argv.index('--memory-response-format') + 1] == selected
    assert ('--binding-relative' in argv) == (arm != 'plain')
    manifest['memory_response_format'] = 'compact' if selected == 'full' else 'full'
    rejected = tmp_path / 'negative' / 'session'
    rejected.mkdir(parents=True)
    (rejected / 'manifest.json').write_text(json.dumps(manifest))
    (rejected / 'effective-input-config.json').write_text(json.dumps(config))
    with pytest.raises(ValueError, match='identity or status'):
        runtime.session(study, {'arm': arm}, tmp_path, tmp_path, tmp_path, rejected)


@pytest.mark.parametrize('arm', ['static', 'cami'])
@pytest.mark.parametrize('selected', ['full', 'compact'])
def test_controller_rejects_valid_hash_opposite_wire_format(monkeypatch, tmp_path, arm, selected):
    from test_format_observation import fixture

    actual = 'full' if selected == 'compact' else 'compact'
    messages, events = fixture(arm, actual)
    out = tmp_path / 'session'
    (out / 'evidence').mkdir(parents=True)
    (out / 'evidence/messages.json').write_text(json.dumps(messages))
    (out / 'evidence/memory-backend-trace.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in events))
    config = harness.configuration(arm, 'prepared/binding.json', selected)
    (out / 'effective-input-config.json').write_text(json.dumps(config))
    manifest = {'status': 'passed', 'image_id': 'image', 'model_requested': True,
                'memory_response_format': selected,
                'artifact_hashes': {str(p.relative_to(out)): runtime.digest(p)
                                    for p in out.rglob('*') if p.is_file()}}
    (out / 'manifest.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(runtime, 'command', lambda *args, **kwargs: {'returncode': 0, 'timeout': False})
    study = {'harness': 'fake.py', 'runtime_manifest_path': 'fake.json',
             'reported_token_budget': 1000000, 'image': 'image', 'cami_source': 'source',
             'adapter': 'adapter', 'model': config['model'], 'memory_response_format': selected}
    with pytest.raises(ValueError, match='actual memory response format'):
        runtime.session(study, {'arm': arm}, tmp_path, tmp_path, tmp_path, out)
    assert json.loads((tmp_path / 'memory-response-format.json').read_text())['status'] == 'unsupported_or_mismatch'
