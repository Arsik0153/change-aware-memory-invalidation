"""Offline Git reads restricted to exactly the protocol's72 complete snapshots."""

from __future__ import annotations

import ast
from pathlib import Path

from packaging_audit_common import canonical, git, parse, require, sha
from packaging_audit_syntax import FUNCTIONS, LIMIT

SEED = "20261104-packaging-derived-development-v1"


class Project:
    def __init__(self, root, p, metadata, repo_override=None):
        self.allowed = [r["commit"] for r in metadata["frame"]]
        self.repo = repo_override or root / p["groups"][0]["repo_path"]
        require(
            all(g["repo_path"] == p["groups"][0]["repo_path"] for g in p["groups"]),
            "one project repo",
        )
        self.log = []
        self.blob_cache = {}
        self.sizes = {}
        self.snapshots = {}
        self.trees = {}
        for row in metadata["frame"]:
            parents = (
                self.command(row["commit"], "rev-list", "--parents", "-n", "1", row["commit"])
                .decode()
                .split()
            )
            require(
                parents == [row["commit"], *row["parents"]], "actual full parent topology mismatch"
            )

    def command(self, commit, *args):
        require(commit in self.allowed, "non-authorized project commit")
        self.log.append({"commit": commit, "argv": list(args)})
        return git(self.repo, *args)

    def body(self, commit, oid):
        require(
            commit in self.snapshots
            and oid in {b["oid"] for b in self.snapshots[commit].values() if b["kind"] == "blob"},
            "blob not bound to authorized tree",
        )
        if oid not in self.blob_cache:
            raw = self.command(commit, "cat-file", "blob", oid)
            require(
                __import__("hashlib")
                .sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw)
                .hexdigest()
                == oid,
                "Git blob OID/hash mismatch",
            )
            self.blob_cache[oid] = raw
        return self.blob_cache[oid]

    def snapshot(self, commit):
        require(commit in self.allowed, "unauthorized snapshot")
        tree = self.command(commit, "ls-tree", "-rz", "--full-tree", commit)
        self.trees[commit] = tree
        blobs = {}
        for item in tree.split(b"\0"):
            if not item:
                continue
            info, path = item.split(b"\t", 1)
            mode, kind, oid = info.decode().split()
            path = path.decode("utf-8")
            require(
                mode in {"100644", "100755", "120000", "160000"} and kind in {"blob", "commit"},
                "unsupported snapshot entry",
            )
            limitation = (
                "submodule_unsupported"
                if kind == "commit"
                else "symlink_unsupported"
                if mode == "120000"
                else None
            )
            if kind == "blob" and oid not in self.sizes:
                self.sizes[oid] = int(self.command(commit, "cat-file", "-s", oid))
            size = self.sizes.get(oid) if kind == "blob" else None
            if limitation is None and size > LIMIT:
                limitation = "file_too_large"
            blobs[path] = {
                "oid": oid,
                "mode": mode,
                "kind": kind,
                "size": size,
                "limitation": limitation,
                "raw": None,
            }
        self.snapshots[commit] = blobs
        for blob in blobs.values():
            if blob["limitation"] is None:
                blob["raw"] = self.body(commit, blob["oid"])
                if blob["raw"].startswith(b"version https://git-lfs.github.com/spec/v1"):
                    blob["limitation"] = "lfs_unsupported"
        return blobs

    def packet(self, result, gid, commit, claim, checker):
        from packaging_audit_syntax import reference

        cid, path = claim["claim_id"], claim["subject"]["path"]
        packet = result / "packets" / gid / commit / cid
        rawtree = self.command(
            commit, "ls-tree", "-z", "--full-tree", commit, "--", ":(literal)" + path
        )
        require(
            (packet / "git-ls-tree.raw").read_bytes() == rawtree, "raw reference Git tree mismatch"
        )
        expected = {
            "id": cid,
            "commit": commit,
            "path": path,
            "verdict": "uncertain",
            "reason": None,
            "git_mode": None,
            "git_oid": None,
            "source_sha256": None,
            "git_ls_tree_sha256": sha(rawtree),
        }
        files = {"git-ls-tree.raw", "decision.json"}
        entries = [x for x in rawtree.split(b"\0") if x]
        unsupported = None
        if not entries:
            for ancestor in reversed(Path(path).parents):
                if str(ancestor) == ".":
                    continue
                raw = self.command(
                    commit,
                    "ls-tree",
                    "-z",
                    "--full-tree",
                    commit,
                    "--",
                    ":(literal)" + str(ancestor),
                )
                name = "ancestor-" + sha(str(ancestor).encode()) + ".raw"
                files.add(name)
                require((packet / name).read_bytes() == raw, "raw ancestor tree mismatch")
                if raw:
                    info, found = raw.rstrip(b"\0").split(b"\t", 1)
                    mode, kind, oid = info.decode().split()
                    if found == str(ancestor).encode() and (mode != "040000" or kind != "tree"):
                        unsupported = {
                            "path": str(ancestor),
                            "git_mode": mode,
                            "git_type": kind,
                            "git_oid": oid,
                        }
                        break
        if unsupported:
            expected.update(
                reason="unsupported non-tree ancestor of exact subject path", evidence=[unsupported]
            )
        elif not entries:
            expected.update(
                verdict="contradicted",
                reason="exact subject path absent from frozen Git tree",
                evidence=[
                    {
                        "kind": "git_path_absence",
                        "commit": commit,
                        "path": path,
                        "command": [
                            "ls-tree",
                            "-z",
                            "--full-tree",
                            commit,
                            "--",
                            ":(literal)" + path,
                        ],
                    }
                ],
            )
        else:
            require(
                len(entries) == 1 and entries[0].split(b"\t", 1)[1] == path.encode(),
                "non-exact subject Git path",
            )
            mode, kind, oid = entries[0].split(b"\t", 1)[0].decode().split()
            expected.update(git_mode=mode, git_type=kind, git_oid=oid)
            if kind == "blob":
                raw = self.body(commit, oid)
                files.add("subject.raw")
                require(
                    (packet / "subject.raw").read_bytes() == raw,
                    "raw subject bytes differ from authorized Git blob",
                )
                expected["source_sha256"] = sha(raw)
            if mode not in {"100644", "100755"} or kind != "blob":
                expected["reason"] = "unsupported Git type or nonregular mode"
            else:
                case = {
                    "id": cid,
                    **{k: claim[k] for k in ("kind", "subject", "predicate", "text", "scope")},
                    "source_path": "subject.raw",
                    "source_sha256": sha(raw),
                }
                require(
                    parse((packet / "case.json").read_bytes()) == case,
                    "raw packet exact claim case mismatch",
                )
                files.add("case.json")
                ref = reference(raw, case)
                expected.update(ref, declared_source_sha256=sha(raw), checker=checker)
        require(
            {p.name for p in packet.iterdir() if p.is_file()} == files, "exact packet file layout"
        )
        decision = parse((packet / "decision.json").read_bytes())
        require(
            canonical(decision) == canonical(expected),
            "independent reference decision/facts/evidence mismatch: " + cid + " @ " + commit,
        )
        return expected


