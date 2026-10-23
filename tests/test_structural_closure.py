from __future__ import annotations

import ast
import importlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import cami.repository as repository
import cami.structural_closure as closure
from cami.artifacts import (
    canonical, digest, file_hash, load_jsonl, read_json, read_jsonl, write_json, write_jsonl,
)
from cami.errors import InputError
from cami.index import ChangeSet, signature
from cami.models import Claim, MemoryState, Node, PolicyConfig, Provenance
from cami.policies import SelectionContext, select_claims

SOURCE = (
    '"""Parent-only fixture."""\n'
    'import external_library\n'
    '@decorate\n'
    'async def target(x: int = 1, /, *args: str, flag: bool = False, **kw: bytes) -> str:\n'
    '    import unavailable_body_import\n'
    '    return external_library.unresolved(x)\n\n'
    'def other():\n'
    '    raise RuntimeError("repository code must never execute")\n'
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True).stdout.decode().strip()


@dataclass(frozen=True)
class Fixture:
    repo: Path
    inputs: Path
    request: Path
    parent: str

    def rows(self, name: str) -> list[dict[str, Any]]:
        return read_jsonl(self.inputs / name)

    def bind(self) -> None:
        request = read_json(self.request)
        claims = {c.claim_id: c for c in load_jsonl(self.inputs / "claims.jsonl", Claim)}
        provenance = {p.claim_id: p for p in load_jsonl(self.inputs / "provenance.jsonl", Provenance)}
        request["claims_sha256"] = file_hash(self.inputs / "claims.jsonl")
        request["provenance_sha256"] = file_hash(self.inputs / "provenance.jsonl")
        for authorization in request["closures"]:
            key = authorization["claim_id"]
            if key not in claims or key not in provenance:
                continue
            authorization["claim_sha256"] = digest(claims[key])
            authorization["provenance_sha256"] = digest(provenance[key])
        write_json(self.request, request)


