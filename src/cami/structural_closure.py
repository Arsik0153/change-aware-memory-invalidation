"""Bounded parent-only provenance closure for synthetic development fixtures."""
from __future__ import annotations

import ast
import hashlib
import keyword
import shutil
import sys
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, TypeVar

from pydantic import Field, field_validator

from cami.artifacts import canonical, digest, file_hash, parse, reserve, within, write_bytes
from cami.errors import InputError
from cami.index import INDEX_VERSION, Definition, Module, parse_module
from cami.models import (
    Anchor, Claim, Equals, Node, Provenance, Record, RepoLocation, Signature, Subject, Value,
    safe_path,
)
from cami.repository import Blob, Snapshot, read_snapshot

ADDENDUM_VERSION = "structural-provenance-closure/1"
DOCUMENT = Path(__file__).resolve().parents[2] / "docs/protocol_1_1_structural_closure_v1.md"
PROTOCOL_DOCUMENT = DOCUMENT.with_name("protocol_1_1.md")
SPEC_DOCUMENT = DOCUMENT.with_name("IMPLEMENTATION_SPEC.md")
DRAFT_REASON = "Draft parent-only anchors; dependency extraction and review pending."
SCOPES = {
    "symbol_exists": frozenset({"Exact syntactic definition, no runtime semantics.",
                                "Exact syntactic definition identity only."}),
    "signature_equals": frozenset({"Exact syntactic definition, no runtime semantics.",
        "Exact normalized syntax, including defaults, annotations, decorators, and async status."}),
}
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
R = TypeVar("R", bound=Record)


class FixtureAuthority(Value):
    type: Literal["automatic_fixture"]
    independent: Literal[False]

    @field_validator("independent", mode="before")
    @classmethod
    def exact_false(cls, value: object) -> object:
        if value is not False:
            raise ValueError("automatic fixture authority requires JSON false")
        return value


class ClosureAuthorization(Value):
    claim_id: str = Field(min_length=1)
    claim_sha256: Sha256
    provenance_sha256: Sha256
    close_reasons: tuple[str, ...] = Field(min_length=1)


class StructuralClosureRequest(Record):
    schema_version: Literal[1] = Field(...)
    protocol_version: Literal["1.1"]
    addendum_version: Literal["structural-provenance-closure/1"]
    addendum_sha256: Sha256
    dataset_kind: Literal["synthetic"]
    split: Literal["development"]
    stratum: Literal["fixture"]
    repo: RepoLocation
    parent_commit: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    claims_path: str
    claims_sha256: Sha256
    provenance_path: str
    provenance_sha256: Sha256
    closures: tuple[ClosureAuthorization, ...] = Field(min_length=1)
    authority: FixtureAuthority
    _paths = field_validator("claims_path", "provenance_path")(safe_path)


class SourceObservation(Value):
    node: Node
    blob_oid: str
    blob_sha256: Sha256
    retained_path: str
    line_count: int
    signature: Signature | None
    parser_unresolved: tuple[Node, ...]
    imports: tuple[tuple[str, str, str | None], ...]
    calls: tuple[str, ...]
    loaded_names: tuple[str, ...]


class ClosureEvidence(Record):
    repo: RepoLocation
    parent_commit: str
    subject: Subject
    claim_sha256: Sha256
    original_provenance_sha256: Sha256
    observations: tuple[SourceObservation, ...]
    anchors: tuple[Anchor, ...]
    binding_check: Literal["unconditional_unique_definition_and_inert_module_bindings"]
    explanation: str


class RemarkDisposition(Value):
    reason: str
    disposition: Literal["discharged_for_exact_syntax_fixture"]


class ClosureHistory(Record):
    claim_id: str
    parent_commit: str
    claim_sha256: Sha256
    original_provenance_sha256: Sha256
    derived_provenance_sha256: Sha256
    evidence_path: str
    evidence_sha256: Sha256
    remarks: tuple[RemarkDisposition, ...]
    authority: FixtureAuthority


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _records(data: bytes, model: type[R]) -> tuple[R, ...]:
    rows = tuple(model.model_validate_json(canonical(parse(line)))
                 for line in data.decode("utf-8").splitlines() if line.strip())
    ids = [getattr(row, "claim_id") for row in rows]
    if len(ids) != len(set(ids)):
        raise InputError("duplicate claim_id in source records")
    return rows


def _simple(name: str) -> bool:
    return name.isidentifier() and not keyword.iskeyword(name)


def _in_roots(path: str, roots: tuple[str, ...]) -> bool:
    return path not in roots and any(
        root == "." or PurePosixPath(path).is_relative_to(root) for root in roots)


