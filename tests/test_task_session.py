"""Fault injection tests use actual child processes and durable SQLite files."""

import json
from pathlib import Path
import signal
import subprocess
import sys

import pytest

from integrations.opencode.task_session import Journal, finish, run, telemetry
from integrations.opencode import task_replay

ROOT = Path(__file__).resolve().parents[1]
USAGE = dict(input=12, output=3, reasoning=2, cache_read=7, cache_write=0)


def fixture(tmp_path):
    workspace = tmp_path / "work"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src/a.py").write_text("old")
    grade = [
        sys.executable,
        "-c",
        "from pathlib import Path; assert Path('src/a.py').read_text() == 'new'",
    ]
    return workspace, grade


def provider(missing=False, code=0, retry=False):
    items = [{"type": "request_started", "id": "a"}, {"type": "partial", "text": "working"}]
    if retry:
        items += [{"type": "transport_error", "id": "a"}, {"type": "request_started", "id": "b"}]
    if not missing:
        items += [{"type": "request_finished", "id": "b" if retry else "a", "usage": USAGE}]
    script = "from pathlib import Path; import sys; Path('src/a.py').write_text('new'); "
    script += "; ".join("print(" + repr(json.dumps(item)) + ",flush=True)" for item in items)
    script += f"; sys.exit({code})"
    return [sys.executable, "-c", script]


@pytest.mark.parametrize(
    "missing,code,retry", [(False, 0, False), (True, 0, False), (False, 1, False), (False, 0, True)]
)
def test_quality_and_eligibility_separate(tmp_path, missing, code, retry):
    work, grade = fixture(tmp_path)
    result = run(
        tmp_path / "session",
        work,
        "exact task",
        "context v1",
        provider(missing, code, retry),
        grade,
        tmp_path / "cache",
        True,
    )
    assert result["quality"] == "pass"
    assert result["cache_eligible"] == (not missing and code == 0 and not retry)
    if missing or retry:
        assert result["telemetry"]["total"] is None
    if retry:
        assert result["telemetry"]["requests"] == 2
        assert result["telemetry"]["known_subtotal"] == USAGE
    if result["cache_recorded"]:
        before = tmp_path / "session/before"
        hit = task_replay.materialize(
            before, "exact task", "context v1", tmp_path / "cache", tmp_path / "hit"
        )
        assert hit["status"] == "candidate_requires_grading"
        assert subprocess.run(grade, cwd=tmp_path / "hit").returncode == 0
        assert (
            task_replay.materialize(
                before, "exact task", "changed context", tmp_path / "cache", tmp_path / "miss"
            )["status"]
            == "miss"
        )
        (before / "src/a.py").chmod(0o700)
        assert (
            task_replay.materialize(
                before, "exact task", "context v1", tmp_path / "cache", tmp_path / "mode"
            )["status"]
            == "miss"
        )


@pytest.mark.parametrize(
    "point",
    ["capture_input_started", "prepared", "response", "agent_finished", "solution_preserved"],
)
def test_sigkill_and_restart(tmp_path, point):
    work, grade = fixture(tmp_path)
    directory = tmp_path / "session"
    # Kill immediately after durable acknowledgement at a chosen boundary.
    script = f"""import os, signal
from integrations.opencode import task_session as m
original=m.Journal.append
def append(self,kind,data):
 original(self,kind,data)
 if kind=={point!r}: os.kill(os.getpid(),signal.SIGKILL)
m.Journal.append=append
m.run({str(directory)!r},{str(work)!r},'task','context',{provider()!r},{grade!r},request_coverage=True)
"""
    p = subprocess.run([sys.executable, "-c", script], cwd=ROOT)
    assert p.returncode == -signal.SIGKILL
    j = Journal(directory / "events.sqlite")
    assert j.events()[-1][0] == point
    j.close()
    # A separate fresh process performs recovery, never another model launch.
    recovered = subprocess.run(
        [
            sys.executable,
            "-m",
            "integrations.opencode.task_session",
            "recover",
            "--directory",
            str(directory),
        ],
        cwd=ROOT,
        capture_output=True,
    )
    if point == "capture_input_started":
        assert recovered.returncode != 0  # input was never committed; cannot reconstruct it
        return
    assert recovered.returncode == 0, recovered.stderr.decode()
    result = json.loads(recovered.stdout)
    assert result["quality"] == ("fail" if point == "prepared" else "pass")
    assert result["cache_eligible"] == (point in ["agent_finished", "solution_preserved"])
    j = Journal(directory / "events.sqlite")
    prior = j.events()
    assert finish(directory, j) == result
    assert j.events() == prior
    j.close()


def test_corrupt_journal(tmp_path):
    path = tmp_path / "events.sqlite"
    path.write_bytes(b"broken sqlite")
    with pytest.raises(Exception):
        Journal(path)


def test_unknown_is_not_zero_and_duplicates_fail():
    assert telemetry([])["total"] is None
    events = [
        ("response", {"line": json.dumps(x)})
        for x in [
            {"type": "request_started", "id": "a"},
            {"type": "request_finished", "id": "a", "usage": USAGE},
            {"type": "request_finished", "id": "a", "usage": USAGE},
        ]
    ]
    assert not telemetry(events)["complete"]


def test_opaque_agent_never_trains(tmp_path):
    work, grade = fixture(tmp_path)
    result = run(
        tmp_path / "session", work, "task", "context", provider(), grade, request_coverage=False
    )
    assert result["quality"] == "pass" and not result["cache_eligible"]


def test_launch_error_preserves_and_grades(tmp_path):
    work, grade = fixture(tmp_path)
    result = run(tmp_path / "session", work, "task", "context", ["/nonexistent/cami-agent"], grade)
    assert result["quality"] == "fail"
    assert result["execution"] == "failed_or_interrupted"
    assert result["telemetry"]["total"] is None


def test_bytes_change_is_a_miss(tmp_path):
    work, grade = fixture(tmp_path)
    result = run(
        tmp_path / "session", work, "task", "context", provider(), grade, tmp_path / "cache", True
    )
    assert result["cache_recorded"]
    before = tmp_path / "session/before"
    (before / "src/a.py").write_text("different")
    assert (
        task_replay.materialize(before, "task", "context", tmp_path / "cache", tmp_path / "out")[
            "status"
        ]
        == "miss"
    )