def make_fixture(tmp_path: Path, source: str = SOURCE, extra: dict[str, bytes] | None = None,
                 symlink: bool = False) -> Fixture:
    repo = tmp_path / "parent repo"
    repo.mkdir()
    git(repo, "init")
    module = repo / "src/module.py"
    module.parent.mkdir()
    module.write_text(source)
    if symlink:
        module.unlink()
        module.symlink_to("elsewhere.py")
    for name, data in (extra or {}).items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
        "commit", "-m", "only parent fixture")
    parent = git(repo, "rev-parse", "HEAD")
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    claims, provenance = [], []
    try:
        node = next(n for n in ast.parse(source).body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        expected = signature(node).model_dump(mode="json")
    except (SyntaxError, StopIteration):
        expected = signature(ast.parse("def target(): pass").body[0]).model_dump(mode="json")
    for claim_id, kind in (("exists", "symbol_exists"), ("signature", "signature_equals"),
                           ("unrequested", "prose")):
        predicate = {"type": kind}
        if kind == "symbol_exists":
            predicate["expected"] = True
        elif kind == "signature_equals":
            predicate["expected_signature"] = expected
        claims.append({"schema_version": 1, "claim_id": claim_id, "repo_id": "fixture",
            "origin_commit": parent, "kind": kind, "text": "Exact fixture syntax.",
            "subject": {"path": "src/module.py", "qualname": "target", "node_kind": "function"},
            "predicate": predicate, "scope": "Exact syntactic definition, no runtime semantics."})
        provenance.append({"schema_version": 1, "claim_id": claim_id, "scenario_id": "intact",
            "anchors": [{"path": "src/module.py", "qualname": "target", "scope": "symbol",
                "observed_commit": parent, "content_hash": closure._sha(source.encode()),
                "origin": "static", "start_line": 1, "end_line": 1}],
            "dependencies": [], "known_incomplete": True,
            "unresolved_reasons": [closure.DRAFT_REASON]})
    write_jsonl(inputs / "claims.jsonl", claims)
    (inputs / "provenance.jsonl").write_bytes(b"\r\n" + b"\r\n".join(
        json.dumps(p, separators=(", ", ": ")).encode() for p in provenance) + b"\r\n\r\n")
    request = inputs / "parents.json"
    write_json(request, {"schema_version": 1, "protocol_version": "1.1",
        "addendum_version": closure.ADDENDUM_VERSION, "addendum_sha256": file_hash(closure.DOCUMENT),
        "dataset_kind": "synthetic", "split": "development", "stratum": "fixture",
        "repo": {"repo_id": "fixture", "path": str(repo), "source_roots": ["src"]},
        "parent_commit": parent, "claims_path": "claims.jsonl", "claims_sha256": "0" * 64,
        "provenance_path": "provenance.jsonl", "provenance_sha256": "0" * 64,
        "closures": [{"claim_id": c["claim_id"], "claim_sha256": "0" * 64,
            "provenance_sha256": "0" * 64, "close_reasons": [closure.DRAFT_REASON]}
            for c in claims[:2]], "authority": {"type": "automatic_fixture", "independent": False}})
    fixture = Fixture(repo, inputs, request, parent)
    fixture.bind()
    return fixture


def assert_rejected(fixture: Fixture, output: Path) -> None:
    with pytest.raises((InputError, ValueError)):
        closure.prepare_structural_closure(fixture.request, output)
    assert not output.exists()


def test_broader_claim_text_cannot_borrow_an_exact_scope(tmp_path):
    fixture = make_fixture(tmp_path)
    claims = fixture.rows("claims.jsonl")
    claims[0]["text"] = "The function always returns a positive integer."
    write_jsonl(fixture.inputs / "claims.jsonl", claims)
    fixture.bind()
    assert_rejected(fixture, tmp_path / "rejected")


def test_source_root_must_be_a_directory_containing_the_subject(tmp_path):
    fixture = make_fixture(tmp_path)
    request = read_json(fixture.request)
    request["repo"]["source_roots"] = ["src/module.py"]
    write_json(fixture.request, request)
    assert_rejected(fixture, tmp_path / "rejected")


@pytest.mark.parametrize("source", [
    "from builtins import globals as ns\ndef target():\n    return ns()\n",
    "from builtins import globals as ns\ndef target():\n    ns().update({'target': 7})\n",
    "from sys import modules as registry\ndef target():\n    return registry\n",
])
def test_aliased_namespace_access_is_rejected(tmp_path, source):
    fixture = make_fixture(tmp_path, source)
    assert_rejected(fixture, tmp_path / "rejected")


def test_closes_both_predicates_with_bound_evidence_and_immutable_sources(tmp_path):
    fixture = make_fixture(tmp_path)
    before = {p: p.read_bytes() for p in fixture.inputs.iterdir()}
    checkout = git(fixture.repo, "status", "--porcelain"), git(fixture.repo, "rev-parse", "HEAD")
    output = tmp_path / "closed"
    manifest_path = closure.prepare_structural_closure(fixture.request, output)
    assert manifest_path == output / "closure_manifest.json"
    manifest = read_json(manifest_path)
    assert manifest["parent_only"] is True and manifest["child_data_used"] is False
    assert manifest["independent_review"] is False and manifest["real_experiment_eligible"] is False
    assert manifest["derived_provenance_version"] == closure.ADDENDUM_VERSION
    assert manifest["python_version"] == sys.version
    assert manifest["addendum_sha256"] == file_hash(closure.DOCUMENT)
    assert manifest["request_sha256"] == file_hash(fixture.request)
    assert manifest["derived_provenance_sha256"] == file_hash(output / "provenance.jsonl")
    files = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}
    assert files == {*manifest["files"], "closure_manifest.json"}
    for name, expected in manifest["files"].items():
        assert file_hash(output / name) == expected
    assert (output / "claims.jsonl").read_bytes() == before[fixture.inputs / "claims.jsonl"]
    assert (output / "source/provenance.jsonl").read_bytes() == before[fixture.inputs / "provenance.jsonl"]
    assert (output / "source/request.json").read_bytes() == before[fixture.request]
    original = fixture.rows("provenance.jsonl")
    derived = read_jsonl(output / "provenance.jsonl")
    for old, new in zip(original[:2], derived[:2], strict=True):
        assert new == {**old, "known_incomplete": False, "unresolved_reasons": []}
    assert derived[2] == original[2]
    raw_unrequested = next(line for line in before[fixture.inputs / "provenance.jsonl"].splitlines(True)
                           if b'"unrequested"' in line)
    assert raw_unrequested in (output / "provenance.jsonl").read_bytes()
    for row in read_jsonl(output / "closure_history.jsonl"):
        index = [p["claim_id"] for p in original].index(row["claim_id"])
        assert row["original_provenance_sha256"] == digest(Provenance.model_validate_json(canonical(original[index])))
        assert row["derived_provenance_sha256"] == digest(Provenance.model_validate_json(canonical(derived[index])))
        assert row["authority"] == {"type": "automatic_fixture", "independent": False}
        assert row["remarks"] == [{"reason": closure.DRAFT_REASON,
                                   "disposition": "discharged_for_exact_syntax_fixture"}]
        assert file_hash(output / row["evidence_path"]) == row["evidence_sha256"]
        evidence = read_json(output / row["evidence_path"])
        subject = evidence["observations"][0]
        assert subject["parser_unresolved"] and subject["imports"]
        assert subject["loaded_names"]
        assert subject["blob_oid"] == git(fixture.repo, "rev-parse", fixture.parent + ":src/module.py")
        assert (output / subject["retained_path"]).read_bytes() == SOURCE.encode()
        assert subject["signature"] == read_jsonl(output / "claims.jsonl")[1]["predicate"]["expected_signature"]
    assert before == {p: p.read_bytes() for p in fixture.inputs.iterdir()}
    assert checkout == (git(fixture.repo, "status", "--porcelain"), git(fixture.repo, "rev-parse", "HEAD"))


