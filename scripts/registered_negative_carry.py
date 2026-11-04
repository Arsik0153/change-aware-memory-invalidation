"""Research-only, single-owner negative carry with registered immutable inputs."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
import sys

from pydantic import BaseModel

from cami.artifacts import canonical
from cami.index import INDEX_VERSION
from cami.models import Claim, MemoryState, PolicyConfig, Provenance, Selection, ValidationResult, safe_path
from cami.policies import SelectionContext, advance_state, select_claims
from cami.validation import VALIDATOR_VERSION, ValidationContext, validate_claim
from negative_carry_witness import ResearchContext, exact_scope, input_hash


def immutable(value):
    """Reject mutable nested values even when an unvalidated copy bypassed schema checks."""
    if type(value) in {str, int, bool, float, bytes, type(None)}:
        return
    if type(value) is tuple:
        for item in value:
            immutable(item)
        return
    if isinstance(value, BaseModel) and type(value).model_config.get("frozen"):
        for name in type(value).model_fields:
            immutable(getattr(value, name))
        return
    if is_dataclass(value) and type(value).__dataclass_params__.frozen:
        for field in fields(value):
            immutable(getattr(value, field.name))
        return
    raise ValueError("registered inputs must contain only deeply immutable schema values")


@dataclass(frozen=True)
class RegisteredInputs:
    owner: object
    claim: Claim
    provenance: Provenance
    context: ResearchContext
    eligible: bool


@dataclass(frozen=True)
class ActualNegative:
    owner: object
    inputs: RegisteredInputs
    checked_commit: str
    input_hash: str
    module_oid: str


class RegisteredCarryOwner:
    """Owns one history entry. No method accepts a foreign state or witness.

    Registration and initial checked-result verification belong inside each logical
    history lifecycle. This is not a security sandbox against arbitrary Python code.
    """
    def __init__(self, base_dir: Path, output_dir: Path):
        self._owner = object()
        self._base_dir, self._output_dir = base_dir, output_dir
        self._submitted = None
        self._inputs = None
        self._state = None
        self._negative = None
        self._dirty = False
        self._run_binding = None
        self.counts = {"registrations": 0, "checked_result_imports": 0, "actual_validation_calls": 0,
                       "original_selected": 0, "effective_selected": 0, "eligibility_attempts": 0,
                       "suppressed": 0, "witness_mint_attempts": 0}

    @property
    def inputs(self):
        return self._inputs

    @property
    def state(self):
        if self._dirty:
            raise ValueError("registered inputs are pending validation")
        return self._state

    @property
    def negative(self):
        return self._negative

    def register(self, claim: Claim, provenance: Provenance, context: ResearchContext):
        submitted = (claim, provenance, context)
        if self._submitted is not None and all(a is b for a, b in zip(submitted, self._submitted, strict=True)):
            return False
        if type(claim) is not Claim or type(provenance) is not Provenance or type(context) is not ResearchContext:
            raise ValueError("register exact structural schemas, not foreign handles")
        immutable(claim)
        immutable(provenance)
        immutable(context)
        # Strict JSON reparse rejects malformed model_copy values and owns the copies.
        frozen_claim = Claim.model_validate_json(canonical(claim))
        frozen_provenance = Provenance.model_validate_json(canonical(provenance))
        frozen_context = ResearchContext(**{field.name: getattr(context, field.name) for field in fields(context)})
        if frozen_claim.kind != "signature_equals" or frozen_claim.claim_id != frozen_provenance.claim_id:
            raise ValueError("registered entry requires one signature claim and its provenance")
        if frozen_context.repo_id != frozen_claim.repo_id:
            raise ValueError("registered context repository mismatch")
        string_fields = ("repo_id", "run_binding", "python", "index_version", "validator_version", "protocol_version", "scope_contract")
        if (any(type(getattr(context, name)) is not str for name in string_fields)
                or type(context.implementation_hashes) is not tuple
                or any(type(pair) is not tuple or len(pair) != 2 or any(type(value) is not str for value in pair)
                       for pair in context.implementation_hashes)):
            raise ValueError("context identity fields must match the immutable schema")
        if (type(context.source_roots) is not tuple or any(type(root) is not str for root in context.source_roots)
                or type(context.build_graph) is not bool or type(context.max_file_bytes) is not int
                or context.max_file_bytes < 1 or len(context.run_binding) != 64
                or any(character not in "0123456789abcdef" for character in context.run_binding)):
            raise ValueError("invalid immutable research context")
        for root in context.source_roots:
            safe_path(root)
        if self._run_binding is not None and context.run_binding != self._run_binding:
            raise ValueError("new run binding requires a new owner and checked-result initialization")
        if self._inputs is not None and frozen_claim.claim_id != self._inputs.claim.claim_id:
            raise ValueError("new claim ID requires a new owner")
        eligible = (exact_scope(frozen_claim, frozen_provenance, frozen_context)
                    and context.index_version == INDEX_VERSION and context.validator_version == VALIDATOR_VERSION
                    and context.python == sys.version)
        self._inputs = RegisteredInputs(self._owner, frozen_claim, frozen_provenance, frozen_context, eligible)
        self._submitted = submitted
        self._run_binding = context.run_binding
        self._negative = None
        self._dirty = True
        self.counts["registrations"] += 1
        return True

    def _identity(self, snapshot, index):
        if self._inputs is None or self._inputs.owner is not self._owner:
            raise ValueError("entry lacks owner-registered inputs")
        if snapshot.repo_id != self._inputs.context.repo_id or index.revision != snapshot.revision:
            raise ValueError("actual snapshot/index identity mismatch")

    def initialize_checked_negative(self, result: ValidationResult, snapshot, index):
        """Once-verify a trusted actual-result binding; never import MemoryState/witness.

        The sealed history builder produced this record using actual validate_claim.
        Hash consistency is not authentication for untrusted fabricated result files.
        """
        if self._state is not None or type(result) is not ValidationResult:
            raise ValueError("initialize only a fresh owner with an actual validation result")
        result = ValidationResult.model_validate_json(canonical(result))
        self._identity(snapshot, index)
        inputs = self._inputs
        if (result.claim_id != inputs.claim.claim_id or result.commit != snapshot.revision
                or result.validator != "structural" or result.verdict != "contradicted"
                or result.reason != "predicate_mismatch"
                or result.input_hash != input_hash(inputs.claim, inputs.provenance, snapshot.revision, inputs.context)):
            raise ValueError("imported actual negative binding mismatch")
        modules = [module for module in index.modules if module.path == inputs.claim.subject.path]
        definitions = [definition for module in modules for definition in module.definitions
                       if definition.node.qualname == inputs.claim.subject.qualname]
        blob = snapshot.by_path().get(inputs.claim.subject.path)
        visible = any(root == "." or inputs.claim.subject.path.startswith(root + "/") for root in inputs.context.source_roots)
        if (not visible or len(modules) != 1 or modules[0].limitation or len(definitions) != 1
                or definitions[0].ambiguous or definitions[0].node_kind != inputs.claim.subject.node_kind
                or definitions[0].signature == inputs.claim.predicate.expected_signature
                or blob is None or blob.mode not in {"100644", "100755"} or blob.limitation or blob.content is None
                or len(blob.content) > inputs.context.max_file_bytes):
            raise ValueError("imported actual mismatch lacks its complete source witness")
        self.counts["checked_result_imports"] += 1
        self._initialize_actual(result, snapshot)

    def initialize_fresh(self, snapshot, index):
        if self._state is not None:
            raise ValueError("fresh initialization requires a new owner")
        self._identity(snapshot, index)
        inputs = self._inputs
        result = validate_claim(inputs.claim, ValidationContext(snapshot, index, inputs.provenance, self._base_dir, self._output_dir))
        self.counts["actual_validation_calls"] += 1
        self._initialize_actual(result, snapshot)
        return result

    def _initialize_actual(self, result, snapshot):
        self._install_actual(result, snapshot)
        decision = Selection(claim_id=self._inputs.claim.claim_id, commit=snapshot.revision,
                             selected=True, reasons=("actual_parent_initialization",))
        self._state = advance_state(self._state, decision, PolicyConfig(id="all_validate"), result, True)

    def _install_actual(self, result, snapshot):
        inputs = self._inputs
        if self._state is None:
            self._state = MemoryState(claim_id=inputs.claim.claim_id, revision=snapshot.revision,
                state="needs_validation", available=False, basis="validated", last_checked_commit=None,
                last_supported_commit=None, last_verdict=None, current_provenance=inputs.provenance)
        self.counts["witness_mint_attempts"] += 1
        self._negative = None
        if inputs.eligible and result.verdict == "contradicted" and result.reason == "predicate_mismatch":
            blob = snapshot.by_path().get(inputs.claim.subject.path)
            if blob and blob.mode in {"100644", "100755"} and blob.content is not None and not blob.limitation:
                self._negative = ActualNegative(self._owner, inputs, result.commit, result.input_hash, blob.object_id)
        self._dirty = False

    def _carry_reason(self, original, before, after):
        if not original.selected or original.reasons != ("previously_unavailable",):
            return "original_selection_requires_normal_behavior"
        inputs, state, negative = self._inputs, self._state, self._negative
        if self._dirty or not inputs.eligible or negative is None:
            return "registration_scope_or_actual_negative_not_eligible"
        if (negative.owner is not self._owner or negative.inputs is not inputs
                or inputs.owner is not self._owner or state.last_checked_commit != negative.checked_commit
                or state.current_provenance is not inputs.provenance or state.available or state.state != "stale"
                or state.last_verdict != "contradicted" or state.withheld_reason != "predicate_mismatch"):
            return "owned_last_actual_negative_identity_mismatch"
        for snapshot in (before, after):
            blob = snapshot.by_path().get(inputs.claim.subject.path)
            if blob is None or blob.mode not in {"100644", "100755"} or blob.limitation or blob.content is None:
                return "subject_not_readable_regular_file"
            if blob.object_id != negative.module_oid:
                return "module_changed_since_last_actual_negative"
        return None

    def step(self, before, after, index, changes, policy: PolicyConfig):
        if policy.id not in {"symbol_validate", "keep_all"}:
            raise ValueError("registered research owner supports only symbol_validate and keep_all")
        if self._dirty and policy.id == "keep_all":
            raise ValueError("changed registered inputs require validation")
        if self._state is None:
            raise ValueError("owner needs actual-check initialization")
        self._identity(after, index)
        inputs = self._inputs
        previous = self._state
        if previous.revision != before.revision or before.repo_id != inputs.context.repo_id:
            raise ValueError("nonconsecutive owned state")
        original, = select_claims(SelectionContext(after.revision, (inputs.claim,), (inputs.provenance,),
            (previous,), changes, protocol_version="1.1"), policy)
        effective, rejection, suppressed = original, None, False
        if policy.id == "symbol_validate":
            self.counts["eligibility_attempts"] += 1
            rejection = self._carry_reason(original, before, after)
            if rejection is None:
                effective = original.model_copy(update={"selected": False, "reasons": ()})
                suppressed = True
            elif self._dirty:
                effective = original.model_copy(update={"selected": True,
                    "reasons": tuple(sorted(set(original.reasons) | {"registered_inputs_changed"}))})
        self.counts["original_selected"] += original.selected
        self.counts["effective_selected"] += effective.selected
        self.counts["suppressed"] += suppressed
        result = None
        if effective.selected and policy.id.endswith("_validate"):
            result = validate_claim(inputs.claim, ValidationContext(after, index, inputs.provenance, self._base_dir, self._output_dir))
            self.counts["actual_validation_calls"] += 1
            self._install_actual(result, after)
        self._state = advance_state(previous, effective, policy, result, True)
        # Registration owns provenance even when an imported historical state used another copy.
        if self._state.current_provenance is not inputs.provenance:
            self._state = self._state.model_copy(update={"current_provenance": inputs.provenance})
        return {"original": original, "effective": effective, "suppressed": suppressed,
                "reason": rejection, "validation": result, "previous": previous, "state": self._state}
