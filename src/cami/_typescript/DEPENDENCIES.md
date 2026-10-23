# Trusted compiler dependency

CAMI loads a compiler path computed by its Python launcher from the per-user cache.
It requires TypeScript version `6.0.3`.
The lockfile records the official npm tarball URL and SHA-512 integrity.

Run `cami setup-typescript` with Node 24 and npm 11. It copies these trusted
manifests into a temporary user-cache directory and runs `npm ci --ignore-scripts`.
Do not run bootstrap in the analyzed repository.
Python package installation does not perform npm installation.
Queries never run npm or target project scripts.
Setup repairs invalid owned caches after verifying a fresh locked install.
The replaced cache remains in a `.invalid-<unique>` quarantine directory.
Queries validate the ready marker, shipped manifests, and compiler checksum.

TypeScript is copyright Microsoft Corporation and is licensed under Apache-2.0.
The npm distribution includes `LICENSE.txt` and `ThirdPartyNoticeText.txt`.
They remain with the installed dependency. CAMI does not vendor compiler implementation files.

Primary references:

- https://raw.githubusercontent.com/microsoft/TypeScript/v6.0.3/package.json
- https://github.com/microsoft/TypeScript/wiki/Using-the-Compiler-API
- https://www.typescriptlang.org/tsconfig/extends.html
