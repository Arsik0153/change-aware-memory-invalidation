"""Runs only inside the prepared probe container."""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


def main() -> None:
    import pytest

    reports: list[dict[str, Any]] = []
    collected: list[str] = []
    target = sys.argv[1]
    sys.path[0:0] = sys.argv[2:]

    class Recorder:
        def pytest_collection_finish(self, session: Any) -> None:
            collected.extend(item.nodeid for item in session.items)

        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_makereport(self, item: Any, call: Any) -> Any:
            outcome = yield
            report = outcome.get_result()
            assertion = call.excinfo is not None and call.excinfo.errisinstance(AssertionError)
            message = str(call.excinfo.value) if call.excinfo is not None else ""
            reports.append({"nodeid": item.nodeid, "when": report.when, "outcome": report.outcome,
                            "assertion": assertion,
                            "fingerprint": hashlib.sha256(message.encode()).hexdigest() if assertion else None})

    code = pytest.main(["-q", "-c", "/dev/null", "--noconftest", "-p", "no:cacheprovider",
                        "--rootdir=/probe", target], plugins=[Recorder()])
    print("CAMI_RESULT=" + json.dumps({"python_version": sys.version.split()[0], "exit_code": int(code), "collected": collected, "reports": reports}), flush=True)


if __name__ == "__main__":
    main()
