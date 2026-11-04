"""Independent AST summaries for bounded syntax; never imports production code."""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from packaging_audit_common import dump, sha, signature

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
LIMIT = 2 * 1024**2


def lexical(nodes):
    """Evaluate lexical binding sites; defer function/class bodies and comp targets."""
    for node in nodes:
        yield node
        if isinstance(node, (*FUNCTIONS, ast.Lambda)):
            outer = [*node.args.defaults, *(x for x in node.args.kw_defaults if x is not None)]
            if not isinstance(node, ast.Lambda):
                outer += [
                    *node.decorator_list,
                    *(
                        a.annotation
                        for a in ast.walk(node.args)
                        if isinstance(a, ast.arg) and a.annotation is not None
                    ),
                ]
                if node.returns is not None:
                    outer.append(node.returns)
            yield from lexical(outer)
        elif isinstance(node, ast.ClassDef):
            yield from lexical(
                [*node.decorator_list, *node.bases, *(x.value for x in node.keywords)]
            )
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            yield from (x for x in ast.walk(node) if isinstance(x, ast.NamedExpr))
        else:
            yield from lexical(ast.iter_child_nodes(node))


def writes(nodes):
    result = set()
    for x in nodes:
        if isinstance(x, ast.Name) and isinstance(x.ctx, (ast.Store, ast.Del)):
            result.add(x.id)
        if isinstance(x, ast.NamedExpr) and isinstance(x.target, ast.Name):
            result.add(x.target.id)
        if isinstance(x, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and x.name:
            result.add(x.name)
        if isinstance(x, ast.MatchMapping) and x.rest:
            result.add(x.rest)
    return result


def class_globals(nodes):
    result, pending = set(), [n for n in lexical(nodes) if isinstance(n, ast.ClassDef)]
    while pending:
        body = tuple(lexical(pending.pop().body))
        result.update(name for n in body if isinstance(n, ast.Global) for name in n.names)
        pending.extend(n for n in body if isinstance(n, ast.ClassDef))
    return result


def module_name(path):
    for root in ("packaging", "src"):
        try:
            rel = PurePosixPath(path).relative_to(root).with_suffix("")
        except ValueError:
            continue
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)
    return None


