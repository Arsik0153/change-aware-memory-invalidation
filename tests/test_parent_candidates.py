import pytest

from cami.pilot import parent_candidates


@pytest.mark.parametrize('tail', [
    'if True:\n    def f(): pass\n',
    'def f(): pass\n',
    'def outer():\n    def f(): pass\n',
    'class C:\n    def f(): pass\n',
    'class f: pass\n',
    'f = 1\n',
    'f, other = (1, 2)\n',
    '(f, other) = (1, 2)\n',
    '[other, f] = (1, 2)\n',
    'other = f = 1\n',
    'f /= 2\n',
    'f //= 2\n',
    'f **= 2\n',
    'f: int\n',
    'del f\n',
    'import other as f\n',
    'from other import f\n',
    'from other import *\n',
    'for f in []: pass\n',
    'with other as f: pass\n',
    'if (f := 1): pass\n',
    'try:\n    pass\nexcept Exception as f:\n    pass\n',
    'match 1:\n    case f: pass\n',
])
def test_rebinding_or_other_definition_is_excluded(tail):
    assert 'f' not in {name for name, _ in parent_candidates('def f(): pass\n' + tail)}


@pytest.mark.parametrize('source', ['def f() pass\n', 'def 123(): pass\n',
                                    'def f(): pass\nx =\n'])
def test_malformed_parent_cannot_receive_confirmation(source):
    assert parent_candidates(source) == ()


def test_unambiguous_top_level_functions_remain_candidates():
    source = ('@decorator\ndef good(x=1):\n    return x\n'
              'async def other(x):\n    return x\n'
              'if True:\n    def conditional(): pass\n'
              'class C:\n    def method(self): pass\n')
    assert parent_candidates(source) == (('good', 2), ('other', 4))


def test_pilot_initial_regression():
    source = ('def good(x):\n    return x\nif True:\n    def conditional(): pass\n'
              'def rebound(): pass\nrebound = other\nclass C:\n    def method(self): pass\n')
    assert parent_candidates(source) == (('good', 1),)


def test_inline_rebinding_is_excluded():
    assert parent_candidates("def f(): pass; f = 1\n") == ()


@pytest.mark.parametrize('tail', ['def g(x=(f := 1)): pass\n',
                                  'def g(x: (f := int)): pass\n',
                                  'def g() -> (f := int): pass\n',
                                  '@(f := decorator)\ndef g(): pass\n',
                                  'class C((f := object)): pass\n'])
def test_outer_definition_bindings_are_excluded(tail):
    assert 'f' not in {name for name, _ in parent_candidates('def f(): pass\n' + tail)}
