import json

import pytest

from cami.artifacts import read_json, read_jsonl
from cami.engine import run_experiment


def use_protocol(config, version):
    data = read_json(config)
    data['protocol_version'] = version
    config.write_text(json.dumps(data))


@pytest.mark.parametrize('policy, expected', [('symbol_validate', 0), ('file_validate', 1)])
def test_exact_syntax_ignores_unrelated_unresolved_calls(repo, policy, expected):
    a = repo.commit({'module.py': 'import sys\ndef f(): return sys.missing()\n'})
    b = repo.commit({'module.py': '# comment\nimport sys\ndef f(): return sys.missing()\n'})
    config = repo.config(a, [b], policy=policy)
    use_protocol(config, '1.1')
    out = config.parent / 'out'
    run_experiment(config, out)
    assert len(read_jsonl(out / 'validations.jsonl')) == expected
    assert read_jsonl(out / 'states.jsonl')[0]['available']


def test_v1_keeps_conservative_structural_contract(repo):
    a = repo.commit({'module.py': 'import sys\ndef f(): return sys.missing()\n'})
    b = repo.commit({'notes.txt': 'unrelated'})
    config = repo.config(a, [b])
    out = config.parent / 'out'
    run_experiment(config, out)
    assert read_jsonl(out / 'selections.jsonl')[0]['reasons'] == ['unresolved_dependency']


def test_exact_syntax_selects_deletion_uncertainty_and_recovery(repo):
    source = 'import sys\ndef f(): return sys.missing()\n'
    a = repo.commit({'module.py': source})
    b = repo.commit({'module.py': 'import sys\n'})
    c = repo.commit({'module.py': 'def f(\n'})
    d = repo.commit({'module.py': source})
    e = repo.commit({'notes.txt': 'unrelated'})
    config = repo.config(a, [b, c, d, e])
    use_protocol(config, '1.1')
    out = config.parent / 'out'
    run_experiment(config, out)
    states = read_jsonl(out / 'states.jsonl')
    assert [s['state'] for s in states] == ['retired', 'needs_validation', 'valid', 'valid']
    assert states[-1]['last_checked_commit'] == d
    assert len(read_jsonl(out / 'validations.jsonl')) == 3


@pytest.mark.parametrize('missing', ['known_incomplete', 'empty_anchors', 'explicit_dependency'])
def test_exact_syntax_preserves_declared_unknown_support(repo, missing):
    a = repo.commit({'module.py': 'import sys\ndef f(): return 1\n'})
    b = repo.commit({'notes.txt': 'unrelated'})
    config = repo.config(a, [b])
    use_protocol(config, '1.1')
    path = config.parent / 'provenance.jsonl'
    prov = read_jsonl(path)[0]
    if missing == 'known_incomplete':
        prov['known_incomplete'] = True
    elif missing == 'empty_anchors':
        prov['anchors'] = []
    else:
        prov['dependencies'] = [{'from': {'path': 'module.py', 'qualname': 'f'},
                                 'to': {'path': 'module.py'}, 'relation': 'evidence_dependency',
                                 'origin': 'manual'}]
    path.write_text(json.dumps(prov) + '\n')
    out = config.parent / 'out'
    run_experiment(config, out)
    assert read_jsonl(out / 'selections.jsonl')[0]['selected']


@pytest.mark.parametrize('source', ['def f(): pass\nfrom other import f\n',
                                    'def f(): pass\nfrom other import *\n',
                                    'def f(): pass\nimport other as f\n',
                                    'def f(): pass\ndel f\n',
                                    'def f(): pass\nfor f in [1]: pass\n',
                                    'def f(): pass\nwith thing as f: pass\n',
                                    'def f(): pass\nif (f := 1): pass\n',
                                    'def f(): pass\nmatch 1:\n    case f: pass\n',
                                    'def f(): pass\ntry: pass\nexcept Exception as f: pass\n'])
def test_rebound_definition_is_uncertain(repo, source):
    a = repo.commit({'module.py': 'def f(): pass\n'})
    b = repo.commit({'module.py': source})
    config = repo.config(a, [b], policy='all_validate')
    out = config.parent / 'out'
    run_experiment(config, out)
    result = read_jsonl(out / 'validations.jsonl')[0]
    assert (result['verdict'], result['reason']) == ('insufficient_evidence', 'ambiguous_subject')