_INERT = (
    ast.Constant, ast.Name, ast.Attribute, ast.Tuple, ast.List, ast.Set, ast.Dict,
    ast.UnaryOp, ast.BinOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.Subscript, ast.Slice,
    ast.Load, ast.operator, ast.unaryop, ast.boolop, ast.cmpop,
)
_DYNAMIC_NAMES = frozenset({
    "exec", "eval", "compile", "globals", "locals", "vars", "setattr", "delattr",
    "getattr", "__import__", "__builtins__", "__loader__", "__spec__",
})
_DYNAMIC_ATTRS = frozenset({
    "__dict__", "__globals__", "__builtins__", "__getattribute__", "__setattr__",
    "__delattr__", "modules", "f_globals", "f_locals", "exec", "eval", "setattr",
    "delattr", "getattr", "globals", "locals", "vars", "__import__",
})


def _inert(expression: ast.AST) -> None:
    if any(not isinstance(part, _INERT) for part in ast.walk(expression)):
        raise InputError("unsupported executable module/header expression")


def _binding_check(tree: ast.Module) -> None:
    for part in ast.walk(tree):
        if getattr(part, "type_params", ()):
            raise InputError("unsupported type_params")
        if isinstance(part, (ast.Global, ast.Nonlocal, ast.NamedExpr)):
            raise InputError("cross-scope or walrus binding uncertainty")
        if isinstance(part, ast.ImportFrom) and any(a.name == "*" for a in part.names):
            raise InputError("wildcard binding uncertainty")
        if isinstance(part, ast.alias) and any(
                name in _DYNAMIC_NAMES or name in _DYNAMIC_ATTRS for name in part.name.split(".")):
            raise InputError("aliased dynamic namespace uncertainty")
        if (isinstance(part, ast.Name) and part.id in _DYNAMIC_NAMES
                or isinstance(part, ast.Attribute) and part.attr in _DYNAMIC_ATTRS):
            raise InputError("dynamic namespace uncertainty")
        if isinstance(part, (ast.Attribute, ast.Subscript)) and isinstance(
                part.ctx, (ast.Store, ast.Del)):
            raise InputError("indirect namespace write uncertainty")
    bindings: set[str] = set()
    for statement in tree.body:
        names: list[str]
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = [statement.name]
            expressions = [*statement.decorator_list, *statement.args.defaults,
                           *(v for v in statement.args.kw_defaults if v is not None),
                           *(a.annotation for a in ast.walk(statement.args)
                             if isinstance(a, ast.arg) and a.annotation is not None)]
            if statement.returns is not None:
                expressions.append(statement.returns)
            for expression in expressions:
                _inert(expression)
        elif isinstance(statement, (ast.Import, ast.ImportFrom)):
            names = [a.asname or (a.name.split(".")[0] if isinstance(statement, ast.Import)
                                 else a.name) for a in statement.names]
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if any(not isinstance(target, ast.Name) for target in targets):
                raise InputError("unsupported module assignment binding")
            names = [target.id for target in targets if isinstance(target, ast.Name)]
            if statement.value is not None:
                _inert(statement.value)
            if isinstance(statement, ast.AnnAssign):
                _inert(statement.annotation)
        elif isinstance(statement, ast.Pass) or (isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)):
            names = []
        else:
            raise InputError("unsupported or conditional module binding")
        for name in names:
            if name in bindings:
                raise InputError("duplicate or rebound module binding")
            bindings.add(name)


class ParentSupport:
    def __init__(self, snapshot: Snapshot, repo: RepoLocation):
        self.snapshot = snapshot
        self.repo = repo
        self.blobs = snapshot.by_path()
        self.modules: dict[str, Module] = {}
        self.retained: dict[str, bytes] = {}

    def observe(self, node: Node) -> tuple[SourceObservation, Definition | None]:
        if not _in_roots(node.path, self.repo.source_roots):
            raise InputError("support outside configured index source roots")
        blob = self.blobs.get(node.path)
        if blob is None or blob.limitation or blob.content is None:
            raise InputError("missing support or relevant blob limitation")
        if blob.mode not in {"100644", "100755"}:
            raise InputError("unsupported support blob mode")
        module: Module | None = None
        definition: Definition | None = None
        if node.path.endswith(".py"):
            module = self._module(blob)
        if node.qualname is not None:
            if module is None or not _simple(node.qualname):
                raise InputError("only exact top-level Python function identities are supported")
            matches = [d for d in module.definitions if d.node == node]
            if len(matches) != 1 or matches[0].ambiguous or matches[0].node_kind != "function":
                raise InputError("missing, duplicate, conditional, or ambiguous definition")
            definition = matches[0]
        retained_path = "evidence/sources/" + blob.content_hash
        self.retained[retained_path] = blob.content
        return SourceObservation(
            node=node, blob_oid=blob.object_id, blob_sha256=blob.content_hash,
            retained_path=retained_path, line_count=len(blob.content.splitlines()),
            signature=definition.signature if definition else None,
            parser_unresolved=module.unresolved if module else (),
            imports=module.imports if module else (), calls=definition.calls if definition else (),
            loaded_names=tuple(sorted(definition.loaded_names)) if definition else (),
        ), definition

    def _module(self, blob: Blob) -> Module:
        if blob.path not in self.modules:
            module = parse_module(blob, blob.path)
            if module.limitation:
                raise InputError("relevant parse limitation")
            tree = ast.parse(module.source, filename=blob.path)
            _binding_check(tree)
            self.modules[blob.path] = module
        return self.modules[blob.path]


