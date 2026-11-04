from cami.index import IndexConfig, build_index, compare_indexes, impacted
from cami.models import Node, RepoLocation
from cami.repository import read_snapshot


def snapshot(repo, revision):
    return read_snapshot(RepoLocation(repo_id="fixture", path=str(repo.root)), revision)


def test_comments_signature_and_checkout(repo):
    a = repo.commit({"module.py": "def f(a: int=1, /, *args, b=None, **kwargs) -> int:\n    return a\n"})
    b = repo.commit({"module.py": "# comment\ndef f(a: int=1, /, *args, b=None, **kwargs) -> int:\n    return a\n"})
    (repo.root / "module.py").write_text("uncommitted")
    before = repo.git("status", "--porcelain")
    old, new = snapshot(repo, a), snapshot(repo, b)
    left, right = build_index(old), build_index(new)
    diff = compare_indexes(left, right, old, new)
    assert diff.files == {"module.py"}
    assert not diff.symbols
    sig = left.modules[0].definitions[0].signature
    assert [p.kind for p in sig.parameters] == ["positional_only", "var_positional", "keyword_only", "var_keyword"]
    assert sig.parameters[0].default_ast == "Constant(value=1)"
    assert sig.parameters[2].default_ast == "Constant(value=None)"
    assert repo.git("status", "--porcelain") == before
    assert (repo.root / "module.py").read_text() == "uncommitted"
    assert repo.git("rev-parse", "HEAD") == b


def test_graph_union_depth_cycle(repo):
    a = repo.commit({"module.py": "def f(): return g()\ndef g(): return f()\ndef h(): return 1\n"})
    b = repo.commit({"module.py": "def f(): return 3\ndef g(): return f()\ndef h(): return 1\n"})
    old, new = snapshot(repo, a), snapshot(repo, b)
    diff = compare_indexes(build_index(old), build_index(new), old, new)
    f, g, h = (Node(path="module.py", qualname=n) for n in ["f", "g", "h"])
    assert g not in impacted(diff, 0)
    assert {f, g} <= impacted(diff, 1)
    assert h not in impacted(diff, 2)
    assert any(e.source == f and e.target == g for e in diff.edges)


def test_ambiguity_and_parse(repo):
    a = repo.commit({"module.py": "if True:\n    def f(): pass\ndef g(): pass\ndef g(): pass\n"})
    index = build_index(snapshot(repo, a), IndexConfig())
    assert all(d.ambiguous for d in index.modules[0].definitions)
    b = repo.commit({"module.py": "def broken("})
    assert build_index(snapshot(repo, b)).limitations() == {"module.py": "parse_error"}


def test_explicit_import(repo):
    a = repo.commit({"a.py": "def f(): return 1\n", "b.py": "from a import f as imported\ndef g(): return imported()\n"})
    index = build_index(snapshot(repo, a))
    assert any(e.source == Node(path="b.py", qualname="g") and e.target == Node(path="a.py", qualname="f") for e in index.edges)


def test_blob_limits_and_symlink(repo):
    a = repo.commit({"large.py": "x" * (2 * 1024 * 1024 + 1), "bad.py": "x = 1\n"})
    (repo.root / "link.py").symlink_to("/etc/passwd")
    b = repo.commit({})
    snap = snapshot(repo, b)
    assert snap.by_path()["link.py"].content is None
    assert snap.by_path()["link.py"].limitation == "symlink_unsupported"
    assert build_index(snap).limitations()["large.py"] == "file_too_large"
    assert a != b


def test_shadowed_call_is_unresolved(repo):
    a = repo.commit({"module.py": "def g(): return 1\ndef f(g): return g()\n"})
    index = build_index(snapshot(repo, a))
    f = Node(path="module.py", qualname="f")
    assert f in index.unresolved
    assert not any(edge.source == f for edge in index.edges)


def test_repeated_enclosing_class_and_function(repo):
    a = repo.commit({"module.py": "class C:\n    def f(self): return 1\nclass C:\n    def g(self): return 2\ndef outer():\n    def inner(): pass\ndef outer(): pass\n"})
    index = build_index(snapshot(repo, a))
    assert all(d.ambiguous for d in index.modules[0].definitions)


def test_rebound_import_is_unresolved(repo):
    a = repo.commit({"a.py": "def target(): pass\n", "module.py": "from a import target\ntarget = factory()\ndef f(): return target()\n"})
    index = build_index(snapshot(repo, a))
    f = Node(path="module.py", qualname="f")
    assert f in index.unresolved
    assert not any(edge.source == f for edge in index.edges)


def test_staged_index_and_sha256_repository(tmp_path):
    import subprocess
    from cami.artifacts import file_hash
    root = tmp_path / "sha256"
    root.mkdir()
    subprocess.run(["git","init","-q","--object-format=sha256",str(root)],check=True)
    def git(*args):
        return subprocess.check_output(["git","-C",str(root),*args]).decode().strip()
    git("config","user.name","fixture")
    git("config","user.email","fixture@example.invalid")
    (root / "module.py").write_text("def f(): pass\n")
    git("add",".")
    git("commit","-qm","parent")
    revision = git("rev-parse","HEAD")
    assert len(revision) == 64
    (root / "module.py").write_text("staged\n")
    git("add",".")
    index_hash = file_hash(root / ".git/index")
    (root / "module.py").write_text("unstaged\n")
    snap = read_snapshot(RepoLocation(repo_id="fixture",path=str(root)),revision)
    assert snap.by_path()["module.py"].content == b"def f(): pass\n"
    assert file_hash(root / ".git/index") == index_hash
    assert (root / "module.py").read_text() == "unstaged\n"


def test_ast_cache_respects_current_snapshot_size_limit(repo):
    revision = repo.commit({'module.py': 'def f(): pass\n'})
    location = RepoLocation(repo_id='fixture', path=str(repo.root))
    cache = {}
    for limit in (1024, 1, 1024, 1):
        current = read_snapshot(location, revision, max_file_bytes=limit)
        cached = build_index(current, cache=cache)
        fresh = build_index(current)
        assert cached == fresh
        assert bool(cached.definitions()) == (limit == 1024)
        assert cached.limitations() == ({} if limit == 1024 else {'module.py': 'file_too_large'})
