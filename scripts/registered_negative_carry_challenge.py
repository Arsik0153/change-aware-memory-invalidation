"""Derivative dispatch: preserve original three algorithms; add one owned candidate."""
from __future__ import annotations

from dataclasses import asdict

from cami.artifacts import digest
from cami.models import PolicyConfig, Selection
from cami.policies import advance_state
from scripts.negative_carry_challenge import VARIANTS as ORIGINAL_VARIANTS
from scripts.negative_carry_challenge import prepare_histories as prepare_histories
from scripts.negative_carry_challenge import run_history as original_run_history
from registered_negative_carry import RegisteredCarryOwner

VARIANTS = (*ORIGINAL_VARIANTS, "registered_inputs")


def negative_record(value):
    if value is None:
        return None
    return {"checked_commit": value.checked_commit, "input_hash": value.input_hash,
            "module_oid": value.module_oid, "claim_hash": digest(value.inputs.claim),
            "provenance_hash": digest(value.inputs.provenance), "context_hash": digest(asdict(value.inputs.context))}


def run_history(history, variant, *, capture=False):
    if variant in ORIGINAL_VARIANTS:
        return original_run_history(history, variant, capture=capture)
    if variant != "registered_inputs":
        raise ValueError("unknown derivative variant")
    # Every logical history reset pays registration and actual-result ingress checks.
    owner = RegisteredCarryOwner(history.root, history.output)
    owner.register(history.initial_claim, history.provenance, history.context)
    owner.initialize_checked_negative(history.parent_result, history.parent, history.parent_index)
    rows = []
    for frame in history.frames:
        changed = owner.register(frame["claim"], history.provenance, frame["context"])
        prior_negative = owner.negative
        policy = PolicyConfig(id=frame["operation"].get("policy", "symbol_validate"))
        result = owner.step(frame["before"], frame["after"], frame["new_index"], frame["changes"], policy)
        if capture:
            fresh = frame["fresh"]
            full = Selection(claim_id=owner.inputs.claim.claim_id, commit=frame["after"].revision,
                             selected=True, reasons=("full_comparison",))
            fresh_state = advance_state(result["previous"], full, PolicyConfig(id="symbol_validate"), fresh, True)
            if policy.id != "keep_all" and any(getattr(result["state"], field) != getattr(fresh_state, field)
                    for field in ("state", "available", "last_verdict", "withheld_reason")):
                raise ValueError("registered candidate fresh-production endpoint mismatch")
            if result["suppressed"] and (fresh.verdict, fresh.reason) != ("contradicted", "predicate_mismatch"):
                raise ValueError("registered candidate carried a non-mismatch")
            rows.append({"history": history.id, "variant": variant, "step": frame["step"], "policy": policy.id,
                "registered_changed": changed, "claim_hash": digest(owner.inputs.claim),
                "claim": owner.inputs.claim.model_dump(mode="json"), "provenance": owner.inputs.provenance.model_dump(mode="json", by_alias=True),
                "context": asdict(owner.inputs.context), "context_hash": digest(asdict(owner.inputs.context)),
                "provenance_hash": digest(owner.inputs.provenance),
                "prior_witness": negative_record(prior_negative), "current_witness": negative_record(owner.negative),
                "original_selection": result["original"].model_dump(mode="json"),
                "effective_selection": result["effective"].model_dump(mode="json"),
                "suppressed": result["suppressed"], "audit_reason": result["reason"],
                "previous_state": result["previous"].model_dump(mode="json"), "state": result["state"].model_dump(mode="json"),
                "validation": result["validation"].model_dump(mode="json") if result["validation"] else None,
                "fresh": fresh.model_dump(mode="json"), "reference": frame["reference"]})
    state = owner.state
    endpoint = (state.state, state.available, state.last_verdict, state.withheld_reason, state.last_checked_commit)
    return {"endpoint": endpoint, "counts": dict(owner.counts), "rows": rows}


def workload_hash(plan):
    return digest({name: plan[name] for name in ("histories", "paired_repetitions", "histories_per_block", "warmup_blocks",
                   "minimum_block_ns", "profile_history_pack_repetitions", "profile_top_functions")})