def _close(claim: Claim, prov: Provenance, authorization: ClosureAuthorization,
           support: ParentSupport) -> tuple[Provenance, ClosureEvidence]:
    if digest(claim) != authorization.claim_sha256 or digest(prov) != authorization.provenance_sha256:
        raise InputError("claim/provenance authorization digest mismatch")
    if claim.kind not in SCOPES or claim.scope not in SCOPES[claim.kind]:
        raise InputError("ineligible claim kind or exact syntactic scope")
    texts = {"Exact fixture syntax.",
             f"Exact {claim.kind} predicate for {claim.subject.path}::{claim.subject.qualname}."}
    if isinstance(claim.predicate, Equals):
        texts.add(f"The exact definition {claim.subject.path}:{claim.subject.qualname} has "
                  f"normalized signature {canonical(claim.predicate.expected_signature).decode()}.")
    else:
        texts.add(f"{claim.subject.path} contains the exact top-level function definition "
                  f"{claim.subject.qualname}.")
    if claim.text not in texts:
        raise InputError("claim text is outside the exact syntactic fixture templates")
    if claim.subject.node_kind != "function" or not _simple(claim.subject.qualname):
        raise InputError("ineligible subject kind or identity")
    if prov.scenario_id != "intact" or prov.dependencies or not prov.known_incomplete:
        raise InputError("closure requires intact, incomplete provenance with zero explicit dependencies")
    reasons = prov.unresolved_reasons
    requested = authorization.close_reasons
    if (not reasons or len(set(reasons)) != len(reasons)
            or len(set(requested)) != len(requested) or set(reasons) != set(requested)
            or any(reason != DRAFT_REASON for reason in reasons)):
        raise InputError("unknown, open, absent, or duplicate source remarks")
    subject = Node(path=claim.subject.path, qualname=claim.subject.qualname)
    observed, definition = support.observe(subject)
    if definition is None:
        raise InputError("subject definition absent")
    if isinstance(claim.predicate, Equals) and definition.signature != (
            claim.predicate.expected_signature):
        raise InputError("normalized signature mismatch")
    if not any(a.scope == "symbol" and a.path == subject.path and a.qualname == subject.qualname
               for a in prov.anchors):
        raise InputError("exact subject symbol anchor required")
    observations = [observed]
    for anchor in prov.anchors:
        if anchor.scope == "file" and anchor.qualname is not None:
            raise InputError("file anchor identity must not contain a qualname")
        item, _ = support.observe(Node(path=anchor.path, qualname=anchor.qualname))
        if anchor.observed_commit != support.snapshot.revision or anchor.content_hash != item.blob_sha256:
            raise InputError("anchor parent or blob hash mismatch")
        if any(line is not None and line > item.line_count
               for line in (anchor.start_line, anchor.end_line)):
            raise InputError("anchor display line bounds invalid")
        observations.append(item)
    derived = prov.model_copy(update={"known_incomplete": False,
                                      "unresolved_reasons": tuple(r for r in reasons if r not in requested)})
    evidence = ClosureEvidence(
        repo=support.repo, parent_commit=support.snapshot.revision, subject=claim.subject,
        claim_sha256=digest(claim), original_provenance_sha256=digest(prov),
        observations=tuple(observations), anchors=prov.anchors,
        binding_check="unconditional_unique_definition_and_inert_module_bindings",
        explanation="Body calls, imports, and loaded names are retained observations. Their runtime "
        "resolution is irrelevant to the exact stored definition and normalized signature syntax. "
        "Binding uncertainty was checked separately. Automatic fixture evidence is not independent review.",
    )
    return derived, evidence


