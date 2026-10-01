import hashlib
import json
import subprocess
from pathlib import Path

import pytest


class GitFixture:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "CAMI fixture")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args]).decode().strip()

    def commit(self, files):
        for name, content in files.items():
            path = self.root / name
            if content is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
        self.git("add", ".")
        self.git("commit", "-qm", "fixture", "--allow-empty")
        return self.git("rev-parse", "HEAD")

    def config(self, parent, children, *, policy="symbol_validate", claims=None):
        base = self.root.parent
        if claims is None:
            claims = [dict(schema_version=1, claim_id="f", repo_id="fixture", origin_commit=parent,
                           kind="symbol_exists", text="f exists", scope="exact definition",
                           subject=dict(path="module.py", qualname="f", node_kind="function"),
                           predicate=dict(type="symbol_exists", expected=True))]
        evidence = base / "parent-evidence.txt"
        evidence.write_text("Manually specified synthetic fixture parent truth.\n")
        def rows(name, data):
            (base / name).write_text("".join(json.dumps(row) + "\n" for row in data))
        rows("claims.jsonl", claims)
        rows("provenance.jsonl", [dict(schema_version=1, claim_id=c["claim_id"], scenario_id="intact",
             anchors=[dict(path=c["subject"]["path"], qualname=c["subject"]["qualname"], scope="symbol",
                           observed_commit=parent, content_hash=hashlib.sha256(
                               self.git("show", f'{parent}:{c["subject"]["path"]}').encode()).hexdigest(), origin="manual")],
             dependencies=[], known_incomplete=False, unresolved_reasons=[]) for c in claims])
        rows("parent_receipts.jsonl", [dict(schema_version=1, claim_id=c["claim_id"], origin_commit=parent,
             status="supported", confirmation_type="synthetic_manual", evidence_path=evidence.name,
             evidence_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest()) for c in claims])
        config = dict(schema_version=1, protocol_version="1.0", repo=dict(repo_id="fixture", path=self.root.name,
                      source_roots=["."]), parent_commit=parent, child_commits=children, claims_path="claims.jsonl",
                      provenance_path="provenance.jsonl", parent_receipts_path="parent_receipts.jsonl",
                      scenario_id="intact", dataset_kind="synthetic", split="development", stratum="fixture",
                      policy=dict(id=policy), validation=dict(execution="disabled", llm="disabled"),
                      allow_network=False, max_calls=0, seed=42)
        path = base / "run.json"
        path.write_text(json.dumps(config))
        return path


@pytest.fixture
def repo(tmp_path):
    return GitFixture(tmp_path / "repo with spaces")
