#!/usr/bin/env python3
"""Rehashed result forgeries against the independent stdlib first-parent auditor."""

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "first_parent_independent_audit", HERE / "audit_real_first_parent_replay.py"
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def save(path, value):
    path.write_bytes(audit.canonical(value) + b"\n")


def write_rows(path, records):
    path.write_bytes(b"".join(audit.canonical(row) + b"\n" for row in records))


def rehash(target):
    manifest = audit.parse((target / "manifest.json").read_bytes())
    manifest["artifact_hashes"] = {
        str(p.relative_to(target)): audit.sha(p.read_bytes())
        for p in target.rglob("*")
        if p.is_file() and p.name != "manifest.json"
    }
    save(target / "manifest.json", manifest)
    assert all(
        audit.sha((target / name).read_bytes()) == expected
        for name, expected in manifest["artifact_hashes"].items()
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=audit.default_root())
    parser.add_argument(
        "--result", type=Path, default=Path("reports/research-20261104/real-first-parent-replay-v1")
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    original = (root / args.result).resolve()
    out = args.out.resolve()
    assert not out.is_relative_to(original)
    out.mkdir(parents=True, exist_ok=False)
    original_hashes = {
        str(p.relative_to(original)): audit.sha(p.read_bytes())
        for p in original.rglob("*")
        if p.is_file()
    }
    baseline = audit.audit(root, original)
    save(out / "baseline.json", baseline)
    checks = []
    controls = [
        "forged_full_parent_order",
        "forged_consistent_merge_flag",
        "old_overlap_semantic_change",
        "omitted_added_observation",
        "forged_new_summary",
        "forged_reference_facts",
        "forged_state_availability",
        "forged_cost_execution_count",
        "forged_source_packet",
        "forged_historical_source_inventory",
    ]
    for name in controls:
        with tempfile.TemporaryDirectory(prefix=name + "-", dir=out) as temporary:
            target = Path(temporary) / "result"
            shutil.copytree(original, target)
            mutation = {"control": name}
            if name == "forged_full_parent_order":
                p = target / "topology.json"
                topology = audit.parse(p.read_bytes())
                gid, commit, node = next(
                    (g, c, n)
                    for g, steps in topology.items()
                    for c, n in steps.items()
                    if len(n["parent_commits"]) > 1
                )
                node["parent_commits"] = list(reversed(node["parent_commits"]))
                node["first_parent_commit"] = node["parent_commits"][0]
                save(p, topology)
                mutation.update(group_id=gid, commit=commit)
                expected = "topology artifact mismatch"
            elif name == "forged_consistent_merge_flag":
                p = target / "topology.json"
                topology = audit.parse(p.read_bytes())
                gid, commit, node = next(
                    (g, c, n)
                    for g, steps in topology.items()
                    for c, n in steps.items()
                    if n["is_merge"]
                )
                node["is_merge"] = False
                save(p, topology)
                changes = target / "changes" / gid / (commit + ".json")
                change = audit.parse(changes.read_bytes())
                change["is_merge"] = False
                save(changes, change)
                records = audit.rows(target / "observations.jsonl")
                for row in records:
                    if row["group_id"] == gid and row["commit"] == commit:
                        row["trajectory"]["is_merge"] = False
                write_rows(target / "observations.jsonl", records)
                mutation.update(group_id=gid, commit=commit, all_trajectory_copies_changed=True)
                expected = "topology artifact mismatch"
            elif name == "old_overlap_semantic_change":
                records = audit.rows(target / "observations.jsonl")
                row = next(
                    r
                    for r in records
                    if r["trajectory"]["coverage_stratum"] == "old_overlap"
                    and r["variant"] == "symbol_anchor"
                    and r["validation"] is not None
                )
                row["validation"]["logs"] = ["fabricated_stable_validation_log"]
                write_rows(target / "observations.jsonl", records)
                mutation.update(
                    identity={k: row[k] for k in ["group_id", "commit", "claim_id", "variant"]},
                    field="validation.logs",
                )
                expected = "old overlap semantic mismatch"
            elif name == "omitted_added_observation":
                records = audit.rows(target / "observations.jsonl")
                number = next(
                    i
                    for i, r in enumerate(records)
                    if r["trajectory"]["coverage_stratum"] == "new_added"
                )
                row = records.pop(number)
                write_rows(target / "observations.jsonl", records)
                mutation.update(
                    removed={k: row[k] for k in ["group_id", "commit", "claim_id", "variant"]}
                )
                expected = "observation coverage mismatch"
            elif name == "forged_new_summary":
                p = target / "report.json"
                report = audit.parse(p.read_bytes())
                report["primary_new_coverage"]["variants"]["symbol_anchor"]["false_available"] += 1
                save(p, report)
                mutation["field"] = "primary_new_coverage.variants.symbol_anchor.false_available"
                expected = "report metric recomputation mismatch"
            elif name == "forged_reference_facts":
                records = audit.rows(target / "observations.jsonl")
                row = next(r for r in records if r["trajectory"]["coverage_stratum"] == "new_added")
                identity = {k: row[k] for k in ["group_id", "commit", "claim_id"]}
                for r in records:
                    if all(r[k] == v for k, v in identity.items()):
                        r["reference"]["facts"]["signature"]["parameters"][0]["name"] = (
                            "forged_parameter"
                        )
                write_rows(target / "observations.jsonl", records)
                packet = (
                    target
                    / "packets"
                    / identity["group_id"]
                    / identity["commit"]
                    / identity["claim_id"]
                    / "decision.json"
                )
                decision = audit.parse(packet.read_bytes())
                decision["facts"]["signature"]["parameters"][0]["name"] = "forged_parameter"
                save(packet, decision)
                mutation.update(identity=identity, all_variant_and_packet_copies_changed=True)
                expected = "reference extracted facts mismatch"
            elif name == "forged_state_availability":
                records = audit.rows(target / "observations.jsonl")
                row = next(r for r in records if r["state"]["state"] == "stale")
                row["state"]["available"] = True
                write_rows(target / "observations.jsonl", records)
                mutation.update(
                    identity={k: row[k] for k in ["group_id", "commit", "claim_id", "variant"]}
                )
                expected = "state transition mismatch"
            elif name == "forged_cost_execution_count":
                records = audit.rows(target / "costs.jsonl")
                row = next(r for r in records if r["phase"] == "child_production_validation")
                row["actual_calls"] = 2
                write_rows(target / "costs.jsonl", records)
                mutation.update(
                    identity={k: row[k] for k in ["group_id", "commit", "claim_id", "variant"]}
                )
                expected = "forged validation cost"
            elif name == "forged_source_packet":
                p = next((target / "packets").rglob("subject.raw"))
                p.write_bytes(p.read_bytes() + b"\n# forged bytes\n")
                mutation["path"] = str(p.relative_to(target))
                expected = "raw Git source mismatch"
            else:
                p = target / "manifest.json"
                manifest = audit.parse(p.read_bytes())
                name_in_source = "src/cami/repository.py"
                for side in ["source_before", "source_after"]:
                    source = manifest[side]
                    source["files"][name_in_source] = "0" * 64
                    source["sha256"] = audit.sha(
                        json.dumps(source["files"], sort_keys=True, ensure_ascii=True).encode()
                    )
                save(p, manifest)
                mutation["path"] = name_in_source
                expected = "frozen input/source hash mismatch"
            rehash(target)
            # Fresh content digests genuinely pass, so semantic checks must reject.
            try:
                audit.audit(root, target)
            except ValueError as error:
                message = str(error)
                assert expected in message, (name, message, expected)
                checks.append(
                    {
                        "control": name,
                        "artifact_hashes_recomputed_and_valid": True,
                        "rejected": True,
                        "reason": message,
                        "mutation": mutation,
                    }
                )
            else:
                raise AssertionError("accepted forged result: " + name)
            save(out / (name + ".json"), checks[-1])
            print(name + ": rejected", flush=True)
    unknown = copy.deepcopy(audit.rows(original / "observations.jsonl")[0])
    unknown["reference"]["verdict"] = "uncertain"
    unknown["state"]["available"] = True
    metric = audit.summarize([unknown])
    assert (
        metric["false_available"] == 0
        and metric["available_unknown"] == 1
        and metric["false_available_per_contradicted"] is None
    )
    after = {
        str(p.relative_to(original)): audit.sha(p.read_bytes())
        for p in original.rglob("*")
        if p.is_file()
    }
    assert original_hashes == after, "original result changed"
    save(
        out / "checks.json",
        {
            "status": "pass",
            "auditor_source_sha256": audit.sha(
                (HERE / "audit_real_first_parent_replay.py").read_bytes()
            ),
            "checker_source_sha256": audit.sha(Path(__file__).read_bytes()),
            "rehashed_corruptions_rejected": len(checks),
            "checks": checks,
            "unknown_separate_from_false_availability": True,
            "original_results_unchanged": True,
            "limits": "Integrity roots remain pinned. Controls mutate result copies and recompute artifact hashes; they do not forge or authenticate trust roots.",
        },
    )
    print(
        json.dumps(
            {"status": "pass", "rehashed_controls": len(checks), "original_results_unchanged": True}
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