@pytest.mark.parametrize('body', ['return X',
    'def nested():\n        X = 9\n    return X',
    'global X\n    X += 1\n    return X',
    'values = [X for X in range(3)]\n    return X'])
def test_global_value_dependency_is_conservative_for_behavior(repo, body):
    from cami.artifacts import load_jsonl
    from cami.index import build_index, compare_indexes
    from cami.models import Claim, MemoryState, PolicyConfig, Prose, Provenance
    from cami.policies import SelectionContext, select_claims
    from test_index import snapshot

    a = repo.commit({'module.py': f'X = 1\ndef f():\n    {body}\n'})
    b = repo.commit({'module.py': f'X = 2\ndef f():\n    {body}\n'})
    config = repo.config(a, [b])
    original = load_jsonl(config.parent / 'claims.jsonl', Claim)[0]
    claim = original.model_copy(update={'kind': 'prose', 'predicate': Prose(type='prose')})
    provenance = load_jsonl(config.parent / 'provenance.jsonl', Provenance)[0]
    previous = MemoryState(claim_id=claim.claim_id, revision=a, state='valid',
                           last_checked_commit=a, last_supported_commit=a,
                           last_verdict='supported', basis='validated',
                           current_provenance=provenance, available=True)
    old, new = snapshot(repo, a), snapshot(repo, b)
    changes = compare_indexes(build_index(old), build_index(new), old, new)
    context = SelectionContext(b, (claim,), (provenance,), (previous,), changes)
    decision = select_claims(context, PolicyConfig(id='symbol_validate'))[0]
    assert decision.selected
    assert 'unresolved_dependency' in decision.reasons


def test_signature_change_remains_relevant_in_v11(repo):
    a = repo.commit({'module.py': 'import sys\ndef f(x): return sys.missing(x)\n'})
    b = repo.commit({'module.py': 'import sys\ndef f(x, y=1): return sys.missing(x)\n'})
    config = repo.config(a, [b])
    use_protocol(config, '1.1')
    path = config.parent / 'claims.jsonl'
    claim = read_jsonl(path)[0]
    claim.update(kind='signature_equals', text='f has one unannotated positional parameter x',
                 predicate={'type': 'signature_equals', 'expected_signature': {
                     'parameters': [{'name': 'x', 'kind': 'positional_or_keyword'}],
                     'returns_ast': None, 'decorators_ast': [], 'is_async': False}})
    path.write_text(json.dumps(claim) + '\n')
    out = config.parent / 'out'
    run_experiment(config, out)
    assert read_jsonl(out / 'validations.jsonl')[0]['reason'] == 'predicate_mismatch'
    assert read_jsonl(out / 'states.jsonl')[0]['state'] == 'stale'


def test_v11_preserves_file_anchor_scope(repo):
    a = repo.commit({'module.py': 'def f(): return 1\n'})
    b = repo.commit({'module.py': '# comment\ndef f(): return 1\n'})
    config = repo.config(a, [b])
    use_protocol(config, '1.1')
    path = config.parent / 'provenance.jsonl'
    prov = read_jsonl(path)[0]
    prov['anchors'][0]['scope'] = 'file'
    path.write_text(json.dumps(prov) + '\n')
    out = config.parent / 'out'
    run_experiment(config, out)
    assert read_jsonl(out / 'selections.jsonl')[0]['reasons'] == ['anchor_file_changed']


def test_default_expression_global_is_not_a_local_parameter(repo):
    from cami.index import build_index
    from cami.models import Node
    from test_index import snapshot

    a = repo.commit({'module.py': 'X = 1\ndef f(X=X): return X\n'})
    assert Node(path='module.py', qualname='f') in build_index(snapshot(repo, a)).unresolved


@pytest.mark.parametrize('tail', ['def g(x=(f := 1)): pass\n',
                                  'def g(x: (f := int)): pass\n',
                                  'def g() -> (f := int): pass\n',
                                  '@(f := decorator)\ndef g(): pass\n',
                                  'class C((f := object)): pass\n',
                                  'g = lambda x=(f := 1): x\n'])
def test_enclosing_definition_expressions_can_rebind_subject(repo, tail):
    test_rebound_definition_is_uncertain(repo, 'def f(): pass\n' + tail)
