"""A class-body global declaration must invalidate the affected structural subject."""
from dataclasses import replace

import pytest

from cami.index import build_index
from cami.models import Node
from scripts.check_structural_carry import claims, observe, snapshot

PARENT = 'def f(x):\n    return x\n'
PLAN = {'known_incomplete': False, 'protocol_version': '1.1', 'dependency_depth': 1}


@pytest.mark.parametrize('suffix', [
    'class C:\n    global f\n    f = 0\n',
    'class Outer:\n    class Inner:\n        global f\n        f = 0\n',
    'if flag:\n    class C:\n        global f\n        del f\n',
    'class C:\n    global f\n    import other as f\n',
    'class C:\n    global f\n    def f(x):\n        return x + 1\n',
    'class C:\n    global f\n',
])
def test_module_target_becomes_ambiguous_and_selected(suffix):
    parent, child = snapshot(PARENT), snapshot(PARENT + suffix)
    for claim in claims(parent, 'class-global'):
        row = observe(parent, child, claim, PLAN)
        assert row['selected'], row
        assert row['child_verdict'] == 'insufficient_evidence', row
        assert row['child_reason'] == 'ambiguous_subject'
        assert row['warm_index_equals_fresh']
    module = build_index(child).modules[0]
    assert Node(path='module.py', qualname='f') in module.unresolved


@pytest.mark.parametrize('suffix', [
    'class C:\n    f = 0\n',
    'class C:\n    def method(self):\n        global f\n        f = 0\n',
    'def deferred():\n    class C:\n        global f\n        f = 0\n',
    'class C:\n    global another\n    another = 0\n',
])
def test_unrelated_or_deferred_class_binding_does_not_poison_target(suffix):
    parent, child = snapshot(PARENT), snapshot(PARENT + suffix)
    row = observe(parent, child, claims(parent, 'local-control')[0], PLAN)
    assert row['child_verdict'] == 'supported'
    assert not row['selected']


def test_same_blob_old_parser_cache_cannot_hide_class_global():
    from cami import index
    import sys
    parent, child = snapshot(PARENT), snapshot(PARENT+'class C:\n    global f\n    f = 0\n')
    # Cache the former parser's unambiguous result under its actual version key.
    former = replace(build_index(parent).modules[0], source=child.blobs[0].content.decode())
    cache = {(child.blobs[0].object_id, sys.version, '3', 'module.py', 'module'): former}
    result = index.build_index(child, cache=cache)
    subject = next(d for d in result.modules[0].definitions if d.node.qualname == 'f')
    assert subject.ambiguous


@pytest.mark.parametrize('policy', ['symbol_validate', 'file_validate', 'all_validate'])
@pytest.mark.parametrize('nested', [False, True])
def test_git_replay_withholds_retries_and_restores(repo, tmp_path, policy, nested):
    import json
    from cami.artifacts import read_jsonl
    from cami.engine import run_experiment

    suffix = ('class C:\n    global f\n    f = 0\n' if not nested else
              'class Outer:\n    class Inner:\n        global f\n        f = 0\n')
    parent = repo.commit({'module.py': PARENT})
    rebound = repo.commit({'module.py': PARENT + suffix})
    unchanged_subject = repo.commit({'note.txt': 'unrelated change\n'})
    restored = repo.commit({'module.py': PARENT})
    config = repo.config(parent, [rebound, unchanged_subject, restored], policy=policy)
    data = json.loads(config.read_bytes())
    data['protocol_version'] = '1.1'
    config.write_text(json.dumps(data))
    output = tmp_path/'replay'
    run_experiment(config, output)
    states = read_jsonl(output/'states.jsonl')
    assert [row['available'] for row in states] == [False, False, True]
    assert [row['last_checked_commit'] for row in states] == [rebound, unchanged_subject, restored]
    assert [row['last_verdict'] for row in states] == ['insufficient_evidence', 'insufficient_evidence', 'supported']


def test_old_validation_cache_does_not_restore_unsupported_availability(repo, tmp_path, monkeypatch):
    import json
    from cami import engine
    from cami.artifacts import read_jsonl

    parent = repo.commit({'module.py': PARENT})
    child = repo.commit({'module.py': PARENT+'class C:\n    global f\n    f = 0\n'})
    config = repo.config(parent, [child], policy='all_validate')
    data = json.loads(config.read_bytes())
    data.update(protocol_version='1.1', cache_dir='validation-cache')
    config.write_text(json.dumps(data))
    real_validate = engine.validate_claim

    def legacy_result(claim, context):
        return real_validate(claim, context).model_copy(update={
            'verdict': 'supported', 'reason': 'authored_legacy_cache_fixture'})

    with monkeypatch.context() as old:
        old.setattr(engine, 'VALIDATOR_VERSION', '4')
        old.setattr(engine, 'validate_claim', legacy_result)
        engine.run_experiment(config, tmp_path/'old-cache-fixture')
    assert read_jsonl(tmp_path/'old-cache-fixture/states.jsonl')[0]['available']
    engine.run_experiment(config, tmp_path/'current')
    result = read_jsonl(tmp_path/'current/validations.jsonl')[0]
    assert not result['cache_hit'] and result['verdict'] == 'insufficient_evidence'
    assert not read_jsonl(tmp_path/'current/states.jsonl')[0]['available']
