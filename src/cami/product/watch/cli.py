from __future__ import annotations

import argparse
from pathlib import Path


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    watch = sub.add_parser("watch", help="refresh product memory as the worktree changes")
    watch.add_argument("watch_action", nargs="?", choices=("status", "stop", "restart"))
    watch.add_argument("--repo", type=Path, required=True)
    watch.add_argument("--format", choices=("text", "json"), default="text")
    watch.add_argument("--source-root", action="append", dest="source_roots")
    watch.add_argument("--exclude", action="append", default=[])


def execute(args: argparse.Namespace) -> int:
    from cami.errors import InputError
    from cami.models import safe_path
    from cami.product.store import CacheCorrupt, state_base
    from cami.product.watch.control import Lease, WatchControlError, inspect
    from cami.product.watch.models import WatchSettings, WatchStatus
    from cami.product.watch.runtime import Watcher

    def render(status: WatchStatus) -> None:
        if args.format == "json":
            print(status.model_dump_json())
        else:
            print(f"cami watch {status.lifecycle}: {status.reason}; data {status.data_freshness}")

    action = args.watch_action
    if action in ("status", "stop", "restart"):
        if action != "restart" and (args.source_roots or args.exclude):
            raise InputError("status and stop use the running session's settings")
        status = inspect(args.repo, stop=action in ("stop", "restart"))
        if action != "restart" or status.lifecycle != "stopped":
            render(status)
            return 4 if status.lifecycle == "unknown" else 0
    try:
        lease = Lease.open(args.repo, create=True)
    except (OSError, ValueError, CacheCorrupt) as exc:
        raise WatchControlError(f"watch_lock_integrity_error: {exc}") from exc
    assert lease is not None
    try:
        settings = WatchSettings(
            canonical_repo=str(lease.root), state_base=str(state_base()),
            source_roots=tuple(sorted({safe_path(p) for p in args.source_roots}))
            if args.source_roots else None,
            excluded_paths=tuple(sorted({safe_path(p) for p in args.exclude})))
        if len(settings.model_dump_json().encode()) > 8192:
            raise InputError("watch settings exceed 8192 bytes")
        if not lease.acquire():
            status = inspect(args.repo)
            if status.lifecycle == "unknown":
                render(status)
                return 4
            if status.lifecycle == "stopped":
                raise WatchControlError("watch_start_race: retry after concurrent session release")
            same = status.settings == settings
            render(status.model_copy(update={"reason": "already_running" if same
                                             else "watch_configuration_conflict"}))
            return 0 if same else 2
        return Watcher(lease, settings, args.format).run()
    finally:
        lease.close()
