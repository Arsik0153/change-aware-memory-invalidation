from __future__ import annotations

import signal
import sys
from pathlib import Path
from typing import Literal

from cami.errors import IncompleteError
from cami.product.service import ProductMemory
from cami.product.watch.control import now
from cami.product.watch.models import OperationResult, Success, WatchError, WatchSettings


def _cancel(signum: int, frame: object) -> None:
    raise IncompleteError("watch_operation_cancelled" if signum == signal.SIGTERM
                          else "watch_operation_timeout")


def main() -> None:
    action: Literal["observe", "refresh"] = "observe" if sys.argv[1] == "observe" else "refresh"
    settings = WatchSettings.model_validate_json(sys.stdin.buffer.read(16385))
    signal.signal(signal.SIGTERM, _cancel)
    signal.signal(signal.SIGALRM, _cancel)
    signal.setitimer(signal.ITIMER_REAL, settings.operation_seconds)
    try:
        service = ProductMemory(Path(settings.canonical_repo), settings.source_roots,
                                settings.excluded_paths)
        if action == "observe":
            result = OperationResult(action=action, observation=service.observe())
        else:
            generation = service.refresh()
            result = OperationResult(action=action, success=Success(
                completed_at=now(), memory_generation_id=generation.memory_generation_id,
                index=generation.index, sequence=generation.sequence,
                catalog_epoch=generation.catalog_epoch))
    except Exception as exc:
        message = str(exc)[:2000]
        result = OperationResult(action=action, error=WatchError(
            code=message.split(":", 1)[0][:120] or type(exc).__name__,
            message=message, occurred_at=now()))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    print(result.model_dump_json(), flush=True)


if __name__ == "__main__":
    main()
