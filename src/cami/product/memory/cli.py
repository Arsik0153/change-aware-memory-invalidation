from __future__ import annotations

import argparse
import json
from pathlib import Path

from cami.product.memory.models import AgentContext, MemoryGeneration, MutationReceipt, RecordHistory


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    memory = sub.add_parser("memory", help="persistent structural facts and manual notes")
    commands = memory.add_subparsers(dest="memory_command", required=True)
    for name in ("context", "remember", "update", "refresh", "history"):
        command = commands.add_parser(name)
        command.add_argument("--repo", type=Path, required=True)
        command.add_argument("--format", choices=("text", "json"), default="text")
        command.add_argument("--source-root", action="append", dest="source_roots")
        command.add_argument("--exclude", action="append", default=[])
        if name in ("context", "remember"):
            if name == "remember":
                command.add_argument("kind", choices=("symbol_exists", "signature_equals", "note"))
            command.add_argument("symbol")
        if name in ("remember", "update"):
            command.add_argument("--from-context", type=Path, required=True)
            command.add_argument("--request-id", required=True)
            command.add_argument("--text")
        if name == "remember":
            command.add_argument("--note-key")
        if name in ("update", "history"):
            command.add_argument("memory_id")
        if name == "update":
            command.add_argument("--if-revision", type=int, required=True)


def execute(args: argparse.Namespace) -> None:
    from cami.errors import IncompleteError
    from cami.product.memory.store import read_evidence
    from cami.product.service import ProductMemory
    from cami.product.store import CacheCorrupt

    service = ProductMemory(args.repo, tuple(args.source_roots) if args.source_roots else None,
                            tuple(args.exclude))
    operation = args.memory_command
    result: AgentContext | MemoryGeneration | MutationReceipt | RecordHistory
    if operation == "context":
        result = service.context(args.symbol)
    elif operation == "refresh":
        result = service.refresh()
    elif operation == "history":
        result = service.history(args.memory_id)
    else:
        try:
            raw = read_evidence(args.from_context)
        except (OSError, CacheCorrupt) as exc:
            raise IncompleteError("context_evidence_unavailable") from exc
        context = AgentContext.model_validate_json(raw)
        if operation == "remember":
            result = service.remember(args.kind, args.symbol, context, args.request_id,
                                      note_key=args.note_key, text=args.text)
        else:
            result = service.update(args.memory_id, args.if_revision, context,
                                    args.request_id, text=args.text)
    value = result.model_dump(mode="json")
    print(json.dumps(value, ensure_ascii=True, sort_keys=True,
                     indent=None if args.format == "json" else 2))
