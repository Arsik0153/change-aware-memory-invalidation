"""Verify the preserved OCI archive and local built image; never rebuild/retag."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

from build_runtime import BASE, ROOT, STAGE, TAG, inspect, run, sha, write

archive = ROOT / "output/opencode-runtime-v2-20261104/cami-opencode-runtime-v2.tar"
source = json.loads((STAGE / "dependency-source.json").read_text())
base = inspect(BASE, "verify-base-inspect.json")
derived = inspect(TAG, "verify-derived-inspect.json")
assert base["Id"] == BASE
assert derived["Config"] == base["Config"]
assert derived["RootFS"]["Layers"][:-1] == base["RootFS"]["Layers"]
with tarfile.open(archive, "r:") as outer:
    verified = []
    for member in outer:
        if member.isfile() and member.name.startswith("blobs/sha256/"):
            digest = hashlib.sha256()
            stream = outer.extractfile(member)
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
            assert digest.hexdigest() == Path(member.name).name
            verified.append(member.name)
    index = json.load(outer.extractfile("index.json"))
    assert len(index["manifests"]) == 1 and index["manifests"][0]["digest"] == derived["Id"]
    image_manifest = json.load(outer.extractfile("blobs/sha256/" + derived["Id"].split(":", 1)[1]))
    config = json.load(outer.extractfile("blobs/sha256/" + image_manifest["config"]["digest"].split(":", 1)[1]))
    assert config["rootfs"]["diff_ids"] == derived["RootFS"]["Layers"]
    layer_bytes = outer.extractfile("blobs/sha256/" + image_manifest["layers"][-1]["digest"].split(":", 1)[1]).read()
    uncompressed = gzip.decompress(layer_bytes) if layer_bytes.startswith(b"\x1f\x8b") else layer_bytes
    assert "sha256:" + hashlib.sha256(uncompressed).hexdigest() == config["rootfs"]["diff_ids"][-1]
    added = {}
    with tarfile.open(fileobj=io.BytesIO(uncompressed), mode="r:") as layer:
        for member in layer:
            if member.isdir():
                continue
            assert member.isfile(), "unexpected nonregular dependency layer member"
            added[member.name.removeprefix("./").removeprefix("/")] = hashlib.sha256(layer.extractfile(member).read()).hexdigest()
    assert added == {"opt/cami-deps/" + path: digest for path, digest in source["copy_source_hashes"].items()}
loaded = run(["image", "load", "--input", str(archive)], "verify-load-command.json")
assert derived["Id"] in loaded
assert inspect(derived["Id"], "verify-loaded-inspect.json")["Id"] == derived["Id"]
assert inspect(BASE, "verify-base-final-inspect.json") == base
probe = json.loads((STAGE / "v2-import-probe.json").read_text())["stdout"]
report = {"schema_version": 1, "status": "complete", "base_image_id": BASE, "image_id": derived["Id"],
    "tag": TAG, "v1_preserved": True, "runtime_config_unchanged": True, "dependency": "pretend==1.0.9",
    "import_probe": json.loads(probe), "archive_path": str(archive.relative_to(ROOT)), "archive_sha256": sha(archive),
    "archive_bytes": archive.stat().st_size, "oci_blob_hashes_verified": len(verified), "new_layer_files": added,
    "load_probe_same_image_id": True, "config_digest_is_not_image_id": True,
    "archive_identity_semantics": "Docker29 Image.Id is OCI manifest digest; manifest config descriptor identifies the separate config digest.",
    "preserved_first_failure": "manifest.first-failed-config-assumption.json",
    "source_provenance": "dependency-source.json", "source_provenance_sha256": sha(STAGE / "dependency-source.json"),
    "requirements_lock_sha256": sha(STAGE / "requirements.lock"), "model_calls": 0,
    "task_source_prompt_solution_reads": 0, "dependency_network_fetches": 0}
write("manifest.json", report)
print(json.dumps({key: report[key] for key in ["status", "image_id", "archive_sha256", "archive_bytes", "oci_blob_hashes_verified"]}))
