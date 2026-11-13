"""One isolated OpenCode session inside a prepared benchmark container."""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
from pathlib import Path
import sqlite3
import shlex
import threading
import time
import urllib.parse
import urllib.request

from container_common import BINARY, EXPECTED_BINARY_SHA, PrivateServer, observe_service_tier, redact as redact, redact_data, redact_string, sanitize_artifact, service_tier_evidence, sha, tree_bytes, write

from native_read_evidence import observe_message as observe_native_reads, summarize as native_read_summary

OUT = Path("/state/evidence")
PRIVATE = Path("/state/server-private")
WORKSPACE = Path("/workspace")
SECRETS = set()


def load_redaction_secrets():
    """Own isolated DB only; values remain in memory, never in evidence."""
    path = Path(os.environ["OPENCODE_DB"])
    if not path.exists():
        return
    def strings(item):
        if isinstance(item, dict):
            for value in item.values():
                strings(value)
        elif isinstance(item, list):
            for value in item:
                strings(value)
        elif isinstance(item, str) and len(item) >= 16 and not item.startswith(("http://", "https://")):
            SECRETS.add(item)
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='credential'").fetchone():
            for raw, in connection.execute("SELECT value FROM credential WHERE integration_id='openai'"):
                strings(json.loads(raw))
    finally:
        connection.close()


def secret_redact(text):
    return redact_string(text, SECRETS)


