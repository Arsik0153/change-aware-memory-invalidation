"""Pure protocol negatives for configured stdio checker; never containers/models."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from literal_stdio_worker import canonical, digest, validate_response


class StdioChecks(unittest.TestCase):
    def fixture(self, backend="static", response_format="full"):
        source = {"path": "src/demo.py", "sha256": "a" * 64, "size": 30}
        record = {
            "id": "origin-1",
            "source": source,
            "payload": {
                "type": "source_excerpt_equals",
                "subject": {
                    "language": "python",
                    "node_kind": "function",
                    "path": "src/demo.py",
                    "qualname": "alpha",
                },
                "expected": {
                    "format": "python.definition-prefix/1",
                    "text": "def alpha():\n    return 1\n",
                    "truncated": False,
                },
                "origin_source": source,
                "origin_span": {"first_line": 1, "last_line": 2},
            },
        }
        entry = {
            "id": record["id"],
            "payload": record["payload"],
            "origin_source": source,
            "label": "origin_literal_source_assertion"
            if backend == "static"
            else "validated_literal_source",
            "availability": "unchecked_current" if backend == "static" else "supported",
        }
        value = {
            "schema_version": 1,
            "backend": backend,
            "entries": [entry],
            "withheld": [],
            "selection_budget": {
                "origin_record_bytes": 16384,
                "used_bytes": len(canonical(record)),
                "ranking_before_availability": True,
            },
        }
        arguments = {"query": record["id"], "limit": 1}
        event = {
            "event": "memory_lookup",
            "backend": backend,
            "query_sha256": digest(arguments),
            "error": None,
        }
        result = {
            "content": [{"type": "text", "text": canonical(value).decode()}],
            "isError": False,
        }
        if response_format == "compact":
            full = copy.deepcopy(result)
            entry.pop("origin_source")
            value["response_format"] = "research-memory-compact/1"
            base = {
                "content": [{"type": "text", "text": canonical(value).decode()}],
                "isError": False,
            }
            payload = {
                "format": "research-memory-compact/1",
                "full_result_sha256": digest(full),
                "projection_result_sha256": digest(base),
            }
            value["audit_receipt"] = digest(payload)
            result = {
                "content": [{"type": "text", "text": canonical(value).decode()}],
                "isError": False,
            }
            event.update(
                response_format="compact",
                response_audit={
                    "receipt_sha256": digest(payload),
                    "receipt_payload": payload,
                    "full_result": full,
                    "model_result_sha256": digest(result),
                },
            )
        return [result, record, backend, response_format, [event], arguments]

    def test_both_backends_both_formats(self):
        for backend in ("static", "cami"):
            for response_format in ("full", "compact"):
                with self.subTest(backend=backend, response_format=response_format):
                    self.assertEqual(
                        validate_response(*self.fixture(backend, response_format))["model_calls"], 0
                    )

    def test_opposite_format_rejected(self):
        args = self.fixture(response_format="compact")
        args[3] = "full"
        with self.assertRaisesRegex(ValueError, "format"):
            validate_response(*args)

    def test_lost_expected_source_span_rejected(self):
        for field in ("expected", "origin_source", "origin_span"):
            args = self.fixture()
            value = json.loads(args[0]["content"][0]["text"])
            value["entries"][0]["payload"].pop(field)
            args[0]["content"][0]["text"] = canonical(value).decode()
            with self.assertRaisesRegex(ValueError, "tuple/source/span"):
                validate_response(*args)

    def test_static_cannot_claim_validated(self):
        args = self.fixture()
        value = json.loads(args[0]["content"][0]["text"])
        value["entries"][0]["label"] = "validated_literal_source"
        args[0]["content"][0]["text"] = canonical(value).decode()
        with self.assertRaisesRegex(ValueError, "trust/status"):
            validate_response(*args)

    def test_unmatched_missing_and_duplicate_trace_rejected(self):
        for trace in (
            [],
            [{"event": "memory_lookup", "query_sha256": "wrong"}],
            self.fixture()[4] * 2,
        ):
            args = self.fixture()
            args[4] = trace
            with self.assertRaisesRegex(ValueError, "trace"):
                validate_response(*args)

    def test_forged_receipt_rejected(self):
        args = self.fixture(response_format="compact")
        args[4][0]["response_audit"]["full_result"] = {"fake": True}
        with self.assertRaisesRegex(ValueError, "receipt"):
            validate_response(*args)

    def test_default_plan_uses_no_controller_or_docker(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("verify_literal_containers.py"))],
            capture_output=True,
            check=True,
        )
        self.assertEqual(json.loads(result.stdout)["status"], "plan_only")
        self.assertFalse(json.loads(result.stdout)["writes"])


if __name__ == "__main__":
    unittest.main()
