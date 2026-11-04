# AI review format audit staging

This standalone stdlib harness audits explicit AI development reviews. It neither
imports CAMI nor creates labels, receipts, admission decisions or scientific seals.
The tests use only tiny synthetic packets created below this staging directory.

Run:

```sh
python3 validate_ai_review.py --packet PUBLIC_PACKET_DIR --review REVIEW.json --out NEW_AUDIT.json
python3 -m unittest discover -s . -p 'test_*.py' -v
```

`--out` must be a new file in an existing directory. A rejected review exits with
code 2 and creates no audit. An accepted audit contains format checks, counts,
input hashes and limitations, without copying individual decisions. Verdict counts
are counts of declarations, not validated truth. An existing audit is never overwritten.

## Public packet

Only `cases.json` and the exact source files named in it are opened. No directory
scan, origin map, oracle, CAMI results or other reviewer answers are read. The cases
file is a nonempty JSON list with exactly these fields per object:

```json
{
  "id": "public-case-id",
  "kind": "symbol_exists",
  "subject": {"path": "module.py", "qualname": "example"},
  "predicate": {"type": "symbol_exists"},
  "text": "Exact claim text.",
  "scope": "Exact claim scope.",
  "source_path": "sources/module.py",
  "source_sha256": "64-lowercase-hex-characters"
}
```

Subject and predicate may be nonempty objects or text. All source files must be
UTF-8, match their declared SHA-256, and resolve inside the packet directory.
Absolute paths, backslashes, empty path components, `.` and `..` are rejected.
The packet ID set is derived from this list; no population size is hardcoded.

The packet SHA-256 is SHA-256 of the canonical UTF-8 JSON representation of:

```text
{"cases_sha256": SHA256(exact cases.json bytes),
 "sources": [{"source_path": PATH, "source_sha256": HASH}, ...]}
```

The source inventory is unique by relative path and sorted by that path. JSON is
serialized using `sort_keys=True, separators=(',', ':'), ensure_ascii=False,
allow_nan=False`. `compute_packet_identity(Path(...))` computes this identity while
checking source integrity. Manifest whitespace changes therefore change identity.
Unreferenced files have no part in the identity and are never opened.

## Review

The complete format is in `review.schema.json`; runtime checks also bind it to the
packet. A record has this header and exactly one item for every public case:

```json
{
  "schema_version": 1,
  "reviewer_kind": "ai_reviewer",
  "human": false,
  "provider": "codex",
  "model": "codex:gpt-6.1-sol",
  "reasoning_effort": "high",
  "agent_task": "/root/your-review-task",
  "identity_basis": "declared_invocation",
  "independence_disclosure": "Model weights and training independence are unverified.",
  "packet_sha256": "64-lowercase-hex-characters",
  "items": [
    {
      "id": "public-case-id",
      "source_sha256": "64-lowercase-hex-characters",
      "verdict": "uncertain",
      "extracted_facts": "Describe the observed facts, including limitations.",
      "reasoning": "Explain why these facts lead to the declared verdict.",
      "scope_notes": "Explain the scope interpreted and any limitation.",
      "evidence": [
        {"source_path": "sources/module.py", "available": true, "line_start": 1, "line_end": 3}
      ]
    }
  ]
}
```

Model metadata describes a declared invocation. The validator cannot authenticate
the actual model, distinguish weights, or establish training/error independence.
The supplied pilot identity is `codex:gpt-6.1-sol`, effort `high`; schema validation
allows other explicitly declared invocations without certifying their identity.

Every item requires nonempty facts, reasoning and scope notes. Facts may also be
a nonempty object or array. `supported` and `contradicted` require at least one
available source citation; every citation must name that case's sealed source and
have integer inclusive line bounds. Source lines are delimited by `\n`, with no
extra line counted for a trailing newline; empty source has zero lines. Boolean
line numbers are rejected.

`uncertain` also requires reasoning but may have no citations. It may document
unavailable evidence with this alternate evidence entry:

```json
{"source_path": "sources/module.py", "available": false,
 "explanation": "Explain what evidence needed for this claim is unavailable."}
```

Here the source path still names the sealed source; `available=false` describes a
missing evidentiary basis such as runtime behavior, not permission to reference
unsealed files. The packet source itself must remain available and hash-valid.
Evidence relevance and the adequacy of explanations are review responsibilities;
the harness checks only presence and structure. Agreement is never converted to
labels, and human authorship is never inferred from an agent identifier.
