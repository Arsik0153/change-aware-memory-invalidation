Staged implementation only. No real development child sources, diffs, trees or outcomes were read or replayed during implementation. All execution tests construct a temporary, authored Git repository inside this directory and remove it afterward.

Integrate `run_real_structural_replay.py` and `real_structural_replay_support.py` together under `scripts/`; integrate the test under `tests/test_real_structural_replay.py`. The driver also supports this staging directory and package invocation with `-m scripts.run_real_structural_replay`. Run `.venv/bin/python scripts/run_real_structural_replay.py --protocol examples/real_structural_replay/protocol.json --out NEW_DIR` only after the coordinator finalizes the protocol and seal.

The protocol is JSON with the following required fields; additional proposal/access/research fields are preserved in the output manifest:

```json
{
  "schema_version": 1,
  "status": "sealed",
  "production_protocol_version": "1.1",
  "split": "development",
  "root": "../..",
  "seal_path": "examples/real_structural_replay/seal.json",
  "reference_path": "scripts/structural_checker_v2.py",
  "cohort_path": "examples/real_structural_replay/cohort.json",
  "confirmations_path": "examples/real_structural_replay/confirmations.jsonl",
  "ai_case_map_path": "examples/real_structural_replay/ai_case_map.json",
  "ai_public_cases_path": "examples/real_structural_replay/ai_public_cases.json",
  "implementation_paths": ["scripts/run_real_structural_replay.py", "scripts/real_structural_replay_support.py", "tests/test_real_structural_replay.py"],
  "candidate_claims": 24,
  "candidate_claim_child_observations_per_variant": 112,
  "provenance": {
    "symbol_anchor": "examples/real_structural_replay/research_provenance/symbol_anchor.jsonl",
    "file_anchor": "examples/real_structural_replay/research_provenance/file_anchor.jsonl",
    "known_incomplete": "examples/real_structural_replay/research_provenance/known_incomplete.jsonl",
    "all_validate": "examples/real_structural_replay/research_provenance/symbol_anchor.jsonl"
  },
  "groups": [{
    "group_id": "ORIGINAL_GROUP_ID",
    "repo_id": "click",
    "repo_path": "ROOT_RELATIVE_LOCAL_REPOSITORY",
    "source_roots": ["src", "click"],
    "parent_commit": "EXACT_40_HEX_ID",
    "child_commits": ["EXACT_FROZEN_CHILD_ID"],
    "claims_path": "examples/real_structural_replay/groups/ORIGINAL_GROUP_ID/claims.jsonl"
  }]
}
```

All paths except `root` are workspace-root-relative safe paths; `root` is relative to the protocol file. The output must be new and never replaces an existing directory. `cohort.json` retains the existing planning rows with `claim`, `claim_sha256`, `group_id`, `parent_source_sha256`, and `parent_git_blob_object_id`. All fixed claims must appear exactly once in the group files and every provenance variant, including eventually excluded parents. Every cohort row must explicitly declare `split:"development"`. Each variant is checked against its declared anchor scope and known-incomplete assumption.

The seal is JSON `{ "protocol_sha256": "RAW_PROTOCOL_FILE_SHA256", "files": { "ROOT_RELATIVE_PATH": "RAW_FILE_SHA256" } }`. Include all protocol inputs and raw AI evidence, driver, helper, tests, `scripts/verify_cami.py`, the reference checker/rubric/tests, production `src/cami/**/*.py`, and any additional artifacts the coordinator binds. The implementation working tree must have clean source status. The seal is checked before any experiment repository access and checked again after replay. All groups' exact single-parent chains are validated before any snapshot access. Protocol metadata and complete seal are retained in the manifest; protocol bytes are bound by SHA-256, so the seal itself is not self-inventoried. The executing driver and helper must be included. The implementation-path list also identifies the integrated test and any analyzer the coordinator adds.

A confirmation row binds the original claim hash to at least two raw AI reviews:

