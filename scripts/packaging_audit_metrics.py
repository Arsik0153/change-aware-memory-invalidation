"""Recompute all declared dependent descriptive projections from raw rows."""

from collections import defaultdict
from packaging_audit_common import summarize
from packaging_audit_inputs import VARIANTS


def metric(rows):
    result = summarize(rows)
    if not rows:
        result["false_available_per_scored_null_reason"] = "no_observations_in_stratum"
    by_claim = defaultdict(list)
    for row in rows:
        if row["eligible"]:
            by_claim[row["claim_id"]].append(row)
    first, runs = [], []
    total = 0
    for cid, records in sorted(by_claim.items()):
        records = sorted(records, key=lambda r: r["trajectory"]["step"])
        current = None
        found = False
        for row in records:
            rank = row["trajectory"]["step"]
            if row["reference"]["verdict"] == "contradicted":
                total += 1
                if not found:
                    first.append({"claim_id": cid, "commit": row["commit"], "step": rank})
                    found = True
                if current is None or current["last_step"] + 1 != rank:
                    current = {
                        "claim_id": cid,
                        "first_step": rank,
                        "last_step": rank,
                        "observations": 0,
                    }
                    runs.append(current)
                current["last_step"] = rank
                current["observations"] += 1
            else:
                current = None
    result["incidence"] = {
        "unique_contradicted_claims": len(first),
        "first_contradiction_observations": len(first),
        "repeated_contradicted_observations": total - len(first),
        "observed_contradiction_runs": len(runs),
        "first_contradictions": first,
        "runs": runs,
        "episode_definition": "Maximal observed consecutive contradicted ranks; unknown breaks an observed run but is not proof of recovery.",
    }
    return result


def stratum(rows, groups):
    return {
        "variants": {v: metric([r for r in rows if r["variant"] == v]) for v in VARIANTS},
        "groups": {
            g["group_id"]: {
                v: metric([r for r in rows if r["variant"] == v and r["group_id"] == g["group_id"]])
                for v in VARIANTS
            }
            for g in groups
        },
        "claim_kinds": {
            kind: {
                v: metric([r for r in rows if r["variant"] == v and r["claim_kind"] == kind])
                for v in VARIANTS
            }
            for kind in ("symbol_exists", "signature_equals")
        },
    }


def report(records, parents, p, costs):
    output = {
        "full23": stratum(records, p["groups"]),
        "prefix12": stratum([r for r in records if r["trajectory"]["step"] <= 12], p["groups"]),
        "topology_strata": {
            name: stratum([r for r in records if r["trajectory"]["is_merge"] == merge], p["groups"])
            for name, merge in [("merge", True), ("nonmerge", False)]
        },
    }
    output["parent_initialization"] = {
        v: {
            "eligible_parent_claims": sum(x["eligible"] for x in parents),
            "supported": sum(
                x["eligible"] and x["variants"][v]["state"]["available"] for x in parents
            ),
            "initially_withheld": sum(
                x["eligible"] and not x["variants"][v]["state"]["available"] for x in parents
            ),
            "actual_validation_calls": sum(x["eligible"] for x in parents),
        }
        for v in VARIANTS
    }
    output["separate_work"] = {
        "parent_reference_calls": sum(
            x.get("reference_calls", 0) for x in costs if x["phase"] == "parent_reference"
        ),
        "child_reference_calls": sum(
            x.get("reference_calls", 0) for x in costs if x["phase"] == "child_reference"
        ),
        "shared_index_builds": sum(x.get("index_builds", 0) for x in costs),
    }
    output["coverage_note"] = (
        "New-derived Packaging development claims; paired predicates and repeated functions/modules/parents remain dependent. Prefix12 is nested in full23; merge strata are descriptive, not causal. No Click overlap evaluation or speedup inference."
    )
    return output
