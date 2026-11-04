"""Trusted pytest entrypoint and outcome counts, before candidate source imports."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


class Outcomes:
    def __init__(self):
        self.collected = 0
        self.nodes = {
            key: set()
            for key in ["executed", "passed", "failed", "skipped", "xfailed", "xpassed", "errors"]
        }

    def pytest_collection_finish(self, session):
        self.collected = len(session.items)

    def pytest_collectreport(self, report):
        if report.failed:
            self.nodes["errors"].add(report.nodeid)
        elif report.skipped:
            self.nodes["skipped"].add(report.nodeid)

    def pytest_runtest_logreport(self, report):
        if report.when == "call":
            self.nodes["executed"].add(report.nodeid)
            if report.passed:
                self.nodes["passed"].add(report.nodeid)
            elif report.failed:
                self.nodes["failed"].add(report.nodeid)
        elif report.failed:
            self.nodes["errors"].add(report.nodeid)
        if report.skipped:
            self.nodes["skipped"].add(report.nodeid)
            if hasattr(report, "wasxfail"):
                self.nodes["xfailed"].add(report.nodeid)
        elif report.passed and hasattr(report, "wasxfail"):
            self.nodes["xpassed"].add(report.nodeid)

    def report(self, exit_code):
        return {
            "exit_code": int(exit_code),
            "collected": self.collected,
            "counts": {name: len(nodes) for name, nodes in self.nodes.items()},
            "node_ids": {name: sorted(nodes) for name, nodes in self.nodes.items()},
            "semantics": "executed=call-phase reports; skipped includes xfailed and collection/setup skips; errors=collection/setup/teardown failures. Counts overlap and are never summed.",
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject-module", action="append", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    # Invoked with -I and cwd /; no candidate-controlled module precedes pytest.
    sys.path.insert(0, "/opt/cami-deps")
    import pytest

    if Path(pytest.__file__).resolve().is_relative_to("/workspace"):
        raise ValueError("pytest runner loaded from candidate source")
    for name in list(sys.modules):
        if any(name == module or name.startswith(module + ".") for module in args.subject_module):
            del sys.modules[name]
    sys.path.insert(0, "/workspace/src")
    os.chdir("/workspace")
    options = args.pytest_args[1:] if args.pytest_args[:1] == ["--"] else args.pytest_args
    outcomes = Outcomes()
    code = pytest.main(options, plugins=[outcomes])
    with args.report.open("x") as stream:
        json.dump(outcomes.report(code), stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
