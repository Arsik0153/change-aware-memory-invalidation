from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cami.index import build_index
from cami.models import RepoLocation
from cami.repository import read_snapshot


@pytest.fixture(autouse=True)
def isolated_product_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def cli(root, symbol, *args, seed="1"):
    return subprocess.run(
        [sys.executable, "-m", "cami.cli", "find", symbol, "--repo", str(root), *args],
        capture_output=True, text=True, check=False,
        env={**os.environ, "PYTHONHASHSEED": seed},
    )


def lookup(root, symbol, *args, seed="1"):
    result = cli(root, symbol, "--format", "json", *args, seed=seed)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    return json.loads(result.stdout)


def test_cli_contract_signature_and_both_directions(repo):
    revision = repo.commit({
        "api.py": "def target(x: int = 1, /, *, flag=False) -> int:\n    return helper(x)\n"
                  "def helper(x): return x\n",
        "caller.py": "from api import target as selected\ndef caller(): return selected()\n",
    })
    data = lookup(repo.root, "target", "--revision", "HEAD")
    assert set(data) == {"schema_version", "query", "requested_revision", "snapshot", "status",
                         "matches", "graph_complete", "limitations", "unresolved",
                         "global_unresolved", "coverage", "absence_confirmed", "observation"}
    assert data["schema_version"] == 2
    assert data["status"] == "found"
    assert data["snapshot"]["kind"] == "git"
    assert data["snapshot"]["revision"] == revision
    assert data["snapshot"]["tree"] == repo.git("rev-parse", "HEAD^{tree}")
    assert data["snapshot"]["source_roots"] == ["."]
    match, = data["matches"]
    assert (match["path"], match["qualname"], match["qualified_name"]) == (
        "api.py", "target", "api.target")
    assert (match["start_line"], match["end_line"], match["node_kind"]) == (1, 2, "function")
    assert match["signature_text"] == "def target(x: int=1, /, *, flag=False) -> int"
    assert match["signature"] == {
        "parameters": [
            {"name": "x", "kind": "positional_only", "default_ast": "Constant(value=1)",
             "annotation_ast": "Name(id='int', ctx=Load())"},
            {"name": "flag", "kind": "keyword_only", "default_ast": "Constant(value=False)",
             "annotation_ast": None},
        ], "returns_ast": "Name(id='int', ctx=Load())", "decorators_ast": [], "is_async": False,
    }
    assert match["outgoing"] == [{
        "source": {"path": "api.py", "qualname": "target"},
        "target": {"path": "api.py", "qualname": "helper"},
        "relation": "calls", "origin": "static",
    }]
    assert {(edge["source"]["path"], edge["source"]["qualname"], edge["relation"])
            for edge in match["incoming"]} == {
                ("caller.py", None, "imports"), ("caller.py", "caller", "calls")}
    assert data["graph_complete"] is False


def test_exact_and_qualified_lookup_preserves_duplicates(repo):
    repo.commit({
        "a.py": "def shared(): pass\nclass C:\n    def shared(self): pass\n"
                "def outer():\n    def shared(): pass\n",
        "b.py": "def shared(): pass\ndef shared_extra(): pass\n",
    })
    ambiguous = lookup(repo.root, "shared")
    assert ambiguous["status"] == "ambiguous"
    assert [(m["path"], m["qualname"]) for m in ambiguous["matches"]] == [
        ("a.py", "C.shared"), ("a.py", "outer.<locals>.shared"), ("a.py", "shared"),
        ("b.py", "shared"),
    ]
    for query, expected in [
        ("b.shared", ("b.py", "shared")), ("a.py:shared", ("a.py", "shared")),
        ("C.shared", ("a.py", "C.shared")),
        ("a.outer.<locals>.shared", ("a.py", "outer.<locals>.shared")),
    ]:
        data = lookup(repo.root, query)
        assert data["status"] == "found"
        match, = data["matches"]
        assert (match["path"], match["qualname"]) == expected
    assert lookup(repo.root, "share")["status"] == "not_found"


