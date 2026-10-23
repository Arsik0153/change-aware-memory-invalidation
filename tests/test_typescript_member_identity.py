"""Compiler-observable static member keys and coverage boundaries."""
import pytest

from cami.typescript_analyzer import analyze_typescript


@pytest.mark.parametrize('spelling,expected', [
    ('method', 'method'), ('metho\\u0064', 'method'),
    ('"method"', 'method'), ("'method'", 'method'),
    ('"metho\\u0064"', 'method'), ('["method"]', 'method'),
    ('16', '16'), ('0x10', '16'), ('0b10000', '16'), ('1.6e1', '16'),
    ('"16"', '16'), ('[16]', '16'), ('[0x10]', '16'),
    ('1.5', '"1.5"'), ('"1.5"', '"1.5"'),
    ('"01"', '"01"'), ('"a.b"', '"a.b"'), ('""', '""'),
    ('"#method"', '"#method"'), ('"\\u0061.b"', '"a.b"'),
])
@pytest.mark.parametrize('container,prefix', [
    ('class C {{ {member} }}', 'C.'),
    ('class C {{ static {member} }}', 'C.'),
    ('const api = {{ {member} }};', ''),
])
def test_static_member_names_share_one_identity(spelling, expected, container, prefix):
    result = analyze_typescript({'api.ts': container.format(member=spelling + '() {}')})
    assert result.analyzed_files == ('api.ts',)
    methods = [d for d in result.definitions if d.key.kind == 'method']
    assert len(methods) == 1
    assert methods[0].name == expected
    assert methods[0].key.qualname == prefix + expected
    assert not methods[0].ambiguous
    assert not any(g.covers('api.ts', prefix + expected, 'method') for g in result.identity_gaps)


@pytest.mark.parametrize('member', [
    '"method" = wrap(() => 1);', '["method"] = wrap(() => 1);',
    'get "method"() {}', 'set ["method"](value) {}',
    '[key]() {}', '["meth" + "od"]() {}', '[`method`]() {}',
    '[("method")]() {}',
])
def test_unsupported_names_and_fields_cover_affected_member_only(member):
    result = analyze_typescript({'api.ts': f'function unrelated() {{}} class C {{ {member} }}'})
    assert not any(d.key.qualname == 'C.method' for d in result.definitions)
    assert any(g.covers('api.ts', 'C.method', 'method') for g in result.identity_gaps)
    assert not any(g.covers('api.ts', 'unrelated', 'function') for g in result.identity_gaps)


@pytest.mark.parametrize('members', [
    'method() {} "method"() {}',
    'method() {} ["method"]() {}',
    'static method() {} "metho\\u0064"() {}',
    '16() {} "16"() {}',
])
def test_duplicate_normalized_keys_are_ambiguous(members):
    result = analyze_typescript({'api.ts': f'class C {{ {members} }}'})
    assert len(result.definitions) == 2
    assert len({d.key.qualname for d in result.definitions}) == 1
    assert all(d.ambiguous for d in result.definitions)


def test_private_public_and_nested_segments_do_not_alias():
    result = analyze_typescript({'api.ts': '''class C {
      #method() {} "#method"() {} "a.b"() {} a() { function b() {} }
    }'''})
    assert {d.key.qualname for d in result.definitions} == {
        'C.#method', 'C."#method"', 'C."a.b"', 'C.a', 'C.a.b'}
    assert not any(d.ambiguous for d in result.definitions)


def test_constructors_stay_distinct_from_indexed_methods():
    result = analyze_typescript({'api.ts': '''class C {
      constructor(public method: () => void) {} get "value"() { return 1; }
      set ["value"](v) {} #private() {}
    }'''})
    assert [d.key.qualname for d in result.definitions] == ['C.#private']
    assert any(g.covers('api.ts', 'C.method', 'method') for g in result.identity_gaps)
    assert any(g.covers('api.ts', 'C.value', 'method') for g in result.identity_gaps)


@pytest.mark.parametrize('member', ['"method" = wrap(() => 1);', 'get "method"() {}'])
def test_known_unsupported_member_covers_nested_identities(member):
    result = analyze_typescript({'api.ts': f'function unrelated() {{}} class C {{ {member} }}'})
    assert any(g.covers('api.ts', 'C.method.inner', 'function') for g in result.identity_gaps)
    assert not any(g.covers('api.ts', 'unrelated', 'function') for g in result.identity_gaps)
