# Structural provenance closure, version 1

This development addendum is recorded before the synthetic demonstration experiments.
Its identifier is `structural-provenance-closure/1`. The base protocol remains 1.1.
The original specification, protocol, datasets, seals, policies, fallback rules, and
core record schemas retain their original meaning and contents.

## Authority and criterion

The only authorized operation is preparation of synthetic, development, fixture
inputs under `automatic_fixture` authority with `independent=false`. Independent
review for real experiments remains **REQUIRED and BLOCKED**. This operation cannot
admit real claims, clear main dataset flags, confirm claim truth independently, or
create a ParentReceipt, label, scientific freeze, or human review.

Closure is per claim. Only `symbol_exists` and `signature_equals` are eligible,
with an exact top-level function subject whose qualname is a simple identifier.
The explicit scope allowlist is:

- `Exact syntactic definition, no runtime semantics.` for either predicate.
- `Exact syntactic definition identity only.` for `symbol_exists`.
- `Exact normalized syntax, including defaults, annotations, decorators, and async status.`
  for `signature_equals`.

The latter two strings recognize generated scopes without authorizing real data.
The original intact provenance must have zero explicit dependencies,
`known_incomplete=true`, and a nonempty list of known remarks. The only dischargeable
remark is exactly `Draft parent-only anchors; dependency extraction and review pending.`.
Every source remark must be named exactly once in that claim's authorization.
Unknown, duplicate, absent, or open remarks prevent closure. There is no batch flag
override. Unrequested provenance retains its original bytes in the derived stream.

## Parent evidence boundary

The operation reads a single resolved parent snapshot and supplied claims/provenance.
It never invokes dataset loading, check-inputs, validation, policy execution, probes,
or repository code. The strict request rejects child, diff, labels, receipts, and graph
fields. No child commit is required to exist. Relative repo and input paths resolve
against the request directory; repo paths may also be absolute. Input files must stay
inside that directory. Output must be outside it and every source input directory.
Existing output is rejected.

Each authorization binds canonical Claim and Provenance SHA-256 digests. The request
also binds the exact input file hashes, full parent object ID, repository location,
configured source roots, protocol, and addendum document hash. Claims must belong to
that repository and parent. The subject must lie within the configured index roots.
The complete subject blob is retained with its Git object ID and SHA-256 digest.

Closure requires exactly one matching definition in the complete matching definition
list, directly in the module body, with no ambiguity or unsupported type parameters.
All anchors are checked for parent commit, full blob hash, scope/identity, and optional
display line bounds. At least one anchor must be the exact subject symbol. Lines need
not cover the definition. Additional valid file or symbol anchors remain unchanged
and preserve their scope. Relevant blobs must be readable regular files; Python
support files must parse. Size, encoding, parse, symlink, submodule, and LFS limitations
prevent closure.

The binding analysis deliberately accepts a small language. Module statements may
be unconditional function definitions, explicit non-wildcard imports, simple named
assignments or annotations with inert syntax, docstrings, and pass. Function headers
may use inert names, attributes, literals, containers, and operators, but no calls,
comprehensions, lambdas, or other executable expression forms. Decorator syntax is
retained, not executed or interpreted. Duplicate module bindings, subject rebinding,
conditional definitions, class scopes, wildcard imports, walrus expressions,
global/nonlocal declarations, attribute/subscript writes, and dynamic namespace
access are rejected. Any expression outside the module/header allowlist fails closed.
These are sufficient conservative conditions, not a general Python completeness test.

Calls, imports, and loaded names inside function bodies may remain unresolved because
their runtime resolution cannot alter the stored AST definition or normalized syntax.
The evidence retains parser unresolved nodes, imports, definition calls, and loaded
names with that specific explanation. Namespace and binding uncertainty is checked
separately and is never discharged as ordinary unresolved call resolution.
`signature_equals` compares the full shared normalized Signature, including all
parameters, defaults, annotations, return annotation, decorators, and async status.
Neither predicate is interpreted as runtime behavior or runtime signature equality.

## Request and artifacts

`prepare_structural_closure(parent_inputs: Path, output: Path) -> Path` accepts one
JSON object, written by the caller, with exactly these required fields:

```text
schema_version=1
protocol_version="1.1"
addendum_version="structural-provenance-closure/1"
addendum_sha256=<SHA-256 of this document's bytes>
dataset_kind="synthetic", split="development", stratum="fixture"
repo=<standard RepoLocation>
parent_commit=<full resolved Git commit object ID>
claims_path=<relative local file>, claims_sha256=<file SHA-256>
provenance_path=<relative local file>, provenance_sha256=<file SHA-256>
closures=[{claim_id, claim_sha256, provenance_sha256, close_reasons:[exact remarks]}]
authority={type:"automatic_fixture", independent:false}
```

All records are strict and frozen. Invalid requests, hashes, eligibility, evidence,
limitations, and open remarks fail before reserving the output directory. The CLI is
`python scripts/prepare_main.py close-structural-provenance --parents PATH --out PATH`.
The return value is the new `closure_manifest.json` path.

The output contains `claims.jsonl` and `source/provenance.jsonl` as exact byte copies,
the exact request at `source/request.json`, ordinary derived `provenance.jsonl`,
`closure_history.jsonl`, per-claim `evidence/` JSON files, retained full source blobs,
and copies of this addendum and the original protocol documents. Only requested
records change, and only `known_incomplete` and the explicitly discharged remarks.
Each history row binds parent, claim, original and derived record digests, evidence
file digest, exact remark dispositions, and automatic fixture authority.

The manifest binds request, original and derived file hashes, version, document and
protocol hashes, implementation hashes, and the complete payload file inventory.
The inventory excludes only the manifest itself to avoid a self-hash cycle.
It records `parent_only=true`, `child_data_used=false`, `independent_review=false`,
and `real_experiment_eligible=false`. These artifacts permit a subsequent synthetic
demo to consume ordinary provenance without changing policy behavior. They do not
establish scientific validity, empirical savings, or eligibility of any real cohort.