def test_repeated_and_conditional_bindings_remain_ambiguous(repo):
    repo.commit({"a.py": "def repeated(): pass\ndef repeated(): pass\n"
                         "if flag:\n    def conditional(): pass\n"})
    repeated = lookup(repo.root, "a.repeated")
    assert repeated["status"] == "ambiguous"
    assert [m["start_line"] for m in repeated["matches"]] == [1, 2]
    assert all(m["ambiguous"] for m in repeated["matches"])
    conditional = lookup(repo.root, "conditional")
    assert conditional["status"] == "ambiguous"
    assert len(conditional["matches"]) == 1


def test_revision_rename_delete_and_dirty_checkout_are_independent(repo):
    before = repo.commit({"old.py": "def original(): return 1\n"})
    renamed = repo.commit({"old.py": None, "new.py": "def renamed(): return 2\n"})
    deleted = repo.commit({"new.py": None, "keep.txt": "repository still has a tree\n"})
    (repo.root / "new.py").write_text("def original(): return 'uncommitted'\n")
    repo.git("add", "new.py")
    (repo.root / "new.py").write_text("def original(): return 'unstaged'\n")
    index_before = (repo.root / ".git/index").read_bytes()
    status_before = repo.git("status", "--porcelain")
    assert lookup(repo.root, "original", "--revision", before)["matches"][0]["path"] == "old.py"
    assert lookup(repo.root, "original", "--revision", renamed)["status"] == "not_found"
    assert lookup(repo.root, "renamed", "--revision", renamed)["matches"][0]["path"] == "new.py"
    absent = lookup(repo.root, "renamed", "--revision", deleted)
    assert absent["status"] == "not_found"
    assert absent["matches"] == []
    assert lookup(repo.root, "original")["status"] == "found"
    assert repo.git("rev-parse", "HEAD") == deleted
    assert repo.git("status", "--porcelain") == status_before
    assert (repo.root / ".git/index").read_bytes() == index_before
    assert "unstaged" in (repo.root / "new.py").read_text()


