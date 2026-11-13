"""Authored synthetic tests only; no pilot candidates or CAMI imports."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.structural_checker import check_case, run


COMPLETE_SOURCE = """@outer(1)
@inner
async def target(a: int, b=1, /, c: str='x', *rest: bytes, required, option: float=None, **extras: object) -> bool:
    return True
"""
COMPLETE_SIGNATURE = {
    "parameters": [
        {"name": "a", "kind": "positional_only", "default_ast": None, "annotation_ast": "Name(id='int', ctx=Load())"},
        {"name": "b", "kind": "positional_only", "default_ast": "Constant(value=1)", "annotation_ast": None},
        {"name": "c", "kind": "positional_or_keyword", "default_ast": "Constant(value='x')", "annotation_ast": "Name(id='str', ctx=Load())"},
        {"name": "rest", "kind": "var_positional", "default_ast": None, "annotation_ast": "Name(id='bytes', ctx=Load())"},
        {"name": "required", "kind": "keyword_only", "default_ast": None, "annotation_ast": None},
        {"name": "option", "kind": "keyword_only", "default_ast": "Constant(value=None)", "annotation_ast": "Name(id='float', ctx=Load())"},
        {"name": "extras", "kind": "var_keyword", "default_ast": None, "annotation_ast": "Name(id='object', ctx=Load())"},
    ],
    "returns_ast": "Name(id='bool', ctx=Load())",
    "decorators_ast": ["Call(func=Name(id='outer', ctx=Load()), args=[Constant(value=1)], keywords=[])", "Name(id='inner', ctx=Load())"],
    "is_async": True,
}


class StructuralCheckerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="authored-test-")
        self.addCleanup(self.temp.cleanup)
        self.packet = Path(self.temp.name).resolve()

    def case(self, source="def target():\n    pass\n", signature=None):
        raw = source if isinstance(source, bytes) else source.encode("utf-8")
        (self.packet / "module.py").write_bytes(raw)
        kind = "symbol_exists" if signature is None else "signature_equals"
        return {"id": "authored-test", "kind": kind,
                "subject": {"path": "public/module.py", "qualname": "target", "node_kind": "function"},
                "predicate": {"type": kind, **({"expected": True} if signature is None else {"expected_signature": copy.deepcopy(signature)})},
                "text": "Authored fixture structural claim", "scope": "top-level Python function",
                "source_path": "module.py", "source_sha256": hashlib.sha256(raw).hexdigest()}

    def verdict(self, case):
        return check_case(self.packet, case)["verdict"]

    def test_complete_signature_and_evidence(self):
        result = check_case(self.packet, self.case(COMPLETE_SOURCE, COMPLETE_SIGNATURE))
        self.assertEqual(result["verdict"], "supported")
        self.assertEqual(result["facts"]["signature"], COMPLETE_SIGNATURE)
        self.assertEqual(result["evidence"], [{"start_line": 1, "end_line": 4, "role": "unconditional definition"}])
        self.assertIn("not parser-independent", result["checker"]["shared_primitive_limitation"])

    def test_every_signature_field_can_contradict(self):
        mutations = [
            lambda s: s["parameters"].reverse(),
            lambda s: s["parameters"][0].update(name="renamed"),
            lambda s: s["parameters"][0].update(kind="positional_or_keyword"),
            lambda s: s["parameters"][1].update(default_ast="Constant(value=2)"),
            lambda s: s["parameters"][0].update(annotation_ast=None),
            lambda s: s.update(returns_ast=None),
            lambda s: s["decorators_ast"].reverse(),
            lambda s: s.update(is_async=False),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(field=index):
                expected = copy.deepcopy(COMPLETE_SIGNATURE)
                mutate(expected)
                self.assertEqual(self.verdict(self.case(COMPLETE_SOURCE, expected)), "contradicted")

    def test_required_keyword_and_none_default_are_distinct(self):
        case = self.case(COMPLETE_SOURCE, COMPLETE_SIGNATURE)
        case["predicate"]["expected_signature"]["parameters"][5]["default_ast"] = None
        self.assertEqual(self.verdict(case), "contradicted")

    def test_absent_and_nested_only_are_contradicted(self):
        for source in ("", "x = 1\n", "def other():\n    def target(): pass\n", "class C:\n    def target(self): pass\n"):
            with self.subTest(source=source):
                self.assertEqual(self.verdict(self.case(source)), "contradicted")

    def test_nested_locals_and_unrelated_namespace_use_are_ignored(self):
        source = """def target(): pass
def other():
    global target
    target = 1
    globals()['other'] = 2
class C:
    target = 9
    def method(self):
        global target
        target = 3
