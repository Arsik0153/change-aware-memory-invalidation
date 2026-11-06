"""Authored v6 tier evidence and rehashed controls; no model, container or corpus use."""
from __future__ import annotations

import copy
import json

import pytest

import aggregate_study as evaluator
import test_aggregate as legacy
from service_tier_evidence import MODEL, PROVIDERS, TIER_POLICY, V6_STUDY_ID, inspect_tier


def assets(values=("default", "default")):
    assistants = [{"id": f"msg_assistant_{i}", "type": "assistant", "agent": "research",
                   "model": {"id": "gpt-6.1-sol", "providerID": "openai", "variant": "high"},
                   "time": {"created": i * 2 + 1, "completed": i * 2 + 2}, "content": []}
                  for i in range(len(values))]
    observations = [{"message_id": message["id"], "completed": message["time"]["completed"],
                     "provider_reported": value, "status": "provider_reported",
                     "source_pointer": "/native/serviceTier"}
                    for message, value in zip(assistants, values, strict=True)]
    return {
        "effective-input-config.json": {"model": MODEL, "providers": copy.deepcopy(PROVIDERS)},
        "evidence/observed-model.json": {"providerID": "openai", "id": "gpt-6.1-sol",
            "modelID": "gpt-6.1-sol", "package": "@opencode/ai/providers/openai/responses",
            "settings": {}, "variants": [{"id": "high", "settings": {
                "serviceTier": "priority", "reasoningEffort": "high"}}]},
        "evidence/messages.json": [{"id": "msg_system", "type": "system",
            "text": "Authored date notice", "time": {"created": 0}}, *assistants],
        "evidence/service-tier.json": {"requested": "priority", "configured": "priority",
            "reasoning_effort": "high", "model_requested": True,
            "assistant_export_complete": True, "assistant_ids": [m["id"] for m in assistants],
            "assistant_response_observations": observations,
            # Deliberately misleading derived claims must never replace recomputation.
            "actual_served": "priority", "provider_reported_values": ["priority"],
            "actual_served_status": "provider_reported_complete",
            "observation_ids_match_exported_assistants": True},
    }


def session():
    return {"status": "passed", "model_requested": True, "service_tier_requested": "priority"}


def freeze(f):
    path = f.root / "study.json"
    path.write_text(json.dumps(f.study))
    (f.run / "frozen-study.json").write_text(json.dumps(f.study))
    (f.run / "run.json").write_text(json.dumps({"study_path": str(path),
        "study_sha256": evaluator.sha(path), "mode": "model"}))


@pytest.fixture
def v6():
    f = legacy.AggregateTests(methodName="runTest")
    f.setUp()
    rules = json.loads(f.protocol.read_text())
    rules.update(study_id=V6_STUDY_ID, service_tier=copy.deepcopy(TIER_POLICY))
    f.protocol.write_text(json.dumps(rules))
    source = {"schema_version": 2, "seed": "origin/literals.json",
              "generator": "seed_source_literals_v2.py", "helpers": ["literal_source.py"],
              "payload_kind": "source_excerpt_equals", "extractor_format": "python.definition-prefix/1"}
    f.study.update(bundle_kind="development", memory_response_format="compact", service_tier="priority")
    f.study["normalized"].update(seed=source["seed"], memory_source=source,
        asset_hashes={name: "a" * 64 for name in ("memory-source.json", source["seed"],
                                                source["generator"], *source["helpers"])})
    freeze(f)
    yield f
    f.tearDown()


def put_tier(f, item, data=None):
    directory, record = f.terminal(item)
    write_tier(f, directory, record, data or assets())
    return directory, record


def write_tier(f, directory, record, data):
    for name, value in data.items():
        path = directory / "session" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    manifest = session()
    manifest["artifact_hashes"] = {name: evaluator.sha(directory / "session" / name) for name in data}
    (directory / "session/manifest.json").write_text(json.dumps(manifest))
    f.rewrite(directory, record)


@pytest.mark.parametrize("reported", ["default", "priority"])
def test_uniform_reported_value_is_recomputed_not_inferred_from_request(reported):
    result = inspect_tier(assets((reported, reported)), session())
    assert result["configuration_valid"] and result["provider_reported_complete"]
    assert result["uniform_provider_reported_tier"] == reported
    assert result["assistant_responses"] == 2


@pytest.mark.parametrize("fault", ["missing", "duplicate", "orphan", "export_ids", "partial", "empty",
                                  "tier_bool", "tier_upper", "wrong_pointer", "status", "time_missing",
                                  "time_bool", "time_inf", "time_huge", "time_mismatch", "time_order"])