def public(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key.lower() in {"native", "authorization", "access_token", "refresh_token", "id_token", "api_key", "apikey", "email", "account_id", "accountid", "encrypted_content"}:
                continue
            clean_key = secret_redact(key)
            if clean_key in result:
                raise ValueError("redaction would merge JSON object keys")
            result[clean_key] = public(item)
        return result
    if isinstance(value, list):
        return [public(item) for item in value]
    return redact_data(value, SECRETS) if isinstance(value, str) else value


def cgroup():
    result = {}
    for name in ("cpu.stat", "cpu.max", "memory.current", "memory.peak", "memory.max", "memory.events", "pids.current", "pids.max"):
        path = Path("/sys/fs/cgroup") / name
        try:
            result[name] = path.read_text().strip()
        except OSError as error:
            result[name] = {"unavailable": type(error).__name__}
    return result


def reported_tokens(tokens):
    return tokens["input"] + tokens["output"] + tokens["reasoning"] + tokens["cache"]["read"] + tokens["cache"]["write"]


def await_mcp(server, location, arm, timeout=30):
    started = time.monotonic()
    observations = []
    while True:
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("MCP startup did not settle before model admission")
        result = server.request("GET", "/api/mcp" + location, timeout=min(5, remaining))
        observations.append({"elapsed_seconds": time.monotonic() - started,
                             "servers": public(result["data"])})
        write(OUT / "mcp-readiness.json", {"observations": observations,
              "timeout_seconds": timeout, "scope": "startup only; no prompt admission or trial retry"})
        write(OUT / "observed-mcp.json", public(result))
        if arm == "plain":
            assert not result["data"], "plain arm unexpectedly exposes MCP servers"
            return result
        assert all(item["name"] == "research_memory" for item in result["data"]), "unexpected MCP server"
        if result["data"]:
            assert len(result["data"]) == 1, "duplicate memory MCP server"
            status = result["data"][0]["status"]["status"]
            if status == "connected":
                return result
            if status != "pending":
                raise RuntimeError("memory MCP startup terminal status: " + status)
        time.sleep(min(0.1, max(0, timeout - (time.monotonic() - started))))


def capture_failure(server, session_id, page_size, manifest, tier_observations=None):
    try:
        latest = server.request("GET", "/api/session/" + session_id, timeout=3)["data"]
        write(OUT / "session.json", public(latest))
        usage = {"session_tokens": latest["tokens"], "session_client_cost_field": latest["cost"],
            "status": "failed_attempt_latest_reported", "scope": "best effort, not complete remote billing record"}
        write(OUT / "failure-usage.json", usage)
        write(OUT / "usage.json", usage)
        pages, entries = messages_all(server, session_id, page_size, deadline=time.monotonic() + 20, tier_observations=tier_observations)
        write(OUT / "message-pages.json", pages)
        write(OUT / "messages.json", entries)
        manifest["failure_usage_capture"] = "available"
        return entries
    except BaseException as error:
        manifest["failure_usage_capture"] = "partial_or_unavailable:" + type(error).__name__
        try:
            receipt = OUT / "native-read-bytes.json"
            observations = json.loads(receipt.read_text())["messages"] if receipt.exists() else []
            write(receipt, native_read_summary(observations, export_complete=False))
        except (OSError, ValueError, KeyError, TypeError) as capture_error:
            manifest["failure_read_capture"] = "unavailable:" + type(capture_error).__name__
        if not (OUT / "usage.json").exists():
            write(OUT / "usage.json", {"session_tokens": None, "session_client_cost_field": None,
                "status": "unavailable", "reason": type(error).__name__})


def messages_all(server, session_id, page_size=200, deadline=None, tier_observations=None):
    pages, all_messages, seen, cursor = [], [], set(), None
    read_observations, export_complete = [], False
    try:
        for _ in range(10000):
            query = {"limit": str(page_size), **({"cursor": cursor} if cursor else {"order": "asc"})}
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("failure message export deadline")
            page = server.request("GET", f"/api/session/{session_id}/message?" + urllib.parse.urlencode(query),
                timeout=15 if deadline is None else min(3, max(0.1, deadline - time.monotonic())))
            pages.append(public(page))
            write(OUT / "partial-message-pages.json", pages)
            for item in page["data"]:
                if item["id"] in seen:
                    raise ValueError("message pagination repeated an ID")
                seen.add(item["id"])
                if tier_observations is not None:
                    observe_service_tier(item, tier_observations)
                read_observations.append(observe_native_reads(item))
                all_messages.append(public(item))
            next_cursor = page["cursor"].get("next")
            if not next_cursor:
                export_complete = True
                return pages, all_messages
            if next_cursor == cursor:
                raise ValueError("message pagination cursor failed to advance")
            cursor = next_cursor
        raise ValueError("message pagination exceeded10000 pages")
    finally:
        write(OUT / "native-read-bytes.json", native_read_summary(read_observations, export_complete=export_complete))


def event_stream(server, done, result):
    auth = "Basic " + base64.b64encode(("opencode:" + server.password).encode()).decode()
    request = urllib.request.Request(server.url + "/api/event", headers={"Authorization": auth})
    count, size = 0, 0
    try:
        with urllib.request.urlopen(request, timeout=1200) as response, (OUT / "events.jsonl").open("w") as stream:
            result["connected"] = True
            for raw in response:
                if done.is_set():
                    break
                if not raw.startswith(b"data: "):
                    continue
                value = public(json.loads(raw[6:]))
                line = json.dumps(value, ensure_ascii=False) + "\n"
                size += len(line.encode())
                count += 1
                if size > 64 * 1024**2:
                    raise ValueError("SSE safety ceiling64MiB reached; trace incomplete")
                stream.write(line)
                stream.flush()
        result.update(status="stopped", events=count, bytes=size)
    except Exception as error:
        result.update(status="stopped" if done.is_set() else "failed", error_type=type(error).__name__, events=count, bytes=size)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=["plain", "static", "cami"], required=True)
    parser.add_argument("--binding-relative")
    parser.add_argument("--run-model", action="store_true")
    parser.add_argument("--boundary-probe", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--message-page-size", type=int, default=200)
    parser.add_argument("--reported-token-budget", type=int, default=250000)
    parser.add_argument("--service-tier", choices=["auto", "priority"])
    parser.add_argument("--opencode-sha256", default=EXPECTED_BINARY_SHA)
    args = parser.parse_args()
    if re.fullmatch(r"[a-f0-9]{64}", args.opencode_sha256) is None:
        parser.error("OpenCode SHA256 must be a lowercase digest")
    OUT.mkdir(exist_ok=False)
    PRIVATE.mkdir()
    started = time.monotonic()
    done, events_result, server, thread = threading.Event(), {}, None, None
    session_id = None
    tier_observations, selected = {}, None
    tier_export_complete, tier_assistant_ids = False, []
    manifest = {"status": "preflight", "arm": args.arm, "model_generation_requested": args.run_model,
        "model_session_launches": 0, "max_agent_steps": 20, "cgroup_before": cgroup()}
    write(OUT / "manifest.json", manifest)
    try:
        assert sha(BINARY) == args.opencode_sha256, "OpenCode binary changed"
        assert os.getuid() == 65534, "requires nonroot65534"
        assert "/workspace" not in os.environ.get("PYTHONPATH", ""), "trusted worker must not import target source"
        assert os.environ.get("OPENCODE_CONFIG_PROJECT_DISABLE") == "1", "project configuration must be disabled"
        load_redaction_secrets()
        configuration = json.loads(Path("/state/config/opencode/opencode.json").read_text())
        write(OUT / "effective-input-config.json", configuration)
        if args.arm != "plain":
            binding_path = Path("/memory") / args.binding_relative
            binding = json.loads(binding_path.read_text())
            assert binding["repo"] == "/workspace" and binding["backend"] == args.arm, "memory prepared for wrong path/arm"
        task_environment = {**os.environ, "PYTHONPATH": "/workspace/src:/opt/cami-src:/opt/cami-deps"}
        task_environment.pop("PYTHONSAFEPATH", None)
        server = PrivateServer(task_environment, WORKSPACE, PRIVATE)
        SECRETS.add(server.password)
        password_path = PRIVATE / "server-password.private"
        password_path.write_text(server.password)
        password_path.chmod(0o600)
        write(OUT / "readiness.json", public(server.wait_ready()))
        location = "?" + urllib.parse.urlencode({"location[directory]": "/workspace"})
        for name, path in (("config", "/api/config"), ("agents", "/api/agent"), ("plugins", "/api/plugin")):
            result = server.request("GET", path + location)
            write(OUT / ("observed-" + name + ".json"), public(result))
            if name == "config":
                assert all(entry.get("path", "").startswith("/state/config/opencode") for entry in result), "unexpected project/global configuration source"
            if name == "plugins":
                forbidden = {"opencode.tool." + n for n in ["subagent", "webfetch", "websearch", "image-generate", "schedule", "question", "artifact"]}
                assert not any(item.get("id") in forbidden for item in result["data"]), "disabled plugin remains available"
        await_mcp(server, location, args.arm)
        registry_started = time.monotonic()
        time.sleep(1)
        write(OUT / "tool-registry-stabilization.json", {
            "requested_seconds": 1,
            "elapsed_seconds": time.monotonic() - registry_started,
            "all_arms": True,
            "reason": "Installed client reloads MCP tools through a 100ms debounced registry after connected status.",
            "limitation": "No public tool-registry completion endpoint; a settling interval is not proof of first-request tool availability.",
        })
        created = server.request("POST", "/api/session", {"location": {"directory": "/workspace"},
            "title": "Fixed research session", "agent": "research",
            "model": {"providerID": "openai", "id": "gpt-6.1-sol", "variant": "high"}})
        write(OUT / "created-session.json", public(created))
        session = created["data"]
        assert session["location"]["directory"] == "/workspace", "wrong created session location"
        assert session["model"] == {"providerID": "openai", "id": "gpt-6.1-sol", "variant": "high"}, "wrong created model identity"
        manifest["session_id"] = session["id"]
        session_id = session["id"]
        thread = threading.Thread(target=event_stream, args=(server, done, events_result), daemon=True)
        thread.start()
        stream_deadline = time.monotonic() + 5
        while not events_result.get("connected") and time.monotonic() < stream_deadline:
            time.sleep(0.05)
        assert events_result.get("connected"), "SSE was not connected before execution"
        if args.boundary_probe:
            # No model: execute one authored command through this exact session.
            probe = '''import os,json
from pathlib import Path
result={"cwd":os.getcwd(),"fixture":Path("fixture.py").read_text(),"socket_exists":Path("/var/run/docker.sock").exists(),"gold_exists":Path("/gold").exists(),"host_repo_accessible":os.access("/root/apps/change-aware-memory-invalidation",os.R_OK)}
assert Path("/opt/boundary-sentinel").read_text().startswith("Authored read-only mount boundary sentinel.")
try:
    with Path("/opt/boundary-sentinel").open("a") as stream: stream.write("UNEXPECTED_WRITE")
    result["readonly_mount_enforced"]=False
except OSError as error:
    result["readonly_mount_enforced"]=error.errno==30
    result["readonly_errno"]=error.errno
temporary=Path("/workspace/.authored-boundary-probe")
temporary.write_text("own writable workspace")
result["workspace_writable"]=temporary.read_text()=="own writable workspace"
temporary.unlink()
print(json.dumps(result))
'''
            command = "python -c " + shlex.quote(probe)
            server.request("POST", f"/api/session/{session['id']}/shell", {"command": command})
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                _, entries = messages_all(server, session["id"], args.message_page_size)
                if any(item["type"] == "shell" and item.get("time", {}).get("completed") for item in entries):
                    break
                time.sleep(0.1)
            server.request("POST", f"/api/session/{session['id']}/shell", {"command": "python -c 'print(\"AUTHORED_PAGINATION_SENTINEL\")'"})
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                _, entries = messages_all(server, session["id"], args.message_page_size)
                if sum(item["type"] == "shell" and bool(item.get("time", {}).get("completed")) for item in entries) == 2:
                    break
                time.sleep(0.1)
        if args.run_model or args.service_tier is not None:
            models = server.request("GET", "/api/model" + location)["data"]
            selected = next(m for m in models if m["id"] == "gpt-6.1-sol" and m["providerID"] == "openai")
            variant = next(v for v in selected["variants"] if v["id"] == "high")
            assert selected["modelID"] == "gpt-6.1-sol" and variant["settings"]["reasoningEffort"] == "high", "effective model settings mismatch"
            write(OUT / "observed-model.json", {key: public(value) for key, value in selected.items() if key in ["id", "modelID", "providerID", "package", "settings", "capabilities", "variants", "limit", "enabled", "status"]})
            if args.service_tier is not None:
                assert selected["package"] == "@opencode/ai/providers/openai/responses", "unverified service tier provider adapter"
                write(OUT / "service-tier.json", service_tier_evidence(args.service_tier, selected, model_requested=args.run_model))
        if args.run_model:
            request = json.load(__import__("sys").stdin)
            prompt = request["prompt"]
            write(OUT / "prompt.json", {"text": prompt})
            manifest["model_session_launches"] = 1
            write(OUT / "model-admission.json", {"session_id": session["id"], "model": session["model"], "location": session["location"], "title": session["title"]})
            response = server.request("POST", f"/api/session/{session['id']}/prompt", {"text": prompt})
            write(OUT / "prompt-admitted.json", public(response))
            deadline = time.monotonic() + args.timeout_seconds
            while time.monotonic() < deadline:
                observed = server.request("GET", "/api/session/" + session["id"])["data"]
                tokens = observed["tokens"]
                reported = reported_tokens(tokens)
                if reported > args.reported_token_budget:
                    manifest.update(token_threshold_exceeded=True, observed_reported_tokens=reported,
                        token_limit_scope="observed normalized components, may overshoot, not billing quota")
                    try:
                        server.request("POST", f"/api/session/{session['id']}/interrupt", {})
                    except Exception as error:
                        manifest["interrupt_error_type"] = type(error).__name__
                    raise RuntimeError("observed reported-token threshold exceeded")
                if observed.get("outcome") in ["succeeded", "failed", "interrupted"] and observed.get("time", {}).get("idle"):
                    break
                time.sleep(0.25)
            else:
                manifest["model_timeout"] = True
                try:
                    server.request("POST", f"/api/session/{session['id']}/interrupt", {})
                except Exception as error:
                    manifest["interrupt_error_type"] = type(error).__name__
                raise TimeoutError("model session deadline reached")
        pages, entries = messages_all(server, session["id"], args.message_page_size,
                                      tier_observations=tier_observations if args.service_tier is not None else None)
        tier_export_complete = True
        tier_assistant_ids = [m["id"] for m in entries if m["type"] == "assistant"]
        write(OUT / "message-pages.json", pages)
        write(OUT / "messages.json", entries)
        final = server.request("GET", "/api/session/" + session["id"])["data"]
        write(OUT / "session.json", public(final))
        assert final["location"]["directory"] == "/workspace" and final["model"] == session["model"], "session identity changed"
        assert final["title"] == session["title"], "fixed session title changed"
        assistants = [m for m in entries if m["type"] == "assistant"]
        assert all(m["model"] == session["model"] for m in assistants), "assistant model identity changed"
        if args.boundary_probe:
            shell = next(item for item in entries if item["type"] == "shell")
            assert shell["status"] == "exited" and shell["exit"] == 0 and not shell["output"]["truncated"], "authored shell boundary command failed"
            probes = json.loads(shell["output"]["output"])
            assert probes["cwd"] == "/workspace" and probes["fixture"] == Path("/workspace/fixture.py").read_text(), "session read path mismatch"
            assert probes["readonly_mount_enforced"] and probes["workspace_writable"] and not any(probes[key] for key in ["socket_exists", "gold_exists", "host_repo_accessible"]), "container boundary probe failed"
            write(OUT / "boundary-proof.json", probes)
        observed_cgroup = cgroup()
        assert observed_cgroup["memory.max"] == "2147483648" and observed_cgroup["cpu.max"] == "200000 100000" and observed_cgroup["pids.max"] == "256", "cgroup resource limits not observed"
        if not args.run_model:
            assert not assistants and final["tokens"]["input"] == final["tokens"]["output"] == 0, "unexpected model activity in no-model preflight"
        write(OUT / "usage.json", {"session_tokens": final["tokens"], "session_client_cost_field": final["cost"],
            "assistant_message_count": len(assistants), "assistant_step_tokens": {key: sum(m.get("tokens", {}).get(key, 0) for m in assistants) for key in ["input", "output", "reasoning"]},
            "installed_normalizer_semantics": "v2.2.5 input=noncached; output=visible output; reasoning and cache are disjoint components. Missing/nonfinite provider fields normalize to0. See pinned reconnaissance/token-semantics source.",
            "reported_full_input_if_provider_fields_present": final["tokens"]["input"] + final["tokens"]["cache"]["read"] + final["tokens"]["cache"]["write"],
            "reported_full_output_if_provider_fields_present": final["tokens"]["output"] + final["tokens"]["reasoning"],
            "memory_lookups": [{"message_id": message["id"], "name": part["name"], "input": part["state"].get("input"), "status": part["state"]["status"]}
                for message in assistants for part in message.get("content", []) if part["type"] == "tool" and part["name"].endswith("memory_lookup")],
            "limits": "Session and message totals retained separately, never summed. Client cost is not subscription billing. Provider missingness lost by normalizer."})
        deltas = {key: final["tokens"][key] - sum(message.get("tokens", {}).get(key, 0) for message in assistants) for key in ["input", "output", "reasoning"]}
        deltas.update({"cache_" + key: final["tokens"]["cache"][key] - sum(message.get("tokens", {}).get("cache", {}).get(key, 0) for message in assistants) for key in ["read", "write"]})
        write(OUT / "usage-reconciliation.json", {"session_minus_all_assistant_messages": deltas, "background_usage_detected": any(deltas.values()), "task_grade": "external grader, not inferred from OpenCode success"})
        if args.run_model:
            assert final.get("outcome") == "succeeded", "OpenCode model execution did not succeed"
            assert not any(deltas.values()), "unexplained auxiliary/background model usage"
        manifest["status"] = "passed"
    except BaseException as error:
        manifest.update(status="failed", failure=type(error).__name__ + ": " + str(error))
        raise
    finally:
        # A failed/paid execution still needs the latest reported session usage
        # and every available message before server termination.
        if manifest["status"] == "failed" and server and session_id:
            failure_entries = capture_failure(server, session_id, args.message_page_size, manifest,
                                              tier_observations if args.service_tier is not None else None)
            if failure_entries is not None:
                tier_export_complete = True
                tier_assistant_ids = [m["id"] for m in failure_entries if m["type"] == "assistant"]
        done.set()
        finalization_errors = []
        if args.service_tier is not None and selected is not None:
            try:
                write(OUT / "service-tier.json", service_tier_evidence(args.service_tier, selected,
                      model_requested=args.run_model, observations=list(tier_observations.values()),
                      export_complete=tier_export_complete, assistant_ids=tier_assistant_ids))
            except BaseException as error:
                finalization_errors.append("service tier evidence:" + type(error).__name__)
        if server:
            try:
                write(OUT / "server-resource.json", server.stop())
                text = (PRIVATE / "server.log").read_text(errors="replace").replace(server.password, "[REDACTED_SERVER_PASSWORD]")
                (OUT / "server.log.redacted.txt").write_text(secret_redact(text))
            except BaseException as error:
                finalization_errors.append("server shutdown:" + type(error).__name__)
        if thread:
            thread.join(timeout=6)
        write(OUT / "event-collector.json", events_result)
        if events_result.get("status") == "failed":
            finalization_errors.append("execution event stream incomplete")
        manifest.update(cgroup_after=cgroup(), worker_wall_seconds=time.monotonic() - started)
        try:
            manifest.update(workspace_bytes=tree_bytes(WORKSPACE), memory_bytes=tree_bytes(Path("/memory")))
        except BaseException as error:
            finalization_errors.append("storage observation:" + type(error).__name__)
        if finalization_errors:
            manifest.update(status="failed", finalization_errors=finalization_errors)
        write(OUT / "manifest.json", public(manifest))
        # Include any OAuth refresh values created during execution, then scrub
        # text evidence again before the host copies it out of the private mount.
        try:
            load_redaction_secrets()
            rejected = []
            for path in OUT.rglob("*"):
                if not path.is_symlink() and path.is_file() and path.suffix in [".json", ".jsonl", ".txt"]:
                    try:
                        sanitize_artifact(path, SECRETS)
                    except (ValueError, UnicodeError, RecursionError) as error:
                        path.unlink()
                        rejected.append({"artifact": secret_redact(str(path.relative_to(OUT))), "error_type": type(error).__name__})
            if rejected:
                manifest.update(status="failed", sanitation_rejected_artifacts=rejected)
                write(OUT / "manifest.json", redact_data(public(manifest), SECRETS))
            write(OUT / "worker-sanitation-complete.json", {"status": "partial" if rejected else "passed",
                  "rejected_artifacts": rejected, "host_must_still_freeze_and_scrub": True})
        except BaseException as error:
            manifest.update(status="failed", sanitation_failure=type(error).__name__)
            write(OUT / "manifest.json", public(manifest))


if __name__ == "__main__":
    main()
