# Readable memory display prototype

This is an offline projection study of all 24 terminal-pinned v6 memory calls (12 static, 12 CAMI). It changes no tools, tasks, ranking, limits, memory, production code or original results. There were no model calls. Source inputs come from the independently sealed packet roster; the original full result, compact result and receipt are preserved per packet in `analysis-v1/packet-NNN/original.json`.

The useful candidate is ordinary Markdown with a shared JSON header, per-record JSON metadata and fenced Python source (`fenced-v1/packet-NNN/display.md`). It uses no length-prefixed source grammar. Backtick fences exceed every backtick run in the source. A separately flagged newline, needed only to close a fence after a non-newline-terminated source, is removed during exact extraction. CRLF, LF, bare CR and Unicode source bytes are preserved by the verifier. This does not establish that a future UI will preserve them.

| Arm | Original text bytes | Inline control | Pool control | Fenced candidate |
| --- | ---: | ---: | ---: | ---: |
| static, 12 calls | 100091 | 98375 | 98555 | 89087 |
| CAMI, 12 calls | 83383 | 82172 | 82340 | 75074 |

These are exact UTF-8 lengths of the text content the model would receive, compared within each original packet. The fenced candidate's hypothetical serialized MCP JSON totals are 95662 bytes (static) and 81086 bytes (CAMI), versus 108362 and 90660 originally. The outer MCP transport still JSON-escapes text. It was not transmitted or rendered. These numbers measure neither tokens nor model readability, quality, latency or efficiency. The arms returned different packets and record counts; their byte totals are not a treatment-effect comparison.

## Visible contract and audit boundary

`field-policy.json` is the precise field map. Per record, the candidate displays the exact ID, entire subject, span, literal prefix, prefix truncation, trust label, availability and optional state type. Shared metadata retains the exact backend, freshness, selection counts, full selection budget, selection truncation and entire withheld array. Kind and literal format are shared only after checking that every record agrees. Requested limit is copied from the original call trace.

Query echo, old schema/format markers and origin-source provenance are audit-only. The full original source hash/size/index metadata remains unchanged in the original packet; its duplicate path must equal the visible subject path. The projection removes no withheld instruction or trust/freshness claim. Unknown semantic fields fail explicitly. The display is lossless for the essential visible contract, **not** a self-contained encoding of every original provenance field. Byte reduction combines source presentation, shared fields and omitted display-only provenance/query repetition; it cannot be attributed to escaping alone.

The old `original_audit_receipt` authenticates the **original** full/compact result. It does not authenticate the new display. Each derivative has a local SHA binding to its display bytes, field policy, original sidecar, original full/model result and old receipt. This is unsigned integrity metadata, not a production projection receipt. `run_fenced_prototype.py` first independently reauthenticates the old compact receipt with the frozen v6 analysis helper, then uses a separate field-by-field verifier that does not call the encoder. Every literal is extracted and compared exactly. Inputs are rehashed after processing.

## Controls and limitations

The earlier `inline-0` and `pool-0` wrappers remain intact as exploratory negative controls. They round-trip the entire compact object, but require bespoke framing and are not proposed for production. No observed packet repeats an identical source string internally, so pooling has no source-deduplication benefit here. Their small escaping-only headroom does not justify shipping a new codec.

The fenced prototype deliberately accepts only nonempty homogeneous literal packets. Empty/withheld-only, mixed-kind and error responses fail explicitly; a production format needs a specified common format or safe fallback for them. Control bytes outside tab/CR/LF are also refused. A production change would need a distinct format and projection receipt, independently authenticated exact display bytes, observer/analysis compatibility, generic lookup coverage, and actual MCP/OpenCode presentation checks. None is implemented here. Markdown source fences do not prevent prompt injection or prove that a model treats code as data. Original trust labels remain unchanged; literal equality is not evidence of behavioral equivalence.

## Reproduce

Run from the repository root with the sealed public v6 input paths still present:

```sh
.venv/bin/ruff check runs/opencode-readable-projection-prototype-20261106/*.py
.venv/bin/pytest -q runs/opencode-readable-projection-prototype-20261106/test_readable_projection.py runs/opencode-readable-projection-prototype-20261106/test_fenced_projection.py
.venv/bin/python runs/opencode-readable-projection-prototype-20261106/run_fenced_prototype.py --out another-new-readback
```

Output must be a new child directory of this stage; existing outputs are never overwritten. `fenced-readback/` was regenerated with the final source and matched all files of `fenced-v1/` byte for byte. The old controls' fixed-output runner requires a fresh copy of the stage without `analysis-v1/`; its exact executed outputs are retained here. These local helpers are development artifacts, not installed relocatable CLIs.

`handoff-manifest.json` pins the public evidence inventory and inputs. Caches are excluded. `execution.json` records commands, checks and the harmless host `python` launcher error encountered during a preparatory source edit; the explicit `.venv/bin/python` invocation then succeeded. Original source inputs and old controls were not changed.
