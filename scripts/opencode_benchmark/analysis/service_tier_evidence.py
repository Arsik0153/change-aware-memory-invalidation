"""Independent v6 tier comparability from hashed public artifacts, not runtime claims."""
from __future__ import annotations

import re

from aggregate_metrics import number

V6_STUDY_ID = "opencode-cami-real-maintenance-development-v6-priority-indexed"
TIER_POLICY = {
    "requested": "priority",
    "reasoning_effort": "high",
    "all_arms_same_configuration": True,
    "comparability_rule": "complete_uniform_provider_reported_tier_across_all_assistant_responses_v1",
    "configuration_rule": "matching_priority_high_model_configuration_required_for_all_primary_metrics_v1",
    "legacy_pooling": False,
}
MODEL = "openai/gpt-6.1-sol#high"
PROVIDERS = {"openai": {"models": {"gpt-6.1-sol": {"settings": {"serviceTier": "priority"}}}}}
ARTIFACTS = ("effective-input-config.json", "evidence/observed-model.json",
             "evidence/messages.json", "evidence/service-tier.json")


def admit_tier_policy(protocol):
    policy = protocol.get("service_tier")
    if not isinstance(policy, dict) or any(
        type(policy.get(key)) is not type(expected) or policy[key] != expected
        for key, expected in TIER_POLICY.items()
    ):
        raise ValueError("v6 requires the exact frozen priority/high tier and configuration rules")


def _timestamp(value):
    try:
        return number(value)
    except OverflowError:
        return None


