"""Launch one owned, resource-limited OpenCode container; default no model."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import time
import uuid

from evidence_safety import collect_private_values, scrub_state_evidence
from trial_guards import git_closure, storage_snapshot

STAGE = Path(__file__).resolve().parent
ROOT = next(p for p in STAGE.parents if (p / "src/cami").is_dir())
BINARY = Path("/root/.opencode/bin/opencode")
IMAGE = "sha256:0e055f29b8dd191bc51b16df3046c1f986f77db48b028b65b4fcf27aa49ecdf3"
EXPECTED_BINARY_SHA = "8d060e1d2fbb9bb44cf09ae6ed1f3f6a7cff070b5227e2f90970132b23a92050"
DOCKER = ["docker", "--host=unix:///var/run/docker.sock"]


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def docker_env():
    result = dict(os.environ)
    for name in ["DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"]:
        result.pop(name, None)
    return result


def command(argv, *, input_bytes=None, timeout=60):
    started = time.monotonic()
    process = subprocess.Popen(argv, env=docker_env(), stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(input_bytes, timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        return {"argv": argv, "returncode": process.returncode, "timed_out": True,
                "wall_seconds": time.monotonic() - started, "stdout": stdout.decode(errors="replace"), "stderr": stderr.decode(errors="replace")}
    return {"argv": argv, "returncode": process.returncode, "wall_seconds": time.monotonic() - started,
            "stdout": stdout.decode(errors="replace"), "stderr": stderr.decode(errors="replace")}


def owned(path, *, create=False):
    if path.is_symlink():
        raise ValueError("trial path cannot be a symlink")
    path = path.resolve()
    if not path.is_relative_to(ROOT / "runs") or path == ROOT / "runs":
        raise ValueError("only explicitly supplied owned trial directories under runs/ are accepted")
    if create:
        path.mkdir(parents=True, exist_ok=False)
    if not path.is_dir() or path.is_symlink():
        raise ValueError("trial mount must be an existing ordinary directory")
    return path


def chown_owned(path):
    os.chown(path, 65534, 65534, follow_symlinks=False)
    for directory, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            os.chown(Path(directory) / name, 65534, 65534, follow_symlinks=False)


def source_inventory(path):
    return {str(p.relative_to(path)): sha(p) for p in sorted(path.rglob("*")) if p.is_file()
            and not any(part in {"__pycache__", ".git", ".pytest_cache", ".ruff_cache"} for part in p.relative_to(path).parts)
            and p.suffix not in {".pyc", ".pyo"}}


def shared_service_url():
    candidates = []
    for path in Path("/proc").iterdir():
        try:
            if not path.name.isdigit() or (path / "comm").read_text().strip() != "opencode":
                continue
            args = (path / "cmdline").read_bytes().split(b"\0")
            if b"--service" not in args:
                continue
            sockets = {str(p.readlink()) for p in (path / "fd").iterdir() if p.is_symlink()}
            for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
                fields = line.split()
                if fields[3] == "0A" and f"socket:[{fields[9]}]" in sockets and fields[1].startswith("0100007F:"):
                    candidates.append("http://127.0.0.1:" + str(int(fields[1].split(":")[1], 16)))
        except (OSError, ProcessLookupError):
            continue
    if len(set(candidates)) != 1:
        raise ValueError("one shared loopback service required; pass explicit --shared-server if ambiguous")
    return candidates[0]


def credential_pipe(container, state, shared_url, *, binary=BINARY):
    # The exporter client uses separate local paths. Its server request is read-only.
    environment = docker_env()
    for name in list(environment):
        if name.startswith("OPENCODE_"):
            environment.pop(name)
    client = state / "private-export-client"
    for key, folder in [("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state"), ("OPENCODE_TEST_HOME", "home"), ("TMPDIR", "tmp")]:
        path = client / folder
        path.mkdir(parents=True)
        environment[key] = str(path)
    environment["OPENCODE_PASSWORD"] = json.loads(Path("/root/.config/opencode/service.json").read_text())["password"]
    started = time.monotonic()
    exporter = subprocess.Popen([str(binary), "auth", "export", "openai", "--server", shared_url],
        env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
    importer = subprocess.Popen([*DOCKER, "exec", "-i", container, "/opt/opencode", "auth", "import", "--standalone"],
        env=docker_env(), stdin=exporter.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    exporter.stdout.close()
    try:
        stdout, stderr = importer.communicate(timeout=120)
        exporter.wait(timeout=10)
    except BaseException:
        for process in (exporter, importer):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        raise
    return {"status": "passed" if exporter.returncode == importer.returncode == 0 else "failed",
            "export_returncode": exporter.returncode, "import_returncode": importer.returncode,
            "import_stdout_bytes": len(stdout), "import_stderr_bytes": len(stderr), "wall_seconds": time.monotonic() - started,
            "credential_body_saved": False, "credential_body_decoded": False, "provider": "openai", "shared_server": shared_url}


def configuration(arm, binding, response_format="full", service_tier=None):
    from container_common import validate_service_tier
    validate_service_tier(service_tier)
    if response_format not in ("full", "compact", "readable"):
        raise ValueError("unsupported memory response format")
    result = {"model": "openai/gpt-6.1-sol#high", "update": "disable", "share": "disabled", "warming": False,
        "snapshots": False, "compaction": {"auto": False}, "websearch": False,
        "plugins": ["-opencode.tool." + name for name in ["subagent", "webfetch", "websearch", "image-generate", "schedule", "question", "artifact"]],
        "permissions": [{"action": "*", "resource": "*", "effect": "allow"}, {"action": "external_directory", "resource": "*", "effect": "deny"}],
        "agents": {"research": {"mode": "primary", "steps": 20, "system": "Complete the user task using only /workspace and the configured tools. Do not inspect /state or credentials, invoke subagents or network tools, or read runtime implementation. Do not change files outside /workspace. When the tool research_memory_memory_lookup is available, call that exact tool once for relevant prior context before broad navigation. Memory is origin-bound; verify current source when needed and query again after edits before relying on its current availability. Keep the final answer concise."}},
        "experimental": {"schedules": False, "artifacts": False, "image_generate": False}}
    if service_tier is not None:
        result["providers"] = {"openai": {"models": {"gpt-6.1-sol": {"settings": {"serviceTier": service_tier}}}}}
    if arm != "plain":
        result["mcp"] = {"servers": {"research_memory": {"type": "local", "command": ["python", "/opt/memory-adapter/memory_adapter.py", "serve",
            "--binding", "/memory/" + binding, "--trace", "/state/evidence/memory-backend-trace.jsonl"], "cwd": "/workspace", "codemode": False,
            "environment": {"PYTHONPATH": "/opt/memory-adapter:/opt/cami-src:/opt/cami-deps", "PYTHONSAFEPATH": "1"},
            "timeout": {"startup": 10000, "catalog": 10000, "execution": 30000}}}}
        if response_format in ("compact", "readable"):
            result["mcp"]["servers"]["research_memory"]["command"] += ["--response-format", response_format]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--memory-dir", type=Path, required=True)
    parser.add_argument("--arm", choices=["plain", "static", "cami"], required=True)
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--binding-relative")
    parser.add_argument("--memory-response-format", choices=["full", "compact", "readable"], default="full")
    parser.add_argument("--service-tier", choices=["auto", "priority"], help="Explicit provider request tier; omission preserves legacy behavior")
    parser.add_argument("--no-model", action="store_true", help="Explicit default; no auth import/prompt admission")
    parser.add_argument("--run-model", action="store_true")
    parser.add_argument("--boundary-probe", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--message-page-size", type=int, default=200)
    parser.add_argument("--reported-token-budget", type=int, default=250000)
    parser.add_argument("--image", default=IMAGE)
    parser.add_argument("--opencode-binary", type=Path)
    parser.add_argument("--opencode-sha256")
    parser.add_argument("--cami-source", type=Path, default=ROOT / "src")
    parser.add_argument("--adapter-dir", type=Path, default=ROOT / "integrations/opencode")
    parser.add_argument("--shared-server")
    parser.add_argument("--runtime-manifest", type=Path, help="Required frozen image/binary/source/adapter identities for model admission")
    args = parser.parse_args()
    if args.no_model and args.run_model:
        parser.error("choose no-model or run-model")
    if args.run_model and not args.prompt_file:
        parser.error("run-model requires prompt-file")
    if args.run_model and not args.runtime_manifest:
        parser.error("run-model requires frozen runtime-manifest")
    if not 1 <= args.timeout_seconds <= 3600:
        parser.error("timeout must be1..3600 seconds")
    if not 1 <= args.message_page_size <= 500 or args.reported_token_budget < 1:
        parser.error("invalid pagination or observed-token threshold")
    if args.arm != "plain" and (not args.binding_relative or Path(args.binding_relative).is_absolute() or ".." in Path(args.binding_relative).parts):
        parser.error("memory arm requires a contained binding-relative")
    if (args.opencode_binary is None) != (args.opencode_sha256 is None):
        parser.error("custom OpenCode binary requires both path and SHA256")
    if args.opencode_binary is not None and (
        not args.opencode_binary.is_absolute()
        or re.fullmatch(r"[a-f0-9]{64}", args.opencode_sha256) is None
    ):
        parser.error("custom OpenCode binary requires absolute path and lowercase SHA256")
    binary = args.opencode_binary if args.opencode_binary is not None else BINARY
    expected_binary_sha = args.opencode_sha256 or EXPECTED_BINARY_SHA
    started = time.monotonic()
    output = owned(args.out, create=True)
    state, container = None, None
    initial_private_values = set()
    manifest = {"status": "preflight", "arm": args.arm, "model_requested": args.run_model, "model_calls_in_development_tests": 0, "memory_response_format": args.memory_response_format}
    if args.service_tier is not None:
        manifest["service_tier_requested"] = args.service_tier
    write(output / "manifest.json", manifest)
    try:
        assert sha(binary) == expected_binary_sha, "installed OpenCode identity changed before auth"
        workspace, memory = owned(args.workspace), owned(args.memory_dir)
        manifest["git_input_closure"] = git_closure(workspace)
        if args.arm == "plain" and any(memory.iterdir()):
            raise ValueError("plain arm requires its own empty dummy memory directory")
        manifest["storage_before"] = storage_snapshot([workspace, memory, output])
        if manifest["storage_before"]["free_bytes"] < 5 * 1024**3:
            raise ValueError("at least5GiB free disk required before a new trial")
        state = owned(args.state_dir, create=True)
        assert len({workspace, memory, state, output}) == 4 and not any(a.is_relative_to(b) for a in [workspace, memory, state, output] for b in [workspace, memory, state, output] if a != b), "trial paths must be disjoint"
        for path in [workspace, memory, state]:
            chown_owned(path)
        (state / "config/opencode").mkdir(parents=True)
        config = configuration(args.arm, args.binding_relative, args.memory_response_format, args.service_tier)
        write(state / "config/opencode/opencode.json", config)
        chown_owned(state)
        write(output / "effective-input-config.json", config)
        source, adapter = args.cami_source.resolve(), args.adapter_dir.resolve()
        assert (source / "cami/__init__.py").is_file() and (adapter / "memory_adapter.py").is_file(), "runtime source layout mismatch"
        manifest["runtime_sources"] = {"cami_path": str(source), "adapter_path": str(adapter), "cami_files": source_inventory(source), "adapter_files": source_inventory(adapter), "binary_sha256": sha(binary)}
        inspected = command([*DOCKER, "image", "inspect", args.image, "--format", "{{.Id}}" ])
        assert inspected["returncode"] == 0, "runtime image not locally present"
        image = inspected["stdout"].strip()
        assert args.image.startswith("sha256:") and image == args.image, "explicit immutable image ID required"
        manifest["image_id"] = image
        runtime_identity = {"image_id": image, "binary_sha256": manifest["runtime_sources"]["binary_sha256"],
            "cami_files": manifest["runtime_sources"]["cami_files"], "adapter_files": manifest["runtime_sources"]["adapter_files"]}
        write(output / "runtime-identity.json", runtime_identity)
        if args.runtime_manifest:
            assert json.loads(args.runtime_manifest.read_text()) == runtime_identity, "frozen runtime identity mismatch before auth"
        mounts = [(binary, "/opt/opencode", True), (source, "/opt/cami-src", True), (adapter, "/opt/memory-adapter", True),
            (STAGE / "container_worker.py", "/opt/harness/container_worker.py", True),
            (STAGE / "container_common.py", "/opt/harness/container_common.py", True),
            (STAGE / "boundary-sentinel.txt", "/opt/boundary-sentinel", True),
            (workspace, "/workspace", False), (state, "/state", False), (memory, "/memory", False),
            (Path("/etc/ssl/certs/ca-certificates.crt"), "/opt/ca-bundle.crt", True)]
        container = "cami-research-" + uuid.uuid4().hex
        manifest["owned_container_name"] = container
        write(output / "manifest.json", manifest)
        argv = [*DOCKER, "run", "--name", container, "--detach", "--pull=never", "--init", "--user", "65534:65534", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--read-only", "--memory=2g", "--cpus=2", "--pids-limit=256", "--tmpfs", "/tmp:rw,nosuid,nodev,size=512m", "--workdir", "/workspace", "--label", "cami.research.owned=true"]
        for host, guest, readonly in mounts:
            argv += ["--mount", f"type=bind,src={host},dst={guest}" + (",readonly" if readonly else "")]
        for setting in ["PYTHONPATH=/opt/harness:/opt/cami-src:/opt/cami-deps", "PYTHONSAFEPATH=1", "PYTHONDONTWRITEBYTECODE=1", "OPENCODE_DB=/state/data/opencode/session.db", "OPENCODE_CONFIG_DIR=/state/config/opencode", "OPENCODE_CONFIG=/state/config/opencode/opencode.json", "OPENCODE_CONFIG_PROJECT_DISABLE=1", "OPENCODE_DISABLE_CLAUDE_CODE=1", "OPENCODE_DISABLE_MODELS_FETCH=1", "XDG_DATA_HOME=/state/data", "XDG_CONFIG_HOME=/state/config", "XDG_CACHE_HOME=/state/cache", "XDG_STATE_HOME=/state/state", "OPENCODE_TEST_HOME=/state/home", "OPENCODE_LOG_LEVEL=none", "NODE_EXTRA_CA_CERTS=/opt/ca-bundle.crt", "SSL_CERT_FILE=/opt/ca-bundle.crt"]:
            argv += ["--env", setting]
        argv += ["--entrypoint", "python", image, "-c", "import time; time.sleep(86400)"]
        launch = command(argv)
        write(output / "container-launch.json", launch)
        assert launch["returncode"] == 0, "container launch failed"
        manifest["container_id"] = launch["stdout"].strip()
        before = command([*DOCKER, "exec", container, "python", "-c", "import json;from pathlib import Path;print(json.dumps({n:(Path('/sys/fs/cgroup')/n).read_text() for n in ['cpu.stat','cpu.max','memory.current','memory.peak','memory.max']}))"])
        write(output / "cgroup-before-auth.json", before)
        assert before["returncode"] == 0, "cgroup-before observation unavailable"
        if args.run_model:
            export_options = {"binary": binary} if args.opencode_binary is not None else {}
            transfer = credential_pipe(container, state, args.shared_server or shared_service_url(), **export_options)
            write(output / "credential-transfer.json", transfer)
            assert transfer["status"] == "passed", "private credential import failed"
            initial_private_values = collect_private_values(state, expect_credential=True)
        worker = [*DOCKER, "exec", "-i", container, "python", "/opt/harness/container_worker.py", "--arm", args.arm, "--timeout-seconds", str(args.timeout_seconds), "--reported-token-budget", str(args.reported_token_budget)]
        worker += ["--message-page-size", str(args.message_page_size)]
        if args.opencode_binary is not None:
            worker += ["--opencode-sha256", expected_binary_sha]
        if args.service_tier is not None:
            worker += ["--service-tier", args.service_tier]
        if args.binding_relative:
            worker += ["--binding-relative", args.binding_relative]
        if args.boundary_probe:
            worker += ["--boundary-probe"]
        payload = None
        if args.run_model:
            worker += ["--run-model"]
            payload = json.dumps({"prompt": args.prompt_file.read_text()}).encode()
        result = command(worker, input_bytes=payload, timeout=args.timeout_seconds + 180)
        if args.run_model:
            result.update(stdout_bytes=len(result["stdout"].encode()), stderr_bytes=len(result["stderr"].encode()))
            result["stdout"] = result["stderr"] = "[Private worker diagnostics not published; see sanitized worker evidence.]"
        write(output / "worker-process.json", result)
        after = command([*DOCKER, "exec", container, "python", "-c", "import json;from pathlib import Path;print(json.dumps({n:(Path('/sys/fs/cgroup')/n).read_text() for n in ['cpu.stat','cpu.max','memory.current','memory.peak','memory.max']}))"])
        write(output / "cgroup-after-worker.json", after)
        assert after["returncode"] == 0, "cgroup-after observation unavailable"
        assert result["returncode"] == 0, "worker failed; preserve copied evidence"
        assert source_inventory(source) == manifest["runtime_sources"]["cami_files"] and source_inventory(adapter) == manifest["runtime_sources"]["adapter_files"] and sha(binary) == manifest["runtime_sources"]["binary_sha256"], "runtime sources changed during execution"
        manifest["status"] = "passed"
    except BaseException as error:
        manifest.update(status="failed", failure=type(error).__name__ + ": " + str(error))
        raise
    finally:
        cleanup_errors = []
        writers_stopped = not container
        if container:
            try:
                removal = command([*DOCKER, "rm", "--force", container])
                write(output / "owned-container-remove.json", removal)
                if removal["returncode"]:
                    cleanup_errors.append("owned container removal failed")
                else:
                    writers_stopped = True
            except BaseException as error:
                cleanup_errors.append("container removal: " + type(error).__name__)
        try:
            if state and state.exists() and writers_stopped:
                publication = scrub_state_evidence(state, expect_credential=args.run_model, initial_private_values=initial_private_values)
                write(output / "publication-guard.json", publication)
                if publication["status"] in {"passed", "partial"}:
                    shutil.copytree(state / "evidence", output / "evidence", symlinks=True)
                    if publication["status"] == "partial":
                        manifest.update(status="failed", failure="Some worker evidence was rejected; safe artifacts retained")
                    worker_manifest = output / "evidence/manifest.json"
                    if not worker_manifest.exists():
                        manifest.update(status="failed", failure="Worker manifest unavailable; safe artifacts retained")
                    elif manifest["status"] == "passed" and json.loads(worker_manifest.read_text()).get("status") != "passed":
                        manifest.update(status="failed", failure="worker final evidence status is not passed")
                else:
                    manifest["status"] = "failed"
                    manifest.setdefault("failure", "expected final worker evidence is unavailable")
            elif state and state.exists():
                manifest.update(status="failed", publication_blocked=True, publication_failure="Container writers not proven stopped")
        except BaseException as error:
            manifest.update(status="failed", publication_blocked=True,
                publication_failure=type(error).__name__ + ": " + str(error),
                missing_payload_reason="Unsafe/unverifiable evidence not published; private payloads discarded on cleanup.")
        if state and state.exists():
            try:
                manifest["storage_before_cleanup"] = storage_snapshot([state, output])
                shutil.rmtree(state)
            except BaseException as error:
                cleanup_errors.append("state cleanup: " + type(error).__name__)
        if cleanup_errors:
            manifest.update(status="failed", cleanup_errors=cleanup_errors)
        manifest.update(total_host_wall_seconds=time.monotonic() - started, state_removed=bool(state and not state.exists()),
            resource_limits={"cpu": 2, "memory_bytes": 2147483648, "pids": 256, "root_readonly": True, "uid": 65534, "reported_token_threshold": args.reported_token_budget, "token_enforcement": "observed disjoint normalized component threshold; interruption may overshoot, not a billing/hard provider cap", "hard_writable_storage_quota": None},
            limitations=["Docker daemon/controller CPU is outside container cgroup counters.", "Default Docker/proxy network retained; native web tools disabled, not strict OS egress isolation.", "Own /state credentials share UID with native tool processes; framework external_directory deny is not OS secret isolation.", "Runtime CAMI/adapter code readable and identical in all arms; host repo/gold/other trials/socket not mounted."])
        manifest["artifact_hashes"] = {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file() and p != output / "manifest.json"}
        write(output / "manifest.json", manifest)
    if manifest["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