```json
{"claim_id":"ORIGINAL_ID","claim_sha256":"ORIGINAL_CLAIM_HASH","reviewer_kind":"ai_reviewer","reviews":[{"review_path":"examples/real_structural_replay/ai_reviews/reviewer_a.json","review_sha256":"RAW_HASH","item_id":"ORIGINAL_BLIND_CASE_ID"},{"review_path":"examples/real_structural_replay/ai_reviews/reviewer_b.json","review_sha256":"RAW_HASH","item_id":"ORIGINAL_BLIND_CASE_ID"}]}
```

Each raw review must declare `human:false`, `reviewer_kind:"ai_reviewer"`, and a distinct nonempty `agent_task`. The exact item ID must occur once, its source hash must match the frozen parent module, and its verdict must be `supported` to establish research eligibility. Missing confirmation rows, fewer than two reviews, or non-supporting verdicts exclude the parent without reducing the candidate denominator. Hash, identity, duplicate, and source mismatches stop execution and preserve a failed manifest. The sealed `ai_case_map_path` must have exactly one `origin_class:"authentic_parent_claim"` row per original candidate, matching `original_candidate_id`, `original_claim_sha256`, and the complete `original_claim`. Its ID must join a unique public case from `ai_public_cases_path` whose kind, subject, predicate, text, scope and source hash equal the original claim and parent module. Every review item ID must equal that authentic public case ID. The coordinator must freeze those authentic private-map/public-case artifacts, and the driver validates the join before any corpus access.

Eligible parents are independently reference-supported and AI-confirmed. Actual production parent validation initializes each variant; unsupported or uncertain production results remain withheld and are reported as initially withheld. No independent reference value feeds production selection or maintained state. Child reference evaluation happens after all four variants finish their transitions for that step. Every selected validation is executed independently using that variant's own provenance; logical selected validations and actual calls are separately counted and equal by construction. All-validate results are recorded beside the other variants as a full-production comparison, never substituted for those variants' actual validation.

The reference uses a separate stdlib subprocess Git reader (`ls-tree` and `show`) on the exact permitted commit/path, preserving raw tree output, Git mode/OID, full raw subject bytes, the checker case, and decision in `packets/`. Missing exact paths are contradicted with Git absence evidence; nonregular modes, unsupported ancestors/types, parse failures, encoding failures and checker uncertainty remain unknown. It imports only the sealed independent v2 checker and never executes subject source or imports the experiment repository.

Outputs are `manifest.json`, `parents.jsonl`, `observations.jsonl`, `costs.jsonl`, `changes/`, `packets/`, and `report.json`. Parent rows preserve every claim and exclusion. Observation rows retain all candidate claim/child/variant combinations and complete eligible previous states, provenance, selection reasons, validation and current states. Candidate reference supported/contradicted/unknown counts include excluded parents; the scored reference counts are separately named without the `candidate_` prefix. Reference-contradicted false availability, available-with-unknown-reference, withheld reference-supported, and all reference-unknown records are reported separately for every group/variant and aggregate. Zero reference-contradicted or zero eligible denominators produce null rates with explicit reasons. Parent validation, independent reference, and shared index work are separate costs. No wall-time speedup or independent-sample inference is claimed.

Verification: `.venv/bin/python runs/real-structural-replay-runner-development-20261104/test_real_structural_replay.py`. The authored fixture covers signature mismatch, exact-path absence, duplicate-definition ambiguity, recovery, reference uncertainty, separate unknown accounting, Git symlink source preservation, parse/encoding failures, no eligible parent, production-withheld eligible parent, seal-before-snapshot failure, output overwrite rejection, relative CLI protocol/output paths, dirty-source refusal, all-groups-before-snapshot chain validation, and same-module AI review item swaps. The fixture source-status snapshots come from its own clean authored repository; the production implementation and fixture files still undergo the actual seal hash checks.