def test_partial_or_unsupported_response_evidence_never_claims_complete_coverage(fault):
    data = assets()
    evidence = data["evidence/service-tier.json"]
    observations = evidence["assistant_response_observations"]
    first = observations[0]
    if fault == "missing":
        observations.pop()
    elif fault == "duplicate":
        observations.append(copy.deepcopy(first))
    elif fault == "orphan":
        observations.append({**first, "message_id": "msg_orphan"})
    elif fault == "export_ids":
        evidence["assistant_ids"] = ["msg_foreign"]
    elif fault == "partial":
        evidence["assistant_export_complete"] = False
    elif fault == "empty":
        data = assets(())
    elif fault.startswith("tier_"):
        first["provider_reported"] = True if fault == "tier_bool" else "Priority"
    elif fault == "wrong_pointer":
        first["source_pointer"] = "/configured/serviceTier"
    elif fault == "status":
        first["status"] = "absent"
    elif fault == "time_missing":
        del first["completed"]
    elif fault == "time_order":
        first["completed"] = 0
        data["evidence/messages.json"][1]["time"]["completed"] = 0
    else:
        first["completed"] = {"time_bool": True, "time_inf": float("inf"),
                              "time_huge": 2 ** 4096, "time_mismatch": 99}[fault]
    result = inspect_tier(data, session())
    assert result["configuration_valid"]
    assert not result["provider_reported_complete"]
    assert result["uniform_provider_reported_tier"] is None
    assert result["tier_errors"]


@pytest.mark.parametrize("fault", ["config_model", "config_tier", "response_model", "reasoning",
                                  "observed_tier", "provider", "package", "request", "declared_reasoning",
                                  "duplicate_high", "missing_model", "duplicate_message"])
def test_independent_configuration_sources_reject_rehashed_identity_disagreements(fault):
    data = assets()
    if fault == "config_model":
        data["effective-input-config.json"]["model"] = "openai/other#high"
    elif fault == "config_tier":
        data["effective-input-config.json"]["providers"] = {}
    elif fault == "response_model":
        data["evidence/messages.json"][1]["model"]["id"] = "other"
    elif fault == "missing_model":
        del data["evidence/messages.json"][1]["model"]
    elif fault == "duplicate_message":
        data["evidence/messages.json"].append(copy.deepcopy(data["evidence/messages.json"][1]))
    elif fault in ("provider", "package"):
        data["evidence/observed-model.json"]["providerID" if fault == "provider" else "package"] = "other"
    elif fault == "request":
        data["evidence/service-tier.json"]["requested"] = "auto"
    elif fault == "declared_reasoning":
        data["evidence/service-tier.json"]["reasoning_effort"] = "low"
    elif fault == "duplicate_high":
        data["evidence/observed-model.json"]["variants"] *= 2
    else:
        settings = data["evidence/observed-model.json"]["variants"][0]["settings"]
        settings["reasoningEffort" if fault == "reasoning" else "serviceTier"] = "low" if fault == "reasoning" else "auto"
    result = inspect_tier(data, session())
    assert not result["configuration_valid"] and result["configuration_errors"]


def test_exact_v6_policy_and_study_are_admitted_without_relaxing_shared_rules(v6, monkeypatch):
    supported = evaluator.read(evaluator.HERE / "supported_rules.json")
    protocol = evaluator.read(v6.protocol)
    assert evaluator.admit_protocol(protocol, supported) == V6_STUDY_ID
    evaluator.admit_study_cohort(V6_STUDY_ID, v6.study)
    monkeypatch.setattr(evaluator, "trial_row", lambda *args: pytest.fail("outcome read before cohort admission"))
    for key in TIER_POLICY:
        broken = copy.deepcopy(protocol)
        del broken["service_tier"][key]
        with pytest.raises(ValueError, match="exact frozen"):
            evaluator.admit_protocol(broken, supported)
    protocol["service_tier"]["all_arms_same_configuration"] = 1
    with pytest.raises(ValueError, match="exact frozen"):
        evaluator.admit_protocol(protocol, supported)
    for field, value in [("service_tier", "auto"), ("service_tier", None),
                         ("memory_response_format", "full"), ("bundle_kind", "heldout")]:
        original = copy.deepcopy(v6.study)
        v6.study[field] = value
        freeze(v6)
        with pytest.raises(ValueError):
            evaluator.aggregate(v6.run, v6.protocol)
        v6.study = original


@pytest.mark.parametrize("fault", [None, "within_trial", "across_trials", "partial", "configuration",
                                  "missing_tier", "unreadable_tier", "missing_config"])
