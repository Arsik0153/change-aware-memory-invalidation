from scripts.check_binding_gate import observe


def test_binding_gate_diagnostic_does_not_execute_body_or_claim_truth():
    source = b'def f():\n    raise RuntimeError("must not execute")\n'
    assert observe(source, None) == ('passes_binding_gate_only', None)


def test_binding_gate_retains_rejection_and_unreadable_outcomes():
    outcome, reason = observe(b'class C:\n    pass\n\ndef f():\n    return 1\n', None)
    assert outcome == 'binding_gate_rejected'
    assert reason == 'unsupported or conditional module binding'
    assert observe(None, 'symlink_unsupported') == ('unreadable_or_unparseable', 'symlink_unsupported')
    assert observe(b'def broken(', None) == ('unreadable_or_unparseable', 'SyntaxError')
