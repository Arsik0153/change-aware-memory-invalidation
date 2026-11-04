"""Synthetic code-audit probes. No actual reviewer answer or pilot source is read."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import runpy
import sys
import tempfile


sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parent
ROOT = next(parent for parent in BASE.parents if (parent / "pyproject.toml").is_file())
sys.path.insert(0, str(ROOT))
checker = runpy.run_path(str(ROOT / "scripts/structural_checker.py"))
validator = runpy.run_path(str(ROOT / "scripts/validate_ai_review.py"))


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


results = {
    "scope": "Synthetic code/protocol audit only. No actual review answers read.",
    "inputs": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
               for name in ("scripts/structural_checker.py", "scripts/validate_ai_review.py",
                            "scripts/analyze_ai_pilot.py", "examples/ai_review_pilot/protocol.json")},
}
with tempfile.TemporaryDirectory(prefix="synthetic-probes-", dir=BASE) as temporary:
    packet = Path(temporary)
    source = (
        "def f():\n    pass\n\n"
        "class Outer:\n    class Inner:\n        global f\n        f = 0\n"
    ).encode()
    (packet / "module.py").write_bytes(source)
    case = {
        "id": "synthetic-nested-class-global", "kind": "symbol_exists",
        "subject": {"path": "module.py", "qualname": "f", "node_kind": "function"},
        "predicate": {"type": "symbol_exists", "expected": True},
        "text": "module.py contains the exact top-level function definition f.",
        "scope": "Unique unconditional top-level function; target rebinding causes uncertainty.",
        "source_path": "module.py", "source_sha256": hashlib.sha256(source).hexdigest(),
    }
    record = checker["check_case"](packet, case)
    results["nested_class_global"] = {
        "source": source.decode(), "rubric_expected": "uncertain",
        "checker_actual": record["verdict"], "reason": record["reason"],
        "facts": record["facts"], "mismatch_reproduced": record["verdict"] != "uncertain",
        "explanation": "The nested class declares global f and assigns f. Class traversal skips this global declaration.",
    }

    # The following JSON is a synthetic validator fixture, not an AI answer.
    simple = b"def f():\n    pass\n"
    (packet / "module.py").write_bytes(simple)
    case["id"] = "synthetic-format-only"
    case["source_sha256"] = hashlib.sha256(simple).hexdigest()
    write(packet / "cases.json", [case])
    packet_hash = validator["compute_packet_identity"](packet)
    fixture = {
        "schema_version": 1, "reviewer_kind": "ai_reviewer", "human": False,
        "provider": "synthetic-fixture", "model": "synthetic-test-not-a-model-response",
        "reasoning_effort": "not-applicable", "agent_task": "/synthetic/validator-fixture",
        "packet_sha256": packet_hash, "identity_basis": "declared_invocation",
        "independence_disclosure": validator["DISCLOSURE"],
        "items": [{"id": case["id"], "source_sha256": case["source_sha256"],
                   "verdict": "supported", "extracted_facts": {"placeholder": True},
                   "reasoning": "Synthetic fixture tests format enforcement only.",
                   "scope_notes": "This is not a reviewer judgment.",
                   "evidence": [{"source_path": "module.py", "available": True,
                                 "line_start": 1, "line_end": 2}]}],
    }
    write(packet / "synthetic-format-fixture.json", fixture)
    audit = validator["audit_review"](packet, packet / "synthetic-format-fixture.json")
    results["required_fact_and_methodology_contract"] = {
        "format_status": audit["status"], "extracted_facts": fixture["items"][0]["extracted_facts"],
        "methodology_sidecar_present": (packet / "methodology.json").exists(),
        "mandatory_rubric_fact_fields_present": False,
        "interpretation": "Format pass does not establish rubric or methodology compliance.",
    }

write(BASE / "synthetic_audit_results.json", results)
print(json.dumps(results, indent=2))
