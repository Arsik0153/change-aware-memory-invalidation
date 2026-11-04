#!/usr/bin/env python3
"""Authored archive tampering controls; no original-corpus Git commands."""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile

STAGE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helper", type=Path, default=STAGE / "package_packaging_offline.py")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    export, archive = args.out.resolve(), args.archive.resolve()
    export.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location("offline_corpus", args.helper.resolve())
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.verify(archive, export / "extracted", args.expected_sha256)
    (export / "corpus-manifest.json").write_bytes((export / "extracted/corpus-manifest.json").read_bytes())
    controls = {}
    with tempfile.TemporaryDirectory(prefix="controls-", dir=export) as directory:
        scratch = Path(directory)

        def rejected(name, path, expected_sha):
            try:
                helper.verify(path, scratch / (name + "-extracted"), expected_sha)
            except (ValueError, KeyError) as exc:
                controls[name] = str(exc)
            else:
                raise AssertionError("forgery accepted: " + name)

        rejected("wrong_archive_hash", archive, "0" * 64)
        manifest = json.loads((export / "corpus-manifest.json").read_text())
        files = {name: export / "extracted" / name for name in manifest["files"]}
        manifest["files"]["repo/.git/hooks/pre-commit"] = {"size": 0, "sha256": helper.digest(b""), "mode": "0644"}
        files["repo/.git/hooks/pre-commit"] = b""
        files["corpus-manifest.json"] = helper.encoded(manifest)
        forged = scratch / "rehashed-extra-hook.tar.gz"
        helper.write_archive(forged, files)
        rejected("rehashed_extra_hook", forged, helper.sha(forged))
        manifest = json.loads((export / "corpus-manifest.json").read_text())
        files = {name: export / "extracted" / name for name in manifest["files"]}
        # Existing pack selected from authorized store inventory; no extra tree traversal.
        removed = "repo/.git/objects/pack/pack-0dca7fed20fabf9089d0534378c05f9eed7ceeaf.pack"
        del files[removed]
        del manifest["files"][removed]
        manifest["object_file_count"] -= 1
        files["corpus-manifest.json"] = helper.encoded(manifest)
        forged = scratch / "rehashed-missing-pack.tar.gz"
        helper.write_archive(forged, files)
        rejected("rehashed_missing_object_pack", forged, helper.sha(forged))
    result = {"status": "passed", "controls_rejected": controls,
              "helper_sha256": helper.sha(args.helper.resolve()),
              "control_script_sha256": helper.sha(Path(__file__)),
              "scope": "Forged copies only; exact allowlisted snapshot Git checks in network namespace; no original source execution or history traversal."}
    helper.save(export / "controls.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