@pytest.mark.parametrize("policy", ["symbol_validate", "file_validate", "symbol_invalidate", "file_invalidate"])
def test_partial_closure_leaves_unrequested_conservative_fallback(tmp_path, policy):
    fixture = make_fixture(tmp_path)
    request = read_json(fixture.request)
    request["closures"] = request["closures"][:1]
    write_json(fixture.request, request)
    output = tmp_path / "closed"
    closure.prepare_structural_closure(fixture.request, output)
    claims = load_jsonl(output / "claims.jsonl", Claim)
    provenance = load_jsonl(output / "provenance.jsonl", Provenance)
    states = tuple(MemoryState(claim_id=c.claim_id, revision=c.origin_commit, state="valid",
        last_checked_commit=c.origin_commit, last_supported_commit=c.origin_commit,
        last_verdict="supported", basis="validated", current_provenance=p, available=True)
        for c, p in zip(claims, provenance, strict=True))
    changes = ChangeSet(frozenset(), frozenset(), (), frozenset({Node(path="src/module.py")}),
                        frozenset(), True)
    selections = select_claims(SelectionContext("synthetic-unit-transition", claims, provenance,
        states, changes, protocol_version="1.1"), PolicyConfig(id=policy))
    assert not selections[0].selected
    assert all(s.selected and "known_incomplete" in s.reasons for s in selections[1:])


@pytest.mark.parametrize("key,value", [
    ("dataset_kind", "real"), ("split", "heldout"), ("stratum", "chronological"),
    ("authority", None), ("authority", {"type": "human_review", "independent": True}),
    ("authority", {"type": "automatic_fixture", "independent": 0}),
    ("authority", {"type": "automatic_fixture", "independent": True}),
    ("protocol_version", "1.0"), ("schema_version", True), ("schema_version", "1"),
    ("addendum_version", "unknown"), ("addendum_sha256", "0" * 64),
    ("parent_commit", "HEAD"), ("parent_commit", "0" * 40),
    ("child_commits", ["do-not-read-child"]), ("labels_path", "do-not-read-labels"),
    ("parent_receipts_path", "do-not-read-receipts"), ("graph_views_path", "do-not-read-graphs"),
    ("diff", "do-not-read-diff"), ("closures", []),
])
def test_strict_request_rejects_nonfixture_authority_and_extra_inputs(tmp_path, key, value):
    fixture = make_fixture(tmp_path)
    request = read_json(fixture.request)
    request[key] = value
    write_json(fixture.request, request)
    assert_rejected(fixture, tmp_path / "rejected")


