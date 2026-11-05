# Closed v5 publication handoff

Completed; no models, Docker, network, heldout access, tracked edits or commits. All 36 original terminals and all 8,094 declared terminal artifacts are preserved byte-exact, including the original failed `r3-static-s1`. The original result remains 36 quality passes / 35 operational passes, with no exclusions; primary superiority is **not established**.

- `public-evidence.tar.gz`: **25,346,941 bytes**, SHA256 `59b143be6546dc26c0cb54c188e9f6d977993a778a10f57decad6ed630921242`. 8,649 payload files plus one internal manifest (8,650 regular tar members); 93,117,220 payload bytes.
- `final-memory-state.tar.gz`: **5,569,797 bytes**, SHA256 `a4cdf3ea12cfebaf0fc1fc22baef1aaf60690c34335eb7ed80183c9722386e1f`. 84 payload files plus one internal manifest (85 regular tar members); 84,493,060 payload bytes. Three final ProductMemory states are separate from OpenCode auth/private state.

Both archives have full internal SHA/size/mode manifests, identical second builds and successful extracted readback. Original included files passed signature/hash rechecks. All 97 frozen runtime source pins match both the current authorized files and the frozen runtime-source.tar. All six immutable 329-record schema2 catalogs match. Three final CAMI databases have only the expected ProductMemory tables; their 329 literal revisions match the corresponding frozen catalog except the explicitly checked runtime-only source index certificate.

The raw package includes the study's four process logs, first-three-admission and completion-check, published protocol/freeze/runtime source, final aggregate/resource/staleness reports, exact analysis code and canonical staleness inputs. Full namespace workspaces, authentication/private state and all heldout assets are excluded. Exact terminal-declared evaluation workspace files remain included. This is already-public redacted evidence, not an export of private provider state.

The extracted unchanged aggregator reproduced the full original report except its relocated run path; all three CSVs match byte-for-byte. Original terminal hashes/coverage, failed controller-admission diagnostic and runtime-passed distinction remain exact. The extracted unchanged schema2 staleness analysis reproduced its counts and coverage categories. No causal reliance annotations are inferred.

Publication overhead: packaging/admission/double compression/extraction/recheck **16.033s wall / 15.252s CPU**; offline verification+aggregate+staleness **10.028s wall**, with **8.876s completed-child CPU** (parent hash/verification CPU is not included in that child counter). These are evaluation/publication costs, never trial costs.

Publish the two archives, `publication-manifest.json`, `admission.json`, `packaging-report.json`, this handoff, README and two scripts, plus verification/logs if desired. Large extracted verification trees are disposable ignored copies and need not be published twice. Runtime images/OpenCode binary/credentials are external pinned dependencies, not bundled. See README for the exact no-model replay command and privacy/continuation limitations. All requested work is complete; stop here.
