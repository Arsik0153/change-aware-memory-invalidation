"""Authored redaction regression controls; no live credentials or model calls."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import container_worker as worker  # noqa: E402
from container_common import redact, redact_data, sanitize_artifact  # noqa: E402
from evidence_safety import scrub_state_evidence  # noqa: E402


PATCH = '-@pytest.fixture(params=[None])\n+@pytest.fixture(params=[1])\n'
FAKE = 'AUTHORED_ONLY_SECRET_"quote"_\\path\nnewline_123456'
JWT = 'eyJhdXRob3JlZCI6dHJ1ZX0.bm90X3JlYWw.c2lnbmF0dXJl'


@pytest.mark.parametrize('payload', [PATCH, PATCH.replace('\n', r'\n'), json.dumps({'patch': PATCH}),
                                    json.dumps({'nested': json.dumps({'patch': PATCH})})])
@pytest.mark.parametrize('extension', ['.json', '.jsonl'])
def test_worker_and_host_preserve_decorators_in_code_and_nested_json(tmp_path, payload, extension):
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    path = evidence / ('messages' + extension)
    before = worker.public({'code': payload, 'email_text': 'person+tag@example.invalid'})
    path.write_text(json.dumps(before) + '\n')
    sanitize_artifact(path, worker.SECRETS)
    result = scrub_state_evidence(tmp_path, expect_credential=False)
    assert result['status'] == 'passed'
    actual = json.loads(path.read_text())
    assert actual['code'] == payload
    assert actual['email_text'] == '[REDACTED_EMAIL]'


@pytest.mark.parametrize('address', ['person@example.invalid', '+tag.person@example.invalid', 'person+tag@example.invalid'])
def test_email_redaction_preserves_surrounding_newline_escape(address):
    assert redact(address) == '[REDACTED_EMAIL]'
    assert redact(r'\n' + address) == r'\n[REDACTED_EMAIL]'
    assert redact('\n' + address) == '\n[REDACTED_EMAIL]'


def test_nested_oauth_jwt_private_values_keys_and_safe_serialization(tmp_path):
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    payload = {FAKE: FAKE, 'nested': json.dumps({'access_token': FAKE, 'id_token': JWT,
              'code': PATCH, 'opaque': FAKE}), 'jwt': JWT, 'refresh_token': 'authored opaque refresh'}
    path = evidence / 'messages.json'
    path.write_text(json.dumps(payload))
    sanitize_artifact(path, {FAKE})
    result = scrub_state_evidence(tmp_path, expect_credential=False, initial_private_values={FAKE})
    assert result['status'] == 'passed'
    data = json.loads(path.read_text())
    assert FAKE not in data and FAKE not in path.read_text() and JWT not in path.read_text()
    nested = json.loads(data['nested'])
    assert nested['code'] == PATCH and nested['access_token'] == '[REDACTED]'
    assert data['refresh_token'] == '[REDACTED]'
    assert data['[REDACTED_PRIVATE_VALUE]'] == '[REDACTED_PRIVATE_VALUE]'


@pytest.mark.parametrize('bad_name,bad_body', [('bad.json', r'{"x":"\[bad]"}'),
                  ('bad.jsonl', '{}\n' + r'{"x":"\[bad]"}'), ('bad.json', '{invalid')])
def test_malformed_artifact_rejected_without_losing_safe_usage(tmp_path, bad_name, bad_body):
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    (evidence / bad_name).write_text(bad_body)
    (evidence / 'usage.json').write_text(json.dumps({'tokens': 17}))
    (evidence / 'good.jsonl').write_text(json.dumps({'patch': PATCH}) + '\n')
    result = scrub_state_evidence(tmp_path, expect_credential=False)
    assert result['status'] == 'partial' and not (evidence / bad_name).exists()
    assert result['rejected_artifacts'] == [{'artifact': bad_name, 'error_type': 'JSONDecodeError'}]
    assert json.loads((evidence / 'usage.json').read_text()) == {'tokens': 17}
    assert json.loads((evidence / 'good.jsonl').read_text()) == {'patch': PATCH}


def test_redacted_key_collision_rejects_whole_artifact_safely(tmp_path):
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    (evidence / 'keys.json').write_text(json.dumps({'a@example.invalid': 1, 'b@example.invalid': 2}))
    result = scrub_state_evidence(tmp_path, expect_credential=False)
    assert result['status'] == 'partial' and not (evidence / 'keys.json').exists()


def test_plain_text_and_nested_private_value_escape_spellings(tmp_path):
    path = tmp_path / 'log.txt'
    path.write_text(PATCH + '\n' + json.dumps({'opaque': FAKE}) + '\n' + JWT)
    sanitize_artifact(path, {FAKE})
    assert path.read_text().startswith(PATCH)
    assert FAKE not in path.read_text() and json.dumps(FAKE)[1:-1] not in path.read_text()
    assert JWT not in path.read_text()


def test_json_strings_and_private_nested_data_are_idempotent():
    data = {'nested': json.dumps({'opaque': FAKE, 'patch': PATCH}), 'code': PATCH}
    first = redact_data(data, {FAKE})
    assert redact_data(first, {FAKE}) == first
