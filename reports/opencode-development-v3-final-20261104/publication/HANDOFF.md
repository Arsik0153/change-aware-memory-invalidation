# Closed v3 publication handoff

Ready for independent review; no tracked writes or commits.

- `public-evidence.tar.gz`: 25,318,799 bytes; SHA-256 `858023276938a2909c1a36a6c25435b79c3e77cc884c2051efb91be365642474`. Contains 8,583 regular files totaling 92,803,869 source bytes.
- `final-memory-state.tar.gz`: 6,527,441 bytes; SHA-256 `29e467ef2bb45fc9c253b2a1171d0f4596d6b91b3d00e5dd177475ec1b359a4b`. Contains 92 regular files totaling 100,544,118 source bytes, limited to final ProductMemory state for three CAMI namespaces.

Both archives have full internal SHA/size/mode manifests, deterministic gzip/tar metadata, an exact matching second build and a verified extracted copy. All 36 terminals and all 8,058 declared terminal files are retained, including exact authorized evaluation workspace files. Namespace workspaces are excluded. All six 329-record immutable catalogs match; final ProductMemory databases have only the expected tables and every stored note revision matches its frozen catalog. No OpenCode/private/auth database was read or admitted.

Historical controller/harness source changed after study closure; four archived files were recovered byte-exact from commit `18188a7` and matched frozen study pins. All admitted originals remained unchanged. Details and source signatures are in `admission.json`.

The offline extracted package passed the existing aggregator unchanged with study override and a separate timing-path relocation derivative. The aggregate summary, all terminal SHA values/artifact coverage and final staleness counts match the archived reports exactly. The raw timing caveat was not modified. Figures, analysis/staleness sources and canonical inputs are included. The later secondary-resource report stays a separate addendum; archives are not rebuilt.

Initial broad metadata admission was refused at an authorization-valued field. `packaging-failure.json` is preserved. The rejected body and unrelated heldout-preflight approval/account inputs are not archived; only the exact referenced timing evidence is included. No unsafe raw quarantine exists.

Observed script spans: refused admission 4.34s wall/2.37s CPU; successful packaging 13.99s wall/13.70s CPU; offline analysis 6.02s wall/4.93s child CPU. These are publication/evaluation overhead, never trial cost; interactive authoring/debug time is outside these spans.

Publish the two archives and small verification/manifests/scripts as desired; unpacked verification directories are retained only in this ignored stage and need not be duplicated in publication. `publication-manifest.json` binds all outputs and logs. See `README.md` for build/replay commands and exact privacy/resource boundaries.