def prepare_structural_closure(parent_inputs: Path, output: Path) -> Path:
    """Validate every requested closure before publishing a fresh fixture artifact."""
    base = parent_inputs.resolve().parent
    request_bytes = parent_inputs.read_bytes()
    request = StructuralClosureRequest.model_validate_json(canonical(parse(request_bytes.decode("utf-8"))))
    if file_hash(DOCUMENT) != request.addendum_sha256:
        raise InputError("addendum document hash mismatch")
    claims_path = within(base, request.claims_path)
    provenance_path = within(base, request.provenance_path)
    if any(output.resolve().is_relative_to(directory)
           for directory in (base, claims_path.parent, provenance_path.parent)):
        raise InputError("output must be outside source inputs")
    if output.exists() or output.is_symlink():
        raise InputError("output already exists")
    claims_bytes, prov_bytes = claims_path.read_bytes(), provenance_path.read_bytes()
    if _sha(claims_bytes) != request.claims_sha256 or _sha(prov_bytes) != request.provenance_sha256:
        raise InputError("source file hash mismatch")
    claims = _records(claims_bytes, Claim)
    provenance = _records(prov_bytes, Provenance)
    cmap, pmap = {c.claim_id: c for c in claims}, {p.claim_id: p for p in provenance}
    if not claims or cmap.keys() != pmap.keys():
        raise InputError("source claim/provenance population mismatch")
    ids = [a.claim_id for a in request.closures]
    if len(ids) != len(set(ids)) or not set(ids) <= cmap.keys():
        raise InputError("duplicate or unknown requested claim")
    repo = request.repo.model_copy(update={"path": str((base / request.repo.path).resolve())})
    snapshot = read_snapshot(repo, request.parent_commit)
    if snapshot.revision != request.parent_commit:
        raise InputError("parent must be the full resolved commit object ID")
    if any(c.origin_commit != snapshot.revision or c.repo_id != repo.repo_id for c in claims):
        raise InputError("claims must bind the exact parent and repository")
    support = ParentSupport(snapshot, repo)
    payload = {"claims.jsonl": claims_bytes, "source/provenance.jsonl": prov_bytes,
               "source/request.json": request_bytes}
    derived: dict[str, Provenance] = {}
    history: list[ClosureHistory] = []
    for authorization in request.closures:
        claim, prov = cmap[authorization.claim_id], pmap[authorization.claim_id]
        closed, evidence = _close(claim, prov, authorization, support)
        derived[claim.claim_id] = closed
        evidence_path = "evidence/" + digest(claim.claim_id) + ".json"
        evidence_bytes = canonical(evidence) + b"\n"
        payload[evidence_path] = evidence_bytes
        history.append(ClosureHistory(
            claim_id=claim.claim_id, parent_commit=snapshot.revision, claim_sha256=digest(claim),
            original_provenance_sha256=digest(prov), derived_provenance_sha256=digest(closed),
            evidence_path=evidence_path, evidence_sha256=_sha(evidence_bytes),
            remarks=tuple(RemarkDisposition(reason=r,
                         disposition="discharged_for_exact_syntax_fixture")
                         for r in authorization.close_reasons), authority=request.authority,
        ))
    payload.update(support.retained)
    lines = []
    for line in prov_bytes.splitlines(keepends=True):
        if line.strip():
            record = Provenance.model_validate_json(canonical(parse(line.decode("utf-8"))))
            if record.claim_id in derived:
                line = canonical(derived[record.claim_id]) + b"\n"
        lines.append(line)
    payload["provenance.jsonl"] = b"".join(lines)
    payload["closure_history.jsonl"] = b"".join(canonical(row) + b"\n" for row in history)
    documents = {"addendum": DOCUMENT, "protocol": PROTOCOL_DOCUMENT, "specification": SPEC_DOCUMENT}
    for name, path in documents.items():
        payload[f"evidence/{name}.md"] = path.read_bytes()
    manifest = {
        "schema_version": 1, "protocol_version": request.protocol_version,
        "addendum_version": request.addendum_version, "addendum_sha256": request.addendum_sha256,
        "document_hashes": {name: _sha(payload[f"evidence/{name}.md"]) for name in documents},
        "request_sha256": _sha(request_bytes), "claims_sha256": request.claims_sha256,
        "source_provenance_sha256": request.provenance_sha256,
        "derived_provenance_sha256": _sha(payload["provenance.jsonl"]),
        "derived_provenance_version": ADDENDUM_VERSION, "repo": repo.model_dump(mode="json"),
        "parent_commit": snapshot.revision, "closed_claim_ids": ids,
        "parent_only": True, "child_data_used": False, "independent_review": False,
        "real_experiment_eligible": False, "authority": request.authority.model_dump(mode="json"),
        "index_version": INDEX_VERSION,
        "python_version": sys.version,
        "signature_normalization": "cami.index.signature; syntax only; index_version=" + INDEX_VERSION,
        "implementation_sha256": {name: file_hash(Path(__file__).with_name(name)) for name in
                                  ("structural_closure.py", "index.py", "repository.py",
                                   "models.py", "artifacts.py")},
        "files": {name: _sha(data) for name, data in sorted(payload.items())},
    }
    payload["closure_manifest.json"] = canonical(manifest) + b"\n"
    reserve(output)
    try:
        for name, data in payload.items():
            write_bytes(output / name, data)
    except BaseException:
        shutil.rmtree(output)
        raise
    return output / "closure_manifest.json"
