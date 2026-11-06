"""Archive sealed candidate2/quiet evidence; never rerun a lookup/model/target."""

from __future__ import annotations

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
C2 = "runs/opencode-indexed-transition-candidate-20261106"
QUIET = "runs/opencode-quiet-lookup-confirmation-20261106"
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
        seals = {
            C2: "6cbc3376a042a68983727cfc5cb57682e47a4d8c7c696c5effa2d085e3dd8b1a",
            QUIET: "762e7b59bfaef1114733b9e520e6f2ecdc4084c4aacbae6812b86e0242721676",
        }
        for base, expected in seals.items():
            self.add(base + "/manifest.json", expected)
            manifest = self.json(base + "/manifest.json")
            for name, checksum in manifest["files"].items():
                self.add(base + "/" + name, checksum)
            for path in sorted((ROOT / base).iterdir()):
                if (
                    path.is_file()
                    and path.name != "manifest.json"
                    and path.name not in manifest["files"]
                ):
                    self.add(path)
        report = self.json(C2 + "/profile-v1/report.json")
        assert report["status"] == "passed" and report["model_calls"] == 0
        admitted, omitted = {}, {}
        for name, expected in report["artifact_hashes"].items():
            if any(x in {"workspace", ".git", "cami-state"} for x in Path(name).parts):
                omitted[name] = {
                    "declared_sha256": expected,
                    "reason": "workspace/Git or memory state body excluded; original declared SHA only, body not reread",
                }
            else:
                self.add(C2 + "/profile-v1/" + name, expected)
                admitted[name] = expected
        self.coverage.append(
            {
                "role": "candidate2-instrumented",
                "original_declared_artifacts": len(report["artifact_hashes"]),
                "included_declared_artifacts": len(admitted),
                "omitted_declared_artifacts": len(omitted),
                "included": admitted,
                "omitted_hash_only": omitted,
            }
        )
        report = self.json(QUIET + "/quiet-v1/report.json")
        assert (
            report["status"] == "passed"
            and not report["failures"]
            and len(report["attempts"]) == 15
        )
        admitted, omitted = {}, {}
        for attempt in report["attempts"]:
            namespace = f"b{attempt['block']}-{attempt['variant']}"
            assert attempt["status"] == "passed"
            for name, expected in attempt["artifact_hashes"].items():
                key = namespace + "/" + name
                if any(x in {"workspace", ".git", "cami-state"} for x in Path(name).parts):
                    omitted[key] = {
                        "declared_sha256": expected,
                        "reason": "workspace/Git or memory state body excluded; original declared SHA only, body not reread",
                    }
                else:
                    self.add(QUIET + "/quiet-v1/" + key, expected)
                    admitted[key] = expected
        assert len(admitted) + len(omitted) == 6135
        self.coverage.append(
            {
                "role": "quiet-unprofiled",
                "original_declared_artifacts": 6135,
                "included_declared_artifacts": len(admitted),
                "omitted_declared_artifacts": len(omitted),
                "included": admitted,
                "omitted_hash_only": omitted,
            }
        )
        freeze = self.json(C2 + "/source-freeze.json")
        plan = self.json(QUIET + "/quiet-v1/plan.json")
        for variant, pin in plan["variants"].items():
            for name, expected in pin["files"].items():
                self.add(Path(pin["root"]) / name, expected)
        assert plan["variants"]["candidate2"]["files"] == freeze["candidate_files"]
        assert plan["variants"]["baseline"]["files"] == freeze["baseline_files"]
        differences = [
            n
            for n in freeze["baseline_files"]
            if freeze["baseline_files"][n] != freeze["candidate_files"][n]
        ]
        assert (
            set(differences)
            == set(freeze["changed_core_files"])
            == {"cami/index.py", "cami/product/memory/validation.py", "cami/product/service.py"}
        )
        for base, pins in [
            (C2, freeze["controller_helper_snapshot"]),
            (QUIET, plan["helper_snapshot"]),
        ]:
            for name, expected in pins.items():
                self.add(base + "/controller-snapshot/" + name, expected)
        profile_plan = self.json(C2 + "/profile-v1/profile-plan.json")
        for pin in profile_plan["source_pins"].values():
            for name, expected in pin["files"].items():
                self.add(Path(pin["root"]) / name, expected)
        self.add(
            "runs/opencode-lookup-profile-publication-20261106/public-profile-evidence.tar.gz",
            "dad2a64d060cbd8144f78487711e88862b442670d34465d6a2e52731bf2ef435",
            name="prerequisites/baseline-candidate1-public-profile-evidence.tar.gz",
        )
        verification = self.json(QUIET + "/additional-verification.json")
        self.add(
            "scripts/opencode_benchmark/analysis/classify_literal_calls.py",
            verification["receipt_authenticator_source_sha256"],
        )
        for name in [
            "classify_memory_calls.py",
            "literal_reference.py",
            "summarize_terminal_staleness.py",
        ]:
            self.add("scripts/opencode_benchmark/analysis/" + name)
        self.add("scripts/analyze_opencode_staleness.py")
        for name in ["build_publication.py", "reproduce_supplement.py", "README.md"]:
            self.add(OUT / name)
        self.generated(
            "publication-analysis/coverage.json",
            canonical(
                {
                    "status": "explicit_partial_raw_payload_archive",
                    "groups": self.coverage,
                    "omitted_bodies_read_or_reverified": False,
                    "model_calls": 0,
                    "profile_reruns": 0,
                    "prerequisite_archive": {
                        "sha256": "dad2a64d060cbd8144f78487711e88862b442670d34465d6a2e52731bf2ef435",
                        "role": "byte-identical earlier baseline/candidate1 package, unchanged independent evidence frame",
                    },
                }
            ),
        )

    def archive(self, path):
        metadata = {
            "schema_version": 1,
            "status": "candidate2_attribution_and_separate_quiet_evidence",
            "files": {
                name: {"sha256": sha(raw), "bytes": len(raw), "mode": mode}
                for name, (raw, mode) in sorted(self.files.items())
            },
            "boundary": "All selected profiler/MCP/preparation/source payloads exact; original omitted workspace/Git/memory-state SHA lists retained. No claim of all-original-raw-payload coverage.",
            "profile_timing": "Candidate2 instrumented attribution and separate unprofiled quiet local results; preserve the prospective noise rule, never a model/end-to-end speedup claim.",
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
        path = OUT / "candidate2-quiet-public-evidence.tar.gz"
        record = pack.archive(path)
        repeat = OUT / "candidate2-quiet-public-evidence.repeat.tar.gz"
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
