#!/usr/bin/env python3
"""Run an independent audit and rehashed tamper controls into a new directory."""

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "independent_registered_negative_carry_audit", HERE / "audit_registered_negative_carry.py"
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def save(path, value):
    with path.open("xb") as stream:
        stream.write(audit.canonical(value) + b"\n")


def replace_json(path, value):
    path.write_bytes(audit.canonical(value) + b"\n")


def replace_rows(path, records):
    path.write_bytes(b"".join(audit.canonical(row) + b"\n" for row in records))


def inventory(directory):
    return {
        str(path.relative_to(directory)): (
            "symlink:" + str(path.readlink()) if path.is_symlink() else audit.sha(path.read_bytes())
        )
        for path in directory.rglob("*")
        if path.is_symlink() or path.is_file()
    }


def rehash(directory):
    manifest = audit.parse((directory / "manifest.json").read_bytes())
    manifest["artifact_hashes"] = {
        str(path.relative_to(directory)): audit.sha(path.read_bytes())
        for path in directory.rglob("*")
        if path.is_file()
        and path != directory / "manifest.json"
        and ".git" not in path.relative_to(directory).parts
    }
    replace_json(directory / "manifest.json", manifest)
    assert all(
        audit.sha((directory / name).read_bytes()) == expected
        for name, expected in manifest["artifact_hashes"].items()
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=audit.default_root())
    parser.add_argument("--result", type=Path, default=Path(audit.DEFAULT_RESULT))
    parser.add_argument("--git-fixtures", type=Path)
    parser.add_argument("--comparison-result", type=Path)
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Create a new directory; existing outputs are refused.",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    result = (root / args.result).resolve()
    fixtures = args.git_fixtures.resolve() if args.git_fixtures else None
    comparison = (root / args.comparison_result).resolve() if args.comparison_result else None
    out = args.out.resolve()
    if out.is_relative_to(result) or (fixtures and out.is_relative_to(fixtures)):
        parser.error("--out must be outside the frozen input directories")
    out.mkdir(parents=True, exist_ok=False)
    original = inventory(result)
    baseline = audit.audit(root, result, fixtures, comparison)
    save(out / "report.json", baseline)
    controls = out / "tamper_controls"
    controls.mkdir()
    results = []
    for name in [
        "missing_correctness_row",
        "forged_timing_median",
        "omitted_registration_reset_cost",
        "omitted_initial_mint_cost",
        "forged_owned_witness",
        "forged_owned_state",
        "forged_profile_metadata",
        "forged_timing_work",
    ]:
        target = controls / name
        shutil.copytree(result, target, symlinks=True)
        if name == "missing_correctness_row":
            records = audit.rows(target / "correctness.jsonl")
            removed = records.pop()
            replace_rows(target / "correctness.jsonl", records)
            mutation = {"removed": {key: removed[key] for key in ["history", "step", "variant"]}}
            expected = "correctness coverage mismatch"
        elif name == "forged_timing_median":
            summary = audit.parse((target / "summary.json").read_bytes())
            summary["variants"]["registered_inputs"]["cpu_ns"]["median"] += 1
            replace_json(target / "summary.json", summary)
            mutation = {"field": "summary.variants.registered_inputs.cpu_ns.median", "increment": 1}
            expected = "timing summary/paired delta mismatch"
        elif name in {"omitted_registration_reset_cost", "omitted_initial_mint_cost"}:
            records = audit.rows(target / "timings.jsonl")
            row = next(row for row in records if row["variant"] == "registered_inputs")
            field = (
                "registrations"
                if name == "omitted_registration_reset_cost"
                else "witness_mint_attempts"
            )
            omitted = 17 * row["history_pack_repetitions"]
            row["counts"][field] -= omitted
            replace_rows(target / "timings.jsonl", records)
            mutation = {
                "variant": "registered_inputs",
                "counter": field,
                "omitted_per_history_pack": 17,
                "omitted_per_timed_block": omitted,
            }
            expected = "timing actual-work count mismatch"
        elif name == "forged_owned_witness":
            records = audit.rows(target / "correctness.jsonl")
            row = next(
                row
                for row in records
                if row["variant"] == "registered_inputs" and row["prior_witness"]
            )
            row["prior_witness"]["input_hash"] = "0" * 64
            replace_rows(target / "correctness.jsonl", records)
            mutation = {
                "field": "prior_witness.input_hash",
                "history": row["history"],
                "step": row["step"],
                "variant": row["variant"],
            }
            expected = "state/witness lineage mismatch"
        elif name == "forged_owned_state":
            records = audit.rows(target / "correctness.jsonl")
            row = next(
                row
                for row in records
                if row["variant"] == "registered_inputs" and row["suppressed"]
            )
            row["state"]["available"] = True
            replace_rows(target / "correctness.jsonl", records)
            mutation = {
                "field": "state.available",
                "from": False,
                "to": True,
                "history": row["history"],
                "step": row["step"],
                "variant": row["variant"],
            }
            expected = "state/current witness recomputation mismatch"
        elif name == "forged_profile_metadata":
            profiles = audit.parse((target / "profiling-work.json").read_bytes())
            row = next(row for row in profiles if row["variant"] == "registered_inputs")
            row["top_cumulative_functions"][0]["own_seconds"] += 0.001
            replace_json(target / "profiling-work.json", profiles)
            replace_json(target / "profiles/registered_inputs.json", row)
            mutation = {
                "field": "top_cumulative_functions[0].own_seconds",
                "copies_changed": ["profiling-work.json", "profiles/registered_inputs.json"],
                "binary_profile_unchanged": True,
            }
            expected = "profile top-function metadata mismatch"
        else:
            records = audit.rows(target / "timings.jsonl")
            records[0]["counts"]["actual_validation_calls"] += 1
            replace_rows(target / "timings.jsonl", records)
            mutation = {"field": "timings[0].counts.actual_validation_calls", "increment": 1}
            expected = "timing actual-work count mismatch"
        rehash(target)
        try:
            audit.audit(root, target, fixtures, comparison)
        except ValueError as error:
            assert expected in str(error), (name, str(error))
            results.append(
                {
                    "control": name,
                    "passed": True,
                    "all_artifact_hashes_recomputed_and_valid": True,
                    "rejected_reason": str(error),
                    "mutation": mutation,
                }
            )
        else:
            raise AssertionError("auditor accepted rehashed corruption: " + name)
    # A stale negative state cannot become available without a successful check.
    previous = copy.deepcopy(audit.rows(result / "correctness.jsonl")[0]["previous_state"])
    carried = audit.advance(previous, "new_revision", False, None)
    assert (
        not carried["available"]
        and carried["last_checked_commit"] == previous["last_checked_commit"]
        and carried["basis"] == "carried_forward"
    )
    results.append(
        {
            "control": "negative_state_carry_preserves_unavailability_and_check_lineage",
            "passed": True,
        }
    )
    # Exercise the actual CLI refusal path; it must stop before running controls.
    before = inventory(out)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--root",
        str(root),
        "--result",
        str(result),
        "--out",
        str(out),
    ]
    if fixtures:
        command.extend(["--git-fixtures", str(fixtures)])
    if comparison:
        command.extend(["--comparison-result", str(comparison)])
    refused = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert (
        refused.returncode != 0 and "FileExistsError" in refused.stderr and inventory(out) == before
    )
    results.append(
        {
            "control": "existing_output_directory_refused",
            "passed": True,
            "existing_evidence_unchanged": True,
        }
    )
    assert inventory(result) == original
    report = {
        "status": "pass",
        "controls": results,
        "original_result_preserved": True,
        "original_inventory_entries": len(original),
        "original_manifest_sha256": original["manifest.json"],
    }
    save(out / "tamper_report.json", report)
    print(
        json.dumps({"status": "pass", "controls": len(results), "original_result_preserved": True})
    )


if __name__ == "__main__":
    main()
