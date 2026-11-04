#!/usr/bin/env python3
"""Sealed parent-only derived cohort and blind-packet collector; no child source reads."""
# ruff: noqa: E402
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import resource
import sys
import time

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "src/cami").is_dir())
for path in (ROOT, ROOT / "src", ROOT / "scripts", Path(__file__).resolve().parent):
    sys.path.insert(0, str(path))

from cami.index import INDEX_VERSION
from cami.artifacts import file_hash, read_json, reserve, within, write_json, write_jsonl
from scripts.verify_cami import source_snapshot
from packaging_parent_collection_support_v2 import preflight, enumerate_parent, derive_claims
from packaging_parent_packets_v2 import build_packet


def now():
    return datetime.now(timezone.utc).isoformat()


def total_cpu():
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time() + child.ru_utime + child.ru_stime


class Budget:
    def __init__(self, output, policy, *, started_wall=None, started_cpu=None):
        self.output, self.policy = output, policy
        self.wall = time.monotonic() if started_wall is None else started_wall
        self.cpu = total_cpu() if started_cpu is None else started_cpu

    def __call__(self):
        storage = sum(path.stat().st_size for path in self.output.rglob("*") if path.is_file())
        if (storage > self.policy["raw_storage_ceiling_GiB"] * 1024**3
                or total_cpu() - self.cpu > self.policy["local_analysis_cpu_ceiling_seconds"]
                or time.monotonic() - self.wall > self.policy["replay_wall_ceiling_minutes"] * 60):
            raise ValueError("frozen resource ceiling reached; partial collection preserved")


def tokenizer_preflight(protocol, seal):
    token = protocol["tokenizer"]
    for field in ("config_path", "vocab_path", "manifest_path", "helper_path"):
        name = token[field]
        if name not in seal["files"]:
            raise ValueError("tokenizer dependency absent from collection seal")
    for field in ("config", "vocab", "manifest"):
        if file_hash(within(ROOT, token[field + "_path"])) != token[field + "_sha256"]:
            raise ValueError("offline tokenizer artifact identity mismatch")
    python = Path(token["python_executable"])
    if not python.is_absolute():
        python = ROOT / python
    if file_hash(python.resolve(strict=True)) != token["python_sha256"]:
        raise ValueError("isolated tokenizer Python identity mismatch")
    config = read_json(within(ROOT, token["config_path"]))
    manifest = read_json(within(ROOT, token["manifest_path"]))
    if (config["encoding_name"] != "o200k_base" or config["package"] != "tiktoken" or config["package_version"] != "0.12.0"
            or manifest["distribution"] != "tiktoken" or manifest["version"] != "0.12.0"):
        raise ValueError("offline named tokenizer identity changed")
    environment = within(ROOT, token["environment_root"])
    for name, expected in manifest["tokenizer_files"].items():
        if file_hash(within(environment, name)) != expected:
            raise ValueError("isolated tokenizer implementation changed")


