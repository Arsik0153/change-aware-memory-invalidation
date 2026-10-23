"""Regression checks for scope evidence projected from the installed compiler traversal."""
from __future__ import annotations

import subprocess

import pytest

from cami.errors import InputError
from cami.product.service import ProductMemory


@pytest.fixture
def hybrid(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    return root, ProductMemory(root)


@pytest.mark.parametrize('replacement', [
    'const target = wrap(() => 1);',
    'const {target} = library;',
    'import {target} from "missing";',
    'namespace target { export function nested() {} }',
])
def test_unsupported_identity_is_withheld_not_deleted(hybrid, replacement):
    root, memory = hybrid
    source = root / 'api.ts'
    source.write_text('function target() {}')
    initial = memory.context('api.ts:target')
    memory.remember('symbol_exists', 'api.ts:target', initial, 'exists')
    source.write_text(replacement)
    result = memory.context('api.ts:target')
    assert not result.facts
    assert result.withheld[0].reason == 'binding_unresolved'
    assert result.withheld[0].state.check.verdict == 'insufficient_evidence'


def test_member_uncertainty_does_not_withhold_unrelated_function(hybrid):
    root, memory = hybrid
    source = root / 'api.ts'
    source.write_text('function target() {}\nclass C { method() {} }')
    initial = memory.context('api.ts:target')
    memory.remember('symbol_exists', 'api.ts:target', initial, 'exists')
    member = memory.context('api.ts:C.method')
    assert len(member.code) == 1 and member.code[0].signature is None
    memory.remember('symbol_exists', 'api.ts:C.method', member, 'member')
    with pytest.raises(InputError, match='unsupported signature'):
        memory.remember('signature_equals', 'api.ts:C.method', member, 'signature')
    source.write_text('function target() {}\nclass C { [key]() {} }\nunknown();')
    result = memory.context('api.ts:target')
    assert len(result.facts) == 1 and not result.withheld
    member = memory.context('api.ts:C.method')
    assert member.withheld[0].reason == 'binding_unresolved'
    source.write_text('function target() {}\nclass C { method = wrap(() => 1); }')
    assert memory.context('api.ts:C.method').withheld[0].reason == 'binding_unresolved'
    source.write_text('function target() {}\nclass C { constructor(public method: () => void) {} }')
    assert memory.context('api.ts:C.method').withheld[0].reason == 'binding_unresolved'
    source.write_text('function target() {}\nclass C {}')
    absent = memory.context('api.ts:C.method')
    assert absent.withheld[0].reason == 'subject_absent'


def test_projection_normalizer_uses_trusted_cache_only(hybrid, monkeypatch):
    from cami.product.memory import adapters
    from cami.typescript_analyzer import TypeScriptAnalyzerUnavailable

    root, _ = hybrid
    compiler = root / 'typescript.js'
    compiler.write_text('throw new Error("must not execute")')
    monkeypatch.setattr(adapters, 'compiler_path', lambda: compiler)
    with pytest.raises(TypeScriptAnalyzerUnavailable):
        adapters.ecma_signatures(())
    with pytest.raises(TypeScriptAnalyzerUnavailable):
        adapters.ecma_signatures((), trusted_compiler=compiler)


def test_wrapped_default_export_does_not_prove_absence(hybrid):
    root, memory = hybrid
    source = root / 'api.ts'
    source.write_text('export default () => 1;')
    initial = memory.context('api.ts:<default>')
    memory.remember('symbol_exists', 'api.ts:<default>', initial, 'default')
    source.write_text('export default wrap(() => 1);')
    result = memory.context('api.ts:<default>')
    assert result.withheld[0].reason == 'binding_unresolved'
    assert result.withheld[0].state.check.verdict == 'insufficient_evidence'


@pytest.mark.parametrize('replacement,reason', [
    ('"method"() {}', None),
    ('"metho\\u0064"() {}', None),
    ('["method"]() {}', None),
    ('"method" = wrap(() => 1);', 'binding_unresolved'),
    ('["method"] = wrap(() => 1);', 'binding_unresolved'),
    ('get "method"() {}', 'binding_unresolved'),
    ('[key]() {}', 'binding_unresolved'),
    ('["meth" + "od"]() {}', 'binding_unresolved'),
    ('method() {} "method"() {}', 'ambiguous_binding'),
    ('static method() {} "method"() {}', 'ambiguous_binding'),
    ('"method"(): void;', 'binding_unresolved'),
])
def test_static_member_spelling_preserves_identity_or_withholds(hybrid, replacement, reason):
    root, memory = hybrid
    source = root / 'api.ts'
    source.write_text('function unrelated() {}\nclass C { method() {} }')
    symbol = 'api.ts:C.method'
    origin = memory.context(symbol)
    memory.remember('symbol_exists', symbol, origin, 'member')
    source.write_text(f'function unrelated() {{}}\nclass C {{ {replacement} }}')
    current = memory.context(symbol)
    if reason:
        assert not current.facts and current.withheld[0].reason == reason
        assert current.withheld[0].state.check.verdict == 'insufficient_evidence'
    else:
        assert len(current.facts) == 1 and not current.withheld
        assert current.code[0].subject == origin.code[0].subject
        assert current.code[0].signature is None
    assert memory.context('api.ts:unrelated').code
    source.write_text('class C {}')
    deleted = memory.context(symbol)
    assert deleted.withheld[0].reason == 'subject_absent'
    assert deleted.withheld[0].state.check.verdict == 'contradicted'


@pytest.mark.parametrize('replacement', [
    '"method" = wrap(() => 1);',
    '["method"] = wrap(() => 1);',
    'get "method"() {}',
])
def test_known_unsupported_member_keeps_other_member_supported(hybrid, replacement):
    root, memory = hybrid
    source = root / 'api.ts'
    source.write_text('class C { method() {} safe() {} }')
    symbol = 'api.ts:C.safe'
    origin = memory.context(symbol)
    memory.remember('symbol_exists', symbol, origin, 'safe')
    source.write_text(f'class C {{ {replacement} safe() {{}} }}')
    current = memory.context(symbol)
    assert len(current.facts) == 1 and not current.withheld


def test_invalid_member_syntax_never_proves_absence(hybrid):
    root, memory = hybrid
    source = root / 'api.ts'
    source.write_text('class C { method() {} }')
    symbol = 'api.ts:C.method'
    origin = memory.context(symbol)
    memory.remember('symbol_exists', symbol, origin, 'invalid')
    source.write_text('class C { "method() {} }')
    current = memory.context(symbol)
    assert current.withheld[0].reason == 'parse_error'
    assert current.withheld[0].state.check.verdict == 'insufficient_evidence'


@pytest.mark.parametrize('replacement', [
    '"method" = wrap(() => 1);', 'get "method"() {}',
])
def test_known_unsupported_member_withholds_nested_function(hybrid, replacement):
    root, memory = hybrid
    source = root / 'api.ts'
    source.write_text('class C { method() { function inner() {} } }')
    symbol = 'api.ts:C.method.inner'
    origin = memory.context(symbol)
    memory.remember('symbol_exists', symbol, origin, 'nested')
    source.write_text(f'class C {{ {replacement} }}')
    current = memory.context(symbol)
    assert current.withheld[0].reason == 'binding_unresolved'
    assert current.withheld[0].state.check.verdict == 'insufficient_evidence'


def test_nested_identity_gap_is_scoped_to_its_source_file(hybrid):
    root, memory = hybrid
    original = 'class C { method() { function inner() {} } }'
    for path in ('safe.ts', 'uncertain.ts'):
        (root / path).write_text(original)
        symbol = f'{path}:C.method.inner'
        memory.remember('symbol_exists', symbol, memory.context(symbol), path)
    (root / 'uncertain.ts').write_text(
        'class C { method() { function inner() {} } "method" = wrap(() => 1); }')

    safe = memory.context('safe.ts:C.method.inner')
    assert len(safe.facts) == 1 and not safe.withheld
    assert not safe.code[0].identity_uncertain
    uncertain = memory.context('uncertain.ts:C.method.inner')
    assert uncertain.code[0].identity_uncertain
    assert not uncertain.facts
    assert uncertain.withheld[0].reason == 'binding_unresolved'
    assert uncertain.withheld[0].state.check.verdict == 'insufficient_evidence'