def test_full36_rehashed_controls_keep_quality_tokens_costs_and_gate_winners(v6, fault):
    for index, item in enumerate(v6.plan):
        data = assets()
        if index == 0 and fault in ("within_trial", "across_trials"):
            data = assets(("priority", "default") if fault == "within_trial" else ("priority", "priority"))
        if index == 0 and fault == "partial":
            data["evidence/service-tier.json"]["assistant_response_observations"][0]["provider_reported"] = None
        if index == 0 and fault == "configuration":
            data["effective-input-config.json"]["model"] = "openai/other#high"
        directory, record = put_tier(v6, item, data)
        if index == 0 and fault in ("missing_tier", "unreadable_tier", "missing_config"):
            path = directory / "session" / ("effective-input-config.json" if fault == "missing_config" else "evidence/service-tier.json")
            if fault == "unreadable_tier":
                path.write_text("not JSON")
                manifest_path = directory / "session/manifest.json"
                manifest = json.loads(manifest_path.read_text())
                manifest["artifact_hashes"]["evidence/service-tier.json"] = evaluator.sha(path)
                manifest_path.write_text(json.dumps(manifest))
            else:
                path.unlink()
            v6.rewrite(directory, record)
    report = evaluator.aggregate(v6.run, v6.protocol)
    summary = report["summary"]
    assert summary["all_trials_operational_quality_pass"]
    assert summary["all_primary_metrics_complete"]
    assert summary["terminal_trials"] == 36 and len(report["trials"]) == 36
    assert all(row["quality"] == "pass" and row["operational_status"] == "passed" for row in report["trials"])
    assert all(row["token_work"] is not None and row["charged_wall_seconds"] is not None for row in report["trials"])
    assert all(block["token_work"]["total"] is not None and block["charged_wall"]["total"] is not None for block in summary["blocks"])
    assert summary["service_tier"]["assistant_responses"] == 72
    configuration_valid = fault not in ("configuration", "missing_config")
    assert summary["primary_metric_eligibility"]["token_work"] is configuration_valid
    assert summary["primary_metric_eligibility"]["charged_wall"] is (fault is None)
    assert summary["winning_metrics_satisfying_all_six_pairs"] == (
        ["charged_wall", "token_work"] if fault is None else ["token_work"] if configuration_valid else [])
    if fault is None:
        assert summary["service_tier"]["uniform_provider_reported_tier"] == "default"
    else:
        assert summary["service_tier"]["wall_ineligibility_reasons"]


def test_nested_manifest_hash_disagreement_remains_an_integrity_error(v6):
    directory, record = put_tier(v6, v6.plan[0])
    path = directory / "session/manifest.json"
    manifest = json.loads(path.read_text())
    manifest["artifact_hashes"]["evidence/service-tier.json"] = "a" * 64
    path.write_text(json.dumps(manifest))
    v6.rewrite(directory, record)
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        evaluator.aggregate(v6.run, v6.protocol)


def test_no_model_mode_disables_every_v6_primary_eligibility_flag(v6):
    for item in v6.plan:
        put_tier(v6, item)
    path = v6.run / "run.json"
    binding = json.loads(path.read_text())
    binding["mode"] = "no-model"
    path.write_text(json.dumps(binding))
    report = evaluator.aggregate(v6.run, v6.protocol)
    assert not report["summary"]["primary_efficiency_eligible"]
    assert not any(report["summary"]["primary_metric_eligibility"].values())
    assert all(not pair[metric]["primary_metric_eligible"]
               for pair in report["summary"]["paired_comparisons"]
               for metric in ("charged_wall", "token_work"))


def test_timing_caveat_still_blocks_wall_with_uniform_reported_tier(v6):
    for item in v6.plan:
        put_tier(v6, item)
    report = evaluator.aggregate(v6.run, v6.protocol, timing_caveats_path=v6.caveat())
    summary = report["summary"]
    assert summary["service_tier"]["wall_comparable"]
    assert not summary["primary_metric_eligibility"]["charged_wall"]
    assert summary["primary_metric_eligibility"]["token_work"]
    assert summary["charged_wall_disqualified_by_timing_caveats"]


def test_missing_terminal_never_opens_active_tier_payload(v6, monkeypatch):
    private = v6.run / "trials" / v6.plan[0]["id"] / "private-state"
    private.mkdir(parents=True)
    original = evaluator.read

    def guarded(path):
        if path.is_relative_to(private.parent):
            pytest.fail("active trial payload read")
        return original(path)

    monkeypatch.setattr(evaluator, "read", guarded)
    report = evaluator.aggregate(v6.run, v6.protocol)
    assert report["summary"]["terminal_trials"] == 0
    assert report["trials"][0]["token_work"] is None
    assert report["summary"]["service_tier"]["assistant_responses"] is None
    assert report["summary"]["service_tier"]["known_assistant_responses_subtotal"] is None
    assert not report["summary"]["primary_efficiency_eligible"]


def test_legacy_aggregation_never_requests_tier_evidence(monkeypatch):
    f = legacy.AggregateTests(methodName="runTest")
    f.setUp()
    try:
        f.fill()
        monkeypatch.setattr(evaluator, "trial_tier", lambda *args: pytest.fail("legacy tier requirement"))
        report = evaluator.aggregate(f.run, f.protocol)
        assert "service_tier" not in report["summary"]
        assert all("service_tier" not in row for row in report["trials"])
        assert set(report["summary"]["winning_metrics_satisfying_all_six_pairs"]) == {"charged_wall", "token_work"}
    finally:
        f.tearDown()
