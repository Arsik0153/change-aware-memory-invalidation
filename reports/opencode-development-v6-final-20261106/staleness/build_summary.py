"""Summarize the frozen literal analyzer output; no target imports or new model work."""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RUN = ROOT / "runs/opencode-development-v6-20261106"
PRIMARY = ROOT / "runs/opencode-development-v6-final-analysis-20261106/report.json"
STUDY_SHA = "b66e4d557b7b7cdf0800b4c9121e793659f3a02029a74b026c7f7c4d75243cdd"
PRIMARY_SHA = "632953c9879fb1f4f05c059d2dde747e0d4d8ead7724a13c1d7d7805faa1100b"
CANONICAL = {
    str(ROOT / "runs/opencode-development-v3-staleness-20261104/origin-and-stage1"):
        "6707f9b10a4b1b29695e319526113894a25fdbb6c4c70ba9a364f4b2e818a6a2",
    str(ROOT / "runs/opencode-development-v3-staleness-20261104/stage3"):
        "b19c9160c31bfdd5c5d50937dfc423984df3cb9707e71360f3f218e1d0265d99",
}


def sha(path):
    assert path.is_file() and not path.is_symlink(), path
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main():
    report = read(OUT / "report.json")
    assert sha(PRIMARY) == PRIMARY_SHA
    primary = read(PRIMARY)
    study = read(RUN / "frozen-study.json")
    assert sha(RUN / "frozen-study.json") == STUDY_SHA == primary["study_sha256"]
    assert report["inputs"]["frozen_study_sha256"] == STUDY_SHA
    assert report["inputs"]["canonical_tree_sha256"] == CANONICAL
    assert report["complete_36"] and report["all_assessed_evidence_supported"]
    assert report["unsupported_call_count"] == 0 and report["unassessed_trial_ids"] == []
    source_pins = {}
    for group, pin in study["pins"].items():
        files = {}
        for relative, expected in pin["files"].items():
            rel = Path(relative)
            assert not rel.is_absolute() and ".." not in rel.parts
            path = Path(pin["root"]) / rel
            assert not any(part in {"private-state", "server-private", "private-export-client"}
                           or "heldout" in part.lower() for part in path.parts)
            assert sha(path) == expected, path
            files[relative] = expected
        source_pins[group] = {"root": pin["root"], "files": files}
    for path, expected in report["inputs"]["implementation_sha256"].items():
        assert sha(Path(path)) == expected

    primary_trials = {t["id"]: t for t in primary["trials"]}
    terminals, messages, traces, resets = {}, {}, {}, {}
    distinct, subjects, per_trial = defaultdict(set), {}, []
    calls_by_arm, formats, boundary_counts, assessments = Counter(), Counter(), Counter(), Counter()
    stale_ids, same_changed_file = set(), Counter()
    for trial in report["trials"]:
        tid, arm = trial["trial"]["id"], trial["trial"]["arm"]
        assert trial["status"] == "assessed" and trial["terminal_status"] == "passed"
        assert trial["terminal_sha256"] == primary_trials[tid]["terminal_sha256"]
        terminals[tid] = trial["terminal_sha256"]
        messages[tid] = trial["messages_sha256"]
        resets[tid] = trial["canonical_reset_sha256"]
        calls = trial["memory_calls"]
        calls_by_arm[arm] += len(calls)
        for call in calls:
            formats[call["response_format"]] += 1
            boundary_counts[call["reason"]] += 1
            assert call["status"] == "supported" and call["source_assessable"]
        if arm != "plain":
            assert trial["backend_crosscheck"]["status"] == "matched"
            traces[tid] = trial["backend_crosscheck"]["sha256"]
        local = Counter()
        for observation in trial["records"]:
            key = arm, observation["channel"], observation["assessment"]
            distinct[key].add(observation["record_id"])
            subjects[observation["record_id"]] = observation["subject"]
            assessments[observation["assessment"]] += 1
            local[observation["channel"], observation["assessment"]] += 1
            if observation["assessment"] == "obsolete_literal_tuple":
                stale_ids.add(observation["record_id"])
            if observation["assessment"] == "same_literal_tuple" and observation["source_file_changed"]:
                same_changed_file[arm, observation["channel"]] += 1
        per_trial.append({"trial_id": tid, "arm": arm, "stage": trial["trial"]["stage"],
                          "memory_calls": len(calls), "observations": [
                              {"channel": c, "assessment": a, "count": n}
                              for (c, a), n in sorted(local.items())]})
    assert set(terminals) == set(primary_trials) and len(terminals) == 36
    artifacts = sum(t["artifact_hashes_verified"] for t in report["trials"])
    assert artifacts == primary["integrity"]["terminal_artifact_hashes_verified"] == 8130
    assert dict(calls_by_arm) == {"plain": 0, "static": 12, "cami": 12}
    assert dict(formats) == {"compact_verified": 24}
    assert not any(key.startswith(("unknown", "unsupported")) for key in assessments)
    assert len(stale_ids) == 2
    summary = {
        "status": "complete_read_only_literal_analysis", "planned_trials": 36,
        "completed_terminal_trials": 36, "terminal_status_counts": dict(Counter(t["terminal_status"] for t in report["trials"])),
        "operational_status_counts": dict(Counter(t["operational_status"] for t in primary["trials"])),
        "quality_counts": dict(Counter(t["quality"] for t in primary["trials"])),
        "literal_evidence": {"all36_trials_retained": True, "assessed_trials": 36,
            "memory_calls_by_arm": dict(calls_by_arm), "response_formats": dict(formats),
            "call_source_boundaries": dict(boundary_counts), "counts": report["counts"],
            "unsupported_calls": 0, "unknown_record_observations": 0,
            "unknown_after_possible_write_observations": 0, "unsupported_or_redacted_receipts": 0,
            "unique_records_by_assessment": [{"arm": a, "channel": c, "assessment": assessment,
                "unique_records": len(ids), "unique_record_ids": sorted(ids)}
                for (a, c, assessment), ids in sorted(distinct.items())],
            "unique_obsolete_records_across_both_arms": [
                {"record_id": rid, "subject": subjects[rid]} for rid in sorted(stale_ids)],
            "same_literal_despite_changed_source_file": [{"arm": a, "channel": c, "observations": n}
                for (a, c), n in sorted(same_changed_file.items())], "per_trial": per_trial},
        "integrity": {"verified_terminal_artifact_hashes": artifacts,
            "terminal_hashes_bound_to_primary": 36, "messages_hashes": 36, "memory_trace_hashes": 24,
            "all_frozen_source_pins_match": True,
            "source_pin_counts": {group: len(pin["files"]) for group, pin in source_pins.items()},
            "canonical_source_inventory_sha256": CANONICAL,
            "catalog_raw_sha256": report["inputs"]["catalog_raw_sha256"],
            "catalog_semantic_sha256": report["inputs"]["catalog_semantic_sha256"]},
        "primary_report_sha256": PRIMARY_SHA,
        "primary_wall_timing_caveat_trial_ids": primary["summary"]["timing_caveat_trial_ids"],
        "timing_caveat_scope": "User cache-cleanup wall caveat retained in primary analysis; no trial excluded or source/staleness classification changed by this analysis.",
        "offline_evaluation_cost": report["offline_evaluation_cost"],
        "limitations": report["limitations"] + [
            "Distinct record sets overlap across channels/stages; do not sum them as independent cases.",
            "Static49same/11obsolete and CAMI48returned_same/12withheld_obsolete are observed retrieval outputs, not a matched counterfactual ranking comparison.",
            "No causal reliance, human annotation, whole-body/behavioral equivalence or efficiency benefit inferred."],
        "model_calls": 0, "Docker_calls": 0, "heldout_reads": False,
        "implementation_changes": False, "trial_retries": 0,
    }
    write("summary.json", summary)
    write("evidence-hashes.json", {"primary_report_sha256": PRIMARY_SHA, "study_sha256": STUDY_SHA,
        "terminal_sha256": terminals, "messages_sha256": messages, "canonical_reset_sha256": resets,
        "backend_trace_sha256": traces, "frozen_source_pins": source_pins,
        "analysis_implementation_sha256": report["inputs"]["implementation_sha256"]})
    print(json.dumps({"counts": report["counts"], "unique_obsolete_records": summary["literal_evidence"]["unique_obsolete_records_across_both_arms"],
                      "unique_record_counts": [{k: v for k, v in row.items() if k != "unique_record_ids"}
                                               for row in summary["literal_evidence"]["unique_records_by_assessment"]]}))


if __name__ == "__main__":
    main()