values = [target for target in range(3)]
"""
        self.assertEqual(self.verdict(self.case(source)), "supported")

    def test_definition_body_and_decorator_are_not_executed(self):
        marker = self.packet / "MUST_NOT_EXIST"
        source = f"""raise RuntimeError('module must never run')
@missing_decorator
def target(x=missing_default()):
    open({str(marker)!r}, 'w').write('executed')
"""
        self.assertEqual(self.verdict(self.case(source)), "supported")
        self.assertFalse(marker.exists())

    def test_conditional_duplicate_and_rebindings_abstain(self):
        sources = [
            "if True:\n    def target(): pass\n",
            "def target(): pass\ndef target(): pass\n",
            "def target(): pass\nif False:\n    def target(): pass\n",
            "target = 1\n", "target: int\n", "target += 1\n", "del target\n",
            "class target: pass\n", "import os as target\n", "from x import target\n",
            "from x import *\n", "for target in []: pass\n",
            "with resource() as target: pass\n",
            "try:\n    pass\nexcept Error as target:\n    pass\n",
            "match value:\n    case {'x': target}: pass\n",
            "match value:\n    case [*target]: pass\n",
            "match value:\n    case {**target}: pass\n",
            "[(target := x) for x in []]\n",
            "def other(x=(target := 1)): pass\n",
            "class C:\n    global target\n    target = 1\n",
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(self.verdict(self.case(source)), "uncertain")

    def test_bad_sources_abstain(self):
        for source in (b"\xff", "def target(:\n", "\x00", "def target[T](x: T): pass\n"):
            with self.subTest(source=source):
                self.assertEqual(self.verdict(self.case(source)), "uncertain")

    def test_hash_and_path_failures_abstain(self):
        for path in ("../outside.py", "/etc/passwd", "missing.py"):
            case = self.case()
            case["source_path"] = path
            self.assertEqual(self.verdict(case), "uncertain")
        case = self.case()
        case["source_sha256"] = "0" * 64
        self.assertEqual(self.verdict(case), "uncertain")
        (self.packet / "outside-link").symlink_to("/etc/passwd")
        case["source_path"] = "outside-link"
        self.assertEqual(self.verdict(case), "uncertain")

    def test_malformed_types_fields_and_scope_abstain(self):
        changes = [
            lambda c: c.update(kind="prose"),
            lambda c: c["predicate"].update(type="symbol_exists"),
            lambda c: c["subject"].update(node_kind="method"),
            lambda c: c["subject"].update(qualname="C.target"),
            lambda c: c.update(scope={}),
            lambda c: c.update(unrecognized=True),
            lambda c: c["predicate"]["expected_signature"].update(is_async=1),
            lambda c: c["predicate"]["expected_signature"].update(decorators_ast="bad"),
            lambda c: c["predicate"]["expected_signature"].pop("returns_ast"),
            lambda c: c["predicate"]["expected_signature"]["parameters"][0].pop("default_ast"),
            lambda c: c["predicate"]["expected_signature"]["parameters"][0].update(default_ast=4),
            lambda c: c["predicate"]["expected_signature"]["parameters"][0].update(kind=[]),
        ]
        for index, mutate in enumerate(changes):
            with self.subTest(change=index):
                case = self.case(COMPLETE_SOURCE, COMPLETE_SIGNATURE)
                mutate(case)
                self.assertEqual(self.verdict(case), "uncertain")
        case = self.case()
        case["predicate"]["expected"] = 1
        self.assertEqual(self.verdict(case), "uncertain")

    def test_cli_and_existing_output_protection(self):
        cases = [self.case()]
        (self.packet / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        output = self.packet / "reference.json"
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/structural_checker.py"), "--packet", str(self.packet), "--out", str(output)]
        first = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(first.returncode, 0, first.stderr)
        original = output.read_bytes()
        self.assertEqual(json.loads(original)["records"][0]["verdict"], "supported")
        second = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(second.returncode, 2)
        self.assertEqual(output.read_bytes(), original)

    def test_duplicate_ids_abstain(self):
        case = self.case()
        (self.packet / "cases.json").write_text(json.dumps([case, case]), encoding="utf-8")
        output = self.packet / "reference.json"
        run(self.packet, output)
        self.assertEqual([r["verdict"] for r in json.loads(output.read_text())["records"]], ["uncertain", "uncertain"])

    def test_duplicate_json_keys_are_rejected_without_output(self):
        (self.packet / "cases.json").write_text('[{"id":"a","id":"b"}]', encoding="utf-8")
        output = self.packet / "reference.json"
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            run(self.packet, output)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
