"""Read-only CAMI selection diagnostics, with no labels or truth metrics."""
from __future__ import annotations

import argparse
import ast
import builtins
from collections import Counter, defaultdict
import json
import hashlib
from pathlib import Path
import sys


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def node_value(node):
    return {"path": node.path, "qualname": node.qualname}


def scan_constructs(index):
    """Count source constructs independently, once per AST occurrence."""
    by_name = defaultdict(list)
    for module in index.modules:
        by_name[module.module_name].append(module)
    counts = Counter()
    examples = defaultdict(list)

    def record(category, module, part, detail):
        counts[category] += 1
        if len(examples[category]) < 6:
            examples[category].append({"path": module.path, "line": getattr(part, "lineno", None), "detail": detail})

    for module in index.modules:
        if module.limitation:
            record("analysis_" + module.limitation, module, ast.Pass(), module.limitation)
            continue
        tree = ast.parse(module.source, filename=module.path)
        local_defs = {d.node.qualname for d in module.definitions if not d.ambiguous}
        imported = {}
        for alias, target_module, symbol in module.imports:
            targets = by_name.get(target_module, [])
            imported[alias] = bool(len(targets) == 1 and symbol and symbol != "*" and any(
                d.node.qualname == symbol and not d.ambiguous for d in targets[0].definitions))
        for part in ast.walk(tree):
            if isinstance(part, (ast.Import, ast.ImportFrom)):
                if isinstance(part, ast.ImportFrom):
                    if any(alias.name == "*" for alias in part.names):
                        record("wildcard_import", module, part, ast.unparse(part))
                    target = part.module or ""
                    if part.level:
                        package = module.module_name.split(".") if module.path.endswith("/__init__.py") else module.module_name.split(".")[:-1]
                        target = ".".join(package[:len(package)-part.level+1] + ([target] if target else []))
                    target_names = [target]
                else:
                    target_names = [alias.name for alias in part.names]
                for target in target_names:
                    if target not in by_name:
                        category = "stdlib_import_outside_index" if target.split(".")[0] in sys.stdlib_module_names else "external_or_missing_import"
                        record(category, module, part, target)
                    elif isinstance(part, ast.Import):
                        record("module_import_unresolved_by_v1", module, part, target)
                    elif len(by_name[target]) != 1:
                        record("ambiguous_module_import", module, part, target)
                    elif isinstance(part, ast.ImportFrom):
                        for alias in part.names:
                            if alias.name != "*" and not any(d.node.qualname == alias.name and not d.ambiguous for d in by_name[target][0].definitions):
                                record("missing_or_reexported_symbol_import", module, part, target + "." + alias.name)
            elif isinstance(part, ast.Call):
                if isinstance(part.func, ast.Attribute):
                    record("attribute_call", module, part, ast.unparse(part.func))
                elif not isinstance(part.func, ast.Name):
                    record("computed_callable", module, part, ast.unparse(part.func))
                elif part.func.id not in local_defs and not imported.get(part.func.id, False):
                    category = ("builtin_name_call" if part.func.id in vars(builtins)
                                else "unresolved_name_call_candidate")
                    record(category, module, part, part.func.id)
        for definition in module.definitions:
            for call in definition.calls:
                if call in definition.local_bindings:
                    record("shadowed_or_parameter_call", module, ast.Pass(), (definition.node.qualname or "") + ":" + call)
            if definition.ambiguous:
                record("ambiguous_definition", module, ast.Pass(), definition.node.qualname)
    return {"counts": dict(sorted(counts.items())), "examples": dict(sorted(examples.items()))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    from cami.artifacts import load_jsonl
    import cami.index as index_implementation
    from cami.models import Claim, Node, Provenance, RepoLocation
    from cami.repository import read_snapshot

    index_path = Path(index_implementation.__file__)
    IndexConfig = index_implementation.IndexConfig
    build_index = index_implementation.build_index
    compare_indexes = index_implementation.compare_indexes
    impacted = index_implementation.impacted

    dataset = json.loads(args.dataset.read_text())
    manifests = sorted(args.runs.rglob("manifest.json"))
    policies = defaultdict(lambda: {"counts": Counter(), "reason_overlap_sets": Counter(), "examples": []})
    totals = Counter()
    indexes = {}
    scans = {}
    transitions = {}
    analyzed = []
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("status") != "complete" or "config" not in manifest:
            continue
        run = manifest_path.parent
        config = manifest["config"]
        policy = config["policy"]["id"]
        bucket = policies[policy]
        bucket["counts"]["runs"] += 1
        claims = {c.claim_id: c for c in load_jsonl(run / "claims.jsonl", Claim)}
        provenance = {p.claim_id: p for p in load_jsonl(run / "provenance.jsonl", Provenance)}
        selected = records(run / "selections.jsonl")
        repo = RepoLocation.model_validate_json(json.dumps(config["repo"]))
        previous_commit = manifest["parent_commit"]
        prior_unavailable = set()
        state_by_commit = defaultdict(dict)
        for state in records(run / "states.jsonl"):
            state_by_commit[state["revision"]][state["claim_id"]] = state
        for commit in manifest["child_commits"]:
            key = (repo.path, repo.repo_id, previous_commit, commit, tuple(repo.source_roots))
            if key not in transitions:
                snapshots = []
                for revision in (previous_commit, commit):
                    ikey = (repo.path, revision, tuple(repo.source_roots))
                    if ikey not in indexes:
                        snap = read_snapshot(repo, revision)
                        index = build_index(snap, IndexConfig(repo.source_roots))
                        indexes[ikey] = (snap, index)
                        scans[ikey] = {"repo_id": repo.repo_id, "commit": revision, **scan_constructs(index)}
                    snapshots.append(indexes[ikey])
                (old, before), (new, after) = snapshots
                changes = compare_indexes(before, after, old, new)
                affected = impacted(changes, config["policy"]["dependency_depth"])
                transitions[key] = (before, after, changes, affected)
            before, after, changes, affected = transitions[key]
            affected = impacted(changes, config["policy"]["dependency_depth"])
            left, right = before.definitions(), after.definitions()
            syntax_changed = {node for node in left.keys() | right.keys() if node not in left or node not in right
                              or left[node].ast_hash != right[node].ast_hash or left[node].ambiguous or right[node].ambiguous
                              or left[node].node_kind != right[node].node_kind}
            transition_counts = Counter()
            decisions = [row for row in selected if row["commit"] == commit]
            for row in decisions:
                claim = claims[row["claim_id"]]
                prov = provenance[claim.claim_id]
                subject = Node(path=claim.subject.path, qualname=claim.subject.qualname)
                reasons = tuple(sorted(row["reasons"]))
                bucket["counts"]["decisions"] += 1
                bucket["counts"]["selected"] += row["selected"]
                for reason in reasons:
                    bucket["counts"]["reason/" + reason] += 1
                bucket["reason_overlap_sets"][" + ".join(reasons) or "none"] += 1
                fallback_codes = {"unresolved_dependency", "graph_free_unresolved_fallback", "global_unresolved_fallback", "analysis_limitation", "known_incomplete"}
                fallback_only = bool(row["selected"] and reasons and set(reasons) <= fallback_codes)
                bucket["counts"]["fallback_only"] += fallback_only
                flags = {
                    "subject_ast_changed": subject in syntax_changed,
                    "subject_affected_depth": subject in affected,
                    "subject_file_changed": subject.path in changes.files,
                    "subject_unresolved": subject in changes.unresolved,
                    "subject_module_unresolved": Node(path=subject.path) in changes.unresolved,
                    "repository_global_unresolved": changes.global_unresolved,
                    "known_incomplete": bool(prov.known_incomplete or prov.unresolved_reasons or not prov.anchors),
                    "previously_unavailable": claim.claim_id in prior_unavailable,
                }
                declared_nodes = {subject, *(Node(path=a.path, qualname=a.qualname) for a in prov.anchors), *(d.target for d in prov.dependencies)}
                declared_paths = {node.path for node in declared_nodes}
                limited = bool(declared_paths & changes.limited_paths)
                explicit_unresolved = any(d.target in changes.unresolved or Node(path=d.target.path) in changes.unresolved for d in prov.dependencies)
                structural = claim.kind in {"symbol_exists", "signature_equals"}
                conservative = flags["known_incomplete"] or limited or explicit_unresolved
                exact_file = conservative or flags["previously_unavailable"] or bool(declared_paths & changes.files)
                exact_symbol = conservative or flags["previously_unavailable"] or subject in syntax_changed
                exact_symbol |= any((a.scope == "file" and a.path in changes.files)
                                    or (a.scope == "symbol" and Node(path=a.path, qualname=a.qualname) in syntax_changed)
                                    for a in prov.anchors)
                exact_symbol |= any(d.target in affected for d in prov.dependencies)
                flags["counterfactual_exact_syntax_file_selected"] = bool(exact_file) if structural else None
                flags["counterfactual_exact_syntax_symbol_selected"] = bool(exact_symbol) if structural else None
                for flag, value in flags.items():
                    if value is not None:
                        transition_counts[flag] += value
                        bucket["counts"][flag] += value
                support = set(declared_nodes)
                frontier = set(support)
                while frontier:
                    deps = {edge.target for edge in changes.edges if edge.source in frontier}
                    frontier = deps - support
                    support.update(frontier)
                local_unknown = support & changes.unresolved
                module_unknown = {Node(path=node.path) for node in support} & changes.unresolved
                transition_counts["decisions"] += 1
                transition_counts["local_unresolved_escalation"] += "unresolved_dependency" in reasons
                transition_counts["global_unresolved_escalation"] += "global_unresolved_fallback" in reasons
                transition_counts["graph_free_global_escalation"] += "graph_free_unresolved_fallback" in reasons
                example = {"run": str(run.resolve()), "claim_id": claim.claim_id, "kind": claim.kind,
                           "subject": node_value(subject), "parent_commit": previous_commit, "commit": commit,
                           "selected": row["selected"], "reasons": reasons, "fallback_only": fallback_only, **flags,
                           "unresolved_support_nodes": [node_value(n) for n in sorted(local_unknown | module_unknown, key=lambda n:(n.path,n.qualname or ""))][:12]}
                if len(bucket["examples"]) < 12:
                    bucket["examples"].append(example)
            if policy == "symbol_validate":
                totals.update(transition_counts)
                analyzed.append({"run": str(run.resolve()), "parent_commit": previous_commit, "commit": commit,
                                 "changed_files": sorted(changes.files), "changed_symbol_count": len(changes.symbols),
                                 "unresolved_node_count": len(changes.unresolved), "module_unresolved_count": sum(n.qualname is None for n in changes.unresolved),
                                 "counts": dict(sorted(transition_counts.items()))})
            prior_unavailable = {claim_id for claim_id, state in state_by_commit[commit].items() if not state["available"]}
            previous_commit = commit
    result = {"schema_version": 1, "dataset": str(args.dataset.resolve()), "dataset_id": dataset.get("dataset_id"),
              "index_implementation": {"path":str(index_path.resolve()), "sha256":hashlib.sha256(index_path.read_bytes()).hexdigest(), "index_version":index_implementation.INDEX_VERSION},
              "runs": str(args.runs.resolve()), "truth_metrics": "not computed; no labels read",
              "notes": ["Original run artifacts are read-only. Counts are operational selector diagnostics.",
                        "Source-construct counts are independent AST occurrence counts, not a one-to-one mapping to unresolved nodes.",
                        "Syntax counterfactual ignores inferred call/import support for structural claims, retains declared provenance, unknown provenance, analysis limits and retry selection.",
                        "Counterfactual does not calculate truth, stale exposure, retention, or cost savings.",
                        "Rebuilt graph uses the installed implementation and intact source snapshots; ablated graph views require separate diagnostics."],
              "symbol_validate_totals": dict(sorted(totals.items())), "transitions": analyzed,
              "policies": {name:{"counts":dict(sorted(value["counts"].items())), "reason_overlap_sets":dict(sorted(value["reason_overlap_sets"].items())), "examples":value["examples"]} for name,value in sorted(policies.items())},
              "source_constructs_by_revision": list(scans.values())}
    args.out.mkdir(parents=True, exist_ok=False)
    output = args.out / "selection_diagnostics.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output":str(output.resolve()), "policies":len(policies), "symbol_validate_totals":result["symbol_validate_totals"]},indent=2))


if __name__ == "__main__":
    main()
