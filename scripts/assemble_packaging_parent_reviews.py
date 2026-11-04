"""Assemble fixed primary AI/reference decisions without changing or replacing them."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from cami.artifacts import file_hash, read_json, reserve, within, write_json, write_jsonl  # noqa: E402
from scripts.validate_ai_review import audit_review  # noqa: E402
from scripts.verify_cami import source_snapshot  # noqa: E402
from scripts.collect_packaging_parents_v2 import tokenizer_preflight  # noqa: E402


def require(condition, message):
    if not condition:
        raise ValueError(message)


def assemble(protocol_path, references, directories_path, output):
    reserve(output)
    manifest = {
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source_before": source_snapshot(ROOT),
        "human_credit": 0,
        "child_source_access": False,
        "review_retry_or_replacement": False,
        "routing_sha256": file_hash(directories_path),
        "implementation_sha256": file_hash(Path(__file__)),
    }
    write_json(output / "manifest.json", manifest)
    try:
        require(not manifest["source_before"]["source_status"], "commit assembly source first")
        protocol = read_json(protocol_path)
        seal = read_json(within(ROOT, protocol["seal_path"]))
        require(seal["protocol_sha256"] == file_hash(protocol_path), "review protocol seal")
        require(
            protocol["status"] == "sealed" and protocol["primary_contexts"] == 6,
            "six frozen primary contexts required",
        )
        for name, expected in seal["files"].items():
            require(file_hash(within(ROOT, name)) == expected, "changed review input: " + name)
        reference_manifest = read_json(references / "manifest.json")
        require(
            reference_manifest["status"] == "complete"
            and reference_manifest["reference_calls"] == 36
            and reference_manifest["source_before"] == reference_manifest["source_after"]
            and reference_manifest["review_protocol_sha256"] == file_hash(protocol_path)
            and reference_manifest["checker_sha256"] == protocol["reference_sha256"],
            "reference execution identity",
        )
        for name, expected in reference_manifest["artifact_hashes"].items():
            require(file_hash(within(references, name)) == expected, "changed reference output")
        generation_path = within(ROOT, protocol["parent_generation_manifest_path"])
        generation = read_json(generation_path)
        tokenizer_preflight(generation["protocol"], generation["seal"])
        token = generation["protocol"]["tokenizer"]
        groups = read_json(within(ROOT, protocol["review_groups_path"]))
        routing = read_json(directories_path)
        expected_tasks = {
            "/root/" + name for names in protocol["review_context_names"].values() for name in names
        }
        require(set(routing) == expected_tasks, "exact six registered primary contexts")
        cohort = {
            r["claim"]["claim_id"]: r for r in read_json(generation_path.parent / "cohort.json")
        }
        decisions, controls, declared, eligibility = [], [], [], {}
        for group in groups:
            gid = group["group_id"]
            packet = within(ROOT, group["packet_root"])
            case_map = generation_path.parent / "private" / (gid + "-case_map.json")
            refs_path = references / (gid + ".json")
            ref = read_json(refs_path)
            require(
                ref["packet_sha256"] == group["packet_sha256"]
                and ref["reference_sha256"] == protocol["reference_sha256"],
                "reference packet",
            )
            answers = {r["id"]: r for r in ref["decisions"]}
            group["case_map_path"] = str(case_map.relative_to(ROOT))
            group["reference_answers_path"] = str(refs_path.relative_to(ROOT))
            group["ai_reviews"] = []
            ai = []
            for name in protocol["review_context_names"][gid]:
                task = "/root/" + name
                original = within(ROOT, routing[task])
                destination = output / "ai" / name
                destination.mkdir(parents=True)
                copied = {}
                for source in sorted(original.rglob("*")):
                    if not source.is_file() or "__pycache__" in source.parts:
                        continue
                    require(not source.is_symlink(), "review artifacts cannot be symlinks")
                    relative = source.relative_to(original)
                    if source.suffix == ".py":
                        relative = relative.with_suffix(".py.txt")
                    target = destination / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    copied[str(source.relative_to(ROOT))] = {
                        "archived_as": str(target.relative_to(ROOT)),
                        "sha256": file_hash(target),
                    }
                write_json(destination / "copy-manifest.json", copied)
                review_path = destination / "review.json"
                require((destination / "methodology.json").is_file(), "preserve review methodology")
                review = read_json(review_path)
                require(
                    review["agent_task"] == task
                    and review["provider"] == protocol["reviewer_provider"]
                    and review["model"] == protocol["reviewer_model"]
                    and review["reasoning_effort"] == protocol["reasoning_effort"],
                    "registered declared invocation identity",
                )
                audit = audit_review(packet, review_path)
                write_json(destination / "format-audit.json", audit)
                command = [
                    token["python_executable"],
                    str(within(ROOT, token["helper_path"])),
                    "--config",
                    str(within(ROOT, token["config_path"])),
                    "--vocab",
                    str(within(ROOT, token["vocab_path"])),
                ]
                measured = subprocess.run(
                    command,
                    input=review_path.read_bytes(),
                    capture_output=True,
                    timeout=120,
                    check=True,
                )
                budget = json.loads(measured.stdout)
                budget.update(
                    review_sha256=file_hash(review_path),
                    response_limit=8000,
                    status="within_estimate_limit"
                    if budget["estimated_tokens"] <= 8000
                    else "exceeds_estimate_limit",
                )
                budget_path = destination / "response-budget.json"
                write_json(budget_path, budget)
                require(budget["status"] == "within_estimate_limit", "primary response size limit")
                group["ai_reviews"].append(
                    {
                        "path": str(review_path.relative_to(ROOT)),
                        "sha256": file_hash(review_path),
                        "response_budget_path": str(budget_path.relative_to(ROOT)),
                        "response_budget_sha256": file_hash(budget_path),
                    }
                )
                ai.append({r["id"]: r for r in review["items"]})
                declared.append(
                    {
                        "group_id": gid,
                        "agent_task": task,
                        "verdicts": audit["counts"]["declared_verdicts"],
                        "response_estimated_tokens": budget["estimated_tokens"],
                    }
                )
            eligible = 0
            for mapped in read_json(case_map):
                cid = mapped["id"]
                verdicts = [answers[cid]["verdict"], *(a[cid]["verdict"] for a in ai)]
                if mapped["origin_class"] == "authored_control":
                    passed = all(v == mapped["expected_verdict"] for v in verdicts)
                    controls.append(
                        {
                            "group_id": gid,
                            "case_id": cid,
                            "expected_verdict": mapped["expected_verdict"],
                            "verdicts": verdicts,
                            "passed": passed,
                        }
                    )
                    continue
                row = cohort[mapped["derived_claim_id"]]
                reasons = []
                if verdicts[0] != "supported":
                    reasons.append("parent_reference_" + verdicts[0])
                if any(v != "supported" for v in verdicts[1:]):
                    reasons.append("fresh_AI_not_both_supported")
                decisions.append(
                    {
                        "group_id": gid,
                        "claim_id": mapped["derived_claim_id"],
                        "claim_sha256": row["claim_sha256"],
                        "parent_source_sha256": row["parent_source_sha256"],
                        "reference_verdict": verdicts[0],
                        "eligible": not reasons,
                        "exclusion_reasons": reasons,
                    }
                )
                eligible += not reasons
            eligibility[gid] = eligible
        write_json(output / "review_groups.json", groups)
        write_jsonl(output / "parent-decisions.jsonl", decisions)
        write_json(output / "controls.json", controls)
        write_json(output / "declared-reviews.json", declared)
        require(
            len(decisions) == 24 and len(controls) == 12 and all(c["passed"] for c in controls),
            "complete primary/control gate failed",
        )
        require(
            all(n >= protocol["minimum_eligible_per_group"] for n in eligibility.values()),
            "parent feasibility failed; all exclusions retained",
        )
        for name, expected in seal["files"].items():
            require(
                file_hash(within(ROOT, name)) == expected, "review input changed during assembly"
            )
        tokenizer_preflight(generation["protocol"], generation["seal"])
        manifest["source_after"] = source_snapshot(ROOT)
        require(
            manifest["source_before"] == manifest["source_after"], "source changed during assembly"
        )
        manifest.update(
            status="complete",
            primary_contexts=6,
            primary_AI_decisions=72,
            reference_decisions=36,
            controls_passed=12,
            eligible_by_group=dict(Counter(r["group_id"] for r in decisions if r["eligible"])),
        )
    except BaseException as error:
        manifest.update(status="failed", failure=f"{type(error).__name__}: {error}")
        raise
    finally:
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        manifest["artifact_hashes"] = {
            str(p.relative_to(output)): file_hash(p)
            for p in output.rglob("*")
            if p.is_file() and p != output / "manifest.json"
        }
        write_json(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--review-directories", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    assemble(
        args.protocol.resolve(),
        args.references.resolve(),
        args.review_directories.resolve(),
        args.out.resolve(),
    )


if __name__ == "__main__":
    main()
