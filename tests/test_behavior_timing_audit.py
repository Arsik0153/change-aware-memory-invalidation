import json

import pytest

from cami.artifacts import write_json, write_jsonl
from scripts.benchmark_behavior_histories import audit_probes


def prepared(tmp_path):
    paths = []
    for i in range(3):
        path = tmp_path / f'repeat-{i}.log'
        payload = {'python_version': '3.12.12', 'exit_code': 0,
            'collected': ['test_behavior.py::test_f'], 'reports': [
                {'nodeid': 'test_behavior.py::test_f', 'when': phase,
                 'outcome': 'passed', 'assertion': False, 'fingerprint': None}
                for phase in ('setup', 'call', 'teardown')]}
        path.write_text('CAMI_RESULT=' + json.dumps(payload) + '\n')
        write_json(path.with_suffix('.json'), {'outcome': 'passed', 'fingerprint': None,
                                             'duration_seconds': .5})
        paths.append(path.name)
    write_jsonl(tmp_path / 'preflight_validations.jsonl', [])
    write_jsonl(tmp_path / 'validations.jsonl', [{'test_executions': 3, 'logs': paths,
        'verdict': 'supported', 'cache_hit': False}])
    return tmp_path / paths[0]


@pytest.mark.parametrize('tamper', ['exit_code', 'collection', 'setup_failure', 'duplicate_payload'])
def test_raw_failures_cannot_be_reported_as_fast_success(tmp_path, tamper):
    path = prepared(tmp_path)
    baseline = audit_probes(tmp_path, '3.12.12')
    assert baseline['executions'] == 3 and baseline['outcomes'] == {'passed': 3}
    payload = json.loads(path.read_text().removeprefix('CAMI_RESULT='))
    if tamper == 'exit_code':
        payload['exit_code'] = 1
    elif tamper == 'collection':
        payload['collected'] = []
    elif tamper == 'setup_failure':
        payload['reports'][0]['outcome'] = 'failed'
    line = 'CAMI_RESULT=' + json.dumps(payload) + '\n'
    path.write_text(line * (2 if tamper == 'duplicate_payload' else 1))
    with pytest.raises(AssertionError):
        audit_probes(tmp_path, '3.12.12')