@pytest.mark.parametrize("damage", [
    "deps", "scope", "method", "nested", "type", "scenario", "already_complete",
    "unknown_reason", "extra_reason", "absent_reason", "duplicate_reason", "wrong_close_reason",
    "missing_close_reason", "duplicate_close_reason", "missing_anchor", "wrong_symbol",
    "wrong_anchor_commit", "wrong_anchor_hash", "wrong_lines", "wrong_repo", "wrong_parent",
    "duplicate_claim", "duplicate_provenance", "unmatched_provenance", "duplicate_closure",
    "unknown_closure", "outside_roots", "signature", "decorators", "async", "defaults",
    "annotations", "claim_digest", "provenance_digest", "claims_file_hash", "provenance_file_hash",
])
def test_ineligible_or_tampered_closure_is_atomic(tmp_path, damage):
    fixture = make_fixture(tmp_path)
    claims, provenance = fixture.rows("claims.jsonl"), fixture.rows("provenance.jsonl")
    claim, prov = claims[0], provenance[0]
    request = read_json(fixture.request)
    authorization = request["closures"][0]
    if damage == "deps":
        prov["dependencies"] = [{"from": {"path": "src/module.py", "qualname": "target"},
            "to": {"path": "src/module.py", "qualname": "other"}, "relation": "calls", "origin": "static"}]
    elif damage == "scope":
        claim["scope"] = "Runtime behavior is correct."
    elif damage == "method":
        claim["subject"]["node_kind"] = "method"
    elif damage == "nested":
        claim["subject"]["qualname"] = "outer.target"
    elif damage == "type":
        claim["kind"], claim["predicate"] = "prose", {"type": "prose"}
    elif damage == "scenario":
        prov["scenario_id"] = "known_missing"
    elif damage == "already_complete":
        prov["known_incomplete"] = False
    elif damage == "unknown_reason":
        prov["unresolved_reasons"] = ["not recognized"]
        authorization["close_reasons"] = ["not recognized"]
    elif damage == "extra_reason":
        prov["unresolved_reasons"].append("open binding uncertainty")
        authorization["close_reasons"] = prov["unresolved_reasons"]
    elif damage == "absent_reason":
        prov["unresolved_reasons"] = []
    elif damage == "duplicate_reason":
        prov["unresolved_reasons"] *= 2
    elif damage == "wrong_close_reason":
        authorization["close_reasons"] = ["not the source remark"]
    elif damage == "missing_close_reason":
        authorization["close_reasons"] = []
    elif damage == "duplicate_close_reason":
        authorization["close_reasons"] *= 2
    elif damage == "missing_anchor":
        prov["anchors"] = []
    elif damage == "wrong_symbol":
        prov["anchors"][0]["qualname"] = "other"
    elif damage == "wrong_anchor_commit":
        prov["anchors"][0]["observed_commit"] = "0" * 40
    elif damage == "wrong_anchor_hash":
        prov["anchors"][0]["content_hash"] = "0" * 64
    elif damage == "wrong_lines":
        prov["anchors"][0]["end_line"] = 10000
    elif damage == "wrong_repo":
        claim["repo_id"] = "another"
    elif damage == "wrong_parent":
        claim["origin_commit"] = "0" * 40
    elif damage == "duplicate_claim":
        claims.append(claim)
    elif damage == "duplicate_provenance":
        provenance.append(prov)
    elif damage == "unmatched_provenance":
        provenance = provenance[:2]
    elif damage == "duplicate_closure":
        request["closures"].append(authorization)
    elif damage == "unknown_closure":
        request["closures"].append({**authorization, "claim_id": "absent"})
    elif damage == "outside_roots":
        request["repo"]["source_roots"] = ["another"]
    elif damage in {"signature", "decorators", "async", "defaults", "annotations"}:
        expected = claims[1]["predicate"]["expected_signature"]
        if damage == "signature":
            expected["returns_ast"] = None
        elif damage == "decorators":
            expected["decorators_ast"] = []
        elif damage == "async":
            expected["is_async"] = False
        elif damage == "defaults":
            expected["parameters"][0]["default_ast"] = None
        else:
            expected["parameters"][0]["annotation_ast"] = None
    write_jsonl(fixture.inputs / "claims.jsonl", claims)
    write_jsonl(fixture.inputs / "provenance.jsonl", provenance)
    write_json(fixture.request, request)
    fixture.bind()
    if damage.endswith("digest") or damage.endswith("file_hash"):
        request = read_json(fixture.request)
        if damage == "claim_digest":
            request["closures"][0]["claim_sha256"] = "0" * 64
        elif damage == "provenance_digest":
            request["closures"][0]["provenance_sha256"] = "0" * 64
        elif damage == "claims_file_hash":
            request["claims_sha256"] = "0" * 64
        else:
            request["provenance_sha256"] = "0" * 64
        write_json(fixture.request, request)
    assert_rejected(fixture, tmp_path / "rejected")


