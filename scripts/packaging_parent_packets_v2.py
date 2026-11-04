"""Blind derived-parent packets and authored controls; no independent verdict calls."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import subprocess

from cami.artifacts import canonical, digest, file_hash, within, write_bytes, write_json
from scripts.validate_ai_review import compute_packet_identity
from packaging_parent_collection_support_v2 import SEED, sha


def stable(*parts):
    return sha("\n".join((SEED, *parts)).encode())


def build_packet(group, cohort, candidates, output, root, protocol, budget):
    public = output / "packets" / group["group_id"]
    cases, mapping, answers = [], [], []
    by_subject = {(candidate.path, candidate.qualname): candidate for candidate in candidates}
    def add(row, claim, raw, identity, kind=None, expected=None, transformation=None):
        case_id = "case-" + stable("alias", identity)[:20]
        source_path = "source/" + sha(raw) + ".raw"
        write_bytes(public / source_path, raw)
        case = {"id": case_id, "kind": claim["kind"], "subject": claim["subject"], "predicate": claim["predicate"],
            "text": claim["text"], "scope": claim["scope"], "source_path": source_path, "source_sha256": sha(raw)}
        cases.append(case)
        mapping.append({"id": case_id, "group_id": group["group_id"],
            "origin_class": "derived_parent_claim" if kind is None else "authored_control",
            "derived_claim_id": row["claim"]["claim_id"], "derived_claim_sha256": row["claim_sha256"],
            "derived_claim": row["claim"], "public_source_path": source_path, "source_sha256": sha(raw),
            "control_kind": kind, "expected_verdict": expected, "transformation": transformation,
            "source_origin": {"repo_id": "packaging", "group_id": group["group_id"], "parent_commit": group["parent_commit"],
                "split": "development", "repository_path": row["claim"]["subject"]["path"],
                "git_blob_object_id": row["parent_git_blob_object_id"], "source_sha256": row["parent_source_sha256"]}})
        if kind is not None:
            answers.append({"id": case_id, "group_id": group["group_id"], "control_kind": kind,
                "expected_verdict": expected, "source_sha256": sha(raw), "public_case_sha256": digest(case)})
    for row in cohort:
        subject = row["claim"]["subject"]
        candidate = by_subject[(subject["path"], subject["qualname"])]
        add(row, deepcopy(row["claim"]), candidate.blob.content, "derived:" + row["claim"]["claim_id"])
    exists = next(row for row in cohort if row["claim"]["kind"] == "symbol_exists")
    subject = exists["claim"]["subject"]
    raw = by_subject[(subject["path"], subject["qualname"])].blob.content
    name = "_case_" + stable("missing", group["group_id"])[:24]
    if name.encode() in raw:
        raise ValueError("fresh authored missing-name collision; no repair authorized")
    missing = deepcopy(exists["claim"])
    missing["subject"]["qualname"] = name
    missing["text"] = f"{subject['path']} contains the exact top-level function definition {name}."
    add(exists, missing, raw, "missing:" + group["group_id"], "nonexistent_function", "contradicted",
        {"type": "nonexistent_function", "new_qualname": name, "source_bytes_changed": False})
    signatures = [row for row in cohort if row["claim"]["kind"] == "signature_equals"][:2]
    for row in signatures:
        subject = row["claim"]["subject"]
        raw = by_subject[(subject["path"], subject["qualname"])].blob.content
        changed = deepcopy(row["claim"])
        params = changed["predicate"]["expected_signature"]["parameters"]
        name = "_case_" + stable("parameter", row["claim"]["claim_id"])[:24]
        if name.encode() in raw or name in {param["name"] for param in params}:
            raise ValueError("fresh authored parameter collision; no repair authorized")
        if params:
            params[0]["name"] = name
            operation = "rename_first_parameter"
        else:
            params.append({"name": name, "kind": "positional_or_keyword", "default_ast": None, "annotation_ast": None})
            operation = "add_parameter_to_empty_signature"
        changed["text"] = f"The exact definition {subject['path']}:{subject['qualname']} has normalized signature {canonical(changed['predicate']['expected_signature']).decode()}."
        add(row, changed, raw, "mismatch:" + row["claim"]["claim_id"], "signature_mismatch", "contradicted",
            {"type": "signature_mismatch", "operation": operation, "new_parameter_name": name, "source_bytes_changed": False})
    subject = exists["claim"]["subject"]
    raw = by_subject[(subject["path"], subject["qualname"])].blob.content
    appended = (f"\n\ndef {subject['qualname']}(*args, **kwargs):\n    pass\n" * 2).encode()
    add(exists, deepcopy(exists["claim"]), raw + appended, "duplicate:" + group["group_id"],
        "duplicate_function_uncertain", "uncertain", {"type": "duplicate_function_uncertain", "source_bytes_changed": True,
        "appended_utf8": appended.decode(), "operation": "append_two_unconditional_target_definitions"})
    cases.sort(key=lambda case: (stable("order", case["id"]), case["id"]))
    if len(cases) != 12 or len({case["id"] for case in cases}) != 12:
        raise ValueError("expected exactly twelve opaque cases per parent")
    write_json(public / "cases.json", cases)
    for field, name in (("rubric_path", "rubric.md"), ("review_schema_path", "review.schema.json")):
        write_bytes(public / name, within(root, protocol[field]).read_bytes())
    for number, name in enumerate(protocol["review_prompt_paths"]):
        write_bytes(public / "review_prompts" / f"{number:02d}-{Path(name).name}", within(root, name).read_bytes())
    write_json(output / "private" / (group["group_id"] + "-case_map.json"), mapping)
    write_json(output / "private" / (group["group_id"] + "-answer_key.json"), answers)
    packet_sha = compute_packet_identity(public)
    files = {str(path.relative_to(root)): file_hash(path) for path in sorted(public.rglob("*")) if path.is_file()}
    manifest_path = output / "packet_manifests" / (group["group_id"] + ".json")
    write_json(manifest_path, {"schema_version": 1, "packet_sha256": packet_sha, "files": files})
    envelope = "Sealed research envelope v1. Uncontrolled harness/system/tool metadata excluded.\n"
    for path in sorted(public.rglob("*")):
        if path.is_file():
            raw = path.read_bytes()
            envelope += f"\nFILE {path.relative_to(public).as_posix()} UTF8_BYTES {len(raw)}\n" + raw.decode("utf-8", "strict") + "\nEND FILE\n"
    envelope_path = output / "budget" / (group["group_id"] + ".txt")
    write_bytes(envelope_path, envelope.encode())
    token = protocol["tokenizer"]
    python = Path(token["python_executable"])
    if not python.is_absolute():
        python = root / python
    result = subprocess.run([str(python), str(within(root, token["helper_path"])), "--config",
        str(within(root, token["config_path"])), "--vocab", str(within(root, token["vocab_path"]))],
        input=envelope.encode(), capture_output=True, timeout=120, check=True)
    estimate = read_json_bytes(result.stdout)
    estimate.update(research_envelope_sha256=sha(envelope.encode()), input_limit=64000, primary_response_estimate_limit=8000,
        response_limit_enforcement="posthoc same named encoding on complete primary JSON response; not native actual model limit")
    budget_path = output / "budget" / (group["group_id"] + ".json")
    write_json(budget_path, estimate)
    budget()
    if estimate["estimated_tokens"] > 64000:
        raise ValueError("complete research packet exceeds named 64k estimate; no truncation or substitution")
    return mapping, answers, {"group_id": group["group_id"], "packet_root": str(public.relative_to(root)),
        "public_cases_path": str((public / "cases.json").relative_to(root)),
        "packet_manifest_path": str(manifest_path.relative_to(root)), "packet_manifest_sha256": file_hash(manifest_path),
        "packet_sha256": packet_sha, "token_budget_path": str(budget_path.relative_to(root)),
        "token_budget_sha256": file_hash(budget_path)}


def read_json_bytes(raw):
    from cami.artifacts import parse
    return parse(raw.decode("utf-8"))
