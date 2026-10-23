import os

import pytest

from cami.artifacts import file_hash
from cami.behavior import ProbeContext, execute_probe
from cami.models import Behavior, Claim, EnvironmentProfile, Subject
from test_index import snapshot


@pytest.mark.docker
@pytest.mark.skipif(not os.environ.get('CAMI_TEST_IMAGE'), reason='prepared Docker image required')
def test_preloaded_pytest_cannot_validate_historical_pytest(repo):
    revision = repo.commit({'_pytest/__init__.py': '', '_pytest/compat.py':
                            "def safe_getattr(obj, name, default): return 'historical-wrong'\n"})
    probe = repo.root.parent / 'test_collision.py'
    probe.write_text('from _pytest.compat import safe_getattr\n'
                     'def test_case():\n'
                     "    assert safe_getattr(object(), 'missing', 'fallback') == 'fallback'\n")
    claim = Claim(claim_id='historical-pytest', repo_id='fixture', origin_commit=revision,
                  kind='behavior_test', text='Historical safe_getattr returns fallback',
                  scope='One fixed invocation',
                  subject=Subject(path='_pytest/compat.py', qualname='safe_getattr', node_kind='function'),
                  predicate=Behavior(type='behavior_test', probe_path=probe.name,
                                     probe_sha256=file_hash(probe), node_id=probe.name+'::test_case',
                                     environment_id='test'))
    profile = EnvironmentProfile(image=os.environ['CAMI_TEST_IMAGE'], python_version='3.12.12')
    result = execute_probe(claim, ProbeContext(snapshot(repo, revision), profile,
                                              probe.parent, probe.parent / 'result'))
    assert (result.verdict, result.reason) == ('insufficient_evidence', 'environment_error')
    assert result.test_executions == 3
