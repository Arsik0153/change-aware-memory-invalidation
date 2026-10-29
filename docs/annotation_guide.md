# Independent annotation and protocol freeze

Run `cami annotate-export --dataset DATASET --out DIR` to create a blinded packet.
The packet contains immutable claims, full parent and child object IDs, source files,
source limitations, and SHA-256 hashes. It excludes policy configuration, policy
outputs, validator verdicts, existing labels, and parent confirmation receipts.
The command never executes repository code. A source file alone may be insufficient
to decide a behavior claim. Obtain independent reviewed test evidence for the exact
frozen test case. Mark missing or ambiguous evidence `uncertain`.

Annotators independently decide `supported`, `contradicted`, or `uncertain` for each
claim at each child revision, including claims a policy later retires. Parent truth
is a separate admission check and requires its own independent confirmation receipt.
Annotators must not see policy outputs. A second human independently reviews at least
20% of the main population before adjudication. Do not use CAMI's production
validators to create the reference labels. Synthetic expectations must remain
explicitly synthetic.

## Import format

`cami annotate-import --input FILE --out DIR` accepts a JSON object with
`schema_version: 1`, an `annotations` array, an optional `adjudications` array, and an
optional `annotation_population` array. Unknown fields, duplicate IDs, duplicate
responses by an author for one item, unresolved Git refs, and invalid numeric values
are errors. Population items have `schema_version`, `claim_id`, and a full `commit`
object ID. Supply the complete predeclared annotation population, including items
without submitted annotations, to calculate the 20% coverage requirement. Without
it the requirement remains unverified rather than being inferred from submitted items.

Each annotation has these fields:

```json
{
  "schema_version": 1,
  "annotation_id": "reviewer-a-item-001",
  "claim_id": "CLAIM_ID",
  "commit": "FULL_40_OR_64_HEX_OBJECT_ID",
  "annotator_id": "reviewer-a",
  "annotator_kind": "human",
  "independent": true,
  "label": "uncertain",
  "evidence": ["Exact source location or independently reviewed test result"],
  "confirmation_type": "human_review",
  "annotation_minutes": 4.0
}
```

`annotator_kind` accepts `human`, `independent_oracle`, and `synthetic_author`.
`confirmation_type` accepts `human_review`, `independent_oracle`, `independent_test`,
and `synthetic_manual`. Human review requires `human`; independent oracle requires
`independent_oracle`; synthetic manual requires `synthetic_author`. An independent
test accepts `human` or `independent_oracle`: record who actually authored the review,
separately from the method used. Only actual declared human reviews count toward
human double-review coverage.
Production validator types are rejected. These fields are declarations. Software
cannot verify that an author is a human or prove that an oracle is independent.
Review authorship and independence outside the tool.

For parent behavior claims, a `supported` decision requires `independent_test`.
If the required environment cannot be restored, record `uncertain` with the actual
review method and evidence of the limitation. Parent import retains nonpositive
decisions without creating confirmation receipts. Environment failure alone does
not justify `contradicted`.

An adjudication record has `schema_version`, `adjudication_id`, `claim_id`, `commit`,
`annotation_ids`, `adjudicator_id`, `status`, `label`, `evidence`, `confirmation_type`,
`annotation_minutes`, and optional `previous_adjudication_id`. Its `annotation_ids`
must refer to all independent originals for that item. Set `status` to `resolved`
and provide a final label, or set `status` to `unresolved` and `label` to `null`.
Subsequent records reference the preceding adjudication ID. Import preserves the
entire ordered history and every original author's response.

Import writes the exact `original_import.json`, `raw_annotations.jsonl`,
`adjudications.jsonl`, `labels.jsonl`, and `annotation_report.json`. Final labels use
the scorer's `Label` schema. Agreement produces a final label; a single response
produces a label marked `single_annotator`; disagreement without resolved adjudication
produces no label. A later unresolved adjudication also produces no label. Missing
labels remain missing rather than becoming arbitrary `uncertain` decisions.

The report calculates agreement and Cohen's kappa before adjudication. For more than
two responses per item it uses the first two independent annotator IDs in lexical
order and discloses that pairing. It reports kappa separately for each fixed
annotator pair. If pairs differ across items, pooled kappa is `null` with
`heterogeneous_annotator_pairs`. Degenerate marginals or no double annotations
also produce `null` kappa with a reason. Only two human responses count towards the second-human requirement.
Annotation and adjudication minutes remain separate from API costs.

## Freeze and heldout inputs

`cami freeze --dataset DATASET --out DIR` checks repository mapping, immutable claim
IDs, identical cohorts for the same parent, protocol versions, splits, episode
clusters, and replay overlap. Related histories sharing a parent or child commit
must share an episode cluster. Clusters cannot cross splits. Replay histories cannot
overlap independent pairs or other replay sequences. Multiple policy configurations
for one replay sequence may share its history through the same `sequence_id`.

Freeze saves original manifests, configurations, claims, provenance, parent receipts
and their evidence, probes, environment files, graph views, labels and raw annotations
when provided. It expands configuration defaults, resolves Git object IDs, records
versions, and hashes every copied artifact. Portable source snapshots preserve
repository file evidence and unsupported-file limitations. Executing the frozen
configuration still needs the recorded local Git repository; snapshots do not
recreate Git history. Freeze never checks out revisions, executes validators, starts
Docker, runs a policy, or generates annotations.

`protocol.json` records the sealed inputs and `seal.json` records its SHA-256 hash.
Missing child labels produce `annotation_status: awaiting_annotation`. The seal is
protocol fixation, not evidence that annotation is finished. Behavioral parent
preflight remains pending and must succeed before an experiment admits that frozen
cohort. Declared unavailable validators or missing parent receipts are excluded in
the frozen cohort and listed with reasons.

Heldout runs use `frozen_protocol_path` in their run configuration. The engine checks
the protocol seal, configuration and cohort membership, and all associated execution
input hashes. The seal digest excludes this locator field to avoid a circular hash.
This check never opens or hashes label files. Scoring remains a separate operation.
Freeze and annotation commands reject an existing output directory.
