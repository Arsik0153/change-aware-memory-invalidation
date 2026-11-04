"""Preserve an authored replay, its Git fixtures and sealed runtime without Git links."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contained_file(root, name):
    path = (root / name).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"not a contained regular-file payload: {name}")
    return path


def run(source, protocol_path, mirror, archive, delivery):
    source, protocol_path, mirror, archive, delivery = (
        path.resolve() for path in (source, protocol_path, mirror, archive, delivery))
    if any(path.exists() for path in (mirror, archive, delivery)):
        raise ValueError("all output locations must be new")
    if any(path.is_relative_to(source) for path in (mirror, archive, delivery)):
        raise ValueError("outputs must be outside the original run")
    manifest_path = source / "manifest.json"
    manifest_hash = sha(manifest_path)
    manifest = json.loads(manifest_path.read_bytes())
    if manifest["status"] != "complete" or manifest["source_before"] != manifest["source_after"]:
        raise ValueError("requires a complete source-stable run")
    if sha(protocol_path) != manifest["protocol_sha256"]:
        raise ValueError("protocol identity mismatch")
    protocol = json.loads(protocol_path.read_bytes())
    if protocol.get("dataset_kind") != "authored_git_histories":
        raise ValueError("only authored Git histories may be packaged by this tool")
    runtime = manifest["seal"]["files"]
    artifacts = manifest["artifact_hashes"]
    for root, inventory in ((ROOT, runtime), (source, artifacts)):
        for name, expected in inventory.items():
            if sha(contained_file(root, name)) != expected:
                raise ValueError(f"input hash mismatch: {name}")
    fixture_count = len(list((source / "git-fixtures").glob("*/.git")))
    if fixture_count != len(protocol["histories"]):
        raise ValueError("authored Git repository count mismatch")
    mirror.mkdir(parents=True)
    for name in artifacts:
        target = mirror / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    shutil.copyfile(manifest_path, mirror / "manifest.json")
    protocol_name = str(protocol_path.relative_to(ROOT))
    seal_name = protocol["seal_path"]
    if json.loads(contained_file(ROOT, seal_name).read_bytes()) != manifest["seal"]:
        raise ValueError("external seal differs from recorded seal")
    readme = ("run/ preserves the complete authored result, local Git databases and fixture symlinks.\n"
              "implementation/ preserves the sealed runtime, protocol and seal. No real corpus is included.\n"
              "Extract into a NEW directory. Audit the published file mirror using --git-fixtures NEW/run/git-fixtures.\n"
              "Historical source verification also uses this research repository's recorded Git commit.\n"
              "The original manifest excludes .git internals and dangling symlinks; this raw archive preserves them too.\n")
    with archive.open("xb") as stream:
        with tarfile.open(fileobj=stream, mode="w:gz", dereference=False) as tar:
            tar.add(source, arcname="run", recursive=True)
            for name in sorted(set(runtime) | {protocol_name, seal_name}):
                tar.add(contained_file(ROOT, name), arcname="implementation/" + name, recursive=False)
            data = readme.encode()
            info = tarfile.TarInfo("README.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    with tarfile.open(archive, "r:gz") as tar:
        for prefix, inventory in (("run/", artifacts), ("implementation/", runtime)):
            for name, expected in inventory.items():
                if hashlib.sha256(tar.extractfile(prefix + name).read()).hexdigest() != expected:
                    raise ValueError(f"archive payload mismatch: {name}")
        links = [{"name": member.name, "target": member.linkname}
                 for member in tar.getmembers() if member.issym()]
    if sha(manifest_path) != manifest_hash or any(sha(source / name) != h for name, h in artifacts.items()):
        raise ValueError("original result changed while packaging")
    receipt = {"status": "verified", "archive_path": str(archive.relative_to(ROOT)),
               "archive_sha256": sha(archive), "archive_bytes": archive.stat().st_size,
               "record_mirror": str(mirror.relative_to(ROOT)), "original_manifest_sha256": manifest_hash,
               "original_artifact_files_checked": len(artifacts), "runtime_files_checked": len(runtime),
               "authored_git_repositories": fixture_count, "preserved_symlinks": links,
               "packager_sha256": sha(Path(__file__)),
               "scope": "File mirror matches original byte inventory; raw archive additionally preserves Git databases and symlinks."}
    with delivery.open("x") as stream:
        stream.write(json.dumps(receipt, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "protocol", "mirror", "archive", "delivery"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.protocol, args.mirror, args.archive, args.delivery)))
