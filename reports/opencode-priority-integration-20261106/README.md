# Explicit OpenCode request service tier

The installed pinned OpenCode **2.2.5** supports `providers.openai.models["gpt-6.1-sol"].settings.serviceTier = "priority"`. This keeps `openai/gpt-6.1-sol#high` and its high reasoning setting. There is no separate verified `fast` boolean. An explicit `auto` setting is also accepted; omission retains the legacy configuration exactly.

The binary SHA256 is `8d060e1d2fbb9bb44cf09ae6ed1f3f6a7cff070b5227e2f90970132b23a92050`. Exact embedded native Responses adapter excerpts and byte offsets are retained here. The native adapter maps `serviceTier` to wire `service_tier`. The legacy OpenAI Codex OAuth plugin redirects the route/auth and adds headers without dropping that setting. The incoming Responses adapter maps `response.service_tier` into provider metadata.

## Installed-binary controls

`proof_request.py` ran the actual binary inside the pinned existing image with **Docker network=none**, isolated temporary OpenCode/XDG state and synthetic `chatgpt-headless` OAuth sentinel credentials only. A temporary authored plugin captured selected nonsecret request fields and threw before transport. `proof-01/wire-selected.json` confirms `/backend-api/codex/responses`, model `gpt-6.1-sol`, reasoning effort `high`, `service_tier=priority`, and authorization-header presence. No header value, real credential, account data or prompt body was captured. This verifies serialization through the Codex auth branch, not real account entitlement or provider scheduling.

`proof_response.py` used the same network-none isolation with a local authored HTTP/SSE stub. An authored response containing `service_tier=priority` completed successfully; the real installed API exposed it as assistant **`/native/serviceTier`**. See `proof-02/response-metadata-shape.json`. This is a synthetic response mapping control, not evidence that a real provider served priority. Temporary fake credential databases existed only in the container's ephemeral `/tmp` and were destroyed with the container.

## Implemented boundary

The seven implementation/test files are pinned in `handoff.json` and copied under `source/`. The new optional study field is `service_tier`; `study_controller.py --make-study ... --service-tier priority` freezes it. The flag cannot override an already loaded study. The controller passes the same value to each arm's harness, verifies host requested/configured values and the hashed observed native Responses model/high variant, and preserves the rest of the model/tool/resource settings. New studies must use a separately supported protocol/cohort; historical reports, frozen studies and thresholds are untouched. The parent separately owns the historical-protocol admission guard.

The harness emits `evidence/service-tier.json` only for explicit tiers. The report separates:

- `requested` / `configured`: frozen intent and effective model setting; not evidence of actual service.
- `request_on_wire_observed_for_this_session=false`: normal studies do not add a transport interception plugin. The separate pinned synthetic control proves the implementation mapping.
- `assistant_response_observations`: only message ID, completion timestamp, the safe scalar from `/native/serviceTier`, status and source pointer, collected before the existing opaque-native scrub. All other native/auth fields remain excluded.
- `actual_served`: populated only for a nonempty, complete paginated assistant export with matching observation IDs, every assistant completed, every tier reported and one uniform tier. Mixed values, missing/malformed fields or partial exports preserve values/missingness and leave this field null. Provider metadata is reported service, not an independent audit of backend scheduling, entitlement, billing or speed.

Failure export also retains this minimal response projection when available. Evidence-write failure joins normal finalization errors instead of skipping cleanup. No default service tier or default model changed; the legacy full configuration golden controls remain equal.

## Verification and preserved setup failures

The final stable-source no-model checks passed **plain/static/CAMI**: `final-preflight.json`; exact source-before/after hashes match. Each `preflight-04/ARM/final-session/manifest.json` has `status=passed`, `model_requested=false`, **`state_removed=true`**. Each corresponding `final-private-state` path is absent. Worker `evidence/manifest.json` records zero model-session launches; `evidence/service-tier.json` records configured high+priority and actual served unavailable. These are startup/configuration/MCP-connectivity checks; they do not claim a memory lookup, task solution, speed improvement or paid-model success.

129 targeted controller/harness controls passed (`targeted-tests-final.txt`); after the final completed-assistant completeness tightening, all 31 service-tier controls passed (`service-tier-tests-final.txt`). Ruff passes for all seven changed files (`ruff-final.txt`). The parent runs broader suites separately. Additional controls cover legacy omission, all-arm parity, invalid settings, loaded-study override denial, high/variant override mismatch, controller forwarding/mismatch, response-only provenance, mixed/malformed/missing tiers, partial pagination and same-message incomplete-to-complete updates.

Early setup/control errors are retained without overwriting: the first test run reused an exclusive output path in its negative fixture; authored preparation attempts 1–3 respectively omitted the adapter import path, selected an unsupported static seed kind, and used the wrong temporary Git ownership. Their source snapshots, stdout/stderr and output directories remain here. Corrected authored setup uses a source-asserted note and owned UID65534 workspace. No production adapter change, task tuning, real model call or real account credential access resulted from these fixture corrections.

No commits were created by this agent. No new measured study was launched. Do not interpret these correctness controls as benchmark timing evidence.
