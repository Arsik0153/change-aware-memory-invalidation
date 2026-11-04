# Bounded Packaging offline corpus

`export/packaging-development-v2-offline.tar.gz` contains the local Git objects needed for exactly 72 authorized Packaging snapshots: three parent commits and their 69 first-parent successors. The archive is 1,130,413 bytes; SHA-256:

```text
423fbc71a9fc7a56b346c8dfb065c830f44db64ab1a78708e8db76749a12b81f
```

This is **not complete Git history or a full dataset backup**. The existing object store includes historical commit/tree metadata acquired before the source phases. Those object files are retained byte for byte, but completeness is asserted only for the 72 authorized snapshot trees and their 296 distinct blobs. No outside snapshot trees were queried, and no `git fsck`, history-object traversal, checkout, source execution or project import was used.

The tar contains:

- `repo/.git/objects/`: 44 existing object files, totaling 1,151,695 bytes, including pack/index/reverse-index/promisor files.
- A synthetic detached `repo/.git/HEAD` pinned to boundary `f58537628042c7f29780b9d33f31597e7fc9d664`.
- A sanitized local `.git/config` with no remote or credential settings, disabled hooks/automatic maintenance, and `protocol.allow=never`.
- Empty refs and necessary directories; no original refs, remotes, hooks, logs, index, checkout or credentials.
- `corpus-manifest.json`: every archived repository file's SHA-256 and size, all 72 commit/tree-output SHA-256 bindings, all 296 blob OIDs/sizes/content SHA-256 values, and exact acquisition/run/protocol/seal hashes.

The original acquisition recorded OIDs and sizes without reading bodies. This export's authorized read measured each of the 296 original blob bodies, checked its native Git SHA-1 and recorded a SHA-256 baseline. The fresh extracted copy matches that baseline, the acquisition sizes/OIDs, and all saved raw `ls-tree -rz --full-tree` hashes. The original repository's complete 108-file SHA-256/size/mode inventory is identical before and after.

## Verify a fresh extraction offline

The helper uses Python's standard library plus Git and Linux `unshare`. Network namespace creation must be permitted. It fails if isolation is unavailable; it does not silently fall back to network-enabled Git.

```sh
.venv/bin/python scripts/package_packaging_offline.py verify \
  --archive reports/research-20261104/packaging-offline-corpus-v1/packaging-development-v2-offline.tar.gz \
  --expected-sha256 423fbc71a9fc7a56b346c8dfb065c830f44db64ab1a78708e8db76749a12b81f \
  --out <new-extraction-directory>
```

Verification rejects unsafe/duplicate tar entries and nonminimal Git files, checks archive/file hashes, then runs 74 Git commands in isolated network namespaces: HEAD resolution, 72 exact allowlisted trees, and one 296-blob batch. Each command also denies all Git transports, disables lazy fetch, ignores inherited Git configuration/environment, disables replacement objects and optional locks, and records command/output hashes. No remote endpoint exists in the extracted configuration.

The new directory contains `repo/`, the embedded manifest, `commands.jsonl` and `verification.json`. To reproduce the sealed experiment, use a separate replay workspace with its original code and evidence artifacts and place this `repo/` at the frozen protocol's `data/corpora/packaging-development-v1` path. The archive alone is the bounded project corpus, not the CAMI runtime, AI responses or experiment evidence. Do not overwrite an existing mutable repository. Read-only snapshot access uses explicit commit IDs; no checkout is needed.

## Rebuild and evidence

From the original workspace, using the unchanged already-authorized local store:

```sh
.venv/bin/python scripts/package_packaging_offline.py build \
  --source data/corpora/packaging-development-v1 --out <new-export-directory>
.venv/bin/python scripts/check_packaging_offline.py \
  --archive reports/research-20261104/packaging-offline-corpus-v1/packaging-development-v2-offline.tar.gz \
  --expected-sha256 423fbc71a9fc7a56b346c8dfb065c830f44db64ab1a78708e8db76749a12b81f \
  --out <new-control-directory>
```

`build` hash-pins the original acquisition manifest, completed replay manifest and exact final protocol before reading blobs. It archives existing object files directly without a staging-store duplicate, builds the archive twice using sorted USTAR members and fixed gzip/tar metadata, and demonstrates byte identity in the current compression environment. The temporary second archive is removed. One extracted verification copy is retained as evidence.

`export/manifest.json` records archive size/hash, source bindings and evidence hashes. `source-before.json` and `source-after.json` show unchanged original files. `original-read-commands.jsonl` records the one original 296-blob batch. `extracted/commands.jsonl` and `extracted/verification.json` preserve the successful offline verification. `controls.json` records rejection of a wrong archive hash, a rehashed extra hook, and a rehashed missing object pack; the last exercises actual bounded Git content completeness rather than only the external archive hash.

The original export was created in ignored staging without modifying the source repository. Root then installed the unchanged verifier and a parameterized control runner, copied this file-only evidence mirror, and independently repeated offline verification and all three tamper controls. The extracted Git repositories remain outside this evidence directory; the tar preserves their necessary bytes. This packaging task did not rerun the experiment or access new project snapshots.
