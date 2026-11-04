"""Tiny authored sources/messages only; no model, Docker or active run scans."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from classify_memory_calls import canonical, classify
from summarize_terminal_staleness import (
    inventory,
    line_boundary_risks,
    load_analyzer,
    verify_terminal,
    crosscheck_backend,
)

ROOT = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "scripts/analyze_opencode_staleness.py").is_file()
)


class StalenessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.origin, self.current = self.root / "origin", self.root / "current"
        self.origin.mkdir()
        self.current.mkdir()
        (self.origin / "m.py").write_text("def a():\n    return 1\n\ndef b():\n    return 0\n")
        (self.current / "m.py").write_text("def a():\n    return 2\n\ndef b():\n    return 0\n")
        self.analyzer = load_analyzer(ROOT / "scripts/analyze_opencode_staleness.py")
        self.records = []
        for name in ("a", "b"):
            _, source_sha, excerpt = self.analyzer.body(self.origin, "m.py", name)
            subject = {
                "language": "python",
                "path": "m.py",
                "qualname": name,
                "node_kind": "function",
            }
            source = {
                "path": "m.py",
                "sha256": source_sha,
                "size": (self.origin / "m.py").stat().st_size,
            }
            self.records.append(
                {
                    "id": name,
                    "source": source,
                    "payload": {"type": "note", "subject": subject, "text": excerpt},
                }
            )
        self.catalog = {"records": self.records}

    def tearDown(self):
        self.temp.cleanup()

    def rows(self, *, returned=("b",), withheld=("a",), after_write=False):
        payload = {
            "backend": "cami",
            "query": "query",
            "catalog_sha256": hashlib.sha256(canonical(self.catalog)).hexdigest(),
            "selected_records": len(returned) + len(withheld),
            "entries": [
                {
                    "id": i,
                    "payload": next(r["payload"] for r in self.records if r["id"] == i),
                    "origin_source": next(r["source"] for r in self.records if r["id"] == i),
                }
                for i in returned
            ],
            "withheld": [
                {
                    "id": i,
                    "kind": next(r["payload"]["type"] for r in self.records if r["id"] == i),
                    "subject": next(r["payload"]["subject"] for r in self.records if r["id"] == i),
                    "reason": "manual_review_required",
                }
                for i in withheld
            ],
        }
        rows = [
            {
                "type": "tool_use",
                "part": {
                    "id": "lookup",
                    "tool": "memory_lookup",
                    "state": {
                        "status": "completed",
                        "output": json.dumps(payload),
                        "time": {"start": 2, "end": 3},
                    },
                },
            }
        ]
        if after_write:
            rows.insert(
                0,
                {
                    "type": "tool_use",
                    "part": {
                        "id": "shell",
                        "tool": "shell",
                        "state": {"time": {"start": 1, "end": 2}},
                    },
                },
            )
        return rows

    def test_returned_unchanged_and_withheld_obsolete_stay_separate(self):
        result = classify(
            self.analyzer, self.rows(), self.catalog, self.origin, self.current, "cami"
        )
        values = {(r["channel"], r["record_id"]): r["assessment"] for r in result["records"]}
        self.assertEqual(values["returned", "b"], "same_literal_excerpt")
        self.assertEqual(values["withheld", "a"], "obsolete_literal_excerpt")
        self.assertTrue(all(r["causal_reliance"] == "not_inferred" for r in result["records"]))

    def test_after_shell_both_channels_unknown(self):
        result = classify(
            self.analyzer,
            self.rows(after_write=True),
            self.catalog,
            self.origin,
            self.current,
            "cami",
        )
        self.assertEqual(
            {r["assessment"] for r in result["records"]}, {"unknown_after_possible_write"}
        )

    def test_unknown_withheld_id_is_preserved_unsupported(self):
        rows = self.rows()
        payload = json.loads(rows[0]["part"]["state"]["output"])
        payload["withheld"][0]["id"] = "unknown"
        rows[0]["part"]["state"]["output"] = json.dumps(payload)
        result = classify(self.analyzer, rows, self.catalog, self.origin, self.current, "cami")
        self.assertEqual(result["unsupported_calls"], 1)
        self.assertIn("unknown", result["memory_calls"][0]["reason"])
        self.assertEqual(result["memory_calls"][0]["reported_withheld_ids"], ["unknown"])
        self.assertEqual(result["records"], [])

    def test_withheld_subject_mismatch_is_not_classified(self):
        rows = self.rows()
        payload = json.loads(rows[0]["part"]["state"]["output"])
        payload["withheld"][0]["subject"] = {"path": "other.py"}
        rows[0]["part"]["state"]["output"] = json.dumps(payload)
        self.assertEqual(
            classify(self.analyzer, rows, self.catalog, self.origin, self.current, "cami")[
                "unsupported_calls"
            ],
            1,
        )

    def test_duplicate_returned_withheld_id_is_unsupported(self):
        result = classify(
            self.analyzer,
            self.rows(returned=("a",), withheld=("a",)),
            self.catalog,
            self.origin,
            self.current,
            "cami",
        )
        self.assertEqual(result["unsupported_calls"], 1)

    def test_typed_records_separate_from_literal_notes(self):
        self.records[0]["payload"] = {
            "type": "symbol_exists",
            "subject": self.records[0]["payload"]["subject"],
            "expected": True,
        }
        result = classify(
            self.analyzer,
            self.rows(returned=("a",), withheld=()),
            self.catalog,
            self.origin,
            self.current,
            "cami",
        )
        self.assertEqual(result["records"][0]["assessment"], "typed_record_not_literal_note")

    def test_exotic_separators_flagged_without_extractor_change(self):
        (self.current / "exotic.py").write_bytes('x="a\u2028b"\rnext=1\n'.encode())
        risks = line_boundary_risks(self.current, inventory(self.current))
        self.assertEqual(risks[0]["exotic_separators"]["LS"], 1)
        self.assertEqual(risks[0]["bare_cr_count"], 1)

    def test_backend_hash_authenticates_full_arguments_not_query_text(self):
        rows = self.rows()
        rows[0]["part"]["state"]["input"] = {"query": "query", "limit": 5}
        result = classify(self.analyzer, rows, self.catalog, self.origin, self.current, "cami")
        catalog_sha = hashlib.sha256(canonical(self.catalog)).hexdigest()
        event = {
            "event": "memory_lookup",
            "backend": "cami",
            "catalog_sha256": catalog_sha,
            "query_sha256": hashlib.sha256(canonical({"query": "query", "limit": 5})).hexdigest(),
            "returned_records": 1,
            "withheld_records": 1,
        }
        path = self.root / "backend.jsonl"
        path.write_text(json.dumps(event) + "\n")
        self.assertEqual(
            crosscheck_backend(path, result, catalog_sha, "cami", rows)["status"], "matched"
        )
        event["query_sha256"] = hashlib.sha256(b"query").hexdigest()
        path.write_text(json.dumps(event) + "\n")
        self.assertTrue(
            crosscheck_backend(path, result, catalog_sha, "cami", rows)["status"].startswith(
                "unsupported"
            )
        )

    def test_terminal_hash_tamper_rejected(self):
        directory = self.root / "trial"
        directory.mkdir()
        (directory / "messages.json").write_text("[]")
        (directory / "terminal.json").write_text(
            json.dumps({"artifact_hashes": {"messages.json": hashlib.sha256(b"[]").hexdigest()}})
        )
        verify_terminal(directory)
        (directory / "messages.json").write_text("[1]")
        with self.assertRaisesRegex(ValueError, "hashes/coverage"):
            verify_terminal(directory)


if __name__ == "__main__":
    unittest.main()
