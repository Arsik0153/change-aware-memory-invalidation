#!/usr/bin/env python3
"""Exercise independent audit checks with honestly rehashed corruptions."""

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import unittest.mock

HERE = Path(__file__).resolve().parent
# Avoid writing bytecode beside an installed script; all evidence belongs in --out.
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    "independent_replay_audit", HERE / "audit_real_structural_replay.py"
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def save(path, value):
    path.write_bytes(audit.canonical(value) + b"\n")


def write_rows(path, records):
    path.write_bytes(b"".join(audit.canonical(x) + b"\n" for x in records))


def rehash(path):
    manifest = audit.parse((path / "manifest.json").read_bytes())
    manifest["artifact_hashes"] = {
        str(x.relative_to(path)): audit.sha(x.read_bytes())
        for x in path.rglob("*")
        if x.is_file() and x.relative_to(path) != Path("manifest.json")
    }
    save(path / "manifest.json", manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=audit.default_root())
    parser.add_argument(
        "--result", type=Path, default=Path("reports/research-20261104/real-structural-replay-v1")
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Create a new evidence directory; an existing directory is refused.",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    original = (root / args.result).resolve()
    out = args.out.resolve()
    if out.is_relative_to(original):
        parser.error("--out must be outside the frozen result directory")
    out.mkdir(parents=True, exist_ok=False)
    baseline = audit.audit(root, original)
    (out / "report.json").write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
    original_inventory = {
        str(x.relative_to(original)): audit.sha(x.read_bytes())
        for x in original.rglob("*")
        if x.is_file()
    }
    results = []
    controls = out / "tamper_controls"
    controls.mkdir()
    for name in [
        "missing_observation",
        "forged_report_metric",
        "state_inconsistency",
        "forged_reference_verdict",
        "forged_git_source",
    ]:
        target = controls / name
        shutil.copytree(original, target)
        if name == "missing_observation":
            path = target / "observations.jsonl"
            records = audit.rows(path)
            removed = records.pop()
            mutation = {
                "removed_identity": {
                    k: removed[k] for k in ["group_id", "commit", "claim_id", "variant"]
                }
            }
            write_rows(path, records)
            expected = "observation coverage mismatch"
        elif name == "forged_report_metric":
            path = target / "report.json"
            report = audit.parse(path.read_bytes())
            report["variants"]["symbol_anchor"]["actual_validation_calls"] += 1
            save(path, report)
            mutation = {
                "field": "variants.symbol_anchor.actual_validation_calls",
                "from": 8,
                "to": 9,
            }
            expected = "report metric recomputation mismatch"
        elif name == "state_inconsistency":
            path = target / "observations.jsonl"
            records = audit.rows(path)
            row = next(x for x in records if x["state"]["state"] == "stale")
            row["state"]["available"] = True
            mutation = {
                "identity": {k: row[k] for k in ["group_id", "commit", "claim_id", "variant"]},
                "field": "state.available",
                "from": False,
                "to": True,
            }
            write_rows(path, records)
            expected = "state transition mismatch"
        elif name == "forged_reference_verdict":
            path = target / "observations.jsonl"
            records = audit.rows(path)
            row = records[0]
            identity = {k: row[k] for k in ["group_id", "commit", "claim_id"]}
            for x in records:
                if all(x[k] == v for k, v in identity.items()):
                    x["reference"]["verdict"] = "contradicted"
            write_rows(path, records)
            packet = (
                target
                / "packets"
                / identity["group_id"]
                / identity["commit"]
                / identity["claim_id"]
                / "decision.json"
            )
            decision = audit.parse(packet.read_bytes())
            decision["verdict"] = "contradicted"
            save(packet, decision)
            mutation = {
                "identity": identity,
                "field": "reference.verdict",
                "from": "supported",
                "to": "contradicted",
                "all_variant_copies_and_packet_changed": True,
            }
            expected = "reference verdict mismatch"
        else:
            path = next((target / "packets").rglob("subject.raw"))
            path.write_bytes(path.read_bytes() + b"\n# forged packet bytes\n")
            mutation = {"artifact": str(path.relative_to(target)), "appended": "comment"}
            expected = "raw Git source mismatch"
        rehash(target)
        # Assert the mutation is beyond simple hash integrity checks.
        manifest = audit.parse((target / "manifest.json").read_bytes())
        assert all(
            audit.sha((target / name).read_bytes()) == digest
            for name, digest in manifest["artifact_hashes"].items()
        )
        try:
            audit.audit(root, target)
        except ValueError as error:
            message = str(error)
            assert expected in message, (name, message)
            results.append(
                {
                    "control": name,
                    "artifact_hashes_recomputed_and_valid": True,
                    "audit_rejected": True,
                    "reason": message,
                    "mutation": mutation,
                }
            )
        else:
            raise AssertionError("auditor accepted " + name)
    # Check the ternary metric contract in an isolated record: unknown is kept
    # separate even while production availability is true.
    sample = copy.deepcopy(audit.rows(original / "observations.jsonl")[0])
    sample["reference"]["verdict"] = "uncertain"
    sample["state"]["available"] = True
    metric = audit.summarize([sample])
    assert metric["false_available"] == 0 and metric["available_unknown"] == 1
    assert metric["reference_contradicted"] == 0 and metric["reference_unknown"] == 1
    assert metric["false_available_per_contradicted"] is None
    results.append(
        {
            "control": "unknown_is_separate_from_contradicted",
            "passed": True,
            "false_available": metric["false_available"],
            "available_unknown": metric["available_unknown"],
            "false_available_per_contradicted": None,
        }
    )
    # One direct definition remains in every fixture; a separate binding can
    # still make the source unsafe for this bounded independent check.
    import ast

    header = "def target():\n    pass\n"
    hazard_tails = {
        "assignment": "target = 1\n",
        "deletion": "del target\n",
        "import_alias": "import os as target\n",
        "from_import": "from os import name as target\n",
        "star_import": "from os import *\n",
        "loop_target": "for target in ():\n    pass\n",
        "with_target": "with context() as target:\n    pass\n",
        "except_target": "try:\n    pass\nexcept Exception as target:\n    pass\n",
        "match_target": "match value:\n    case target:\n        pass\n",
        "match_mapping_rest": "match value:\n    case {**target}:\n        pass\n",
        "walrus": "if (target := 1):\n    pass\n",
        "class_global": "class Outer:\n    class Inner:\n        global target\n        target = 1\n",
        "class_store_conservative": "class Outer:\n    target = 1\n",
        "class_definition": "class target:\n    pass\n",
        "namespace_mutation": "globals()['target'] = 1\n",
        "evaluated_function_default": "def other(x=exec('target = 1')):\n    pass\n",
        "evaluated_lambda_default": "other = lambda x=exec('target = 1'): x\n",
    }
    for name, tail in hazard_tails.items():
        tree = ast.parse(header + tail)
        assert audit.binding_hazards(tree, "target", tree.body[0]), name
    deferred = ast.parse(
        header
        + "def other():\n    global target\n    target = 1\nother_lambda = lambda: globals()\n"
    )
    assert not audit.binding_hazards(deferred, "target", deferred.body[0])
    results.append(
        {
            "control": "conservative_binding_screen",
            "passed": True,
            "hazard_cases_rejected": sorted(hazard_tails),
            "deferred_function_lambda_bodies_excluded": True,
        }
    )
    # A different authentic claim from the same module has the same source
    # hash. That is insufficient to authorize its review item for this claim.
    protocol = audit.parse((root / audit.PROTOCOL).read_bytes())
    cohort = {
        x["claim"]["claim_id"]: x
        for x in audit.parse((root / protocol["cohort_path"]).read_bytes())
    }
    authentic = audit.authentic_case_ids(
        cohort,
        audit.parse((root / protocol["ai_case_map_path"]).read_bytes()),
        audit.parse((root / protocol["ai_public_cases_path"]).read_bytes()),
    )
    confirmations = audit.rows(root / protocol["confirmations_path"])
    pair = next(
        (a, b)
        for a in cohort
        for b in cohort
        if a != b and cohort[a]["parent_source_sha256"] == cohort[b]["parent_source_sha256"]
    )
    confirmation = copy.deepcopy(next(x for x in confirmations if x["claim_id"] == pair[0]))
    for review in confirmation["reviews"]:
        review["item_id"] = authentic[pair[1]]
    try:
        audit.confirmation_eligible(
            pair[0], confirmation, cohort, authentic, lambda name: (root / name).read_bytes()
        )
    except ValueError as error:
        assert "exact authentic original claim" in str(error)
        results.append(
            {
                "control": "same_module_AI_review_item_swap",
                "passed": True,
                "claim_ids": list(pair),
                "shared_source_sha256": cohort[pair[0]]["parent_source_sha256"],
                "rejected_reason": str(error),
            }
        )
    else:
        raise AssertionError("same-module review item swap accepted")
    # Both installed scripts and ignored staging paths infer the same repo root.
    installed = root / "scripts" / "audit_real_structural_replay.py"
    with unittest.mock.patch.object(audit, "__file__", str(installed)):
        assert audit.default_root() == root
    assert audit.default_root() == root
    results.append(
        {
            "control": "repository_root_discovery",
            "passed": True,
            "installed_script_path": str(installed),
            "staging_script_path": str(HERE / "audit_real_structural_replay.py"),
        }
    )
    # Simulate later local source bytes without editing the shared workspace.
    source = "src/cami/policies.py"
    seal = audit.parse((root / audit.SEAL).read_bytes())
    expected = seal["files"][source]
    original_read = Path.read_bytes

    def changed_read(path):
        if path == root / source:
            return b"# simulated later implementation\n"
        return original_read(path)

    with unittest.mock.patch.object(Path, "read_bytes", changed_read):
        inputs = audit.Inputs(root)
        raw = inputs.read(source, expected)
        assert audit.sha(raw) == expected and inputs.history == [source]
    results.append(
        {
            "control": "historical_source_fallback",
            "passed": True,
            "simulated_current_source_change": source,
            "historical_commit": audit.IMPLEMENTATION_COMMIT,
            "verified_frozen_sha256": expected,
            "shared_workspace_edited": False,
        }
    )
    after_inventory = {
        str(x.relative_to(original)): audit.sha(x.read_bytes())
        for x in original.rglob("*")
        if x.is_file()
    }
    assert after_inventory == original_inventory
    report = {
        "status": "pass",
        "tamper_controls": results,
        "original_artifacts_preserved": True,
        "original_file_count": len(original_inventory),
        "original_manifest_sha256": original_inventory["manifest.json"],
    }
    (out / "tamper_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {"status": "pass", "controls": len(results), "original_artifacts_preserved": True}
        )
    )


if __name__ == "__main__":
    main()
