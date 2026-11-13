"""Exact overlap is evidence of repeated text, not redundant work."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from memory_read_overlap import numbered_source, prefix_present  # noqa: E402


def test_exact_prefix_with_extra_context_and_newline_normalization():
    state = {"status": "completed", "content": [{"type": "text", "text": "Read file /workspace/a.py, lines 2-5\n2: def f():\n3:     return 1\n4: \n5: extra = 2"}]}
    text = numbered_source(state)
    assert prefix_present("def f():\r\n    return 1\r\n", text) is True
    assert "extra = 2" in text
    assert prefix_present("def f():\n    return 2\n", text) is False


def test_unknown_content_is_not_measured_as_nonoverlap():
    assert numbered_source({"status": "error"}) is None
    assert numbered_source({"status": "completed", "content": [{"type": "text", "text": "1: [REDACTED]"}]}) is None
    assert prefix_present("", "body") is None
    assert prefix_present("[REDACTED]", "body") is None
    assert prefix_present("body", None) is None
