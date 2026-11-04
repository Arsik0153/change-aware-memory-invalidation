import hashlib

from scripts import structural_checker, structural_checker_v2


def record(tmp_path, source):
    raw = source.encode()
    (tmp_path/'module.py').write_bytes(raw)
    return {'id': 'authored', 'kind': 'symbol_exists',
            'subject': {'path': 'module.py', 'qualname': 'f', 'node_kind': 'function'},
            'predicate': {'type': 'symbol_exists', 'expected': True},
            'text': 'Exact syntactic f', 'scope': 'Unique top-level definition',
            'source_path': 'module.py', 'source_sha256': hashlib.sha256(raw).hexdigest()}


def test_v1_counterexample_is_preserved_and_v2_abstains(tmp_path):
    case = record(tmp_path, 'def f(): pass\nclass Outer:\n    class Inner:\n        global f\n        f = 0\n')
    assert structural_checker.check_case(tmp_path, case)['verdict'] == 'supported'
    assert structural_checker_v2.check_case(tmp_path, case)['verdict'] == 'uncertain'


def test_deferred_function_global_and_ordinary_class_local_do_not_abstain(tmp_path):
    for suffix in ('class Outer:\n    def method(self):\n        global f\n        f = 0\n',
                   'class Outer:\n    class Inner:\n        f = 0\n'):
        case = record(tmp_path, 'def f(): pass\n'+suffix)
        assert structural_checker_v2.check_case(tmp_path, case)['verdict'] == 'supported'
