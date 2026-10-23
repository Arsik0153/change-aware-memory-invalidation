"""Absence requires coverage of every ancestor of a structural identity."""
from __future__ import annotations

import subprocess

import pytest

from cami.product.service import ProductMemory
from cami.product.memory.models import AbsenceWitness


BODY = '''function inner() {} const arrow = () => 1; const expr = function() {};
          class Nested { member() {} }'''


@pytest.fixture
def scope_memory(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    return root, ProductMemory(root)


@pytest.mark.parametrize('name,replacement', [
    ('method', '[("method")]() {{ {body} }}'),
    ('method', '[key]() {{ {body} }}'),
    ('method', 'get [key]() {{ {body} }}'),
    ('method', '[key] = wrap(() => {{ {body} }});'),
    ('method', '"method" = wrap(() => {{ {body} }});'),
    ('16', '[0x10] = wrap(() => {{ {body} }});'),
    ('#private', '#private = wrap(() => {{ {body} }});'),
    ('method', 'constructor(public method: () => void) {{}}'),
])
def test_unknown_owner_withholds_all_descendant_kinds(scope_memory, name, replacement):
    root, memory = scope_memory
    source = root / 'api.ts'
    source.write_text(f'class C {{ {name}() {{ {BODY} }} }}')
    symbols = [f'api.ts:C.{name}.{suffix}'
               for suffix in ('inner', 'arrow', 'expr', 'Nested.member')]
    receipts = []
    for symbol in symbols:
        origin = memory.context(symbol)
        assert len(origin.code) == 1
        receipts.append(memory.remember('symbol_exists', symbol, origin, symbol))
    source.write_text('class C { ' + replacement.format(body=BODY) + ' }')
    generation = memory.refresh()
    for receipt in receipts:
        state = next(s for s in generation.states if s.record.memory_id == receipt.memory_id)
        assert state.state.check.verdict == 'insufficient_evidence'
        assert state.state.check.reason == 'binding_unresolved'
        assert not any(isinstance(e, AbsenceWitness) for e in state.state.check.evidence)


def test_unknown_scope_preserves_file_and_qualified_owner_boundaries(scope_memory):
    root, memory = scope_memory
    source = root / 'api.ts'
    base = f'''class C {{ owner() {{
      class N {{ method() {{ {BODY} }} }}
      class N2 {{ method() {{ function inner() {{}} }} }}
      function sibling() {{}}
    }} }}
    function unrelated() {{}}'''
    source.write_text(base)
    (root / 'other.ts').write_text(base)
    symbols = ('api.ts:C.owner.N.method.inner', 'api.ts:C.owner.N2.method.inner',
               'api.ts:C.owner.sibling', 'api.ts:unrelated', 'other.ts:C.owner.N.method.inner')
    for symbol in symbols:
        memory.remember('symbol_exists', symbol, memory.context(symbol), symbol)
    source.write_text(base.replace('method()', '[key]()', 1))
    assert memory.context(symbols[0]).withheld[0].reason == 'binding_unresolved'
    for symbol in symbols[1:]:
        current = memory.context(symbol)
        assert len(current.facts) == 1 and not current.withheld


def test_exact_binding_gap_does_not_cover_class_members(scope_memory):
    root, memory = scope_memory
    (root / 'api.ts').write_text('class C { method() { function inner() {} } }')
    symbol = 'api.ts:C.method.inner'
    memory.remember('symbol_exists', symbol, memory.context(symbol), 'exists')
    assert len(memory.context(symbol).facts) == 1


def test_covered_deletion_and_recovery_keep_immutable_check_history(scope_memory):
    root, memory = scope_memory
    source = root / 'api.ts'
    base = f'class C {{ method() {{ {BODY} }} }}'
    source.write_text(base)
    symbol = 'api.ts:C.method.inner'
    receipt = memory.remember('symbol_exists', symbol, memory.context(symbol), 'exists')
    original = memory.history(receipt.memory_id)
    source.write_text(base.replace('method()', '[key]()'))
    uncertain = memory.context(symbol)
    assert uncertain.withheld[0].reason == 'binding_unresolved'
    source.write_text(base)
    recovered = memory.context(symbol)
    assert len(recovered.facts) == 1
    source.write_text(base.replace('function inner() {}', ''))
    absent = memory.context(symbol)
    assert absent.withheld[0].reason == 'subject_absent'
    check = absent.withheld[0].state.check
    assert check.verdict == 'contradicted'
    assert check.evidence[0].reason == 'symbol_absent_in_parsed_file'
    assert memory.context('api.ts:C.method.arrow').code
    history = memory.history(receipt.memory_id)
    assert history.revisions == original.revisions
    assert history.checks[:len(original.checks)] == original.checks
    assert [c.reason for c in history.checks] == [
        'predicate_matches', 'binding_unresolved', 'predicate_matches', 'subject_absent']
    assert len({c.check_id for c in history.checks}) == 4
    assert len({c.checked_at for c in history.checks}) == 4
    assert memory.context(symbol).memory_generation_id == absent.memory_generation_id
