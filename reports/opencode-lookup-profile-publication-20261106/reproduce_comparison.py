"""Verify retained hashes and recompute attribution from existing profiles only."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import pstats
import stat

BASE = "runs/opencode-lookup-profile-20261106"
CAND = "runs/opencode-membership-candidate-20261106"


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.root.absolute(), args.out.absolute()
    assert not out.is_relative_to(root) and not root.is_relative_to(out)
    out.mkdir(exist_ok=False)
    manifest = read(root / "PUBLICATION-MANIFEST.json")
    for name, expected in manifest["files"].items():
        p = root / name
        assert not Path(name).is_absolute() and ".." not in Path(name).parts
        assert not any(q.is_symlink() for q in [p, *p.parents])
        info = p.lstat()
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        assert digest(p) == expected["sha256"] and info.st_size == expected["bytes"]
        assert stat.S_IMODE(info.st_mode) == expected["mode"]
    coverage = read(root / "publication-analysis/coverage.json")["groups"]
    for group, base in zip(coverage, [BASE, CAND], strict=True):
        declared = read(root / base / "profile-v1/report.json")["artifact_hashes"]
        assert set(declared) == set(group["included"]) | set(group["omitted_hash_only"])
        assert not set(group["included"]) & set(group["omitted_hash_only"])
        for name, checksum in group["included"].items():
            assert digest(root / base / "profile-v1" / name) == checksum == declared[name]
        for name, row in group["omitted_hash_only"].items():
            assert row["declared_sha256"] == declared[name]
            assert not (root / base / "profile-v1" / name).exists()
    spec = importlib.util.spec_from_file_location(
        "frozen_profile_comparison", root / CAND / "compare_profiles.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(
        module
    )  # Definitions only; its main/raw-body assertions are not executed.
    baseline = read(root / BASE / "profile-v1/report.json")
    candidate = read(root / CAND / "profile-v1/report.json")
    rows = []
    for case in candidate["cases"]:
        namespace, label = case["namespace"], case["case"]
        old_case = next(
            row
            for row in baseline["cases"]
            if row["namespace"] == namespace and row["case"] == label
        )
        for old, new in zip(old_case["report"]["cases"], case["report"]["cases"], strict=True):
            assert old["label"] == new["label"]
            name = new["label"]
            profiles, payloads = [], []
            for base in [BASE, CAND]:
                directory = root / base / "profile-v1" / namespace / label
                profiles.append(module.attributes(pstats.Stats(str(directory / (name + ".prof")))))
                result = read(directory / (name + "-mcp-result.json"))
                assert result["isError"] is False
                value = json.loads(result["content"][0]["text"])
                assert value.pop("audit_receipt", None)
                payloads.append(value)
            assert payloads[0] == payloads[1]
            assert (
                old["returned_ids"] == new["returned_ids"]
                and old["withheld_ids"] == new["withheld_ids"]
            )
            rows.append(
                {
                    "namespace": namespace,
                    "case": name,
                    "portable_mcp_content_equal_except_receipt": True,
                    "returned_ids": new["returned_ids"],
                    "withheld_ids": new["withheld_ids"],
                    "baseline": profiles[0],
                    "candidate": profiles[1],
                    "baseline_instrumented_dispatch_wall_seconds": old[
                        "profiled_dispatch_wall_seconds"
                    ],
                    "candidate_instrumented_dispatch_wall_seconds": new[
                        "profiled_dispatch_wall_seconds"
                    ],
                }
            )
    original = read(root / CAND / "comparison.json")
    assert rows == original["rows"] and len(rows) == 15
    changed = [row for row in rows if row["case"] == "changed-new-process"]
    summary = {
        side: {key: module.stats([row[side][key] for row in changed]) for key in changed[0][side]}
        for side in ["baseline", "candidate"]
    }
    assert summary == original["changed_snapshot_attribution"]
    plans = [read(root / base / "profile-v1/profile-plan.json") for base in [BASE, CAND]]
    pins = [plan["source_pins"]["production"] for plan in plans]
    # Root paths in original evidence remain unchanged; only this verifier resolves them below extraction.
    original_root = Path("/root/apps/change-aware-memory-invalidation")
    for pin in [*pins, plans[0]["source_pins"]["adapter"]]:
        for name, checksum in pin["files"].items():
            assert digest(root / Path(pin["root"]).relative_to(original_root) / name) == checksum
    assert set(pins[0]["files"]) == set(pins[1]["files"])
    assert [n for n in pins[0]["files"] if pins[0]["files"][n] != pins[1]["files"][n]] == [
        "cami/index.py"
    ]
    for repetition in range(1, 4):
        name = f"profile-v1/r{repetition}-cami/memory/prepared/catalog.json"
        assert (root / BASE / name).read_bytes() == (root / CAND / name).read_bytes()
    result = {
        "status": "passed",
        "verified_public_payload_files": len(manifest["files"]),
        "comparison_rows_exact": True,
        "comparison_rows": len(rows),
        "changed_attribution_summary_exact": True,
        "portable_mcp_payloads_equal_except_original_receipts": True,
        "all_core_files_equal_except_index_py": True,
        "shared_catalogs_byte_identical": True,
        "coverage": [
            {k: v for k, v in g.items() if k not in ["included", "omitted_hash_only"]}
            for g in coverage
        ],
        "original_omitted_hashes_retained_not_payload_verified": True,
        "model_calls": 0,
        "profile_reruns": 0,
        "Docker_calls": 0,
        "network_calls": 0,
        "target_source_execution": False,
        "scope": "Stored cProfile attribution/portable output reproduction only; not new timing or a complete re-execution of original profile setup.",
    }
    (out / "verification.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