def analyze(path, blob):
    out = {
        "path": path,
        "module": module_name(path),
        "definitions": [],
        "imports": [],
        "unresolved": set(),
        "limitation": blob["limitation"],
        "tree": None,
        "source": None,
    }
    if blob["limitation"]:
        return out
    try:
        source = blob["raw"].decode("utf-8")
        tree = ast.parse(source, filename=path)
    except (UnicodeError, SyntaxError, ValueError, RecursionError):
        out["limitation"] = "parse_error"
        return out
    out.update(tree=tree, source=source)
    assignments, counts = set(class_globals(tree.body)), Counter()

    def statements(body, prefix="", in_class=False, conditional=False):
        for st in body:
            assignments.update(prefix + name for name in writes(lexical([st])))
            if isinstance(st, FUNCTIONS):
                name = prefix + st.name
                counts[name] += 1
                local_nodes = tuple(lexical(st.body))
                local = {a.arg for a in ast.walk(st.args) if isinstance(a, ast.arg)} | writes(
                    local_nodes
                )
                local.update(
                    x.name for x in local_nodes if isinstance(x, (*FUNCTIONS, ast.ClassDef))
                )
                local.difference_update(
                    name
                    for n in local_nodes
                    if isinstance(n, (ast.Global, ast.Nonlocal))
                    for name in n.names
                )
                calls = []
                outer = [
                    *st.decorator_list,
                    *st.args.defaults,
                    *(x for x in st.args.kw_defaults if x is not None),
                ]
                if any(isinstance(x, ast.Name) for expr in outer for x in ast.walk(expr)):
                    out["unresolved"].add((path, name))
                for x in ast.walk(st):
                    if isinstance(x, ast.Call):
                        if isinstance(x.func, ast.Name):
                            calls.append(x.func.id)
                        else:
                            out["unresolved"].add((path, name))
                    if isinstance(x, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
                        out["unresolved"].add((path, name))
                out["definitions"].append(
                    {
                        "name": name,
                        "kind": "method" if in_class else "function",
                        "node": st,
                        "signature": signature(st),
                        "hash": sha(dump(st).encode()),
                        "conditional": conditional,
                        "calls": calls,
                        "local": local,
                        "loads": {
                            x.id
                            for x in ast.walk(st)
                            if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load)
                        },
                    }
                )
                statements(st.body, name + ".<locals>.", False, conditional)
            elif isinstance(st, ast.ClassDef):
                counts[prefix + st.name] += 1
                statements(st.body, prefix + st.name + ".", True, conditional)
            elif isinstance(st, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
                targets = st.targets if isinstance(st, (ast.Assign, ast.Delete)) else [st.target]
                assignments.update(
                    prefix + x.id
                    for target in targets
                    for x in ast.walk(target)
                    if isinstance(x, ast.Name)
                )
            elif isinstance(st, (ast.Import, ast.ImportFrom)):
                for a in st.names:
                    bound = a.asname or (
                        a.name.split(".")[0] if isinstance(st, ast.Import) else a.name
                    )
                    counts[prefix + bound] += 1
                if not prefix:
                    mod = st.module or "" if isinstance(st, ast.ImportFrom) else None
                    if isinstance(st, ast.ImportFrom) and st.level:
                        package = (
                            out["module"].split(".")
                            if path.endswith("/__init__.py")
                            else out["module"].split(".")[:-1]
                        )
                        mod = ".".join(
                            package[: len(package) - st.level + 1] + ([mod] if mod else [])
                        )
                    for a in st.names:
                        if isinstance(st, ast.ImportFrom):
                            out["imports"].append((a.asname or a.name, mod, a.name))
                            if a.name == "*":
                                out["unresolved"].add((path, None))
                        else:
                            out["imports"].append((a.asname or a.name, a.name, None))
            else:
                for key, value in ast.iter_fields(st):
                    if key in {"body", "orelse", "finalbody"} and isinstance(value, list):
                        statements(value, prefix, in_class, True)
                    elif key in {"handlers", "cases"} and isinstance(value, list):
                        for item in value:
                            statements(item.body, prefix, in_class, True)

    statements(tree.body)
    occurrences = Counter(d["name"] for d in out["definitions"])
    bad = {name for name, count in counts.items() if count > 1} | assignments
    wildcard = any(symbol == "*" for _, _, symbol in out["imports"])
    for d in out["definitions"]:
        d["ambiguous"] = (
            d["conditional"]
            or occurrences[d["name"]] > 1
            or wildcard
            or any(d["name"] == scope or d["name"].startswith(scope + ".") for scope in bad)
        )
    out["unresolved"].update((path, name) for name in assignments)
    out["assignments"] = assignments
    return out


def index(blobs):
    modules = {
        path: analyze(path, blob)
        for path, blob in blobs.items()
        if path.endswith(".py") and module_name(path) is not None
    }
    by_module = defaultdict(list)
    definitions, unresolved, edges = {}, set(), set()
    for path, mod in modules.items():
        by_module[mod["module"]].append(mod)
        unresolved.update(mod["unresolved"])
        definitions.update({(path, d["name"]): d for d in mod["definitions"]})
    for path, mod in modules.items():
        imported = {}
        local = {d["name"]: d for d in mod["definitions"]}
        for alias, target_mod, symbol in mod["imports"]:
            targets = by_module.get(target_mod, [])
            candidates = (
                [d for d in targets[0]["definitions"] if d["name"] == symbol and not d["ambiguous"]]
                if len(targets) == 1 and symbol and symbol != "*"
                else []
            )
            if len(candidates) == 1:
                target = (targets[0]["path"], candidates[0]["name"])
                imported[alias] = target
                edges.add(((path, None), target, "imports", "static"))
            else:
                unresolved.add((path, None))
        for d in mod["definitions"]:
            node = (path, d["name"])
            if d["loads"] - d["local"] - set(d["calls"]):
                unresolved.add(node)
            for call in d["calls"]:
                if call in d["local"] or (path, call) in mod["unresolved"]:
                    unresolved.add(node)
                    continue
                target = (
                    (path, call)
                    if call in local and not local[call]["ambiguous"]
                    else imported.get(call)
                )
                if target is None:
                    unresolved.add(node)
                else:
                    edges.add((node, target, "calls", "static"))
    return {
        "modules": modules,
        "definitions": definitions,
        "edges": edges,
        "unresolved": unresolved,
        "limitations": {p for p, m in modules.items() if m["limitation"]},
        "global_unresolved": any(n is None for _, n in unresolved),
    }


def changes(old_blobs, new_blobs, before, after):
    files = {
        p
        for p in old_blobs.keys() | new_blobs.keys()
        if p not in old_blobs
        or p not in new_blobs
        or (old_blobs[p]["oid"], old_blobs[p]["mode"])
        != (new_blobs[p]["oid"], new_blobs[p]["mode"])
    }
    left, right = before["definitions"], after["definitions"]
    symbols = {
        n
        for n in left.keys() | right.keys()
        if n not in left
        or n not in right
        or left[n]["hash"] != right[n]["hash"]
        or left[n]["ambiguous"]
        or right[n]["ambiguous"]
    }
    symbols.update(edge[0] for edge in before["edges"] ^ after["edges"])
    return {
        "files": files,
        "symbols": symbols,
        "edges": before["edges"] | after["edges"],
        "unresolved": before["unresolved"] | after["unresolved"],
        "limited_paths": before["limitations"] | after["limitations"],
        "global_unresolved": before["global_unresolved"] or after["global_unresolved"],
    }


def production(claim, blobs, indexed):
    path, name = claim["subject"]["path"], claim["subject"]["qualname"]
    ancestor = [
        b["limitation"]
        for p, b in blobs.items()
        if b["limitation"] and (path == p or path.startswith(p + "/"))
    ]
    mod = indexed["modules"].get(path)
    defs = [d for d in mod["definitions"] if d["name"] == name] if mod else []
    if ancestor:
        return "insufficient_evidence", ancestor[0]
    if mod and mod["limitation"]:
        return "insufficient_evidence", mod["limitation"]
    if path in blobs and mod is None:
        return "insufficient_evidence", "outside_source_roots"
    if (
        any(d["ambiguous"] for d in defs)
        or len(defs) > 1
        or not defs
        and (path, name) in indexed["unresolved"]
    ):
        return "insufficient_evidence", "ambiguous_subject"
    if not defs or defs[0]["kind"] != claim["subject"]["node_kind"]:
        return "contradicted", "subject_absent"
    if (
        claim["kind"] == "signature_equals"
        and defs[0]["signature"] != claim["predicate"]["expected_signature"]
    ):
        return "contradicted", "predicate_mismatch"
    return "supported", "predicate_matches"


def reference(raw, claim):
    """Independent lexical-event reference; no production/index extraction reuse."""
    facts, evidence, definitions, bindings = {}, [], [], []
    try:
        source = raw.decode("utf-8")
        tree = ast.parse(source, filename=claim["subject"]["path"])
    except (UnicodeError, SyntaxError, ValueError, RecursionError) as error:
        return {
            "verdict": "uncertain",
            "facts": {},
            "evidence": [],
            "reason": type(error).__name__ + ": " + str(error),
        }
    target = claim["subject"]["qualname"]
    direct = {id(n) for n in tree.body}

    def location(n, role):
        start = min([n.lineno, *(x.lineno for x in getattr(n, "decorator_list", []))])
        return {"start_line": start, "end_line": n.end_lineno or n.lineno, "role": role}

    def binding(name, n, role):
        if name == target:
            bindings.append(location(n, role))

    stars = []

    def walk(n):
        if isinstance(n, FUNCTIONS):
            if n.name == target:
                definitions.append((n, id(n) in direct))
            exprs = [
                *n.decorator_list,
                *n.args.defaults,
                *(x for x in n.args.kw_defaults if x is not None),
                *(
                    a.annotation
                    for a in ast.walk(n.args)
                    if isinstance(a, ast.arg) and a.annotation is not None
                ),
            ]
            if n.returns is not None:
                exprs.append(n.returns)
            for x in exprs:
                walk(x)
        elif isinstance(n, ast.Lambda):
            for x in [*n.args.defaults, *(x for x in n.args.kw_defaults if x is not None)]:
                walk(x)
        elif isinstance(n, ast.ClassDef):
            binding(n.name, n, "class binding")
            for x in [*n.decorator_list, *n.bases, *(x.value for x in n.keywords)]:
                walk(x)

            def class_declares(items):
                return any(
                    (isinstance(x, ast.Global) and target in x.names)
                    or (
                        not isinstance(x, (*FUNCTIONS, ast.Lambda))
                        and class_declares(ast.iter_child_nodes(x))
                    )
                    for x in items
                )

            if class_declares(n.body):
                bindings.append(location(n, "class body declares target global; unsupported scope"))
        elif isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for g in n.generators:
                walk(g.iter)
                for x in g.ifs:
                    walk(x)
            for x in [n.key, n.value] if isinstance(n, ast.DictComp) else [n.elt]:
                walk(x)
        else:
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                binding(n.id, n, "module name binding or deletion")
            if isinstance(n, ast.Import):
                for a in n.names:
                    binding(a.asname or a.name.split(".")[0], n, "import binding")
            if isinstance(n, ast.ImportFrom):
                for a in n.names:
                    if a.name == "*":
                        stars.append(location(n, "star import ambiguity"))
                    else:
                        binding(a.asname or a.name, n, "import binding")
            if isinstance(n, ast.ExceptHandler):
                binding(n.name, n, "exception name binding")
            if isinstance(n, (ast.MatchAs, ast.MatchStar)):
                binding(n.name, n, "match capture binding")
            if isinstance(n, ast.MatchMapping):
                binding(n.rest, n, "match rest binding")
            for child in ast.iter_child_nodes(n):
                walk(child)

    walk(tree)
    facts.update(
        definition_count=len(definitions),
        unconditional_definition_count=sum(d for _, d in definitions),
    )
    evidence = (
        [
            location(n, "unconditional definition" if d else "conditional definition")
            for n, d in definitions
        ]
        + bindings
        + stars
    )
    if bindings or stars:
        reason = "target rebinding or module namespace ambiguity"
    elif any(not d for _, d in definitions):
        reason = "conditional target definition is outside supported scope"
    elif len(definitions) > 1:
        reason = "duplicate target definitions"
    elif not definitions:
        facts["exists"] = False
        evidence = (
            [
                {
                    "start_line": 1,
                    "end_line": len(source.splitlines()),
                    "role": "complete module inspected for absence",
                }
            ]
            if tree.body
            else []
        )
        return {
            "verdict": "contradicted",
            "facts": facts,
            "evidence": evidence,
            "reason": "no top-level syntactic function definition for target",
        }
    elif getattr(definitions[0][0], "type_params", []):
        reason = "target type parameters are unsupported"
    else:
        sig = signature(definitions[0][0])
        facts.update(exists=True, signature=sig)
        verdict = (
            "supported"
            if claim["kind"] == "symbol_exists" or sig == claim["predicate"]["expected_signature"]
            else "contradicted"
        )
        reason = (
            "unique unconditional top-level syntactic function definition"
            if claim["kind"] == "symbol_exists"
            else "all complete signature fields match"
            if verdict == "supported"
            else "signature mismatch in: "
            + ", ".join(
                sorted(k for k in sig if sig[k] != claim["predicate"]["expected_signature"][k])
            )
        )
        return {"verdict": verdict, "facts": facts, "evidence": evidence, "reason": reason}
    return {
        "verdict": "uncertain",
        "facts": facts,
        "evidence": evidence,
        "reason": "Uncertain: " + reason,
    }
