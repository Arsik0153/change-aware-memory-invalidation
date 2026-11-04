"""Copy one verified generic dependency onto the exact local v1 runtime."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time

STAGE = Path(__file__).resolve().parent
ROOT = next(p for p in STAGE.parents if (p / "src/cami").is_dir())
BASE = "sha256:0e055f29b8dd191bc51b16df3046c1f986f77db48b028b65b4fcf27aa49ecdf3"
TAG = "cami-opencode-runtime:development-v2"
DOCKER = ["docker", "--host=unix:///var/run/docker.sock"]


def write(name, value):
    (STAGE / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(args, name, *, stdout_file=None, timeout=300):
    env = dict(os.environ)
    for key in ["DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"]:
        env.pop(key, None)
    env["DOCKER_BUILDKIT"] = "0"
    started = time.monotonic()
    if stdout_file:
        with stdout_file.open("xb") as stream:
            result = subprocess.run([*DOCKER, *args], env=env, stdout=stream, stderr=subprocess.PIPE, timeout=timeout)
        stdout = "[binary archive]"
    else:
        result = subprocess.run([*DOCKER, *args], env=env, capture_output=True, timeout=timeout)
        stdout = result.stdout.decode(errors="replace")
    record = {"argv": [*DOCKER, *args], "returncode": result.returncode, "wall_seconds": time.monotonic() - started,
        "stdout": stdout, "stderr": result.stderr.decode(errors="replace")}
    write(name, record)
    if result.returncode:
        raise RuntimeError("local Docker command failed; preserved " + name)
    return stdout


def inspect(image, name):
    raw = run(["image", "inspect", image], name)
    # No container credentials exist in this source-only image. Preserve only
    # the explicit provenance/config keys needed to compare base and derivative.
    data = json.loads(raw)[0]
    return {key: data[key] for key in ["Id", "RootFS", "Config"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", type=Path, required=True)
    args = parser.parse_args()
    archive_dir = args.archive_dir.resolve()
    assert archive_dir.is_relative_to(ROOT / "output"), "archive must stay under output/"
    report = {"status": "preflight", "base_image_id": BASE, "new_tag": TAG,
        "model_calls": 0, "task_source_prompt_solution_reads": 0, "dependency_network_fetches": 0}
    write("manifest.json", report)
    try:
        assert shutil.disk_usage(ROOT).free >= 5 * 1024**3, "at least5GiB free required"
        source = json.loads((STAGE / "dependency-source.json").read_text())
        deps = STAGE / "context/python-deps"
        assert all(sha(deps / name) == expected for name, expected in source["copy_source_hashes"].items())
        base = inspect(BASE, "base-inspect-command.json")
        assert base["Id"] == BASE and base["Config"]["User"] == "65534:65534"
        # Refuse replacing an existing v2 tag; v1 image and tag remain unchanged.
        check = subprocess.run([*DOCKER, "image", "inspect", TAG], capture_output=True)
        assert check.returncode != 0, "v2 tag already exists; never overwrite"
        probe = "import importlib.util,json; print(json.dumps({'pretend_absent':importlib.util.find_spec('pretend') is None}))"
        assert json.loads(run(["run", "--rm", "--network=none", "--read-only", "--user", "65534:65534", "--workdir", "/", "--entrypoint", "python", BASE, "-c", probe], "v1-import-probe.json"))["pretend_absent"]
        run(["build", "--pull=false", "--network=none", "--tag", TAG, "--file", str(STAGE / "context/Dockerfile"), str(STAGE / "context")], "build-command.json")
        derived = inspect(TAG, "v2-inspect-command.json")
        assert derived["RootFS"]["Layers"][:-1] == base["RootFS"]["Layers"]
        assert derived["Config"] == base["Config"], "runtime config/environment changed beyond dependency layer"
        before = inspect(BASE, "base-after-build-command.json")
        assert before == base, "v1 image changed"
        probe = "import sys,json,hashlib,importlib.metadata,pretend,pytest,pydantic; from pathlib import Path; assert pretend.stub(value=7).value==7; print(json.dumps({'python':sys.version.split()[0],'pretend':importlib.metadata.version('pretend'),'pretend_path':pretend.__file__,'pretend_sha256':hashlib.sha256(Path(pretend.__file__).read_bytes()).hexdigest(),'pytest':pytest.__version__,'pydantic':pydantic.__version__}))"
        result = json.loads(run(["run", "--rm", "--network=none", "--read-only", "--user", "65534:65534", "--workdir", "/", "--entrypoint", "python", derived["Id"], "-c", probe], "v2-import-probe.json"))
        assert result["pretend"] == "1.0.9" and result["pretend_sha256"] == source["copy_source_hashes"]["pretend.py"]
        archive_dir.mkdir(parents=True, exist_ok=False)
        archive = archive_dir / "cami-opencode-runtime-v2.tar"
        run(["image", "save", derived["Id"]], "save-command.json", stdout_file=archive)
        with tarfile.open(archive, "r:") as outer:
            manifests = json.load(outer.extractfile("manifest.json"))
            assert len(manifests) == 1
            manifest = manifests[0]
            config = outer.extractfile(manifest["Config"]).read()
            index = json.load(outer.extractfile("index.json"))
            descriptor = index["manifests"][0]
            assert descriptor["digest"] == derived["Id"]
            image_manifest = outer.extractfile("blobs/sha256/" + derived["Id"].split(":", 1)[1]).read()
            assert "sha256:" + hashlib.sha256(image_manifest).hexdigest() == derived["Id"]
            assert "sha256:" + hashlib.sha256(config).hexdigest() == json.loads(image_manifest)["config"]["digest"]
            added = {}
            with tarfile.open(fileobj=io.BytesIO(outer.extractfile(manifest["Layers"][-1]).read()), mode="r:*") as layer:
                for member in layer:
                    if member.isdir():
                        continue
                    assert member.isfile(), "new dependency layer contains nonregular entry"
                    data = layer.extractfile(member).read()
                    added[member.name.removeprefix("./").removeprefix("/")] = hashlib.sha256(data).hexdigest()
            assert added == {"opt/cami-deps/" + name: digest for name, digest in source["copy_source_hashes"].items()}, "new layer contains unexpected files or overwrites"
        report.update(status="complete", image_id=derived["Id"], import_probe=result, v1_preserved=True,
            runtime_config_unchanged=True, new_layer_files=added, archive_path=str(archive.relative_to(ROOT)),
            archive_sha256=sha(archive), archive_bytes=archive.stat().st_size,
            dockerfile_sha256=sha(STAGE / "context/Dockerfile"), dependency_source_sha256=sha(STAGE / "dependency-source.json"))
    except BaseException as error:
        report.update(status="failed", failure=type(error).__name__ + ": " + str(error))
        raise
    finally:
        write("manifest.json", report)
    print(json.dumps({key: report[key] for key in ["status", "image_id", "archive_path", "archive_sha256", "archive_bytes"]}))


if __name__ == "__main__":
    main()