def inspect_tier(artifacts, session, artifact_errors=(), response_artifact_errors=()):
    """Schema/identity failures affect both metrics; response missingness affects wall only."""
    configuration_errors = list(artifact_errors)
    tier_errors = list(response_artifact_errors)
    config = artifacts.get("effective-input-config.json")
    model = artifacts.get("evidence/observed-model.json")
    messages = artifacts.get("evidence/messages.json")
    evidence = artifacts.get("evidence/service-tier.json")
    if not isinstance(session, dict) or (session.get("service_tier_requested") != "priority"
                                        or session.get("model_requested") is not True):
        configuration_errors.append("session requested tier/model identity differs or is unavailable")
    if not isinstance(config, dict) or config.get("model") != MODEL or config.get("providers") != PROVIDERS:
        configuration_errors.append("effective configuration differs from frozen priority/high model")
    if not isinstance(model, dict):
        configuration_errors.append("observed model metadata unavailable")
    else:
        variants = model.get("variants")
        high = [v for v in variants if isinstance(v, dict) and v.get("id") == "high"] if isinstance(variants, list) else []
        settings = model.get("settings", {})
        variant_settings = high[0].get("settings") if len(high) == 1 else None
        if not isinstance(settings, dict) or not isinstance(variant_settings, dict):
            configuration_errors.append("observed high variant/settings unavailable or nonunique")
        else:
            effective = {**settings, **variant_settings}
            if (model.get("providerID") != "openai" or model.get("id") != "gpt-6.1-sol"
                    or model.get("modelID") != "gpt-6.1-sol"
                    or model.get("package") != "@opencode/ai/providers/openai/responses"
                    or effective.get("serviceTier") != "priority"
                    or effective.get("reasoningEffort") != "high"):
                configuration_errors.append("observed provider/model/reasoning/tier differs")
    if not isinstance(evidence, dict):
        tier_errors.append("response tier evidence unavailable")
        evidence = {}
    elif any(key in evidence and (type(evidence[key]) is not type(expected) or evidence[key] != expected)
             for key, expected in (("requested", "priority"), ("configured", "priority"),
                                   ("reasoning_effort", "high"), ("model_requested", True))):
        configuration_errors.append("tier evidence request/configuration identity differs")

    assistants, ids = {}, set()
    if not isinstance(messages, list):
        configuration_errors.append("complete exported message array unavailable")
        tier_errors.append("complete exported message array unavailable")
    else:
        for message in messages:
            if (not isinstance(message, dict) or not isinstance(message.get("id"), str)
                    or not message["id"].startswith("msg_") or message["id"] in ids
                    or not isinstance(message.get("type"), str)):
                configuration_errors.append("invalid or duplicate exported message identity")
                tier_errors.append("invalid or duplicate exported message identity")
                continue
            ids.add(message["id"])
            if message["type"] != "assistant":
                continue
            assistants[message["id"]] = message
            reference = message.get("model")
            if (not isinstance(reference, dict) or reference.get("providerID") != "openai"
                    or reference.get("id") != "gpt-6.1-sol"
                    or "variant" in reference and reference["variant"] != "high"):
                configuration_errors.append("assistant response model identity differs or is unavailable")

    observations = evidence.get("assistant_response_observations")
    by_id = {}
    if not isinstance(observations, list):
        tier_errors.append("response observations unavailable")
    else:
        for observation in observations:
            if (not isinstance(observation, dict) or not isinstance(observation.get("message_id"), str)
                    or observation["message_id"] in by_id):
                tier_errors.append("invalid or duplicate response observation identity")
                continue
            by_id[observation["message_id"]] = observation
    exported_ids = evidence.get("assistant_ids")
    if (not isinstance(exported_ids, list) or not all(isinstance(value, str) for value in exported_ids)
            or len(set(exported_ids)) != len(exported_ids) or set(exported_ids) != set(assistants)):
        tier_errors.append("declared assistant IDs differ from independently exported assistants")
    if evidence.get("assistant_export_complete") is not True:
        tier_errors.append("assistant export is not complete")
    if not assistants or set(by_id) != set(assistants):
        tier_errors.append("response observations do not exactly cover nonempty exported assistants")
    reported = set()
    for message_id, message in assistants.items():
        observation = by_id.get(message_id, {})
        timing = message.get("time")
        created = _timestamp(timing.get("created")) if isinstance(timing, dict) else None
        completed = _timestamp(timing.get("completed")) if isinstance(timing, dict) else None
        observed_completed = _timestamp(observation.get("completed"))
        if (created is None or completed is None or observed_completed is None
                or completed < created or completed != observed_completed):
            tier_errors.append("assistant completion timestamp absent, invalid or inconsistent")
        value = observation.get("provider_reported")
        if (observation.get("status") != "provider_reported"
                or observation.get("source_pointer") != "/native/serviceTier"
                or not isinstance(value, str) or re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", value) is None):
            tier_errors.append("assistant provider-reported tier absent or unsupported")
        else:
            reported.add(value)
    complete = not tier_errors
    return {
        "configuration_valid": not configuration_errors,
        "configuration_errors": sorted(set(configuration_errors)),
        "provider_reported_complete": complete,
        "provider_reported_values": sorted(reported),
        "uniform_provider_reported_tier": next(iter(reported)) if complete and len(reported) == 1 else None,
        "assistant_responses": len(assistants) if isinstance(messages, list) else None,
        "tier_errors": sorted(set(tier_errors)),
        "evidence_scope": "Pinned runtime projection of each exported assistant native.serviceTier before native scrub; not independent wire/scheduler, entitlement or billing verification.",
    }


def study_tier_summary(rows):
    evidence = [row["service_tier"] for row in rows]
    configured = len(rows) == 36 and all(item["configuration_valid"] for item in evidence)
    complete = len(rows) == 36 and all(item["provider_reported_complete"] for item in evidence)
    values = sorted({value for item in evidence for value in item["provider_reported_values"]})
    counts = [item["assistant_responses"] for item in evidence]
    known_counts = [count for count in counts if count is not None]
    reasons = []
    if not configured:
        reasons.append("frozen request/model/reasoning configuration is incomplete or mismatched")
    if not complete:
        reasons.append("provider response tiers do not completely cover every assistant in all36 trials")
    if len(values) != 1:
        reasons.append("provider-reported response tiers are mixed or unavailable across the full study")
    return {
        "requested": "priority", "reasoning_effort": "high",
        "configuration_valid": configured,
        "provider_reported_complete": complete,
        "provider_reported_values": values,
        "uniform_provider_reported_tier": values[0] if complete and len(values) == 1 else None,
        "wall_comparable": configured and complete and len(values) == 1,
        "wall_ineligibility_reasons": reasons,
        "assistant_responses": sum(known_counts) if len(known_counts) == len(rows) else None,
        "known_assistant_responses_subtotal": sum(known_counts) if known_counts else None,
        "configuration_failure_trials": [r["id"] for r in rows if not r["service_tier"]["configuration_valid"]],
        "response_tier_incomplete_trials": [r["id"] for r in rows if not r["service_tier"]["provider_reported_complete"]],
        "rule": TIER_POLICY["comparability_rule"],
        "configuration_rule": TIER_POLICY["configuration_rule"],
        "scope": "Every assistant response in all36 scheduled trials; no arm/trial filtering. A uniform reported default is comparable but is not proof of priority service.",
    }