@pytest.mark.parametrize("source", [
    "def target(): pass\ndef target(): pass\n",
    "if True:\n    def target(): pass\n",
    "def target(): pass\nif False:\n    def target(): pass\n",
    "def target(): pass\ntarget = 1\n",
    "target: int\ndef target(): pass\n",
    "from external import target\ndef target(): pass\n",
    "import other as target\ndef target(): pass\n",
    "from external import *\ndef target(): pass\n",
    "def target(): pass\n(target := 1)\n",
    "def target(): pass\ndef setter():\n    global target\n    target = 1\n",
    "def outer():\n    def target(): pass\n",
    "class C:\n    def target(): pass\n",
    "def target(): pass\nglobals()['target'] = 1\n",
    "def target():\n    return globals()\n",
    "def target(): pass\nnamespace = globals\nnamespace()['target'] = 1\n",
    "import builtins\ndef target(): pass\nbuiltins.exec('target = 1')\n",
    "def target():\n    obj.__dict__['target'] = 1\n",
    "def target():\n    obj.target = 1\n",
    "def target():\n    return sys.modules\n",
    "def target(): pass\nrun_arbitrary_code()\n",
    "def target(x=run_arbitrary_code()): pass\n",
    "@factory()\ndef target(): pass\n",
    "def target[T](x: T): pass\n",
    "def target():\n    def nested[T](): pass\n",
    "def target(): pass\nfor target in []: pass\n",
    "def target(): pass\ndel target\n",
    "def target(): pass\ntry:\n    pass\nexcept Exception as target:\n    pass\n",
    "def target(): pass\nmatch value:\n    case {'key': target}: pass\n",
])
def test_binding_hazards_and_unsupported_forms_fail_closed(tmp_path, source):
    fixture = make_fixture(tmp_path, source)
    assert_rejected(fixture, tmp_path / "rejected")


@pytest.mark.parametrize("source,symlink", [
    ("def invalid(\n", False),
    ("version https://git-lfs.github.com/spec/v1\noid sha256:0000\nsize 1\n", False),
    ("def target(): pass\n" + "#" * (repository.MAX_FILE_BYTES + 1), False),
    ("def target(): pass\n", True),
], ids=["parse", "lfs", "size", "symlink"])
def test_relevant_blob_limitations_are_atomic(tmp_path, source, symlink):
    fixture = make_fixture(tmp_path, source, symlink=symlink)
    assert_rejected(fixture, tmp_path / "rejected")


