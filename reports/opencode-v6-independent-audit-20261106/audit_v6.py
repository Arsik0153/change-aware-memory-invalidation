"""Independent stdlib audit of v6 terminal accounting, tiers, token rule and raw hashes."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import statistics

PRIVATE = {"private-state", "server-private", "private-export-client"}
ARMS = ["plain", "static", "cami"]
STUDY_SHA = "b66e4d557b7b7cdf0800b4c9121e793659f3a02029a74b026c7f7c4d75243cdd"
ROOT_ANALYSIS_SHA = "632953c9879fb1f4f05c059d2dde747e0d4d8ead7724a13c1d7d7805faa1100b"


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    assert path.is_file() and not path.is_symlink(), str(path)
    return json.loads(path.read_bytes())


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def tokens(value):
    raw = value["session_tokens"] if "session_tokens" in value else value
    result = {key: raw[key] for key in ["input", "output", "reasoning"]}
    result.update(cache_read=raw["cache"]["read"], cache_write=raw["cache"]["write"])
    assert all(finite(x) and int(x) == x for x in result.values())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--timing-caveats", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    try:
        root = args.run.resolve()
        protocol, study, plan = (
            read(args.protocol),
            read(root / "frozen-study.json"),
            read(root / "plan.json")["trials"],
        )
        assert sha(root / "frozen-study.json") == STUDY_SHA == protocol["study_sha256"]
        assert sha(args.analysis) == ROOT_ANALYSIS_SHA
        analysis = read(args.analysis)
        assert analysis["study_sha256"] == STUDY_SHA and study["service_tier"] == "priority"
        caveats = read(args.timing_caveats)
        assert caveats["study_sha256"] == STUDY_SHA
        affected = sorted({trial for row in caveats["caveats"] for trial in row["trial_ids"]})
        assert affected == ["r2-cami-s3", "r2-plain-s3", "r2-static-s3"]
        evidence = []
        for caveat in caveats["caveats"]:
            path = args.timing_caveats.parent / caveat["evidence_path"]
            assert sha(path) == caveat["evidence_sha256"]
            evidence.append({"path": str(path.resolve()), "sha256": sha(path)})
        expected = []
        sequence = study["normalized"]["sequence"]
        for rep in range(1, 4):
            for stage, task in enumerate(sequence, 1):
                offset = (rep + stage - 2) % 3
                for arm in ARMS[offset:] + ARMS[:offset]:
                    expected.append(
                        {
                            "id": f"r{rep}-{arm}-s{stage}",
                            "arm": arm,
                            "repetition": rep,
                            "stage": stage,
                            "task": task,
                            "predecessor": f"r{rep}-{arm}-s{stage - 1}" if stage > 1 else None,
                        }
                    )
        assert plan == expected and len(plan) == 36
        rows, inputs, verified, response_tiers = [], {}, 0, Counter()
        for trial in plan:
            directory = root / "trials" / trial["id"]
            terminal = read(directory / "terminal.json")
            assert terminal["trial"] == trial
            actual = {}
            for folder, directories, files in os.walk(directory, followlinks=False):
                assert not PRIVATE.intersection(directories + files)
                for name in directories + files:
                    assert not (Path(folder) / name).is_symlink()
                for name in files:
                    path = Path(folder) / name
                    if path == directory / "terminal.json":
                        continue
                    assert path.is_file()
                    actual[path.relative_to(directory).as_posix()] = sha(path)
            assert actual == terminal["artifact_hashes"]
            verified += len(actual)
            inputs[trial["id"]] = {
                "terminal_sha256": sha(directory / "terminal.json"),
                "public_artifact_hashes": actual,
            }
            assert (
                terminal["status"]
                == terminal["operational_status"]
                == terminal["session_status"]
                == "passed"
            )
            assert (
                terminal["quality"] == "pass"
                and not terminal["failures"]
                and terminal["costs"]["complete"] is True
            )
            grade = read(directory / "evaluation/report.json")
            assert (
                grade["status"] == "pass"
                and grade["fixed_tests_restored"] is True
                and grade["agent_tests_scored"] is False
            )
            for check in ["acceptance", "regression"]:
                outcome = grade["outcomes"][check]
                counts = outcome["counts"]
                assert (
                    outcome["exit_code"] == 0
                    and counts["executed"] > 0
                    and counts["failed"] == counts["errors"] == 0
                )
                if check == "acceptance":
                    assert counts["skipped"] == counts["xfailed"] == counts["xpassed"] == 0
            costs = terminal["costs"]
            assert all(
                finite(costs[key])
                for key in [
                    "charged_host_wall_seconds",
                    "controller_total_host_wall_seconds",
                    "infrastructure_host_wall_seconds",
                    "construction_host_wall_seconds",
                    "session_host_wall_seconds",
                    "guard_and_orchestration_host_wall_seconds",
                ]
            )
            assert math.isclose(
                costs["charged_host_wall_seconds"],
                costs["controller_total_host_wall_seconds"]
                - costs["infrastructure_host_wall_seconds"],
                abs_tol=1e-6,
            )
            assert math.isclose(
                costs["charged_host_wall_seconds"],
                sum(
                    costs[key]
                    for key in [
                        "construction_host_wall_seconds",
                        "session_host_wall_seconds",
                        "guard_and_orchestration_host_wall_seconds",
                    ]
                ),
                abs_tol=1e-6,
            )
            construction = trial["stage"] == 1 and trial["arm"] != "plain"
            assert (
                costs["construction_host_wall_seconds"] > 0
                if construction
                else costs["construction_host_wall_seconds"] == 0
            )
            usage = read(directory / "session/evidence/usage.json")
            normalized = tokens(usage)
            assert tokens(terminal["usage"]) == normalized
            messages = read(directory / "session/evidence/messages.json")
            assert isinstance(messages, list) and len({m["id"] for m in messages}) == len(messages)
            assistants = {m["id"]: m for m in messages if m["type"] == "assistant"}
            assert assistants
            step_sum = {
                key: sum(tokens(m["tokens"])[key] for m in assistants.values())
                for key in normalized
            }
            assert step_sum == normalized
            config = read(directory / "session/effective-input-config.json")
            assert config["model"] == "openai/gpt-6.1-sol#high"
            assert config["providers"] == {
                "openai": {"models": {"gpt-6.1-sol": {"settings": {"serviceTier": "priority"}}}}
            }
            observed = read(directory / "session/evidence/observed-model.json")
            high = [v for v in observed["variants"] if v["id"] == "high"]
            assert (
                len(high) == 1
                and {**observed["settings"], **high[0]["settings"]}["serviceTier"] == "priority"
            )
            assert (
                high[0]["settings"]["reasoningEffort"] == "high"
                and observed["id"] == observed["modelID"] == "gpt-6.1-sol"
            )
            assert (
                observed["providerID"] == "openai"
                and observed["package"] == "@opencode/ai/providers/openai/responses"
            )
            session = read(directory / "session/manifest.json")
            assert (
                session["status"] == "passed"
                and session["model_requested"] is True
                and session["service_tier_requested"] == "priority"
            )
            tier = read(directory / "session/evidence/service-tier.json")
            assert (
                tier["requested"] == tier["configured"] == "priority"
                and tier["reasoning_effort"] == "high"
            )
            assert tier["model_requested"] is True and tier["assistant_export_complete"] is True
            by_id = {v["message_id"]: v for v in tier["assistant_response_observations"]}
            assert len(by_id) == len(tier["assistant_response_observations"]) == len(assistants)
            assert set(by_id) == set(tier["assistant_ids"]) == set(assistants)
            tiers = Counter()
            for message_id, message in assistants.items():
                model = message["model"]
                assert (
                    model["providerID"] == "openai"
                    and model["id"] == "gpt-6.1-sol"
                    and model.get("variant", "high") == "high"
                )
                value = by_id[message_id]
                assert finite(message["time"]["created"]) and finite(message["time"]["completed"])
                assert (
                    value["completed"] == message["time"]["completed"] >= message["time"]["created"]
                )
                assert (
                    value["source_pointer"] == "/native/serviceTier"
                    and value["status"] == "provider_reported"
                )
                tiers[value["provider_reported"]] += 1
            response_tiers.update(tiers)
            construction_cpu = costs["construction_cgroup"]["cpu_seconds"] if construction else 0
            peaks = [costs["session_cgroup"]["peak_memory_bytes"]] + (
                [costs["construction_cgroup"]["peak_memory_bytes"]] if construction else []
            )
            row = {
                **trial,
                "tokens": normalized,
                "token_work": sum(
                    normalized[key] for key in ["input", "cache_write", "output", "reasoning"]
                ),
                "assistant_responses": len(assistants),
                "provider_reported_tiers": dict(tiers),
                "requested_priority_wire_observed": tier.get(
                    "request_on_wire_observed_for_this_session"
                ),
                "charged_wall_seconds_descriptive_only": costs["charged_host_wall_seconds"],
                "construction_wall_seconds": costs["construction_host_wall_seconds"],
                "session_wall_seconds": costs["session_host_wall_seconds"],
                "guard_wall_seconds": costs["guard_and_orchestration_host_wall_seconds"],
                "evaluation_infrastructure_seconds_separate": costs[
                    "infrastructure_host_wall_seconds"
                ],
                "container_cpu_seconds": construction_cpu + costs["session_cgroup"]["cpu_seconds"],
                "construction_cpu_seconds": construction_cpu,
                "maximum_container_peak_bytes_nonadditive": max(peaks),
                "persistent_memory_logical_bytes_after": terminal["memory_bytes_after"],
            }
            admitted = next(value for value in analysis["trials"] if value["id"] == trial["id"])
            assert (
                admitted["terminal_sha256"] == inputs[trial["id"]]["terminal_sha256"]
                and admitted["token_work"] == row["token_work"]
                and admitted["tokens"] == normalized
            )
            rows.append(row)
        blocks = []
        for rep in range(1, 4):
            for arm in ARMS:
                selected = [row for row in rows if row["repetition"] == rep and row["arm"] == arm]
                block = {
                    "repetition": rep,
                    "arm": arm,
                    "token_work": sum(row["token_work"] for row in selected),
                    "tokens": {
                        key: sum(row["tokens"][key] for row in selected)
                        for key in rows[0]["tokens"]
                    },
                    "charged_wall_seconds_descriptive_only": sum(
                        row["charged_wall_seconds_descriptive_only"] for row in selected
                    ),
                    "container_cpu_seconds": sum(row["container_cpu_seconds"] for row in selected),
                    "maximum_container_peak_bytes_nonadditive": max(
                        row["maximum_container_peak_bytes_nonadditive"] for row in selected
                    ),
                    "final_persistent_memory_logical_bytes": selected[-1][
                        "persistent_memory_logical_bytes_after"
                    ],
                }
                blocks.append(block)
        pairs = []
        for rep in range(1, 4):
            cami = next(row for row in blocks if row["repetition"] == rep and row["arm"] == "cami")
            for comparator in ["plain", "static"]:
                other = next(
                    row for row in blocks if row["repetition"] == rep and row["arm"] == comparator
                )
                pairs.append(
                    {
                        "repetition": rep,
                        "comparator": comparator,
                        "cami_token_work": cami["token_work"],
                        "comparator_token_work": other["token_work"],
                        "delta_cami_minus_comparator": cami["token_work"] - other["token_work"],
                        "token_strictly_lower": cami["token_work"] < other["token_work"],
                        "charged_wall_strictly_lower_descriptive_only": cami[
                            "charged_wall_seconds_descriptive_only"
                        ]
                        < other["charged_wall_seconds_descriptive_only"],
                    }
                )
        independent_token_winner = all(row["token_strictly_lower"] for row in pairs)
        assert independent_token_winner == (
            "token_work" in analysis["summary"]["winning_metrics_satisfying_all_six_pairs"]
        )
        assert analysis["summary"]["primary_metric_eligibility"] == {
            "charged_wall": False,
            "token_work": True,
        }
        assert analysis["summary"]["charged_wall_disqualified_by_timing_caveats"] is True
        assert (
            analysis["summary"]["timing_caveat_trial_ids"] == affected
            and not analysis["summary"]["excluded_trial_ids"]
        )
        assert (
            sum(response_tiers.values())
            == analysis["summary"]["service_tier"]["assistant_responses"]
        )
        assert response_tiers == {"default": 469}
        summaries = {}
        for arm in ARMS:
            selected = [row for row in rows if row["arm"] == arm]
            arm_blocks = [row for row in blocks if row["arm"] == arm]
            summaries[arm] = {
                "tokens_total": {
                    key: sum(row["tokens"][key] for row in selected) for key in rows[0]["tokens"]
                },
                "token_work_blocks": [row["token_work"] for row in arm_blocks],
                "token_work_median": statistics.median(row["token_work"] for row in arm_blocks),
                "token_work_range": [
                    min(row["token_work"] for row in arm_blocks),
                    max(row["token_work"] for row in arm_blocks),
                ],
                "charged_wall_seconds_total_descriptive_only": sum(
                    row["charged_wall_seconds_descriptive_only"] for row in selected
                ),
                "construction_wall_seconds_total": sum(
                    row["construction_wall_seconds"] for row in selected
                ),
                "container_cpu_seconds_total": sum(
                    row["container_cpu_seconds"] for row in selected
                ),
                "max_container_peak_bytes_nonadditive": max(
                    row["maximum_container_peak_bytes_nonadditive"] for row in selected
                ),
                "assistant_responses": sum(row["assistant_responses"] for row in selected),
            }
        result = {
            "status": "independent_audit_passed",
            "study_sha256": STUDY_SHA,
            "protocol_sha256": sha(args.protocol),
            "bound_frozen_analysis_sha256": ROOT_ANALYSIS_SHA,
            "timing_caveats_sha256": sha(args.timing_caveats),
            "timing_evidence": evidence,
            "wall_primary_disqualified_whole_cohort": True,
            "affected_trial_ids_retained": affected,
            "trials": 36,
            "operational_quality_pass": 36,
            "artifact_hashes_verified": verified,
            "assistant_response_tier_observations": dict(response_tiers),
            "requested": "priority",
            "effective_reasoning": "high",
            "tier_scope": "Independently joined hashed exported assistant IDs/completion times to pinned pre-scrub native.serviceTier projection; not independent provider-wire/scheduler/billing verification. Priority configuration is not proof of priority service.",
            "independent_token_winning_rule_all_six": independent_token_winner,
            "paired_token_comparisons": pairs,
            "arm_summaries": summaries,
            "blocks": blocks,
            "trial_rows": rows,
            "limits": [
                "No historical pooling; this is the declared two-task development cohort only.",
                "All raw costs retained; wall ineligible across the cohort due mandatory shared-host cleanup caveat, even with uniform reported default tier.",
                "Client-normalized fields may hide missing provider fields as0; raw billing/remote inference resources unavailable. Session and assistant-step sums agree but are never added together.",
                "Container CPU phases sum, memory peaks max, persistent bytes stage observations; host and remote resources are separate.",
            ],
            "model_calls": 0,
            "heldout_reads": False,
            "tracked_writes": False,
        }
        (args.out / "report.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        (args.out / "input-hashes.json").write_text(
            json.dumps(inputs, indent=2, sort_keys=True) + "\n"
        )
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "hashes": verified,
                    "tokens_all_six": independent_token_winner,
                    "assistant_tiers": dict(response_tiers),
                }
            )
        )
    except BaseException as error:
        (args.out / "failure.json").write_text(
            json.dumps(
                {"status": "failed_preserved", "error": type(error).__name__ + ": " + str(error)},
                indent=2,
            )
            + "\n"
        )
        raise


if __name__ == "__main__":
    main()
