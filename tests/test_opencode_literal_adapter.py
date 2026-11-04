"""Fast stdlib/fake-core contracts only. Real ProductMemory checks are separate."""

from __future__ import annotations

import builtins
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'integrations/opencode'))

from compact_response import compact_result  # noqa: E402
from memory_adapter import TOOL, serve  # noqa: E402
from literal_catalog import catalog_from_seed2, reauthenticate  # noqa: E402
from literal_source import FORMAT, UnsupportedSource, literal, prepare_module  # noqa: E402
import memory_backend as backend  # noqa: E402
from seed_source_literals_v2 import build  # noqa: E402



class Value:
    def __init__(self, value):
        self.value = value

    def model_dump(self, mode):
        return copy.deepcopy(self.value)


class LiteralAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        (self.repo / "src/pkg").mkdir(parents=True)
        (self.repo / "src/pkg/m.py").write_text(
            "def alpha():\n    return 1\n\ndef beta():\n    return 2\n"
        )
        self.seed, _ = build(self.repo, ["src/pkg"])
        self.spec = self.root / "seed.json"
        backend.save(self.spec, self.seed)

    def tearDown(self):
        self.temp.cleanup()

    def fake_core(self, *, forged=False):
        seed = self.seed
        repo = self.repo
        state = SimpleNamespace(requests=[], records=[], constructors=0, available=True)
        index = {"index": "authored-only"}

        class Input:
            def __init__(self, **kwargs):
                if set(kwargs) != {"kind", "query", "context", "request_id"}:
                    raise AssertionError("caller supplied forbidden registration data")
                self.__dict__.update(kwargs)
                state.requests.append(kwargs)

        class Service:
            def __init__(self, *args):
                state.constructors += 1

            def context_many(self, selectors):
                contexts = []
                for selector in selectors:
                    (item,) = [r for r in seed["records"] if r["selector"] == selector]
                    source = dict(item["origin_source"], index=index)
                    expected = item["expected"]
                    certificate = {
                        "status": "ready",
                        "format": FORMAT,
                        "span": item["origin_span"],
                        "prefix_characters": len(expected["text"]),
                        "prefix_sha256": hashlib.sha256(expected["text"].encode()).hexdigest(),
                        "truncated": expected["truncated"],
                    }
                    contexts.append(
                        SimpleNamespace(
                            code=[
                                SimpleNamespace(
                                    subject=Value(item["subject"]),
                                    source=Value(source),
                                    ambiguous=False,
                                    identity_uncertain=False,
                                    python_excerpt=Value(certificate),
                                )
                            ]
                        )
                    )
                return tuple(contexts)

            def remember_batch(self, requests):
                receipts = []
                for request in requests:
                    path, qualname = request.query.split(":", 1)
                    raw = (repo / path).read_bytes()
                    kind, expected, span = literal(prepare_module(raw), qualname)
                    if forged:
                        expected = dict(expected, text="forged server tuple")
                    payload = {
                        "type": "source_excerpt_equals",
                        "subject": request.context.code[0].subject.model_dump("json"),
                        "expected": expected,
                        "origin_source": dict(request.context.code[0].source.model_dump("json")),
                        "origin_span": span,
                    }
                    memory_id = hashlib.sha256(request.query.encode()).hexdigest()
                    state.records.append(
                        SimpleNamespace(memory_id=memory_id, revision=1, payload=Value(payload))
                    )
                    receipts.append(SimpleNamespace(memory_id=memory_id, revision=1))
                return tuple(receipts)

            def refresh(self):
                return SimpleNamespace(
                    index=SimpleNamespace(snapshot_id="a" * 64),
                    memory_generation_id="b" * 64,
                    states=[
                        SimpleNamespace(record=record, state=SimpleNamespace(type="checked"))
                        for record in state.records
                    ],
                )

        service = ModuleType("cami.product.service")
        service.ProductMemory = Service
        models = ModuleType("cami.product.memory.models")
        models.RememberInput = Input
        validation = ModuleType("cami.product.memory.validation")
        validation.availability = (
            lambda item: SimpleNamespace()
            if state.available
            else SimpleNamespace(reason="contradicted", required_action="revalidate")
        )
        return state, {
            "cami.product.service": service,
            "cami.product.memory.models": models,
            "cami.product.memory.validation": validation,
        }

    def test_new_tool_description_states_literal_boundary_common_to_both_arms(self):
        description = TOOL["description"]
        self.assertIn("prefix and truncation flag", description)
        self.assertIn("not behavior", description)
        self.assertIn("native tools for missing code or context", description)
        self.assertNotIn("Native code search/read tools remain necessary", description)

    def test_source_files_symlinks_special_and_oversize_are_excluded_without_read(self):
        package = self.repo / "src/pkg"
        (package / "link.py").symlink_to(package / "m.py")
        os.mkfifo(package / "pipe.py")
        with (package / "large.py").open("wb") as stream:
            stream.truncate(3 * 1024 * 1024)
        seed, metrics = build(self.repo, ["src/pkg"])
        self.assertEqual(len(seed["records"]), 2)
        self.assertEqual(
            {r["path"] for r in metrics["excluded"]},
            {"src/pkg/link.py", "src/pkg/pipe.py", "src/pkg/large.py"},
        )

    def test_static_is_stdlib_only_and_unchecked(self):
        original = builtins.__import__

        def denied(name, *args, **kwargs):
            if name == "cami" or name.startswith("cami."):
                raise AssertionError("static imported CAMI")
            return original(name, *args, **kwargs)

        with patch("builtins.__import__", denied):
            binding = backend.prepare(
                "static", self.repo, self.root / "static", spec_path=self.spec
            )
            result, _ = backend.Backend(self.root / "static/binding.json").lookup("alpha")
        self.assertEqual(binding["schema_version"], 1)
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["entries"][0]["availability"], "unchecked_current")
        self.assertEqual(result["entries"][0]["label"], "origin_literal_source_assertion")

    def test_both_arms_identical_catalog_and_server_minted_registration(self):
        backend.prepare("static", self.repo, self.root / "static", spec_path=self.spec)
        state, modules = self.fake_core()
        with patch.dict(sys.modules, modules):
            backend.prepare(
                "cami",
                self.repo,
                self.root / "cami",
                spec_path=self.spec,
                state_home=self.root / "state",
            )
            result, _ = backend.Backend(self.root / "cami/binding.json").lookup("alpha")
        self.assertEqual(
            (self.root / "static/catalog.json").read_bytes(),
            (self.root / "cami/catalog.json").read_bytes(),
        )
        self.assertEqual(len(state.requests), 2)
        self.assertTrue(
            all(set(r) == {"kind", "query", "context", "request_id"} for r in state.requests)
        )
        self.assertEqual(result["entries"][0]["label"], "validated_literal_source")

    def test_derived_payload_mismatch_rejected_after_registration(self):
        _, modules = self.fake_core(forged=True)
        with (
            patch.dict(sys.modules, modules),
            self.assertRaisesRegex(ValueError, "registered semantic payload mismatch"),
        ):
            backend.prepare(
                "cami",
                self.repo,
                self.root / "forged",
                spec_path=self.spec,
                state_home=self.root / "state",
            )

    def test_tampered_seed_fails_before_core_construction(self):
        changed = copy.deepcopy(self.seed)
        changed["records"][0]["expected"]["text"] = "forged"
        backend.save(self.spec, changed)
        state, modules = self.fake_core()
        with (
            patch.dict(sys.modules, modules),
            self.assertRaisesRegex(ValueError, "tuple/span/subject"),
        ):
            backend.prepare(
                "cami",
                self.repo,
                self.root / "tamper",
                spec_path=self.spec,
                state_home=self.root / "state",
            )
        self.assertEqual(state.constructors, 0)
        self.assertEqual(state.requests, [])

    def test_withheld_has_no_historical_payload_and_no_replacement(self):
        state, modules = self.fake_core()
        with patch.dict(sys.modules, modules):
            backend.prepare(
                "cami",
                self.repo,
                self.root / "cami",
                spec_path=self.spec,
                state_home=self.root / "state",
            )
            state.available = False
            result, _ = backend.Backend(self.root / "cami/binding.json").lookup("alpha", 1)
        self.assertEqual(result["entries"], [])
        self.assertEqual(len(result["withheld"]), 1)
        self.assertNotIn("payload", result["withheld"][0])
        self.assertNotIn("expected", result["withheld"][0])
        self.assertEqual(result["selected_records"], 1)

    def test_only_origin_index_is_normalized(self):
        payload = catalog_from_seed2(self.seed)["records"][0]["payload"]
        with_index = copy.deepcopy(payload)
        with_index["origin_source"]["index"] = {"private": "origin-index"}
        self.assertEqual(backend.plain_payload(Value(with_index)), payload)
        self.assertIn("index", with_index["origin_source"])

    def test_compact_keeps_new_expected_source_and_span(self):
        backend.prepare("static", self.repo, self.root / "static", spec_path=self.spec)
        value, _ = backend.Backend(self.root / "static/binding.json").lookup("alpha")
        result, _ = compact_result(
            {
                "content": [{"type": "text", "text": backend.canonical(value).decode()}],
                "isError": False,
            }
        )
        compact = json.loads(result["content"][0]["text"])
        self.assertEqual(compact["entries"][0]["payload"], value["entries"][0]["payload"])
        self.assertEqual(compact["entries"][0]["label"], "origin_literal_source_assertion")

    def test_generator_and_reauthentication_prepare_once_per_module(self):
        import seed_source_literals_v2 as generator
        import literal_catalog

        with patch.object(generator, "prepare_module", wraps=prepare_module) as prepared:
            seed, _ = generator.build(self.repo, ["src/pkg"])
            self.assertEqual(prepared.call_count, 1)
        with patch.object(literal_catalog, "prepare_module", wraps=prepare_module) as prepared:
            reauthenticate(self.repo, seed, seed=True)
            self.assertEqual(prepared.call_count, 1)

    def test_source_scope_same_direct_public_candidates(self):
        path = self.repo / "src/pkg/m.py"
        path.write_text(
            "def public():\n    def nested(): pass\n    return nested\ndef _private(): pass\nclass C:\n    def __init__(self): pass\n    def __call__(self): pass\n    def _private(self): pass\n    def method(self): pass\n"
        )
        seed, _ = build(self.repo, ["src/pkg"])
        self.assertEqual(
            {r["subject"]["qualname"] for r in seed["records"]},
            {"public", "C.__init__", "C.__call__", "C.method"},
        )
        self.assertTrue(all("note_key" not in r and "text" not in r for r in seed["records"]))

    def test_physical_line_endings_and_decorators(self):
        for newline in ["\n", "\r\n", "\r"]:
            text = newline.join(
                ["@decorator(", '    "x"', ")", "async def f():", '    return "é😀" # ending', ""]
            )
            _, expected, span = literal(prepare_module(text.encode()), "f")
            self.assertEqual(expected["text"], text)
            self.assertFalse(expected["truncated"])
            self.assertEqual(span, {"first_line": 1, "last_line": 5})

    def test_parenthesized_decorator_starts_at_lexical_at(self):
        for newline in ["\n", "\r\n", "\r"]:
            text = newline.join(["@(", "    decorator", ")", "def f():", "    return 1", ""])
            module = prepare_module(text.encode())
            self.assertGreater(module.definitions["f"][0][1].decorator_list[0].lineno, 1)
            _, expected, span = literal(module, "f")
            self.assertEqual(expected["text"], text)
            self.assertEqual(span["first_line"], 1)
            changed = text.replace("@(", "@ (")
            self.assertNotEqual(literal(prepare_module(changed.encode()), "f")[1], expected)

    def test_decorator_comments_matrix_and_at_strings_do_not_confuse_opening(self):
        text = '# @not_a_decorator\nvalue = "@fake"\n@(\n    decorator(left @ right)  # inner matrix operator\n)\n# interstitial comment\n@other("@string")\ndef f():\n    return 1\n'
        _, expected, span = literal(prepare_module(text.encode()), "f")
        self.assertEqual(span["first_line"], 3)
        self.assertEqual(expected["text"], "".join(text.splitlines(keepends=True)[2:]))

    def test_class_decorator_chain_does_not_leak_into_method(self):
        text = '@(\n decorator\n)\nclass C:\n    @other\n    def method(self): return "@string"\n'
        _, expected, span = literal(prepare_module(text.encode()), "C.method")
        self.assertEqual(span["first_line"], 5)
        self.assertEqual(expected["text"], '    @other\n    def method(self): return "@string"\n')

    def test_exotic_separators_are_characters_not_physical_lines(self):
        text = 'def f():\n    """a\v\f\x85\u2028\u2029b"""\n    return 1\n'
        _, expected, _ = literal(prepare_module(text.encode()), "f")
        self.assertEqual(expected["text"], text)

    def test_exact_unicode_prefix_and_truncation_boundaries(self):
        for length in [2399, 2400, 2401]:
            prefix, suffix = 'def f(): return "', '"\n'
            text = prefix + "😀" * (length - len(prefix) - len(suffix)) + suffix
            _, expected, _ = literal(prepare_module(text.encode()), "f")
            self.assertEqual(expected["text"], text[:2400])
            self.assertEqual(expected["truncated"], length > 2400)

    def test_bom_and_non_utf8_cookie_are_unsupported(self):
        for raw in [
            b"\xef\xbb\xbfdef f(): pass\n",
            b"# coding: latin1\ndef f(): pass\n",
            b"# coding: latin1\rdef f(): pass\r",
            b'def f(): return "\xff"\n',
        ]:
            with self.assertRaises(UnsupportedSource):
                prepare_module(raw)

    def test_new_schema_never_converts_manual_notes(self):
        changed = copy.deepcopy(self.seed)
        changed["records"][0]["kind"] = "note"
        with self.assertRaisesRegex(ValueError, "no automatic"):
            catalog_from_seed2(changed)
        changed = copy.deepcopy(self.seed)
        changed["records"][0]["text"] = "manual"
        with self.assertRaisesRegex(ValueError, "forbids manual"):
            catalog_from_seed2(changed)

    def test_origin_span_and_truncated_are_frozen_comparison_data(self):
        for key in ["span", "truncated"]:
            changed = copy.deepcopy(self.seed)
            if key == "span":
                changed["records"][0]["origin_span"]["last_line"] += 1
            else:
                changed["records"][0]["expected"]["truncated"] = True
            with self.assertRaises(ValueError):
                reauthenticate(self.repo, changed, seed=True)

    def test_literal_content_query_shared_by_both_arms_with_exact_selector_priority(self):
        (self.repo / "src/pkg/m.py").write_text(
            'def alpha():\n    return "quokka"\n\ndef beta():\n    return "alpha"\n'
        )
        self.seed, _ = build(self.repo, ["src/pkg"])
        backend.save(self.spec, self.seed)
        backend.prepare("static", self.repo, self.root / "static", spec_path=self.spec)
        _, modules = self.fake_core()
        with patch.dict(sys.modules, modules):
            backend.prepare(
                "cami",
                self.repo,
                self.root / "cami",
                spec_path=self.spec,
                state_home=self.root / "state",
            )
            outputs = [
                backend.Backend(self.root / name / "binding.json").lookup("quokka")[0]
                for name in ("static", "cami")
            ]
        alpha = next(r["id"] for r in self.seed["records"] if r["subject"]["qualname"] == "alpha")
        self.assertEqual(
            [[r["id"] for r in result["entries"]] for result in outputs], [[alpha], [alpha]]
        )
        selected, _ = backend.rank(catalog_from_seed2(self.seed), "src/pkg/m.py:alpha", 2)
        self.assertEqual(selected[0]["id"], alpha)

    def test_truncation_false_tamper_with_same_2400_prefix_rejected(self):
        prefix, suffix = 'def alpha(): return "', '"\n'
        (self.repo / "src/pkg/m.py").write_text(
            prefix + "x" * (2401 - len(prefix) - len(suffix)) + suffix
        )
        seed, _ = build(self.repo, ["src/pkg"])
        self.assertTrue(seed["records"][0]["expected"]["truncated"])
        seed["records"][0]["expected"]["truncated"] = False
        with self.assertRaisesRegex(ValueError, "tuple/span/subject"):
            reauthenticate(self.repo, seed, seed=True)

    def test_schema2_catalog_input_is_reauthenticated(self):
        catalog = catalog_from_seed2(self.seed)
        path = self.root / "catalog.json"
        backend.save(path, catalog)
        backend.prepare("static", self.repo, self.root / "from-catalog", catalog_path=path)
        self.assertEqual(backend.load(self.root / "from-catalog/catalog.json"), catalog)
        catalog["records"][0]["source"]["sha256"] = "a" * 64
        backend.save(path, catalog)
        with self.assertRaisesRegex(ValueError, "origin source bytes differ"):
            backend.prepare("static", self.repo, self.root / "bad-catalog", catalog_path=path)

    def test_root_and_exclusion_policy_fail_closed_before_registration(self):
        for field, value in [("source_roots", ["other"]), ("excluded_paths", ["src/pkg"])]:
            changed = copy.deepcopy(self.seed)
            changed[field] = value
            with self.assertRaises(ValueError):
                reauthenticate(self.repo, changed, seed=True)

    def test_shared_origin_budget_remains_16k_before_availability(self):
        catalog = catalog_from_seed2(self.seed)
        first = catalog["records"][0]
        first["payload"]["expected"] = {"format": FORMAT, "text": "😀" * 2400, "truncated": True}
        chosen, matched = backend.rank(catalog, first["id"], 20)
        self.assertEqual(chosen, [])
        self.assertGreaterEqual(matched, 1)
        self.assertEqual(len(backend.canonical(first)) > 16384, True)

    def test_stdio_full_default_and_compact_preserve_literal_payload(self):
        backend.prepare("static", self.repo, self.root / "static", spec_path=self.spec)
        for selected in ("full", "compact"):
            requests = [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "authored"},
                    },
                },
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "memory_lookup",
                        "arguments": {"query": "alpha", "limit": 1},
                    },
                },
            ]
            incoming = io.BytesIO(b"".join(backend.canonical(row) + b"\n" for row in requests))
            outgoing = io.BytesIO()
            kwargs = {} if selected == "full" else {"response_format": "compact"}
            serve(
                self.root / "static/binding.json",
                self.root / (selected + "-trace.jsonl"),
                incoming,
                outgoing,
                **kwargs,
            )
            result = json.loads(outgoing.getvalue().splitlines()[-1])["result"]
            value = json.loads(result["content"][0]["text"])
            self.assertEqual(value["schema_version"], 1)
            self.assertEqual(
                value["entries"][0]["payload"],
                catalog_from_seed2(self.seed)["records"][0]["payload"],
            )
            self.assertEqual("response_format" in value, selected == "compact")
            self.assertEqual(value["entries"][0]["availability"], "unchecked_current")

    def test_schema1_note_result_matches_legacy_backend(self):
        spec = {
            "schema_version": 1,
            "source_roots": ["src/pkg"],
            "excluded_paths": [],
            "records": [
                {
                    "id": "manual",
                    "kind": "note",
                    "selector": "src/pkg/m.py:alpha",
                    "subject": self.seed["records"][0]["subject"],
                    "note_key": "unchanged-old-key",
                    "text": "historical manual note",
                }
            ],
        }
        old_spec = self.root / "old.json"
        backend.save(old_spec, spec)
        backend.prepare("static", self.repo, self.root / "new-oldpath", spec_path=old_spec)
        b, _ = backend.Backend(self.root / "new-oldpath/binding.json").lookup("manual")
        golden = json.loads(
            (Path(__file__).parent / "fixtures/legacy_schema1_full_response.json").read_bytes()
        )
        self.assertEqual(backend.canonical(b), backend.canonical(golden))
        self.assertEqual(b["entries"][0]["payload"]["type"], "note")


if __name__ == "__main__":
    unittest.main()
