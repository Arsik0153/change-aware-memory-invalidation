# Independent structural checker: development artifact

This stdlib-only checker was authored from the public `schemas/Claim.json`,
`docs/annotation_guide.md`, and the task's packet/rubric contract. It imports no
CAMI code and was implemented and tested without inspecting pilot sources,
production structural validators, existing oracle scripts, outputs, or decisions.
The included fixtures are newly authored synthetic sources, not real candidates.

CPython `ast.parse` and `ast.dump(..., include_attributes=False)` are shared
primitives. **This checker does not have parser independence.** It provides fresh
binding/scope selection and signature extraction logic, not a second parser.
Every output record discloses this limitation, checker version, and Python version.
This is a development reference artifact, not a human review or CAMI label/receipt.

## Run

```sh
python3 runs/independent-oracle-development-20261104/structural_checker.py \
  --packet PACKET_DIR --out NEW_JSON
python3 runs/independent-oracle-development-20261104/test_structural_checker.py
```

`PACKET_DIR/cases.json` must be a JSON list. Each case has exactly `id`, `kind`,
`subject`, `predicate`, `text`, `scope`, `source_path`, and `source_sha256`.
`kind` is `symbol_exists` or `signature_equals` and must equal `predicate.type`.
`subject` contains exactly `path`, `qualname`, and `node_kind`; only a simple
identifier qualname and `node_kind=function` are supported. `scope` is retained as
required nonempty contract text; it is not interpreted as a separate query
language. Top-level scope is enforced structurally by the qualname and AST.

The source is a complete UTF-8 module, never imported or executed. A lowercase
SHA-256 digest must match its exact bytes before parsing. Source paths must remain
within the packet, including after symlink resolution. The output must be new;
an existing output is never overwritten. Malformed outer JSON, duplicate JSON
keys, a non-list packet, or output errors fail the CLI with status 2. Individual
case errors produce an uncertain record; duplicate case IDs are uncertain.

The output object has `format` and `records`. Each record includes `id`, `verdict`,
`reason`, `facts`, `evidence`, actual and declared source hashes, and `checker`.
Evidence ranges are inclusive and include decorators for function definitions.
Absence evidence covers the complete nonempty module. Empty modules have no
physical line range. Parsing/encoding/hash/path errors have no asserted source
facts. No CAMI-format annotation labels or confirmation receipts are produced.

## Decision contract and coverage limits

Existence means a unique direct module-body `FunctionDef` or `AsyncFunctionDef`.
Absence of such a definition contradicts a positive claim when no ambiguity is
found. An existing definition is supported for existence even if runtime calls,
decorators, imports, or function bodies would fail; runtime behavior is outside
this exact syntactic predicate.

Conditional/duplicate target function definitions, other module-scope bindings
or deletions of the target name, and module-scope star imports cause abstention.
Binding recognition includes imports, assignment targets, exception targets,
loops, context manager targets, pattern captures, and named expressions. Function
and lambda bodies and class locals do not contribute module bindings. Expressions
in function defaults/decorators/annotations and class bases/decorators do. A class
body that explicitly declares the target global is conservatively unsupported;
this is a coverage limit, even if it contains no effective rebinding. Nested local
functions' global declarations are ignored. Comprehension iteration targets are
local; named expressions in their other expressions are conservatively treated
as containing-scope bindings. Arbitrary calls, `globals()` reads, and unrelated
namespace writes are not blanket reasons to abstain. This is a lexical syntactic
check, not whole-program analysis of dynamic namespace mutation or aliases.

Target type parameters are unsupported; older CPython versions instead reject
their syntax at parsing. Other AST-version differences are exposed by the recorded
Python version. No parser equivalence across Python versions is claimed.

Signatures include ordered parameters with `name`, `kind`, `default_ast`, and
`annotation_ast`; ordered `decorators_ast`; `returns_ast`; and boolean `is_async`.
All expressions use exact CPython AST dumps without location attributes. Missing
defaults/annotations are JSON null; a literal `None` default is
`Constant(value=None)`. Bare `*` and `/` are represented by parameter kinds. All
these fields participate in comparison.

The public schema permits omitting several signature fields with defaults. This
pilot checker deliberately requires a *complete* explicit expected signature and
complete parameter objects; missing, unknown, or mistyped fields abstain rather
than being normalized. This stricter acceptance rule is a documented coverage
limit, not a contradiction of a partial expectation. Parameter-kind/order
semantics are compared literally; the checker does not execute or infer the
behavior of annotations/defaults/decorators.

## Authored validation

The test suite covers every signature field and parameter kind, positional default
alignment, required keyword-only parameters versus literal `None`, decorator order,
async, absence, conditional/duplicate definitions, module name rebinding forms,
nested scope exclusions, malformed fields, parse/encoding/hash/path failures,
symlink escapes, duplicate IDs/JSON keys, CLI output, and no-overwrite behavior.
The no-execution fixture contains a module-level raise, undefined decorator and
default calls, and a file-writing function body; checking still supports existence
without creating the marker. Temporary fixture files stay under this directory.