def test_explicit_git_revision_does_not_require_worktree_backend(repo):
    repo.commit({"a.py": "def target(): pass\n"})
    script = ("import sys\nsys.modules['fcntl'] = None\n"
              "from cami.cli import main\n"
              f"raise SystemExit(main(['find', 'target', '--repo', {str(repo.root)!r}, "
              "'--revision', 'HEAD', '--format', 'json']))")
    result = subprocess.run([sys.executable, "-c", script], capture_output=True,
                            text=True, check=False, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "found"


def test_source_roots_and_paths_with_spaces(repo):
    repo.commit({"src/pkg/api.py": "async def target(*args, **kwargs): return 1\n",
                 "other folder/api.py": "def target(): return 2\n"})
    match, = lookup(repo.root, "pkg.api.target")["matches"]
    assert match["path"] == "src/pkg/api.py"
    assert match["signature"]["is_async"] is True
    assert lookup(repo.root, "other folder/api.py:target")["status"] == "found"
    explicit = lookup(repo.root, "src.pkg.api.target", "--source-root", ".")
    assert explicit["status"] == "found"
    restricted = lookup(repo.root, "target", "--source-root", "src")
    assert len(restricted["matches"]) == 1
    assert restricted["snapshot"]["source_roots"] == ["src"]


def test_partial_graph_and_parse_limits_are_explicit(repo):
    repo.commit({"a.py": "def dynamic(callback): return callback()\n",
                 "broken.py": "def broken(\n", "external.py": "from missing import target\n",
                 "typescript.ts": "function absent() {}\n"})
    data = lookup(repo.root, "dynamic")
    assert data["graph_complete"] is False
    assert data["matches"][0]["outgoing"] == []
    assert {"path": "a.py", "qualname": "dynamic"} in data["unresolved"]
    assert data["global_unresolved"] is True
    assert {"code": "parse_error", "path": "broken.py"} in data["limitations"]
    absent = lookup(repo.root, "absent")
    assert absent["status"] == "not_found"
    assert {"code": "python_functions_and_methods_only", "path": None} in absent["limitations"]


def test_generic_async_signature_keeps_type_parameters_and_decorators(repo):
    repo.commit({"a.py": "@decorate\nasync def target[T](x: T, /, *, flag=True) -> T:\n"
                         "    return x\n"})
    match, = lookup(repo.root, "target")["matches"]
    assert match["signature_text"] == "async def target[T](x: T, /, *, flag=True) -> T"
    assert match["signature"]["is_async"] is True
    assert match["signature"]["decorators_ast"] == ["Name(id='decorate', ctx=Load())"]
    assert (match["start_line"], match["end_line"]) == (2, 3)


def test_local_import_calls_are_candidates_without_changing_research_index(repo):
    revision = repo.commit({
        "src/pkg/engine.py": "def target(): pass\n",
        "src/pkg/cli.py": "def main(flag):\n    if flag:\n"
                          "        from .engine import target as run\n        run()\n",
    })
    data = lookup(repo.root, "pkg.engine.target")
    assert data["matches"][0]["incoming"] == [{
        "source": {"path": "src/pkg/cli.py", "qualname": "main"},
        "target": {"path": "src/pkg/engine.py", "qualname": "target"},
        "relation": "calls", "origin": "static",
    }]
    assert {"path": "src/pkg/cli.py", "qualname": "main"} in data["unresolved"]
    snapshot = read_snapshot(RepoLocation(repo_id="fixture", path=str(repo.root)), revision)
    assert build_index(snapshot).edges == ()


def test_relative_import_overflow_never_calls_root_init_target(repo):
    revision = repo.commit({
        "__init__.py": "def target(): pass\n",
        "cli.py": "def main():\n    from . import target\n    target()\n",
        "pkg/cli.py": "def nested():\n    from .. import target\n    target()\n",
    })
    data = lookup(repo.root, "__init__.py:target", "--revision", revision)
    assert data["status"] == "found"
    assert data["matches"][0]["incoming"] == []
    assert data["unresolved"] == [
        {"path": "cli.py", "qualname": "main"},
        {"path": "pkg/cli.py", "qualname": "nested"},
    ]
    assert data["graph_complete"] is False
    assert {"code": "unresolved_is_conservative", "path": None} in data["limitations"]
    for path, name in [("cli.py", "main"), ("pkg/cli.py", "nested")]:
        caller = lookup(repo.root, f"{path}:{name}", "--revision", revision)
        assert caller["matches"][0]["outgoing"] == []


@pytest.mark.parametrize("path, level", [
    ("cli.py", 3), ("__init__.py", 1),
    ("pkg/cli.py", 2), ("pkg/__init__.py", 3),
    ("pkg/nested/cli.py", 3), ("pkg/nested/__init__.py", 4),
])
@pytest.mark.parametrize("module", ["", "name"])
def test_relative_import_overflow_stays_unresolved(repo, path, level, module):
    files = {"__init__.py": "def target(): pass\n", "name.py": "def target(): pass\n"}
    files[path] = files.get(path, "") + (
        f"def caller():\n    from {'.' * level}{module} import target as run\n    run()\n")
    revision = repo.commit(files)
    for target in ("__init__.py:target", "name.py:target"):
        data = lookup(repo.root, target, "--revision", revision)
        assert data["matches"][0]["incoming"] == []
        assert {"path": path, "qualname": "caller"} in data["unresolved"]
    caller = lookup(repo.root, f"{path}:caller", "--revision", revision)
    assert caller["matches"][0]["outgoing"] == []


@pytest.mark.parametrize("caller_path, target_path, module", [
    ("pkg/cli.py", "pkg/engine.py", ".engine"),
    ("pkg/cli.py", "pkg/__init__.py", "."),
    ("pkg/nested/cli.py", "pkg/engine.py", "..engine"),
    ("pkg/nested/cli.py", "pkg/__init__.py", ".."),
    ("pkg/__init__.py", "pkg/engine.py", ".engine"),
    ("pkg/nested/__init__.py", "pkg/__init__.py", ".."),
])
@pytest.mark.parametrize("alias", ["target", "run"])
def test_valid_relative_local_import_keeps_call(repo, caller_path, target_path, module, alias):
    alias_clause = f" as {alias}" if alias != "target" else ""
    revision = repo.commit({
        target_path: "def target(): pass\n",
        caller_path: f"def caller():\n    from {module} import target{alias_clause}\n    {alias}()\n",
    })
    data = lookup(repo.root, f"{target_path}:target", "--revision", revision)
    edge = {"source": {"path": caller_path, "qualname": "caller"},
            "target": {"path": target_path, "qualname": "target"},
            "relation": "calls", "origin": "static"}
    assert data["matches"][0]["incoming"] == [edge]
    caller = lookup(repo.root, f"{caller_path}:caller", "--revision", revision)
    assert caller["matches"][0]["outgoing"] == [edge]


@pytest.mark.parametrize("imports", [
    "from .. import target\n    from .engine import target",
    "from .engine import target\n    from .. import target",
])
def test_unresolvable_relative_import_keeps_competing_binding_ambiguous(repo, imports):
    revision = repo.commit({
        "pkg/engine.py": "def target(): pass\n",
        "pkg/cli.py": f"def caller():\n    {imports}\n    target()\n",
    })
    data = lookup(repo.root, "pkg.engine.target", "--revision", revision)
    assert data["matches"][0]["incoming"] == []
    assert {"path": "pkg/cli.py", "qualname": "caller"} in data["unresolved"]


@pytest.mark.parametrize("body", [
    "from engine import target\n    target = replacement\n    target()",
    "from engine import target\n    del target\n    target()",
    "from engine import target\n    import other as target\n    target()",
    "from engine import target\n    from other import target\n    target()",
    "from engine import target\n    def target(): pass\n    target()",
    "global target\n    from engine import target\n    target()",
])
def test_shadowed_local_import_never_invents_a_call(repo, body):
    repo.commit({"engine.py": "def target(): pass\n",
                 "other.py": "def target(): pass\n",
                 "cli.py": "def main():\n    " + body + "\n"})
    assert lookup(repo.root, "engine.target")["matches"][0]["incoming"] == []


def test_local_import_does_not_choose_between_colliding_module_names(repo):
    repo.commit({"engine.py": "def target(): pass\n",
                 "engine/__init__.py": "def target(): pass\n",
                 "cli.py": "def main():\n    from engine import target\n    target()\n"})
    data = lookup(repo.root, "engine.target")
    assert data["status"] == "ambiguous"
    assert len(data["matches"]) == 2
    assert all(match["incoming"] == [] for match in data["matches"])


def test_json_is_byte_deterministic_across_hash_seeds(repo):
    repo.commit({"a.py": "def target(): return helper()\ndef helper(): pass\n",
                 "b.py": "from a import target\ndef caller(): return target()\n"})
    first = cli(repo.root, "target", "--revision", "HEAD", "--format", "json", seed="11")
    second = cli(repo.root, "target", "--revision", "HEAD", "--format", "json", seed="97")
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    json.loads(first.stdout)


def test_human_output_is_default_and_mentions_incomplete_graph(repo):
    repo.commit({"a.py": "def target(): pass\n"})
    result = cli(repo.root, "target")
    assert result.returncode == 0
    assert "found: target" in result.stdout
    assert "a.py:1-1 target" in result.stdout
    assert "Graph is partial" in result.stdout
    assert "def target()" in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize("extra", [
    ["--revision", "missing-ref"], ["--revision=-invalid"], ["--source-root", "../escape"],
    ["--format", "yaml"],
])
def test_invalid_arguments_report_stderr(repo, extra):
    repo.commit({"a.py": "def target(): pass\n"})
    result = cli(repo.root, "target", *extra)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "error" in result.stderr.lower()
    assert "Traceback" not in result.stderr


def test_invalid_repo_empty_symbol_and_empty_history(tmp_path, repo):
    for root, symbol in [(tmp_path / "absent", "x"), (tmp_path, "x"),
                         (repo.root, " ")]:
        result = cli(root, symbol)
        assert result.returncode == 2
        assert result.stdout == ""
        assert "input error:" in result.stderr
        assert "Traceback" not in result.stderr
    assert lookup(repo.root, "x")["status"] == "not_found"
    assert cli(repo.root, "x", "--revision", "HEAD").returncode == 2


def test_cami_finds_static_call_from_its_own_cli():
    root = Path(__file__).resolve().parents[1]
    data = lookup(root, "run_experiment", "--revision", "HEAD", "--source-root", "src")
    assert data["status"] == "found"
    match, = data["matches"]
    assert match["path"] == "src/cami/engine.py"
    assert any(edge["source"] == {"path": "src/cami/cli.py", "qualname": "main"}
               and edge["relation"] == "calls" for edge in match["incoming"])
