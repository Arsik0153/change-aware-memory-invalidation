"""Verify the actual final installed-command run against its preserved inputs."""

import hashlib
import json
from pathlib import Path
import sqlite3
import zipfile

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "runs/practical-complete-20261115"
REPORT = ROOT / "reports/practical-complete-20261115"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    launch = RUN / "ordinary-smoke/launch-accounting-final.log"
    result = json.loads(launch.read_text())
    directory = Path(result["journal"])
    db = sqlite3.connect(f"file:{directory / 'events.sqlite'}?mode=ro", uri=True)
    try:
        assert db.execute("pragma integrity_check").fetchone()[0] == "ok"
        events = [
            (kind, json.loads(data))
            for kind, data in db.execute("select kind,data from events order by seq")
        ]
    finally:
        db.close()
    prepared = next(data for kind, data in events if kind == "prepared")
    terminal = next(data for kind, data in events if kind == "terminal")
    assert terminal == {key: value for key, value in result.items() if key != "journal"}
    context = json.loads(prepared["context"])
    receipt = json.loads((directory / "api-session.json").read_text())
    assert receipt["workspace"] == prepared["workspace"]
    assert receipt["model"] == {"providerID": "openai", "id": "gpt-6.1-sol", "variant": "high"}
    assert context["origin"] == "admission"
    assert terminal["quality"] == "pass" and terminal["execution"] == "success"
    assert terminal["telemetry"]["complete"]
    wheel = RUN / "wheel-final-accounting/cami-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as archive:
        for name, field in [
            ("run_task.py", "runner_sha256"),
            ("task_session.py", "capture_sha256"),
            ("task_replay.py", "replay_sha256"),
        ]:
            payload = archive.read("cami/opencode/" + name)
            assert hashlib.sha256(payload).hexdigest() == context[field]
            assert payload == (ROOT / "integrations/opencode" / name).read_bytes()
    assert prepared["task"] == (RUN / "ordinary-smoke/task.txt").read_bytes().decode()
    before = (directory / "before/src/example.py").read_text()
    solution = (directory / "solution/src/example.py").read_text()
    assert before != solution
    namespace = {}
    exec(compile(solution, "preserved authored admission", "exec"), namespace)
    assert namespace["twice"](3) == 6 and namespace["twice"](-2) == -4
    observations = sum(
        kind == "response" and json.loads(data["line"]).get("type") == "assistant_observation"
        for kind, data in events
        if kind == "response"
    )
    assert observations > 0
    evidence = {
        "status": "verified",
        "wheel_sha256": digest(wheel),
        "journal": str(directory.relative_to(ROOT)),
        "input_key": terminal["input_key"],
        "quality": terminal["quality"],
        "execution": terminal["execution"],
        "usage": terminal["telemetry"],
        "visible_response_observations": observations,
        "origin": "admission; excluded from primary sample and production repeat frequency",
        "checks": "Exact task, durable receipt, model/workspace, all packaged capture source hashes, changed source, fresh grading, observed responses and normalized usage.",
    }
    (REPORT / "installed-task-accounting-admission.json").write_text(
        json.dumps(evidence, indent=2) + "\n"
    )
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
