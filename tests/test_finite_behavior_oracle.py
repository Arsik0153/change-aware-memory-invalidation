import pytest

from scripts.finite_behavior_oracle import value_of


def test_reads_called_function_and_direct_return():
    assert value_of("def f(): return g()\ndef g(): return 2\n") == 2
    assert value_of("def f(): return 3\ndef g(): return 1\n") == 3
    assert value_of("def f(): return g()\ndef g(): return h()\ndef h(): return 17\n") == 17


@pytest.mark.parametrize("source", [
    "import os\ndef f(): return 1\n",
    "def f(x=1): return 1\n", "def f(): return True\n",
    "def f(): return 1 + 1\n", "def f(): return g(1)\ndef g(): return 1\n",
    "def f(): return f()\n", "def f(): return missing()\n",
    "def f(): return 1\ndef f(): return 2\n", "def f(): pass\n",
    "@decorator\ndef f(): return 1\n", "async def f(): return 1\n",
    "def f():\n    global x\n    return 1\n", "def f() -> int: return 1\n",
    "def f(): return\n", "def f(): return '1'\n",
])
def test_rejects_unsupported_semantics_instead_of_guessing(source):
    with pytest.raises(ValueError):
        value_of(source)