def test_all_additional_anchors_checked_and_scope_preserved(tmp_path):
    fixture = make_fixture(tmp_path, extra={"src/notes.txt": b"only parent evidence\n"})
    provenance = fixture.rows("provenance.jsonl")
    provenance[0]["anchors"].append({"path": "src/notes.txt", "scope": "file", "qualname": None,
        "observed_commit": fixture.parent, "content_hash": closure._sha(b"only parent evidence\n"),
        "origin": "manual", "start_line": 1, "end_line": 1})
    write_jsonl(fixture.inputs / "provenance.jsonl", provenance)
    fixture.bind()
    closure.prepare_structural_closure(fixture.request, tmp_path / "closed")
    derived = read_jsonl(tmp_path / "closed/provenance.jsonl")
    assert derived[0]["anchors"] == provenance[0]["anchors"]
    provenance[0]["anchors"][-1]["content_hash"] = "0" * 64
    write_jsonl(fixture.inputs / "provenance.jsonl", provenance)
    fixture.bind()
    assert_rejected(fixture, tmp_path / "rejected")


def test_missing_schema_and_authority_and_duplicate_json_keys_rejected(tmp_path):
    fixture = make_fixture(tmp_path)
    original = read_json(fixture.request)
    for key in ("schema_version", "authority"):
        request = dict(original)
        del request[key]
        write_json(fixture.request, request)
        assert_rejected(fixture, tmp_path / "rejected")
    fixture.request.write_bytes(b'{"schema_version":1,' + canonical(original)[1:])
    assert_rejected(fixture, tmp_path / "rejected")


def test_no_overwrite_or_nested_output_or_escaping_input(tmp_path):
    fixture = make_fixture(tmp_path)
    assert_rejected(fixture, fixture.inputs / "nested")
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "sentinel").write_text("preserved")
    with pytest.raises(InputError, match="already exists"):
        closure.prepare_structural_closure(fixture.request, existing)
    assert list(existing.iterdir()) == [existing / "sentinel"]
    assert (existing / "sentinel").read_text() == "preserved"
    request = read_json(fixture.request)
    request["claims_path"] = "../escape.jsonl"
    write_json(fixture.request, request)
    assert_rejected(fixture, tmp_path / "rejected")


def test_parent_only_boundary_with_no_child_and_forbidden_operations_guarded(tmp_path, monkeypatch):
    fixture = make_fixture(tmp_path)
    assert git(fixture.repo, "rev-list", "--count", "HEAD") == "1"
    forbidden = []
    def deny(*args, **kwargs):
        forbidden.append((args, kwargs))
        raise AssertionError("forbidden experiment/dataset/probe operation")
    for module_name, names in {
        "cami.inputs": ["check_inputs"],
        "cami.dataset": ["check_dataset", "freeze_dataset", "annotate_export"],
        "cami.engine": ["run_experiment", "check_inputs"],
        "cami.validation": ["validate_claim"],
        "cami.behavior": ["execute_probe", "check_docker"],
        "cami.policies": ["select_claims"],
        "cami.repository": ["chain", "changed_files", "materialize"],
    }.items():
        module = importlib.import_module(module_name)
        for name in names:
            monkeypatch.setattr(module, name, deny)
    original_snapshot = closure.read_snapshot
    seen = []
    def parent_only(repo, revision):
        assert revision == fixture.parent
        seen.append(revision)
        return original_snapshot(repo, revision)
    monkeypatch.setattr(closure, "read_snapshot", parent_only)
    original_git = repository.git
    def bounded_git(repo, *args, **kwargs):
        assert args[0] in {"rev-parse", "ls-tree", "cat-file"}
        return original_git(repo, *args, **kwargs)
    monkeypatch.setattr(repository, "git", bounded_git)
    original_read_bytes, original_read_text = Path.read_bytes, Path.read_text
    readable = {fixture.request, fixture.inputs / "claims.jsonl", fixture.inputs / "provenance.jsonl",
                closure.DOCUMENT, closure.PROTOCOL_DOCUMENT, closure.SPEC_DOCUMENT}
    readable.update(Path(closure.__file__).with_name(name) for name in (
        "structural_closure.py", "index.py", "repository.py", "models.py", "artifacts.py"))
    def guarded_bytes(path):
        assert path in readable
        return original_read_bytes(path)
    def guarded_text(path, *args, **kwargs):
        assert path in readable
        return original_read_text(path, *args, **kwargs)
    with monkeypatch.context() as reads:
        reads.setattr(Path, "read_bytes", guarded_bytes)
        reads.setattr(Path, "read_text", guarded_text)
        closure.prepare_structural_closure(fixture.request, tmp_path / "closed")
    assert seen == [fixture.parent] and not forbidden
    output_names = [p.name for p in (tmp_path / "closed").rglob("*")]
    assert not any(word in name for name in output_names
                   for word in ("child", "labels", "receipts", "graphs", "probe"))


