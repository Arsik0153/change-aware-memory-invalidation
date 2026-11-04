"""Independent audit primitives reused from the authored Click audit; stdlib only."""

import ast
import copy
import hashlib
import json
import os
import subprocess


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def pairs(items):
    out = {}
    for key, value in items:
        require(key not in out, "duplicate JSON key: " + key)
        out[key] = value
    return out


def parse(raw):
    def invalid_constant(value):
        raise ValueError("invalid JSON constant: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def rows(path):
    return [parse(line) for line in path.read_bytes().splitlines() if line.strip()]


def git(repo, *args):
    result = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "--no-optional-locks",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(repo),
            *args,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        env={
            **os.environ,
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
        },
    )
    require(result.returncode == 0, "Git read failed: " + repr(args))
    return result.stdout


def safe(base, name):
    path = (base / name).resolve()
    require(path.is_relative_to(base.resolve()), "path escapes root: " + name)
    return path


def dump(node):
    return ast.dump(node, include_attributes=False) if node is not None else None


def signature(fn):
    args = fn.args
    positional = args.posonlyargs + args.args
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    parameters = []
    for i, arg in enumerate(positional):
        parameters.append(
            {
                "name": arg.arg,
                "kind": "positional_only" if i < len(args.posonlyargs) else "positional_or_keyword",
                "annotation_ast": dump(arg.annotation),
                "default_ast": dump(defaults[i]),
            }
        )
    if args.vararg:
        parameters.append(
            {
                "name": args.vararg.arg,
                "kind": "var_positional",
                "annotation_ast": dump(args.vararg.annotation),
                "default_ast": None,
            }
        )
    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        parameters.append(
            {
                "name": arg.arg,
                "kind": "keyword_only",
                "annotation_ast": dump(arg.annotation),
                "default_ast": dump(default),
            }
        )
    if args.kwarg:
        parameters.append(
            {
                "name": args.kwarg.arg,
                "kind": "var_keyword",
                "annotation_ast": dump(args.kwarg.annotation),
                "default_ast": None,
            }
        )
    return {
        "parameters": parameters,
        "returns_ast": dump(fn.returns),
        "decorators_ast": list(map(dump, fn.decorator_list)),
        "is_async": isinstance(fn, ast.AsyncFunctionDef),
    }


def advance(previous, commit, selected, validation):
    state = copy.deepcopy(previous)
    state.update(revision=commit, basis="carried_forward")
    if validation is not None:
        verdict, reason = validation["verdict"], validation["reason"]
        state.update(last_checked_commit=commit, last_verdict=verdict, basis="validated")
        if verdict == "supported":
            state.update(
                state="valid", available=True, last_supported_commit=commit, withheld_reason=None
            )
        elif verdict == "contradicted":
            state.update(
                state="retired" if reason == "subject_absent" else "stale",
                available=False,
                withheld_reason=reason,
            )
        else:
            state.update(state="needs_validation", available=False, withheld_reason=reason)
    elif selected:
        state.update(
            state="needs_validation", available=False, withheld_reason="validation_pending"
        )
    return state


def summarize(records):
    scored = [x for x in records if x["eligible"]]

    def count(predicate, source=scored):
        return sum(bool(predicate(x)) for x in source)

    def ref(record):
        return record["reference"]["verdict"]

    def available(record):
        return record["state"]["available"]

    contradicted = count(lambda x: ref(x) == "contradicted")
    false = count(lambda x: available(x) and ref(x) == "contradicted")
    out = {
        "candidate_observations": len(records),
        "scored_observations": len(scored),
        "excluded_parent_observations": len(records) - len(scored),
        "available": count(available),
        "false_available": false,
        "available_unknown": count(lambda x: available(x) and ref(x) == "uncertain"),
        "withheld_supported": count(lambda x: not available(x) and ref(x) == "supported"),
        "false_available_per_contradicted": false / contradicted if contradicted else None,
        "false_available_per_contradicted_null_reason": None
        if contradicted
        else "zero_reference_contradicted_observations",
        "false_available_per_scored": false / len(scored) if scored else None,
        "false_available_per_scored_null_reason": None if scored else "no_eligible_parent_claims",
        "selected_logical_validations": count(lambda x: x["selection"]["selected"]),
        "actual_validation_calls": count(lambda x: x["validation"] is not None),
        "carried_states": count(lambda x: not x["selection"]["selected"]),
        "available_full_production_contradicted": count(
            lambda x: available(x) and x["full_production_validation"]["verdict"] == "contradicted"
        ),
        "full_production_unknown": count(
            lambda x: x["full_production_validation"]["verdict"] == "insufficient_evidence"
        ),
    }
    for label, verdict in [
        ("supported", "supported"),
        ("contradicted", "contradicted"),
        ("unknown", "uncertain"),
    ]:
        out["reference_" + label] = count(lambda x: ref(x) == verdict)
        out["candidate_reference_" + label] = count(lambda x: ref(x) == verdict, records)
    return out


def unique_index(records, key, label):
    out = {}
    for row in records:
        identity = key(row)
        require(identity not in out, "duplicate " + label + ": " + repr(identity))
        out[identity] = row
    return out
