#!/usr/bin/env python3
"""Small synchronous stdio MCP server for a frozen static/CAMI memory catalog."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
import time

from memory_backend import Backend, LEXICAL_RANKING, RANKING_POLICIES, canonical, cpu, digest, prepare, storage
from compact_response import compact_result
from readable_response import readable_result

PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")
MAX_MESSAGE = 1024 * 1024
TOOL = {
    "name": "memory_lookup",
    "description": (
        "Retrieve origin memory. Statuses distinguish unchecked origin, manual assertions and literal records. "
        "A supported source excerpt certifies only the displayed prefix and truncation flag under the current verified readset, not behavior. "
        "Withheld summaries are unusable. Query again after edits. Use native tools for missing code or context."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 1000},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


class RpcError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def trace(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as stream:
        stream.write(canonical(value) + b"\n")


class Server:
    def __init__(self, binding_path, trace_path, response_format="full", *, ranking_policy=LEXICAL_RANKING):
        if response_format not in {"full", "compact", "readable"}:
            raise ValueError("response format must be full, compact or readable")
        self.response_format = response_format
        self.ranking_policy = ranking_policy
        started, started_cpu = time.perf_counter(), cpu()
        self.backend = Backend(binding_path, ranking_policy=ranking_policy)
        self.trace_path = trace_path
        if trace_path.is_relative_to(Path(self.backend.binding["repo"])):
            raise ValueError("trace must be outside target repo")
        self.phase = "new"
        trace(
            trace_path,
            {
                "event": "server_start",
                "backend": self.backend.binding["backend"],
                "catalog_sha256": self.backend.binding["catalog_sha256"],
                **({"ranking_policy": ranking_policy} if ranking_policy != LEXICAL_RANKING else {}),
                "wall_seconds": time.perf_counter() - started,
                "cpu_seconds_self_and_completed_children": cpu() - started_cpu,
                "timing_scope": "server constructor; excludes Python/stdlib imports/CLI startup; first CAMI import charged to first lookup",
            },
        )

    def dispatch(self, message):
        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != "2.0"
            or not isinstance(message.get("method"), str)
        ):
            raise RpcError(-32600, "Invalid JSON-RPC request")
        method, params = message["method"], message.get("params", {})
        if not isinstance(params, dict):
            raise RpcError(-32602, "params must be an object")
        if "id" not in message:
            if method == "notifications/initialized" and self.phase == "negotiated":
                self.phase = "ready"
            return None
        if type(message["id"]) not in (int, str):
            raise RpcError(-32600, "request id must be integer or string")
        if method == "ping":
            return {}
        if method == "initialize":
            if self.phase != "new":
                raise RpcError(-32600, "Already initialized")
            if (
                not isinstance(params.get("protocolVersion"), str)
                or not isinstance(params.get("clientInfo"), dict)
                or not isinstance(params.get("capabilities"), dict)
            ):
                raise RpcError(
                    -32602, "initialize requires protocolVersion, clientInfo and capabilities"
                )
            self.phase = "negotiated"
            return {
                "protocolVersion": params["protocolVersion"]
                if params["protocolVersion"] in PROTOCOLS
                else PROTOCOLS[-1],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "research-memory", "version": "0.1.0"},
            }
        if self.phase != "ready":
            raise RpcError(-32600, "Initialize and send notifications/initialized first")
        if method == "tools/list":
            if params:
                raise RpcError(-32602, "No pagination cursor")
            return {"tools": [TOOL]}
        if method == "tools/call":
            if params.get("name") != "memory_lookup":
                raise RpcError(-32602, "Unknown tool")
            arguments = params.get("arguments", {})
            if not isinstance(arguments, dict) or not {"query"} <= set(arguments) <= {
                "query",
                "limit",
            }:
                raise RpcError(-32602, "memory_lookup requires query and optional limit")
            started, started_cpu = time.perf_counter(), cpu()
            detail, error = {}, None
            try:
                with redirect_stdout(sys.stderr):
                    value, detail = self.backend.lookup(
                        arguments["query"], arguments.get("limit", 5)
                    )
                result = {
                    "content": [{"type": "text", "text": canonical(value).decode()}],
                    "isError": False,
                }
            except Exception as exc:
                error = {"type": type(exc).__name__, "message": str(exc)[:500]}
                value = {
                    "schema_version": 1,
                    "error": {
                        "code": "memory_lookup_failed",
                        "type": error["type"],
                        "message": "Current memory unavailable; no historical data returned. Inspect the local trace.",
                    },
                    "entries": [],
                    "withheld": [],
                    "freshness": "unavailable; no historical result substituted",
                }
                result = {
                    "content": [{"type": "text", "text": canonical(value).decode()}],
                    "isError": True,
                }
            response_audit = {}
            if self.response_format == "compact":
                result, audit = compact_result(result)
                response_audit = {"response_format": "compact", "response_audit": audit}
            elif self.response_format == "readable":
                result, audit = readable_result(result)
                response_audit = {"response_format": "readable", "response_audit": audit}
            state_home = self.backend.binding["state_home"]
            # Storage scan and response serialization are included in the observed tool span.
            state_bytes = storage(Path(state_home)) if state_home else 0
            trace(
                self.trace_path,
                {
                    "event": "memory_lookup",
                    "backend": self.backend.binding["backend"],
                    "query_sha256": digest(arguments),
                    "requested_limit": arguments.get("limit", 5),
                    "catalog_sha256": self.backend.binding["catalog_sha256"],
                    "wall_seconds": time.perf_counter() - started,
                    "cpu_seconds_self_and_completed_children": cpu() - started_cpu,
                    "state_bytes": state_bytes,
                    "response_bytes": len(canonical(result)),
                    "error": error,
                    **detail,
                    **({"ranking_policy": self.ranking_policy} if self.ranking_policy != LEXICAL_RANKING else {}),
                    **response_audit,
                    "timing_scope": "tool backend/imports/retrieval/serialization/storage observation; excludes JSON-RPC input/output and trace append; external harness must time whole process/session",
                },
            )
            return result
        raise RpcError(-32601, "Method not found")


def serve(
    binding_path, trace_path, input_stream=None, output_stream=None, *, response_format="full",
    ranking_policy=LEXICAL_RANKING,
):
    incoming = input_stream or sys.stdin.buffer
    outgoing = output_stream or sys.stdout.buffer
    with redirect_stdout(sys.stderr):
        server = Server(binding_path, trace_path, response_format=response_format, ranking_policy=ranking_policy)
    while True:
        line = incoming.readline(MAX_MESSAGE + 1)
        if not line:
            return
        request_id = None
        try:
            if len(line) > MAX_MESSAGE:
                while line and not line.endswith(b"\n"):
                    line = incoming.readline(MAX_MESSAGE + 1)
                raise RpcError(-32700, "Message too large")
            try:
                message = json.loads(line)
            except (ValueError, UnicodeError):
                raise RpcError(-32700, "Parse error") from None
            if isinstance(message, dict):
                request_id = message.get("id") if type(message.get("id")) in (int, str) else None
            result = server.dispatch(message)
            if isinstance(message, dict) and "id" not in message:
                continue
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except RpcError as exc:
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": exc.code, "message": exc.message},
            }
        outgoing.write(canonical(response) + b"\n")
        outgoing.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("prepare")
    init.add_argument("--backend", choices=("static", "cami"), required=True)
    init.add_argument("--repo", type=Path, required=True)
    inputs = init.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--catalog", type=Path)
    inputs.add_argument("--seed-spec", type=Path)
    init.add_argument("--out", type=Path, required=True)
    init.add_argument("--state-home", type=Path)
    server = commands.add_parser("serve")
    server.add_argument("--binding", type=Path, required=True)
    server.add_argument("--trace", type=Path, required=True)
    server.add_argument("--ranking-policy", choices=RANKING_POLICIES, default=LEXICAL_RANKING)
    server.add_argument(
        "--response-format",
        choices=("full", "compact", "readable"),
        default="full",
        help="Model-facing format; compact/readable write full response receipts to --trace; readable projects literal prefixes and otherwise falls back to compact",
    )
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            with redirect_stdout(sys.stderr):
                prepare(
                    args.backend,
                    args.repo.resolve(),
                    args.out.resolve(),
                    args.catalog.resolve() if args.catalog else None,
                    args.seed_spec.resolve() if args.seed_spec else None,
                    args.state_home.resolve() if args.state_home else None,
                )
            print(
                json.dumps(
                    {"status": "prepared", "binding": str(args.out.resolve() / "binding.json")}
                )
            )
        else:
            serve(
                args.binding.resolve(), args.trace.resolve(), response_format=args.response_format,
                ranking_policy=args.ranking_policy,
            )
        return 0
    except (OSError, ValueError) as exc:
        print(f"adapter error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
