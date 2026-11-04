"""Pure controller/worker policy checks; no containers, models, or core construction."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "src/cami").is_dir())
sys.path.insert(0, str(HERE))
from memory_seed_schema import literal_catalog, policy_for, validate_policy  # noqa:E402
from preparation_worker import preparation_commands  # noqa:E402
import study_runtime as runtime  # noqa:E402
import study_schema as schema  # noqa:E402


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n"
    )


class LiteralControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        self.policy = {
            "schema_version": 2,
            "seed": "literal-seed.json",
            "generator": "seed_source_literals_v2.py",
            "helpers": ["literal_source.py"],
            "payload_kind": "source_excerpt_equals",
            "extractor_format": "python.definition-prefix/1",
        }
        self.subject = {
            "language": "python",
            "path": "src/pkg/m.py",
            "qualname": "alpha",
            "node_kind": "function",
        }
        self.origin = {"path": "src/pkg/m.py", "sha256": "a" * 64, "size": 25}
        self.seed = {
            "schema_version": 2,
            "source_roots": ["src/pkg"],
            "excluded_paths": [],
            "records": [
                {
                    "id": "alpha",
                    "kind": "source_excerpt_equals",
                    "selector": "src/pkg/m.py:alpha",
                    "subject": self.subject,
                    "expected": {
                        "format": "python.definition-prefix/1",
                        "text": "def alpha(): return 1\n",
                        "truncated": False,
                    },
                    "origin_source": self.origin,
                    "origin_span": {"first_line": 1, "last_line": 1},
                }
            ],
        }
        save(self.bundle / self.policy["seed"], self.seed)
        self.study = {
            "bundle_path": str(self.bundle),
            "normalized": {
                "seed": self.policy["seed"],
                "source_roots": ["src/pkg"],
                "memory_source": self.policy,
            },
        }
        self.memory = self.root / "memory"
        save(self.memory / "seed/seed-spec.json", self.seed)
        self.catalog = literal_catalog(self.seed)
        self.binding = {
            "backend": "static",
            "repo": "/workspace",
            "catalog_path": "/memory/prepared/catalog.json",
            "state_home": None,
            "catalog_sha256": runtime.hashlib.sha256(
                runtime.json.dumps(
                    self.catalog, sort_keys=True, ensure_ascii=True, separators=(",", ":")
                ).encode()
            ).hexdigest(),
        }
        save(self.memory / "prepared/catalog.json", self.catalog)
        save(self.memory / "prepared/binding.json", self.binding)

    def tearDown(self):
        self.temp.cleanup()

    def rehash_catalog(self):
        save(self.memory / "prepared/catalog.json", self.catalog)
        self.binding["catalog_sha256"] = hashlib.sha256(
            json.dumps(
                self.catalog, sort_keys=True, ensure_ascii=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        save(self.memory / "prepared/binding.json", self.binding)

    def test_schema2_exact_catalog_passes(self):
        hashes = runtime.verify_memory(self.study, self.memory, "static")
        self.assertEqual(
            set(hashes), {"seed/seed-spec.json", "prepared/catalog.json", "prepared/binding.json"}
        )

    def test_rehashed_expected_span_source_and_kind_tamper_rejected(self):
        for field in ["expected", "span", "source", "kind"]:
            with self.subTest(field=field):
                self.catalog = literal_catalog(self.seed)
                payload = self.catalog["records"][0]["payload"]
                if field == "expected":
                    payload["expected"] = dict(payload["expected"], text="forged")
                elif field == "span":
                    payload["origin_span"] = {"first_line": 2, "last_line": 2}
                elif field == "source":
                    payload["origin_source"] = dict(payload["origin_source"], sha256="b" * 64)
                else:
                    payload["type"] = "note"
                self.rehash_catalog()
                with self.assertRaisesRegex(ValueError, "schema2 catalog differs"):
                    runtime.verify_memory(self.study, self.memory, "static")

    def test_catalog2_does_not_drop_origin_source_or_span(self):
        for field in ["origin_source", "origin_span"]:
            catalog = literal_catalog(self.seed)
            catalog["records"][0]["payload"].pop(field)
            self.catalog = catalog
            self.rehash_catalog()
            with self.assertRaises(ValueError):
                runtime.verify_memory(self.study, self.memory, "static")

    def test_immutable_hash_guard_even_semantic_equivalence(self):
        before = runtime.verify_memory(self.study, self.memory, "static")
        with (self.memory / "prepared/catalog.json").open("a") as stream:
            stream.write("\n")
        with self.assertRaisesRegex(ValueError, "immutable memory"):
            runtime.verify_memory(self.study, self.memory, "static", before)

    def test_cami_mapping_exact_ids(self):
        self.binding.update(backend="cami", state_home="/memory/cami-state", mapping={})
        save(self.memory / "prepared/binding.json", self.binding)
        with self.assertRaisesRegex(ValueError, "mapping"):
            runtime.verify_memory(self.study, self.memory, "cami")
        self.binding["mapping"] = {"alpha": {"memory_id": "c" * 64, "revision": 1}}
        save(self.memory / "prepared/binding.json", self.binding)
        runtime.verify_memory(self.study, self.memory, "cami")

    def test_schema2_seed_rejects_manual_fields_and_implicit_origin_index(self):
        for field, value in [
            ("text", "manual"),
            ("note_key", "manual"),
            ("expected", {"format": "unknown", "text": "a", "truncated": False}),
        ]:
            changed = copy.deepcopy(self.seed)
            changed["records"][0][field] = value
            with self.assertRaises(ValueError):
                literal_catalog(changed)
        changed = copy.deepcopy(self.seed)
        changed["records"][0]["origin_source"]["index"] = {}
        with self.assertRaises(ValueError):
            literal_catalog(changed)

    def test_policy2_requires_explicit_versioned_helper(self):
        changed = dict(self.policy, helpers=[])
        with self.assertRaises(ValueError):
            validate_policy(changed)
        changed = dict(self.policy, generator="../source.py")
        with self.assertRaises(ValueError):
            validate_policy(changed)
        self.assertEqual(policy_for({"seed": "old.json"})["schema_version"], 1)

    def test_worker2_safe_import_paths_and_exact_commands(self):
        commands, environments = preparation_commands(
            "cami", ["src/pkg"], 2, {"PYTHONPATH": "/workspace/src", "PYTHONSAFEPATH": "0"}
        )
        self.assertEqual(commands[0][1], "/opt/literal-generator/seed_source_literals_v2.py")
        self.assertEqual(commands[1][-2:], ["--state-home", "/memory/cami-state"])
        env, adapter_env = environments
        self.assertNotIn("/workspace", env["PYTHONPATH"])
        self.assertEqual(env["PYTHONSAFEPATH"], "1")
        self.assertIn("/opt/literal-generator", env["PYTHONPATH"])
        self.assertIn("/opt/memory-adapter", env["PYTHONPATH"])
        self.assertEqual(
            adapter_env["PYTHONPATH"], "/opt/memory-adapter:/opt/cami-src:/opt/cami-deps"
        )
        self.assertNotIn("/opt/literal-generator", adapter_env["PYTHONPATH"])

    def test_legacy_worker_unchanged_generator_route(self):
        commands, environments = preparation_commands("static", ["src/pkg"])
        self.assertEqual(commands[0][1], "/opt/seed_source_notes.py")
        self.assertNotIn("--state-home", commands[1])
        self.assertNotIn("/opt/literal-generator", environments[0]["PYTHONPATH"])
        self.assertEqual(environments[0], environments[1])
        self.assertEqual(environments[0]["PYTHONSAFEPATH"], "1")

    def test_schema2_mounts_only_readonly_generator_and_helper(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        # Use a separate initially empty memory directory; stop before any container.
        memory = self.root / "empty-memory"
        memory.mkdir()
        captured = {}

        def stop(study, mounts, argv, out, **kwargs):
            captured.update(mounts=mounts, argv=argv)
            raise RuntimeError("authored stop before container")

        self.study.update(cami_source=str(self.root / "src"), adapter=str(self.root / "adapter"))
        with (
            patch.object(runtime, "container", side_effect=stop),
            patch.object(runtime, "chown"),
            self.assertRaisesRegex(RuntimeError, "authored stop"),
        ):
            runtime.origin_memory(self.study, workspace, memory, self.root / "out", "static")
        mounts = {guest: (host, ro) for host, guest, ro in captured["mounts"]}
        self.assertEqual(
            mounts["/opt/literal-generator/seed_source_literals_v2.py"],
            (self.bundle / self.policy["generator"], True),
        )
        self.assertEqual(
            mounts["/opt/literal-generator/literal_source.py"],
            (self.bundle / "literal_source.py", True),
        )
        self.assertNotIn("/opt/seed_source_notes.py", mounts)
        self.assertEqual(captured["argv"][captured["argv"].index("--seed-schema-version") + 1], "2")

    def test_original_dev_normalization_identical_to_format_stage(self):
        original = ROOT / "examples/opencode_benchmark_development_v1"
        expected = json.loads((HERE / "fixtures/legacy-normalized-development.json").read_bytes())
        self.assertEqual(schema.normalize(original, "development"), expected)

    def test_new_devbundle_preserves_original_assets_and_explicitly_selects329(self):
        bundle = ROOT / "examples/opencode_benchmark_development_v2"
        data = schema.normalize(bundle, "development")
        manifest = json.loads((HERE / "fixtures/devbundle-v2-manifest.json").read_bytes())
        for path, expected in manifest["original_assets_copied_unchanged"].items():
            self.assertEqual(hashlib.sha256((bundle / path).read_bytes()).hexdigest(), expected)
        self.assertEqual(len(json.loads((bundle / data["seed"]).read_bytes())["records"]), 329)
        self.assertEqual(data["memory_source"]["schema_version"], 2)
        self.assertIn("literal_source.py", data["asset_hashes"])
        self.assertNotEqual(data["seed"], "memory-origin/seed-spec.json")


if __name__ == "__main__":
    unittest.main()
