"""Read-only, independently implemented aggregation of one frozen study version."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
from pathlib import Path
import stat

from aggregate_metrics import ARMS, TOKEN_KEYS, number, token_fields, summarize
from service_tier_evidence import (
    ARTIFACTS as TIER_ARTIFACTS, V6_STUDY_ID, admit_tier_policy,
    inspect_tier, study_tier_summary,
)

HERE = Path(__file__).resolve().parent
PRIVATE = {"private-state", "server-private", "private-export-client"}

LITERAL_COMPACT_DEVELOPMENT_ID = "opencode-cami-real-maintenance-development-v4-literal-compact"
LITERAL_COMPACT_DEVELOPMENT_IDS = (
    LITERAL_COMPACT_DEVELOPMENT_ID,
    "opencode-cami-real-maintenance-development-v5-literal-compact",
)


def admit_protocol(protocol, supported):
    """Explicit version IDs share the unchanged frozen success/cost/token rules."""
    expected = supported
    if protocol.get("study_id") in (*LITERAL_COMPACT_DEVELOPMENT_IDS, V6_STUDY_ID):
        expected = {**supported, "study_id": protocol['study_id']}
    if {key: protocol.get(key) for key in supported} != expected:
        raise ValueError("protocol success rules differ from independently supported frozen rules")
    if protocol["study_id"] == V6_STUDY_ID:
        admit_tier_policy(protocol)
    return protocol["study_id"]


def _cohort_path(value, basename=None):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return False
    path = Path(value)
    return (not path.is_absolute() and ".." not in path.parts and str(path) == value
            and bool(path.parts) and (basename is None or path.name == basename))


def admit_study_cohort(protocol_id, study):
    if protocol_id == V6_STUDY_ID:
        if study.get("service_tier") != "priority":
            raise ValueError("v6 requires frozen study service_tier priority")
    elif study.get("service_tier") is not None:
        raise ValueError("historical protocol IDs did not freeze an explicit service tier; use a separately supported protocol")
    if protocol_id not in (*LITERAL_COMPACT_DEVELOPMENT_IDS, V6_STUDY_ID):
        return
    normalized = study.get("normalized")
    source = normalized.get("memory_source") if isinstance(normalized, dict) else None
    if (study.get("bundle_kind") != "development"
            or study.get("memory_response_format") != "compact"
            or not isinstance(source, dict)
            or set(source) != {"schema_version", "seed", "generator", "helpers",
                               "payload_kind", "extractor_format"}
            or type(source["schema_version"]) is not int or source["schema_version"] != 2
            or source["payload_kind"] != "source_excerpt_equals"
            or source["extractor_format"] != "python.definition-prefix/1"
            or not _cohort_path(source["seed"])
            or source["seed"] != normalized.get("seed")
            or not _cohort_path(source["generator"], "seed_source_literals_v2.py")
            or not isinstance(source["helpers"], list) or len(source["helpers"]) != 1
            or not _cohort_path(source["helpers"][0], "literal_source.py")):
        raise ValueError("literal/compact ID requires its explicit development schema2 study cohort")
    hashes = normalized.get("asset_hashes")
    required = ["memory-source.json", source["seed"], source["generator"], source["helpers"][0]]
    if not isinstance(hashes, dict) or any(
            not isinstance(hashes.get(name), str)
            or not re.fullmatch(r"[a-f0-9]{64}", hashes[name]) for name in required):
        raise ValueError("literal/compact source policy assets must be explicitly frozen")


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            value.update(chunk)
    return value.hexdigest()


def read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("expected regular public JSON artifact")
    return json.loads(path.read_bytes())


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def safe_path(root, name):
    rel = Path(name)
    if rel.is_absolute() or ".." in rel.parts or any(x in PRIVATE for x in rel.parts):
        raise ValueError("unsafe/private artifact reference refused without reading")
    path = root / rel
    if any(p.is_symlink() for p in [path, *path.parents] if p.is_relative_to(root)):
        raise ValueError("artifact symlink refused")
    return path


def artifact_files(root):
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        if any(name in PRIVATE for name in dirs + files):
            raise ValueError("private state present; refused without reading it")
        for name in dirs + files:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ValueError("nonregular terminal artifact refused")
            rel = path.relative_to(root).as_posix()
            if rel != "terminal.json":
                result[rel] = sha(path)
    return result


def verify_terminal(directory):
    if directory.is_symlink():
        raise ValueError("trial directory symlink refused")
    # No trial payload is inspected at all until terminal.json exists.
    terminal = directory / "terminal.json"
    record = read(terminal)
    expected = record.get("artifact_hashes")
    if not isinstance(expected, dict):
        raise ValueError("terminal has no artifact hash map")
    for name in expected:
        safe_path(directory, name)
    if artifact_files(directory) != expected:
        raise ValueError("terminal artifact hashes or exact file coverage differ")
    return record, sha(terminal), len(expected)


def schedule(study):
    sequence = study["normalized"]["sequence"]
    if (
        len(sequence) != 4
        or len(set(sequence)) != 2
        or sequence != [sequence[0]] * 2 + [sequence[2]] * 2
    ):
        raise ValueError("study does not contain the declared two-task/four-stage sequence")
    result = []
    for repetition in range(1, 4):
        for stage, task in enumerate(sequence, 1):
            offset = (repetition + stage - 2) % 3
            for arm in ARMS[offset:] + ARMS[:offset]:
                result.append(
                    {
                        "id": f"r{repetition}-{arm}-s{stage}",
                        "repetition": repetition,
                        "arm": arm,
                        "stage": stage,
                        "task": task,
                        "predecessor": f"r{repetition}-{arm}-s{stage - 1}" if stage > 1 else None,
                    }
                )
    return result


def trial_row(directory, expected):
    if directory.is_symlink():
        raise ValueError("trial directory symlink refused")
    if not (directory / "terminal.json").is_file():
        return dict(
            expected,
            terminal_present=False,
            status="missing_or_in_progress",
            operational_status="unknown",
            session_status="unknown",
            quality="unknown",
            quality_eligible=False,
            wall_complete=False,
            tokens_complete=False,
            charged_wall_seconds=None,
            tokens={k: None for k in TOKEN_KEYS},
            token_work=None,
            failures=[],
            unknown_reasons=["no terminal artifact; trial contents not inspected"],
        )
    record, terminal_sha, artifact_count = verify_terminal(directory)
    if record["trial"] != expected:
        raise ValueError("terminal trial identity or schedule differs")
    costs = record.get("costs", {})
    charged = number(costs.get("charged_host_wall_seconds"))
    total = number(costs.get("controller_total_host_wall_seconds"))
    infrastructure = number(costs.get("infrastructure_host_wall_seconds"))
    construction = number(costs.get("construction_host_wall_seconds"))
    session_wall = number(costs.get("session_host_wall_seconds"))
    if total is not None and infrastructure is not None:
        if infrastructure > total + 1e-6:
            raise ValueError("evaluation infrastructure exceeds entire controller duration")
        recomputed = max(0, total - infrastructure)
        if charged is not None and not math.isclose(
            charged, recomputed, rel_tol=1e-8, abs_tol=1e-6
        ):
            raise ValueError(
                "charged wall is inconsistent with inclusive controller minus infrastructure"
            )
        charged = recomputed
    if charged is not None and construction is not None and session_wall is not None:
        if charged + 1e-6 < construction + session_wall:
            raise ValueError("charged wall omits construction/session work")
    if construction is not None and (
        (expected["arm"] == "plain" or expected["stage"] != 1) and construction != 0
    ):
        raise ValueError("construction charged to plain or repeated after origin")
    raw_usage = directory / "session/evidence/usage.json"
    usage = read(raw_usage) if raw_usage.is_file() else record.get("usage", {})
    if not isinstance(usage, dict):
        usage = {"session_tokens": None, "status": "unavailable"}
    if (
        raw_usage.is_file()
        and isinstance(record.get("usage"), dict)
        and record["usage"].get("session_tokens") is not None
    ):
        if record["usage"].get("session_tokens") != usage.get("session_tokens"):
            raise ValueError("terminal usage differs from hashed session usage")
    tokens = token_fields(usage)
    known_tokens = all(value is not None for value in tokens.values())
    usage_status = (
        usage.get("status", "client_normalized") if isinstance(usage, dict) else "unavailable"
    )
    usage_status = usage_status if isinstance(usage_status, str) else "unknown"
    incomplete_usage = (
        any(
            word in usage_status
            for word in [
                "failed",
                "partial",
                "incomplete",
                "unavailable",
                "unreadable",
                "unknown",
                "not_available",
            ]
        )
        or usage.get("complete") is False
        or usage.get("telemetry_complete") is False
    )
    telemetry_complete = known_tokens and raw_usage.is_file() and not incomplete_usage
    token_work = (
        sum(tokens[k] for k in ("input", "cache_write", "output", "reasoning"))
        if all(tokens[k] is not None for k in ("input", "cache_write", "output", "reasoning"))
        else None
    )
    raw_grade = directory / "evaluation/report.json"
    raw_session = directory / "session/manifest.json"
    grade = read(raw_grade) if raw_grade.is_file() else None
    session = read(raw_session) if raw_session.is_file() else None
    if (
        grade is not None
        and record.get("quality") in {"pass", "fail"}
        and record["quality"] != grade["status"]
    ):
        raise ValueError("terminal quality differs from hashed fixed-grade report")
    runtime_passed_admission_failed = bool(
        session is not None and session.get('status') == 'passed'
        and record.get('session_status') == 'failed'
        and record.get('status') == 'failed' and record.get('operational_status') == 'failed'
        and any(isinstance(failure, dict) and failure.get('phase') == 'model_session'
                for failure in record.get('failures', []))
    )
    if (
        session is not None
        and record.get("session_status") in {"passed", "failed"}
        and record["session_status"] != session["status"]
        and not runtime_passed_admission_failed
    ):
        raise ValueError("terminal session differs from hashed runtime report")
    quality_evidence = bool(
        grade
        and grade.get("status") == "pass"
        and set(grade.get("outcomes", {})) == {"acceptance", "regression"}
    )
    if quality_evidence:
        for check in ("acceptance", "regression"):
            outcome = grade["outcomes"][check]
            counts = outcome.get("counts", {})
            required_counts = (
                "executed",
                "passed",
                "failed",
                "errors",
                "skipped",
                "xfailed",
                "xpassed",
            )
            if any(number(counts.get(key), integer=True) is None for key in required_counts):
                quality_evidence = False
            if (
                outcome.get("exit_code") != 0
                or not counts.get("executed")
                or counts.get("errors")
                or counts.get("failed")
            ):
                quality_evidence = False
            if check == "acceptance" and any(
                counts.get(k) for k in ("skipped", "xfailed", "xpassed")
            ):
                quality_evidence = False
    quality_eligible = (
        record.get("status") == "passed"
        and record.get("operational_status") == "passed"
        and record.get("session_status") == "passed"
        and record.get("quality") == "pass"
        and costs.get("complete") is True
        and not record.get("failures")
        and quality_evidence
        and session is not None
        and session.get("status") == "passed"
        and session.get("model_requested") is True
    )
    wall_complete = costs.get("complete") is True and all(
        x is not None for x in (charged, total, infrastructure, construction, session_wall)
    )
    if (
        quality_eligible
        and expected["stage"] == 1
        and expected["arm"] != "plain"
        and construction is not None
        and construction <= 0
    ):
        raise ValueError("passing memory origin has no construction cost")
    return dict(
        expected,
        terminal_present=True,
        terminal_sha256=terminal_sha,
        artifact_hashes_verified=artifact_count,
        status=record.get("status", "unknown"),
        operational_status=record.get("operational_status", "unknown"),
        session_status=record.get("session_status", "unknown"),
        runtime_manifest_status=session.get('status') if session is not None else None,
        runtime_passed_controller_admission_failed=runtime_passed_admission_failed,
        quality=record.get("quality", "unknown"),
        quality_eligible=quality_eligible,
        wall_complete=wall_complete,
        tokens_complete=telemetry_complete,
        charged_wall_seconds=charged,
        tokens=tokens,
        token_work=token_work,
        usage_status=usage_status,
        usage_source="hashed_session_evidence"
        if raw_usage.is_file()
        else "terminal_only_or_missing",
        failures=record.get("failures", [])
        or ([record["failure"]] if record.get("failure") else []),
        unknown_reasons=[
            name
            for name, valid in [("wall", wall_complete), ("normalized_tokens", telemetry_complete)]
            if not valid
        ],
        resource_components=costs,
        memory_bytes_after=record.get("memory_bytes_after"),
    )


def load_timing_caveats(path, expected_ids, study_sha):
    if path is None:
        return {
            "provided": False,
            "source_path": None,
            "source_sha256": None,
            "entries": [],
            "affected_trial_ids": [],
            "trials_excluded": [],
        }
    path = Path(path).absolute()
    if any(part in PRIVATE for part in path.parts):
        raise ValueError("private timing-caveat input refused without reading")
    content = read(path)
    if content.get("schema_version") != 1 or not isinstance(content.get("caveats"), list):
        raise ValueError("unsupported timing-caveat schema")
    if content.get("study_sha256") not in (None, study_sha):
        raise ValueError("timing caveats bind a different study version")
    affected, entries = set(), []
    for item in content["caveats"]:
        ids = item.get("trial_ids")
        if (
            not isinstance(ids, list)
            or not ids
            or not all(isinstance(x, str) for x in ids)
            or len(set(ids)) != len(ids)
            or not set(ids) <= expected_ids
        ):
            raise ValueError("timing caveat contains unknown/invalid trial IDs")
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("timing caveat requires a nonempty reason")
        evidence_path = item.get("evidence_path")
        declared = item.get("evidence_sha256")
        if declared is not None and (
            not isinstance(declared, str) or not re.fullmatch(r"[a-f0-9]{64}", declared)
        ):
            raise ValueError("invalid timing-caveat evidence SHA256")
        if evidence_path is None and declared is None:
            raise ValueError("timing caveat needs an evidence file or SHA256")
        if evidence_path is not None:
            if not isinstance(evidence_path, str) or not evidence_path:
                raise ValueError("invalid timing-caveat evidence path")
            evidence = Path(evidence_path)
            evidence = evidence if evidence.is_absolute() else path.parent / evidence
            if (
                any(part in PRIVATE for part in evidence.parts)
                or evidence.is_symlink()
                or any(p.is_symlink() for p in evidence.parents)
                or not evidence.is_file()
            ):
                raise ValueError("unsafe/nonregular timing evidence refused")
            observed = sha(evidence)
            if declared is not None and declared != observed:
                raise ValueError("timing-caveat evidence SHA256 mismatch")
            evidence_path, evidence_sha, verification = (
                str(evidence.absolute()),
                observed,
                "file_hash_verified",
            )
        else:
            evidence_sha, verification = declared, "declared_hash_only_no_file_read"
        entries.append(
            {
                "trial_ids": sorted(ids),
                "reason": reason,
                "evidence_path": evidence_path,
                "evidence_sha256": evidence_sha,
                "evidence_verification": verification,
            }
        )
        affected.update(ids)
    return {
        "provided": True,
        "source_path": str(path),
        "source_sha256": sha(path),
        "entries": entries,
        "affected_trial_ids": sorted(affected),
        "trials_excluded": [],
    }


def trial_tier(directory, row):
    """Read only terminal-authenticated files; preserve partial evidence as explicit unknowns."""
    if not row["terminal_present"]:
        return inspect_tier({}, None, ("no terminal artifact; trial tier contents not inspected",))
    path = directory / "session/manifest.json"
    session = read(path) if path.is_file() else None
    hashes = session.get("artifact_hashes") if isinstance(session, dict) else None
    artifacts, errors, response_errors = {}, [], []
    for name in TIER_ARTIFACTS:
        path = directory / "session" / name
        target_errors = response_errors if name == "evidence/service-tier.json" else errors
        if not isinstance(hashes, dict) or name not in hashes or not path.is_file():
            target_errors.append("required session tier/configuration artifact unavailable: " + name)
            continue
        if sha(path) != hashes[name]:
            raise ValueError("session tier/configuration artifact hash mismatch: " + name)
        try:
            artifacts[name] = read(path)
        except (ValueError, OSError):
            target_errors.append("session tier/configuration artifact unreadable: " + name)
    return inspect_tier(artifacts, session, errors, response_errors)


def aggregate(
    run, protocol_path, expected_study_sha=None, study_path=None, timing_caveats_path=None
):
    protocol = read(protocol_path)
    supported = read(HERE / "supported_rules.json")
    protocol_id = admit_protocol(protocol, supported)
    binding = read(run / "run.json")
    if expected_study_sha and binding["study_sha256"] != expected_study_sha:
        raise ValueError("unexpected study version; never pool attempts")
    original = Path(study_path or binding["study_path"])
    if any(part in PRIVATE for part in original.parts):
        raise ValueError("private study reference refused without reading")
    if sha(original) != binding["study_sha256"]:
        raise ValueError("frozen input study SHA differs from run binding")
    study = read(original)
    if (
        read(run / "frozen-study.json") != study
        or study["arms"] != list(ARMS)
        or study["repetitions"] != 3
        or study["model"] != protocol["model"]
    ):
        raise ValueError("run/study design binding differs")
    admit_study_cohort(protocol_id, study)
    planned = schedule(study)
    if read(run / "plan.json")["trials"] != planned:
        raise ValueError("stored plan differs from independently reconstructed cyclic schedule")
    expected_ids = {r["id"] for r in planned}
    trial_root = run / "trials"
    if any(p.name not in expected_ids for p in trial_root.iterdir()):
        raise ValueError("unregistered trial directory/file; possible version pooling")
    caveats = load_timing_caveats(timing_caveats_path, expected_ids, binding["study_sha256"])
    rows = [trial_row(trial_root / item["id"], item) for item in planned]
    for row in rows:
        row["timing_caveat"] = row["id"] in caveats["affected_trial_ids"]
    tier = None
    if protocol_id == V6_STUDY_ID:
        for row in rows:
            row["service_tier"] = trial_tier(trial_root / row["id"], row)
        tier = study_tier_summary(rows)
    summary = summarize(rows, caveats["affected_trial_ids"], service_tier=tier)
    if binding.get("mode") != "model":
        summary.update(
            primary_efficiency_eligible=False,
            primary_superiority="not_established",
            winning_metrics_satisfying_all_six_pairs=[],
            incomplete_study=True,
        )
        if protocol_id == V6_STUDY_ID:
            summary["primary_metric_eligibility"] = {"charged_wall": False, "token_work": False}
            for pair in summary["paired_comparisons"]:
                for metric in ("charged_wall", "token_work"):
                    pair[metric]["primary_metric_eligible"] = False
    return {
        "schema_version": 1,
        "run": str(run),
        "study_sha256": binding["study_sha256"],
        "externally_expected_study_sha_verified": expected_study_sha is not None,
        "protocol_sha256": sha(protocol_path),
        "supported_rules_sha256": sha(HERE / "supported_rules.json"),
        "study_kind": study.get("bundle_kind", "unknown"),
        "claim_scope": "Development/synthetic application of frozen criterion; not a final heldout success claim."
        if study.get("bundle_kind") != "heldout"
        else "Predeclared heldout task sequence only; no population claim.",
        "runtime_image": study.get("image"),
        "reported_token_budget": study.get("reported_token_budget"),
        "summary": summary,
        "timing_caveats": caveats,
        "trials": rows,
        "integrity": {
            "terminal_artifact_hashes_verified": sum(
                r.get("artifact_hashes_verified", 0) for r in rows
            ),
            "terminal_sha256": {
                r["id"]: r["terminal_sha256"] for r in rows if r["terminal_present"]
            },
            "private_state_read": False,
            "active_trial_payloads_read": False,
        },
        "limits": [
            "One frozen version only; no retry or cross-version pooling.",
            "Normalized counters are resource proxies, not bills. Client-normalized zero cannot prove raw-provider zero; provider missingness may be unrecoverable.",
            "Input/cache.read/cache.write/output/reasoning are disjoint normalized counters; token work excludes cached reads but retains them separately.",
            "Session totals and assistant-step sums are never added. Resource component spans remain nested; charged wall is used once, with construction included.",
            "Final ledger hashing/publication is controller bookkeeping outside its operational timer; fixture/export/fixed grading are separate infrastructure.",
            "Three dependent four-stage blocks per arm, only two task instances; no population, causal, contamination-free or billing claim.",
        ],
    }


def export_csv(out, report):
    fields = [
        "id",
        "repetition",
        "arm",
        "stage",
        "task",
        "terminal_present",
        "status",
        "operational_status",
        "session_status",
        "quality",
        "quality_eligible",
        "wall_complete",
        "tokens_complete",
        "timing_caveat",
        "charged_wall_seconds",
        "construction_host_wall_seconds",
        "session_host_wall_seconds",
        "infrastructure_host_wall_seconds",
        "guard_and_orchestration_host_wall_seconds",
        "controller_total_host_wall_seconds",
        *TOKEN_KEYS,
        "token_work",
        "usage_status",
    ]
    with (out / "trials.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in report["trials"]:
            writer.writerow(
                {
                    key: (
                        row["tokens"].get(key)
                        if key in TOKEN_KEYS
                        else row.get("resource_components", {}).get(key)
                        if key.endswith("host_wall_seconds")
                        else row.get(key)
                    )
                    for key in fields
                }
            )
    with (out / "blocks.csv").open("x", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "repetition",
                "arm",
                "quality_pass",
                "wall_total",
                "wall_observed_subtotal",
                "token_work_total",
                "token_work_observed_subtotal",
                *TOKEN_KEYS,
            ]
        )
        for row in report["summary"]["blocks"]:
            writer.writerow(
                [
                    row["repetition"],
                    row["arm"],
                    row["all_four_operational_quality_pass"],
                    row["charged_wall"]["total"],
                    row["charged_wall"]["observed_subtotal"],
                    row["token_work"]["total"],
                    row["token_work"]["observed_subtotal"],
                    *[row["tokens"][k]["total"] for k in TOKEN_KEYS],
                ]
            )
    with (out / "paired.csv").open("x", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "repetition",
                "comparator",
                "metric",
                "cami",
                "comparator_value",
                "delta_cami_minus_comparator",
                "ratio_cami_over_comparator",
                "strictly_lower",
                "primary_metric_eligible",
            ]
        )
        for row in report["summary"]["paired_comparisons"]:
            for key in ("charged_wall", "token_work"):
                item = row[key]
                writer.writerow(
                    [
                        row["repetition"],
                        row["comparator"],
                        key,
                        item["cami"],
                        item["comparator"],
                        item["delta_cami_minus_comparator"],
                        item["ratio_cami_over_comparator"],
                        item["strictly_lower"],
                        item["primary_metric_eligible"],
                    ]
                )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--study-sha256")
    parser.add_argument(
        "--study", type=Path, help="Byte-identical frozen study metadata at a relocated path"
    )
    parser.add_argument(
        "--timing-caveats",
        type=Path,
        help="Explicit timing confounds; preserve rows and disqualify wall superiority",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run, out = args.run.absolute(), args.out.absolute()
    if (
        out.is_relative_to(run)
        or run.is_relative_to(out)
        or out.is_symlink()
        or any(p.is_symlink() for p in out.parents)
    ):
        parser.error("analysis output must be new and separate from input run")
    out.mkdir(parents=True, exist_ok=False)
    try:
        report = aggregate(
            run, args.protocol.absolute(), args.study_sha256, args.study, args.timing_caveats
        )
        write(out / "report.json", report)
        export_csv(out, report)
    except Exception as error:
        write(
            out / "rejection.json",
            {
                "status": "rejected",
                "failure": type(error).__name__ + ": " + str(error),
                "primary_superiority": "not_established",
                "model_calls": 0,
            },
        )
        raise


if __name__ == "__main__":
    main()