def test_request_and_authorization_are_frozen_and_strict(tmp_path):
    fixture = make_fixture(tmp_path)
    request = closure.StructuralClosureRequest.model_validate_json(fixture.request.read_bytes())
    with pytest.raises(ValidationError):
        request.split = "heldout"
    with pytest.raises(ValidationError):
        request.closures[0].claim_id = "another"


def test_relative_repository_and_generated_scope_allowlist(tmp_path):
    fixture = make_fixture(tmp_path)
    claims = fixture.rows("claims.jsonl")
    claims[0]["scope"] = "Exact syntactic definition identity only."
    claims[1]["scope"] = (
        "Exact normalized syntax, including defaults, annotations, decorators, and async status.")
    write_jsonl(fixture.inputs / "claims.jsonl", claims)
    request = read_json(fixture.request)
    request["repo"]["path"] = "../parent repo"
    write_json(fixture.request, request)
    fixture.bind()
    manifest = closure.prepare_structural_closure(fixture.request, tmp_path / "closed")
    assert read_json(manifest)["repo"]["path"] == str(fixture.repo)


@pytest.mark.parametrize("anchor_damage", ["missing_file", "missing_symbol", "parse_error", "identity"])
def test_every_additional_anchor_must_be_valid(tmp_path, anchor_damage):
    fixture = make_fixture(tmp_path, extra={"src/broken.py": b"def invalid(\n"})
    provenance = fixture.rows("provenance.jsonl")
    anchor = dict(provenance[0]["anchors"][0])
    if anchor_damage == "missing_file":
        anchor["path"] = "src/absent.py"
    elif anchor_damage == "missing_symbol":
        anchor["qualname"] = "absent"
    elif anchor_damage == "parse_error":
        anchor.update(path="src/broken.py", content_hash=closure._sha(b"def invalid(\n"),
                      scope="file", qualname=None)
    else:
        anchor["scope"] = "file"
    provenance[0]["anchors"].append(anchor)
    write_jsonl(fixture.inputs / "provenance.jsonl", provenance)
    fixture.bind()
    assert_rejected(fixture, tmp_path / "rejected")


def test_bad_encoding_and_symlink_input_escape_are_rejected(tmp_path):
    fixture = make_fixture(tmp_path, extra={"src/module.py": b"\xff\xfe"})
    assert_rejected(fixture, tmp_path / "encoding-rejected")
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes((fixture.inputs / "claims.jsonl").read_bytes())
    (fixture.inputs / "claims.jsonl").unlink()
    (fixture.inputs / "claims.jsonl").symlink_to(outside)
    assert_rejected(fixture, tmp_path / "symlink-rejected")


def test_cli_uses_parent_manifest_and_returns_artifact(tmp_path):
    fixture = make_fixture(tmp_path)
    script = Path(__file__).resolve().parents[1] / "scripts/prepare_main.py"
    result = subprocess.run([sys.executable, str(script), "close-structural-provenance",
        "--parents", str(fixture.request), "--out", str(tmp_path / "closed")],
        check=True, capture_output=True, text=True)
    assert result.stdout.strip() == str(tmp_path / "closed/closure_manifest.json")
    invalid = read_json(fixture.request)
    invalid["dataset_kind"] = "real"
    write_json(fixture.request, invalid)
    result = subprocess.run([sys.executable, str(script), "close-structural-provenance",
        "--parents", str(fixture.request), "--out", str(tmp_path / "rejected")],
        check=False, capture_output=True, text=True)
    assert result.returncode == 2 and "preparation error" in result.stderr
    assert not (tmp_path / "rejected").exists()
