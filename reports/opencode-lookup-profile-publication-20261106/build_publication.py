"""Archive existing profile evidence only; never execute a profile/model/target."""

from __future__ import annotations

import difflib
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import resource
import stat
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BASE = "runs/opencode-lookup-profile-20261106"
CAND = "runs/opencode-membership-candidate-20261106"
PRIVATE = {
    ".git",
    "private-state",
    "server-private",
    "private-export-client",
    ".ssh",
    ".codex",
    "workspace",
    "cami-state",
}
SENSITIVE = {
    "access_token",
    "refresh_token",
    "id_token",
    "api_key",
    "apikey",
    "authorization",
    "encrypted_content",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (
        json.dumps(
            value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
        ).encode()
        + b"\n"
    )


def safe(name):
    p = Path(name)
    if p.is_absolute() or ".." in p.parts or str(p) != name or any(x in PRIVATE for x in p.parts):
        raise ValueError("unsafe/private publication path")
    if p.name.startswith(("session.db", "opencode.db", "auth.db")) or p.name in {
        "auth.json",
        "credentials.json",
        "service.json",
    }:
        raise ValueError("credential database/config refused")


def raw_file(path):
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError("symlink input refused")
    a = path.lstat()
    if (
        not stat.S_ISREG(a.st_mode)
        or a.st_nlink != 1
        or a.st_mode & 0o7000
        or a.st_size > 128 * 1024**2
    ):
        raise ValueError("nonordinary/hardlinked/privileged/oversize input refused")
    raw = path.read_bytes()
    b = path.lstat()
    assert (a.st_ino, a.st_size, a.st_mtime_ns, a.st_ctime_ns) == (
        b.st_ino,
        b.st_size,
        b.st_mtime_ns,
        b.st_ctime_ns,
    )
    return raw, stat.S_IMODE(a.st_mode)


def privacy(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.casefold() in SENSITIVE and item not in (None, "", False, [], {}):
                if not isinstance(item, str) or not item.startswith(("[REDACTED", "${", "$env:")):
                    raise ValueError("credential-valued field refused")
            privacy(item)
    elif isinstance(value, list):
        for item in value:
            privacy(item)
    elif isinstance(value, str):
        if re.search(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", value) or re.search(
            r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._+/=-]{20,}", value
        ):
            raise ValueError("credential-shaped text refused")
        if value.lstrip().startswith(("{", "[")):
            try:
                decoded = json.loads(value)
            except ValueError:
                return
            privacy(decoded)


class Pack:
    def __init__(self):
        self.files, self.sources, self.coverage = {}, {}, []

    def add(self, path, expected=None, name=None):
        path = Path(path)
        if not path.is_absolute():
            path = ROOT / path
        name = name or str(path.relative_to(ROOT))
        safe(name)
        raw, mode = raw_file(path)
        if expected is not None:
            assert sha(raw) == expected, "input hash mismatch: " + name
        if path.suffix in {".json", ".jsonl"}:
            values = (
                [json.loads(x) for x in raw.splitlines() if x.strip()]
                if path.suffix == ".jsonl"
                else [json.loads(raw)]
            )
            for value in values:
                privacy(value)
        elif path.suffix in {".txt", ".log"}:
            privacy(raw.decode("utf-8", errors="replace"))
        value = (raw, mode)
        assert name not in self.files or self.files[name] == value
        self.files[name] = value
        self.sources[str(path)] = sha(raw)
        return raw

    def generated(self, name, raw):
        safe(name)
        assert name not in self.files
        self.files[name] = (raw, 0o644)

    def json(self, path):
        return json.loads(raw_file(ROOT / path)[0])

    def inventory(self):
        for label, base, manifest_name in [
            ("baseline", BASE, "baseline-manifest.json"),
            ("candidate1", CAND, "manifest.json"),
        ]:
            m = self.json(base + "/" + manifest_name)
            self.add(base + "/" + manifest_name)
            for name, expected in m["files"].items():
                self.add(base + "/" + name, expected)
            # Preserve additional publication-time logs; these were not original manifest pins.
            extras = []
            for path in sorted((ROOT / base).iterdir()):
                if path.is_file() and path.name not in m["files"] and path.name != manifest_name:
                    self.add(path)
                    extras.append(path.name)
            report = self.json(base + "/profile-v1/report.json")
            assert report["status"] == "passed" and report["model_calls"] == 0
            admitted, omitted = {}, {}
            for name, expected in report["artifact_hashes"].items():
                parts = Path(name).parts
                if "workspace" in parts or ".git" in parts or "cami-state" in parts:
                    omitted[name] = {
                        "declared_sha256": expected,
                        "reason": "full workspace/Git or ProductMemory state body excluded; original declared SHA retained, body not reread/reverified",
                    }
                else:
                    self.add(base + "/profile-v1/" + name, expected)
                    admitted[name] = expected
            assert len(admitted) + len(omitted) == m["raw_profile_artifacts_bound"]
            self.coverage.append(
                {
                    "role": label,
                    "original_declared_artifacts": len(report["artifact_hashes"]),
                    "included_declared_artifacts": len(admitted),
                    "omitted_declared_artifacts": len(omitted),
                    "included": admitted,
                    "omitted_hash_only": omitted,
                    "extra_top_level_files_publication_snapshot": extras,
                }
            )
        plans = [self.json(base + "/profile-v1/profile-plan.json") for base in [BASE, CAND]]
        assert (
            plans[0]["arguments"] == plans[1]["arguments"]
            and plans[0]["image"] == plans[1]["image"]
        )
        eq = self.json(CAND + "/equivalence.json")
        old, new = eq["baseline_files"], eq["candidate_files"]
        assert set(old) == set(new)
        differences = [name for name in old if old[name] != new[name]]
        assert differences == ["cami/index.py"]
        for role, plan in zip(["baseline", "candidate1"], plans, strict=True):
            for kind, pin in plan["source_pins"].items():
                for name, expected in pin["files"].items():
                    self.add(Path(pin["root"]) / name, expected)
            assert plan["source_pins"]["production"]["files"] == (
                old if role == "baseline" else new
            )
        assert plans[0]["source_pins"]["adapter"] == plans[1]["source_pins"]["adapter"]
        base_index = Path(plans[0]["source_pins"]["production"]["root"]) / "cami/index.py"
        cand_index = Path(plans[1]["source_pins"]["production"]["root"]) / "cami/index.py"
        diff = "".join(
            difflib.unified_diff(
                raw_file(base_index)[0].decode().splitlines(True),
                raw_file(cand_index)[0].decode().splitlines(True),
                fromfile="baseline/cami/index.py",
                tofile="candidate1/cami/index.py",
            )
        )
        self.generated("publication-analysis/source-comparison.patch", diff.encode())
        study_path = "runs/opencode-development-v5-20261104/frozen-study.json"
        study_raw = self.add(study_path, plans[0]["study_sha256"])
        assert plans[1]["study_sha256"] == sha(study_raw)
        study = json.loads(study_raw)
        assert study["bundle_kind"] == "development"
        worker = "scripts/opencode_benchmark/controller/preparation_worker.py"
        assert plans[0]["preparation_worker_sha256"] == plans[1]["preparation_worker_sha256"]
        self.add(worker, plans[0]["preparation_worker_sha256"])
        current = {}
        for name in [
            "study_common.py",
            "study_runtime.py",
            "study_workspace.py",
            "study_schema.py",
            "memory_seed_schema.py",
        ]:
            path = "scripts/opencode_benchmark/controller/" + name
            raw = self.add(path, name="publication-context/current-controller/" + name)
            current[name] = {
                "sha256": sha(raw),
                "source_path": path,
                "role": "publication-time corroboration, not independently execution-hashed at profile start",
            }
        frozen = {}
        source_tar = ROOT / "reports/opencode-study-design-v5-20261104/runtime-source.tar"
        with tarfile.open(source_tar) as archive:
            for name, expected in study["pins"]["controller"]["files"].items():
                member = archive.getmember("scripts/opencode_benchmark/controller/" + name)
                assert member.isfile()
                raw = archive.extractfile(member).read()
                assert sha(raw) == expected
                self.generated("publication-context/frozen-study-controller/" + name, raw)
                frozen[name] = expected
        self.generated(
            "publication-analysis/source-provenance.json",
            canonical(
                {
                    "only_core_file_difference": differences,
                    "baseline_core_inventory": old,
                    "candidate1_core_inventory": new,
                    "profile_plan_explicit_pins": [
                        "production",
                        "adapter",
                        "profile_worker.py",
                        "orchestrator",
                        "preparation_worker.py",
                    ],
                    "controller_start_time_loaded_byte_identity": "Not separately recorded; never retroactively inferred.",
                    "controller_publication_snapshot": current,
                    "frozen_study_controller_expected": frozen,
                    "frozen_study_controller_source_tar_sha256": sha(raw_file(source_tar)[0]),
                    "input_boundary": "Full task archive/workspace payloads and original model transcript are external, hash-referenced inputs; not included here. Exact profile query/config/seed/catalog/reset inventories are included.",
                }
            ),
        )
        for name in ["build_publication.py", "reproduce_comparison.py", "README.md"]:
            self.add(OUT / name)
        self.generated(
            "publication-analysis/coverage.json",
            canonical(
                {
                    "status": "explicit_partial_raw_payload_archive",
                    "groups": self.coverage,
                    "no_models_or_profile_reruns": True,
                    "omitted_bodies_read_by_packager": False,
                }
            ),
        )

    def archive(self, path):
        metadata = {
            "schema_version": 1,
            "status": "public_profile_attribution_evidence_only",
            "files": {
                name: {"sha256": sha(raw), "bytes": len(raw), "mode": mode}
                for name, (raw, mode) in sorted(self.files.items())
            },
            "boundary": "All selected profiler/MCP/preparation/source payloads exact; original omitted workspace/Git/memory-state SHA lists retained. No claim of all-original-raw-payload coverage.",
            "profile_timing": "Instrumented attribution with cProfile/concurrency; never a quiet or end-to-end/model speedup claim.",
        }
        entries = {**self.files, "PUBLICATION-MANIFEST.json": (canonical(metadata), 0o644)}
        with (
            path.open("xb") as target,
            gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0, compresslevel=6) as gz,
        ):
            with tarfile.open(fileobj=gz, mode="w|", format=tarfile.USTAR_FORMAT) as archive:
                for name, (raw, mode) in sorted(entries.items()):
                    info = tarfile.TarInfo(name)
                    info.size = len(raw)
                    info.mode = mode
                    info.mtime = 0
                    info.uid = info.gid = 0
                    archive.addfile(info, io.BytesIO(raw))
        return {
            "sha256": sha(path.read_bytes()),
            "bytes": path.stat().st_size,
            "regular_members_including_manifest": len(entries),
        }