def execute(protocol_path, output):
    started_wall, started_cpu = time.monotonic(), total_cpu()
    protocol_path, output = protocol_path.resolve(), output.resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError("collector output must stay inside the research workspace")
    reserve(output)
    manifest = {"schema_version": 1, "status": "preflight", "started_at": now(), "source_before": source_snapshot(ROOT),
        "parent_only": True, "child_source_access": False, "network": False, "source_execution": False,
        "evaluation_eligible": False, "original630_modified": False, "human_credit": 0,
        "reference_calls": 0, "AI_reviews": 0, "groups_completed": [], "python": sys.version, "index_version": INDEX_VERSION,
        "metadata_informed": True, "original_plan_succeeded": False, "primary_horizon": 23,
        "phase_boundary": "Generation only. Root must seal packet/rubric/reference before any independent reference or AI decision."}
    write_json(output / "manifest.json", manifest)
    cohort, all_provenance, case_map, answer_key, review_groups = [], {variant: [] for variant in ("symbol_anchor", "file_anchor", "known_incomplete")}, [], [], []
    try:
        if manifest["source_before"]["source_status"]:
            raise ValueError("commit implementation source before parent collection")
        if sys.version_info[:2] != (3, 12):
            raise ValueError("parent collection requires the pinned CPython3.12 parser")
        protocol, seal, topology, repo = preflight(protocol_path, ROOT)
        own = str(Path(__file__).resolve().relative_to(ROOT))
        if own not in protocol["implementation_paths"] or own not in seal["files"]:
            raise ValueError("executing parent collector is not explicitly frozen")
        for name in ("packaging_parent_packets_v2.py", "packaging_parent_collection_support_v2.py"):
            relative = str(Path(__file__).with_name(name).relative_to(ROOT))
            if relative not in protocol["implementation_paths"] or relative not in seal["files"]:
                raise ValueError("collector helper implementation not frozen")
        caps = protocol["resource_budget"]
        if (not 0 < caps["raw_storage_ceiling_GiB"] <= 2 or not 0 < caps["local_analysis_cpu_ceiling_seconds"] <= 1200
                or not 0 < caps["replay_wall_ceiling_minutes"] <= 30 or len(protocol["review_prompt_paths"]) < 2):
            raise ValueError("collection resource budget exceeds proposal or omits review prompt text")
        tokenizer_preflight(protocol, seal)
        budget = Budget(output, caps, started_wall=started_wall, started_cpu=started_cpu)
        budget()
        manifest.update(status="collecting_parents", protocol_sha256=file_hash(protocol_path), protocol=protocol, seal=seal,
            source_parent_allowlist=protocol["source_access_parent_commits"], tokenizer_estimate_only=True)
        write_json(output / "manifest.json", manifest)
        for group in topology["groups"]:
            group_output = output / "parents" / group["group_id"]
            candidates = enumerate_parent(repo, group["parent_commit"], group_output, budget,
                allowed_parents=tuple(protocol["source_access_parent_commits"]))
            rows, claims, provenance = derive_claims(group, candidates)
            cohort.extend(rows)
            write_jsonl(output / "groups" / group["group_id"] / "claims.jsonl", claims)
            for variant, values in provenance.items():
                all_provenance[variant].extend(values)
            write_json(output / "cohort.json", cohort)
            for variant, values in all_provenance.items():
                write_jsonl(output / "research_provenance" / (variant + ".jsonl"), values)
            mapping, answers, review = build_packet(group, rows, candidates, output, ROOT, protocol, budget)
            case_map.extend(mapping)
            answer_key.extend(answers)
            review_groups.append(review)
            write_json(output / "private" / "case_map.json", case_map)
            write_json(output / "private" / "answer_key.json", answer_key)
            write_json(output / "review_groups.json", review_groups)
            manifest["groups_completed"].append(group["group_id"])
            write_json(output / "manifest.json", manifest)
            budget()
        if len(cohort) != 24 or len(case_map) != 36 or len(answer_key) != 12:
            raise ValueError("fixed derived cohort/packet/control population incomplete")
        for name, expected in seal["files"].items():
            if file_hash(within(ROOT, name)) != expected:
                raise ValueError("sealed implementation/input changed during collection")
        tokenizer_preflight(protocol, seal)
        manifest["source_after"] = source_snapshot(ROOT)
        if manifest["source_before"] != manifest["source_after"]:
            raise ValueError("implementation source changed during collection")
        manifest.update(status="prepared_awaiting_packet_seal_and_independent_review", finished_at=now(),
            candidate_claims=24, selected_function_occurrences=12, public_cases=36, authored_controls=12,
            artifact_hashes={str(path.relative_to(output)): file_hash(path) for path in output.rglob("*")
                if path.is_file() and path != output / "manifest.json"})
    except BaseException as error:
        manifest.update(status="failed", finished_at=now(), failure=f"{type(error).__name__}: {error}", source_after=source_snapshot(ROOT))
        manifest["artifact_hashes"] = {str(path.relative_to(output)): file_hash(path) for path in output.rglob("*")
            if path.is_file() and path != output / "manifest.json"}
        write_json(output / "manifest.json", manifest)
        raise
    write_json(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    execute(args.protocol, args.out)


if __name__ == "__main__":
    main()
