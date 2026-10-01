from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from cami.artifacts import canonical, digest, file_hash, parse, within, write_bytes, write_json
from cami.errors import InputError, ResourceError
from cami.models import Behavior, Claim, EnvironmentProfile, Record, ValidationResult, Verdict
from cami.repository import Snapshot, materialize


class TestReport(Record):
    nodeid: str
    when: str
    outcome: str
    assertion: bool
    fingerprint: str | None


class ProbePayload(Record):
    python_version: str = ""
    exit_code: int
    collected: tuple[str, ...]
    reports: tuple[TestReport, ...]


class ProbeOutcome(Record):
    outcome: Literal["passed", "assertion_failure", "technical_error"]
    reason: str
    fingerprint: str | None = None
    duration_seconds: float = Field(ge=0)
    log_path: str


@dataclass(frozen=True)
class ProbeContext:
    snapshot: Snapshot
    profile: EnvironmentProfile
    base_dir: Path
    output_dir: Path
    phase: str = "maintenance"


def check_docker(profile: EnvironmentProfile) -> None:
    try:
        info = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                              capture_output=True, timeout=15)
        image = subprocess.run(["docker", "image", "inspect", profile.image], capture_output=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ResourceError(f"Docker unavailable: {exc}") from exc
    if info.returncode or image.returncode:
        raise ResourceError("Docker daemon or pinned image unavailable; prepare the image before run")


def classify(payload: ProbePayload, node_id: str) -> tuple[Literal["passed", "assertion_failure", "technical_error"], str, str | None]:
    if payload.collected != (node_id,):
        return "technical_error", "collection_error", None
    reports = payload.reports
    if len(reports) != 3 or {r.when for r in reports} != {"setup", "call", "teardown"}:
        return "technical_error", "environment_error", None
    if any(r.nodeid != node_id for r in reports):
        return "technical_error", "collection_error", None
    if any(r.outcome != "passed" for r in reports if r.when != "call"):
        return "technical_error", "environment_error", None
    call = next(r for r in reports if r.when == "call")
    if call.outcome == "passed" and payload.exit_code == 0:
        return "passed", "test_passed", None
    if call.outcome == "failed" and call.assertion and payload.exit_code == 1:
        return "assertion_failure", "predicate_mismatch", call.fingerprint
    return "technical_error", "environment_error", None


def combine(outcomes: tuple[ProbeOutcome, ...]) -> tuple[Verdict, str]:
    if len(outcomes) != 3:
        return "insufficient_evidence", "environment_error"
    if all(outcome.outcome == "passed" for outcome in outcomes):
        return "supported", "test_passed"
    if all(outcome.outcome == "assertion_failure" for outcome in outcomes):
        if len({outcome.fingerprint for outcome in outcomes}) == 1:
            return "contradicted", "predicate_mismatch"
    if len({(o.outcome, o.reason, o.fingerprint) for o in outcomes}) > 1:
        return "insufficient_evidence", "flaky"
    return "insufficient_evidence", outcomes[0].reason


def execute_probe(claim: Claim, context: ProbeContext) -> ValidationResult:
    predicate = claim.predicate
    assert isinstance(predicate, Behavior)
    probe = within(context.base_dir, predicate.probe_path)
    if file_hash(probe) != predicate.probe_sha256:
        raise InputError("frozen probe changed")
    profile = context.profile
    started, cpu = time.perf_counter(), time.process_time()
    key = digest({"claim": digest(claim), "commit": context.snapshot.revision,
                  "profile": profile.model_dump(mode="json"), "probe_runner": file_hash(Path(__file__).with_name("probe_runner.py"))})
    logs = context.output_dir / "logs" / context.phase / key
    logs.mkdir(parents=True, exist_ok=True)
    outcomes: list[ProbeOutcome] = []
    with tempfile.TemporaryDirectory(prefix="cami-probe-") as temporary:
        root = Path(temporary)
        repository = root / "repo"
        try:
            materialize(context.snapshot, repository)
        except ResourceError as exc:
            write_bytes(logs / "materialize.txt", str(exc).encode())
            return ValidationResult(claim_id=claim.claim_id, commit=context.snapshot.revision,
                validator="behavior", verdict="insufficient_evidence", reason="environment_error",
                input_hash=key, duration_seconds=time.perf_counter()-started,
                logs=(str((logs / "materialize.txt").relative_to(context.output_dir)),))
        probes = root / "probe"
        probes.mkdir()
        shutil.copyfile(probe, probes / probe.name)
        runner = root / "runner.py"
        shutil.copyfile(Path(__file__).with_name("probe_runner.py"), runner)
        for repetition in range(3):
            name = "cami-" + uuid.uuid4().hex
            command = ["docker", "run", "--rm", "--pull", "never", "--name", name,
                       "--network", "none", "--read-only", "--user", profile.user,
                       "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                       "--cpus", str(profile.cpus), "--memory", f"{profile.memory_mib}m",
                       "--memory-swap", f"{profile.memory_mib}m", "--pids-limit", str(profile.pids_limit),
                       "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m", "--workdir", "/tmp",
                       "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
                       "--mount", f"type=bind,src={repository},dst=/repo,readonly",
                       "--mount", f"type=bind,src={probes},dst=/probe,readonly",
                       "--mount", f"type=bind,src={runner},dst=/runner.py,readonly",
                       profile.image, "python", "/runner.py", "/probe/" + predicate.node_id,
                       *["/repo" if path == "." else "/repo/" + path for path in profile.source_paths]]
            tick = time.perf_counter()
            log_path = logs / f"repeat-{repetition}.log"
            outcome: Literal["passed", "assertion_failure", "technical_error"] = "technical_error"
            reason, fingerprint = "environment_error", None
            try:
                process = subprocess.run(command, capture_output=True, timeout=profile.timeout_seconds)
                output = process.stdout + b"\nSTDERR:\n" + process.stderr
                write_bytes(log_path, output)
                markers = [line[len(b"CAMI_RESULT="):] for line in process.stdout.splitlines() if line.startswith(b"CAMI_RESULT=")]
                if markers and process.returncode == 0:
                    payload = ProbePayload.model_validate_json(canonical(parse(markers[-1].decode())))
                    if payload.python_version == profile.python_version:
                        outcome, reason, fingerprint = classify(payload, predicate.node_id)
            except subprocess.TimeoutExpired as exc:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
                write_bytes(log_path, (exc.stdout or b"") + (exc.stderr or b""))
                reason = "timeout"
            except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
                write_bytes(log_path, str(exc).encode())
            record = ProbeOutcome(outcome=outcome, reason=reason, fingerprint=fingerprint,
                                  duration_seconds=time.perf_counter()-tick,
                                  log_path=str(log_path.relative_to(context.output_dir)))
            write_json(logs / f"repeat-{repetition}.json", record)
            outcomes.append(record)
    verdict, reason = combine(tuple(outcomes))
    return ValidationResult(claim_id=claim.claim_id, commit=context.snapshot.revision,
        validator="behavior", verdict=verdict, reason=reason,
        evidence=(f"{context.snapshot.revision}:{claim.subject.path}", predicate.probe_sha256),
        input_hash=key, duration_seconds=time.perf_counter()-started, cpu_seconds=time.process_time()-cpu,
        test_executions=3, logs=tuple(outcome.log_path for outcome in outcomes))