def main():
    started, cpu = time.monotonic(), time.process_time()
    pack = Pack()
    try:
        pack.inventory()
        path = OUT / "public-profile-evidence.tar.gz"
        record = pack.archive(path)
        repeat = OUT / "public-profile-evidence.repeat.tar.gz"
        assert pack.archive(repeat) == record
        repeat.unlink()
        extracted = OUT / "extracted"
        extracted.mkdir()
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            assert len(members) == len(pack.files) + 1
            assert len({m.name for m in members}) == len(members)
            for member in members:
                safe(member.name)
                assert member.isfile() and not member.linkname
                raw = archive.extractfile(member).read()
                target = extracted / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                target.chmod(member.mode)
                if member.name != "PUBLICATION-MANIFEST.json":
                    assert (raw, member.mode) == pack.files[member.name]
        for source, expected in pack.sources.items():
            assert sha(raw_file(Path(source))[0]) == expected
        report = {
            "status": "passed",
            "archive": record,
            "byte_identical_second_build": True,
            "extracted_sha_sizes_modes_match": True,
            "all_admitted_originals_unchanged": True,
            "payload_files": len(pack.files),
            "coverage": [
                {k: v for k, v in group.items() if k not in ["included", "omitted_hash_only"]}
                for group in pack.coverage
            ],
            "model_calls": 0,
            "profile_reruns": 0,
            "Docker_calls": 0,
            "network_calls": 0,
            "workspace_or_memory_state_bodies_read": False,
            "overhead": {
                "wall_seconds": time.monotonic() - started,
                "cpu_seconds": time.process_time() - cpu,
                "scope": "publication hashing/double compression/extraction only, never trial/profile cost",
            },
            "python": __import__("sys").version,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
        (OUT / "packaging-report.json").write_bytes(canonical(report))
        print(json.dumps(report))
    except BaseException as error:
        (OUT / "packaging-failure.json").write_bytes(
            canonical(
                {"status": "failed_preserved", "type": type(error).__name__, "reason": str(error)}
            )
        )
        raise


if __name__ == "__main__":
    main()
