"""Sealed parent-only access, complete module/subject enumeration and claim derivation."""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

from cami.artifacts import canonical, digest, file_hash, read_json, within, write_bytes, write_json, write_jsonl
from cami.index import IndexConfig, build_index
from cami.models import Claim, Equals, Exists, Subject
from cami.repository import Blob, Snapshot, git, resolve

SEED = "20261104-packaging-derived-development-v1"
ROOTS = ("src", "packaging")
PREFIXES = ("src/packaging/", "packaging/")
EXCLUDED = frozenset({"tests", "test", "_vendor", "vendor", "__pycache__"})
LIMIT = 2 * 1024 * 1024
PROTOCOL_ID = "packaging-derived-parent-collection-v2"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def preflight(protocol_path, root):
    protocol = read_json(protocol_path)
    if (protocol.get("schema_version") != 1 or protocol.get("status") != "sealed"
            or protocol.get("protocol_id") != PROTOCOL_ID or protocol.get("split") != "development"
            or (protocol_path.parent / protocol["root"]).resolve() != root):
        raise ValueError("requires a separately sealed derived-parent collection protocol")
    seal = read_json(within(root, protocol["seal_path"]))
    if seal["protocol_sha256"] != file_hash(protocol_path):
        raise ValueError("collection protocol hash mismatch")
    for name, expected in seal["files"].items():
        if file_hash(within(root, name)) != expected:
            raise ValueError(f"sealed collection input changed: {name}")
    def require(name):
        if name not in seal["files"]:
            raise ValueError(f"unsealed collection dependency: {name}")
        return within(root, name)
    for name in protocol["implementation_paths"]:
        require(name)
    for name in ("scripts/verify_cami.py", "scripts/validate_ai_review.py", "pyproject.toml", ".python-version", "uv.lock"):
        require(name)
    for path in (root / "src/cami").rglob("*.py"):
        require(str(path.relative_to(root)))
    require(str(Path(__file__).resolve().relative_to(root)))
    for name in [protocol["metadata_manifest_path"], protocol["reference_path"], protocol["rubric_path"],
                 protocol["review_schema_path"], *protocol["review_prompt_paths"], *protocol["reference_contract_paths"]]:
        require(name)
    if (protocol["rank_seed"] != SEED or tuple(protocol["repo"]["source_roots"]) != ROOTS
            or protocol["repo"]["repo_id"] != "packaging"):
        raise ValueError("fixed project, source roots or rank seed changed")
    source = protocol["source_configuration"]
    if (source["eligible_module_prefixes"] != list(PREFIXES) or set(source["excluded_path_components"]) != EXCLUDED
            or source["extensions"] != [".py"] or source["max_file_bytes"] != LIMIT
            or set(source["regular_modes"]) != {"100644", "100755"}
            or source["proposed_index_source_roots"] != list(ROOTS)):
        raise ValueError("parent source envelope changed")
    metadata = read_json(require(protocol["metadata_manifest_path"]))
    acquisition = read_json(require(protocol["metadata_protocol_path"]))
    if (acquisition.get("schema_version") != 1 or acquisition.get("status") != "sealed"
            or acquisition.get("phase") != "metadata_only"
            or acquisition.get("protocol_id") != "packaging-derived-development-collection-v2"
            or file_hash(require(protocol["metadata_protocol_path"])) != metadata["protocol_sha256"]
            or acquisition["selection"]["horizon"] != 23 or acquisition["selection"]["minimum_frame"] != 72
            or acquisition["selection"]["parents"] != 3 or acquisition["selection"]["prefix"] != 12
            or acquisition["selection"]["minimum_parent_gap"] != 24
            or acquisition["metadata_informed"] is not True or acquisition["original_plan_succeeded"] is not False):
        raise ValueError("parent v2 requires the separately frozen h23 metadata protocol, never v1")
    acquisition_seal = read_json(require(acquisition["seal_path"]))
    if acquisition_seal["protocol_sha256"] != metadata["protocol_sha256"]:
        raise ValueError("metadata acquisition seal protocol mismatch")
    for name, expected in acquisition_seal["files"].items():
        if file_hash(require(name)) != expected:
            raise ValueError("metadata acquisition sealed input changed")
    collection_path = require(protocol["metadata_collection_manifest_path"])
    collection = read_json(collection_path)
    if (collection.get("status") != "complete" or collection.get("protocol_sha256") != metadata["protocol_sha256"]
            or collection.get("seal") != acquisition_seal):
        raise ValueError("metadata collection must be complete with the exact acquisition seal")
    artifacts = collection.get("artifact_hashes", {})
    topology_path = require(protocol["metadata_manifest_path"])
    if not any((collection_path.parent / name).resolve() == topology_path for name in artifacts):
        raise ValueError("completed metadata collection must bind the topology artifact")
    for name, expected in artifacts.items():
        artifact = (collection_path.parent / name).resolve()
        if file_hash(require(str(artifact.relative_to(root)))) != expected:
            raise ValueError("metadata collection artifact changed")
    bindings = {}
    for label in ("study_plan", "amendment"):
        name, expected = protocol[label + "_path"], protocol[label + "_sha256"]
        if (acquisition[label + "_path"] != name or acquisition[label + "_sha256"] != expected
                or file_hash(require(name)) != expected):
            raise ValueError("v2 method amendment binding mismatch")
        bindings[label] = read_json(require(name))
    amendment = bindings["amendment"]
    if (bindings["study_plan"]["amendment"] != amendment
            or amendment.get("kind") != "metadata_informed_pre_source_amendment" or amendment["original_horizon"] != 24
            or amendment["new_horizon"] != 23 or amendment["observed_frame_length"] != 72
            or amendment["original_plan_succeeded"] is not False
            or amendment["parent_sources_read_before_amendment"] != 0
            or amendment["child_sources_read_before_amendment"] != 0
            or amendment["AI_or_reference_decisions_before_amendment"] != 0):
        raise ValueError("v2 must disclose the pre-source metadata-informed amendment")
    for label in ("prior_metadata_protocol", "prior_metadata_seal", "prior_failure_manifest", "infeasibility_report", "frame_binding"):
        binding = amendment[label]
        if file_hash(require(binding["path"])) != binding["sha256"]:
            raise ValueError("original infeasibility/amendment evidence changed")
    if read_json(require(amendment["prior_failure_manifest"]["path"]))["status"] != "failed":
        raise ValueError("original h24 plan must remain failed")
    if (amendment["frame_binding"]["path"] != acquisition["frame_binding_path"]
            or amendment["frame_binding"]["sha256"] != acquisition["frame_binding_sha256"]):
        raise ValueError("v2 metadata frame binding changed")
    if (acquisition["start_commit"] != protocol["start_commit"] or acquisition["boundary_commit"] != protocol["boundary_commit"]
            or acquisition["repo_path"] != protocol["repo"]["path"] or acquisition["source_configuration"] != source
            or metadata["source_configuration"] != source or metadata["schema_version"] != 1):
        raise ValueError("metadata source configuration differs from parent collection")
    frame, groups = metadata["frame"], metadata["groups"]
    if len({group["group_id"] for group in groups}) != 3:
        raise ValueError("derived parent group IDs must be distinct")
    length = len(frame)
    if metadata["frame_length"] != length or length < 72 or len(groups) != 3:
        raise ValueError("topology cannot support the fixed three disjoint windows")
    if length != amendment["observed_frame_length"] or collection.get("frame_length") != length:
        raise ValueError("completed metadata collection frame length changed")
    positions = [0, (length - 24) // 2, length - 24]
    if collection.get("parent_positions") != positions:
        raise ValueError("completed metadata collection parent positions changed")
    if any(b-a < 24 for a, b in zip(positions, positions[1:])):
        raise ValueError("frozen parent separation below 24 positions")
    ids = [row["commit"] for row in frame]
    if within(root, acquisition["frame_binding_path"]).read_text().splitlines() != ids:
        raise ValueError("v2 changed the already observed commit-only frame")
    if (len(ids) != len(set(ids)) or any(re.fullmatch(r"[0-9a-f]{40}", oid) is None for oid in ids)
            or metadata["start_commit"] != ids[0] or metadata["boundary_commit"] != ids[-1]
            or protocol["start_commit"] != ids[0] or protocol["boundary_commit"] != ids[-1]):
        raise ValueError("fixed metadata boundary/commit identity changed")
    allowed = [ids[position] for position in positions]
    if (protocol["source_access_parent_commits"] != allowed
            or metadata["parent_source_allowlist_after_separate_commit"] != allowed
            or metadata["child_source_access_authorized"] is not False):
        raise ValueError("source access must be exactly the three frozen parents")
    child_ids = []
    for group, position in zip(groups, positions, strict=True):
        parent = ids[position]
        children = ids[position+1:position+24]
        if (group["parent_position"] != position or group["parent_commit"] != parent
                or group["group_id"] != "packaging-derived-" + parent[:12]
                or group["child_commits"] != children or len(children) != 23
                or group["source_roots"] != list(ROOTS) or group["repo_id"] != "packaging"
                or group["repo_path"] != protocol["repo"]["path"] or len(group["steps"]) != 23):
            raise ValueError("frozen group/rank/window mismatch")
        for number, step in enumerate(group["steps"], 1):
            row = frame[position+number]
            previous = ids[position+number-1]
            if (step["step"] != number or step["commit"] != row["commit"] or step["parents"] != row["parents"]
                    or step["previous_commit"] != previous or not row["parents"] or row["parents"][0] != previous
                    or step["is_merge"] != (len(row["parents"]) > 1)):
                raise ValueError("frozen child topology mismatch")
        child_ids.extend(children)
    if len(set(child_ids)) != 69 or set(allowed).intersection(child_ids):
        raise ValueError("parent/child source windows overlap")
    repo = within(root, protocol["repo"]["path"])
    if resolve(repo, ids[0]) != ids[0] or resolve(repo, ids[-1]) != ids[-1]:
        raise ValueError("repository fixed endpoint mismatch")
    actual_path = [ids[0], *git(repo, "rev-list", "--first-parent", "--reverse", f"{ids[0]}..{ids[-1]}").decode().splitlines()]
    if actual_path != ids:
        raise ValueError("actual first-parent metadata frame changed")
    actual_rows = git(repo, "show", "--no-patch", "--format=%H%x00%P%x00%ct", *ids).decode().splitlines()
    actual = {line.split("\0")[0]: (line.split("\0")[1].split(), int(line.split("\0")[2])) for line in actual_rows if line}
    for position, row in enumerate(frame):
        if (row["position"] != position or actual.get(row["commit"]) != (row["parents"], row["committer_epoch"])
                or (position and (not row["parents"] or row["parents"][0] != ids[position-1]))):
            raise ValueError("actual full parent list/frame position changed")
    return protocol, seal, metadata, repo


@dataclass(frozen=True)
class Candidate:
    path: str
    qualname: str
    rank_sha256: str
    definition: object
    blob: Blob
    line_count: int


def enumerate_parent(repo, parent, output, budget, *, allowed_parents):
    """Read metadata for one allowed parent; source reads are only package regular .py."""
    if parent not in allowed_parents:
        raise ValueError("parent-only source allowlist denies this revision")
    tree = git(repo, "ls-tree", "-rz", "--full-tree", parent)
    write_bytes(output / "git-ls-tree.raw", tree)
    budget()
    inventory, blobs = [], []
    for raw in tree.split(b"\0"):
        if not raw:
            continue
        info, raw_path = raw.split(b"\t", 1)
        try:
            path = raw_path.decode("utf-8", "strict")
        except UnicodeError:
            inventory.append({"path": None, "raw_path_hex": raw_path.hex(), "exclusion_reason": "unsupported_git_path_encoding"})
            continue
        mode, kind, oid = info.decode().split()
        size = None
        parts = path.split("/")
        reason = None
        if not path.startswith(PREFIXES):
            reason = "outside_package_roots"
        elif EXCLUDED.intersection(parts):
            reason = "excluded_path_component"
        elif not path.endswith(".py"):
            reason = "not_python_module"
        elif mode not in {"100644", "100755"} or kind != "blob":
            reason = "nonregular_git_entry"
        if reason is None:
            size = int(git(repo, "cat-file", "-s", oid).decode().strip())
            if size < 0 or size > LIMIT:
                reason = "file_too_large"
        row = {"path": path, "git_mode": mode, "git_type": kind, "git_oid": oid,
               "size_bytes": size, "exclusion_reason": reason,
               "source_sha256": None, "source_evidence_path": None}
        if reason is None:
            content = git(repo, "cat-file", "blob", oid)
            if len(content) != size or len(content) > LIMIT:
                raise ValueError("parent blob size changed or exceeded frozen limit")
            retained = output / "source" / (sha(content) + ".raw")
            write_bytes(retained, content)
            row.update(source_sha256=sha(content), source_evidence_path="source/" + retained.name)
            limitation = "lfs_unsupported" if content.startswith(b"version https://git-lfs.github.com/spec/v1") else None
            blobs.append(Blob(path, oid, mode, content, limitation))
        inventory.append(row)
        write_jsonl(output / "module_inventory.jsonl", inventory)
        budget()
    snapshot = Snapshot("packaging", parent, tuple(blobs))
    index = build_index(snapshot, IndexConfig(ROOTS, False))
    by_module = {module.path: module for module in index.modules}
    subjects, candidates = [], []
    for blob in blobs:
        module = by_module[blob.path]
        row = next(row for row in inventory if row["path"] == blob.path)
        if blob.limitation or module.limitation:
            row["exclusion_reason"] = blob.limitation or module.limitation
            continue
        try:
            text = blob.content.decode("utf-8", "strict")
            tree = ast.parse(text, filename=blob.path)
        except (SyntaxError, UnicodeError, ValueError, RecursionError) as error:
            row["exclusion_reason"] = type(error).__name__
            continue
        direct = {id(node) for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        def visit(node, ancestors=()):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scope = "direct_module" if id(node) in direct else "nested_function" if any(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) for item in ancestors) else "class_method" if any(isinstance(item, ast.ClassDef) for item in ancestors) else "conditional_module"
                definitions = [definition for definition in module.definitions if definition.node.qualname == node.name]
                reasons = []
                if scope != "direct_module":
                    reasons.append(scope)
                if getattr(node, "type_params", ()):
                    reasons.append("unsupported_type_parameters")
                if scope == "direct_module" and len([item for item in tree.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == node.name]) != 1:
                    reasons.append("duplicate_direct_definition")
                if len(definitions) != 1 or any(definition.ambiguous for definition in definitions):
                    reasons.append("ambiguous_or_missing_production_definition")
                rank = sha((SEED + "\n" + parent + "\n" + blob.path + "\n" + node.name).encode())
                record = {"path": blob.path, "qualname": node.name, "scope": scope, "start_line": node.lineno,
                    "end_line": node.end_lineno, "rank_sha256": rank, "eligible": not reasons, "exclusion_reasons": reasons}
                subjects.append(record)
                if not reasons:
                    candidates.append(Candidate(blob.path, node.name, rank, definitions[0], blob, len(text.splitlines())))
            for child in ast.iter_child_nodes(node):
                visit(child, (*ancestors, node))
        visit(tree)
        budget()
    write_jsonl(output / "module_inventory.jsonl", inventory)
    write_jsonl(output / "subject_inventory.jsonl", subjects)
    ordered = sorted(candidates, key=lambda row: (row.rank_sha256, row.path, row.qualname))
    write_json(output / "ranking.json", [{"function_rank": rank, "path": row.path, "qualname": row.qualname,
        "rank_sha256": row.rank_sha256, "selected": rank < 4} for rank, row in enumerate(ordered)])
    if len(ordered) < 4:
        raise ValueError("fewer than four eligible parent subjects; no substitution authorized")
    return ordered[:4]


def derive_claims(group, candidates):
    rows, claims, provenance = [], [], {variant: [] for variant in ("symbol_anchor", "file_anchor", "known_incomplete")}
    for rank, candidate in enumerate(candidates):
        for kind, suffix in (("symbol_exists", "exists"), ("signature_equals", "signature")):
            path, name = candidate.path, candidate.qualname
            predicate = Exists(type=kind, expected=True) if kind == "symbol_exists" else Equals(type=kind, expected_signature=candidate.definition.signature)
            scope = "Exact syntactic definition identity only." if kind == "symbol_exists" else "Exact normalized syntax, including defaults, annotations, decorators, and async status."
            text = f"{path} contains the exact top-level function definition {name}." if kind == "symbol_exists" else f"The exact definition {path}:{name} has normalized signature {canonical(predicate.expected_signature).decode()}."
            claim = Claim(claim_id=f"{group['group_id']}-f{rank:02d}-{suffix}", repo_id="packaging", origin_commit=group["parent_commit"],
                kind=kind, subject=Subject(path=path, qualname=name, node_kind="function"), predicate=predicate, text=text, scope=scope)
            claim_json = claim.model_dump(mode="json", by_alias=True)
            claims.append(claim_json)
            rows.append({"schema_version": 1, "origin_kind": "new_derived_parent_claim", "original_candidate_id": None,
                "split": "development", "group_id": group["group_id"], "claim": claim_json, "claim_sha256": digest(claim),
                "parent_source_sha256": candidate.blob.content_hash, "parent_git_blob_object_id": candidate.blob.object_id,
                "symbol_ast_sha256": candidate.definition.ast_hash, "rank_sha256": candidate.rank_sha256, "function_rank": rank})
            for variant in provenance:
                file_scope = variant == "file_anchor"
                anchor = {"scope": "file" if file_scope else "symbol", "path": path, "observed_commit": group["parent_commit"],
                    "content_hash": candidate.blob.content_hash if file_scope else candidate.definition.ast_hash, "origin": "static",
                    "start_line": 1 if file_scope else candidate.definition.start_line,
                    "end_line": candidate.line_count if file_scope else candidate.definition.end_line}
                if not file_scope:
                    anchor["qualname"] = name
                provenance[variant].append({"schema_version": 1, "claim_id": claim.claim_id,
                    "scenario_id": "packaging_research_" + variant + "_v1", "anchors": [anchor], "dependencies": [],
                    "known_incomplete": variant == "known_incomplete",
                    "unresolved_reasons": ["Deliberate known-incomplete research baseline; no original630 provenance is changed."] if variant == "known_incomplete" else []})
    return rows, claims, provenance