def parent_population(group, blobs, indexed, f):
    gid, parent = group["group_id"], group["parent_commit"]
    generation = Path(f.protocol["parent_generation_manifest_path"]).parent
    base = generation / "parents" / gid
    modules = []
    subjects = []
    eligible = []
    for path, b in blobs.items():
        reason = None
        if not path.startswith(("src/packaging/", "packaging/")):
            reason = "outside_package_roots"
        elif {"tests", "test", "_vendor", "vendor", "__pycache__"} & set(path.split("/")):
            reason = "excluded_path_component"
        elif not path.endswith(".py"):
            reason = "not_python_module"
        elif b["mode"] not in {"100644", "100755"} or b["kind"] != "blob":
            reason = "nonregular_git_entry"
        size = b["size"] if reason is None else None
        if reason is None and size > LIMIT:
            reason = "file_too_large"
        row = {
            "path": path,
            "git_mode": b["mode"],
            "git_type": b["kind"],
            "git_oid": b["oid"],
            "size_bytes": size,
            "exclusion_reason": reason,
            "source_sha256": None,
            "source_evidence_path": None,
        }
        if reason is None:
            raw = b["raw"]
            require(raw is not None, "allowed parent raw source unavailable")
            digest = sha(raw)
            row.update(source_sha256=digest, source_evidence_path="source/" + digest + ".raw")
            require(
                f.read(str(base / row["source_evidence_path"])) == raw,
                "complete parent module evidence hash/Git identity",
            )
            mod = indexed["modules"][path]
            if mod["limitation"]:
                row["exclusion_reason"] = mod["limitation"]
            else:
                direct = {id(n) for n in mod["tree"].body if isinstance(n, FUNCTIONS)}
                direct_names = [n.name for n in mod["tree"].body if isinstance(n, FUNCTIONS)]

                def visit(node, ancestors=()):
                    if isinstance(node, FUNCTIONS):
                        scope = (
                            "direct_module"
                            if id(node) in direct
                            else "nested_function"
                            if any(isinstance(a, FUNCTIONS) for a in ancestors)
                            else "class_method"
                            if any(isinstance(a, ast.ClassDef) for a in ancestors)
                            else "conditional_module"
                        )
                        defs = [d for d in mod["definitions"] if d["name"] == node.name]
                        reasons = []
                        if scope != "direct_module":
                            reasons.append(scope)
                        if getattr(node, "type_params", []):
                            reasons.append("unsupported_type_parameters")
                        if scope == "direct_module" and direct_names.count(node.name) != 1:
                            reasons.append("duplicate_direct_definition")
                        if len(defs) != 1 or any(d["ambiguous"] for d in defs):
                            reasons.append("ambiguous_or_missing_production_definition")
                        rank = sha((SEED + "\n" + parent + "\n" + path + "\n" + node.name).encode())
                        subjects.append(
                            {
                                "path": path,
                                "qualname": node.name,
                                "scope": scope,
                                "start_line": node.lineno,
                                "end_line": node.end_lineno,
                                "rank_sha256": rank,
                                "eligible": not reasons,
                                "exclusion_reasons": reasons,
                            }
                        )
                        if not reasons:
                            eligible.append((rank, path, node.name, node))
                    for child in ast.iter_child_nodes(node):
                        visit(child, (*ancestors, node))

                visit(mod["tree"])
        modules.append(row)
    require(
        f.rows(str(base / "module_inventory.jsonl")) == modules,
        "complete parent module inventory independently recomputed",
    )
    require(
        f.rows(str(base / "subject_inventory.jsonl")) == subjects,
        "complete parent subject inventory independently recomputed",
    )
    eligible.sort(key=lambda x: x[:3])
    ranking = [
        {"function_rank": i, "path": path, "qualname": name, "rank_sha256": rank, "selected": i < 4}
        for i, (rank, path, name, _) in enumerate(eligible)
    ]
    require(
        f.json(str(base / "ranking.json")) == ranking and len(eligible) >= 4,
        "complete parent SHA ranking/first-four selection",
    )
    return eligible[:4], {
        "tree_entries": len(modules),
        "eligible_python_modules": sum(row["exclusion_reason"] is None for row in modules),
        "retained_parent_module_blobs": sum(row["source_sha256"] is not None for row in modules),
        "function_occurrences": len(subjects),
        "eligible_subjects": len(eligible),
        "selected_functions": 4,
    }
