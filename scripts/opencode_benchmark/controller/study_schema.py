"""Normalize sealed development/heldout bundles without solution-dependent logic."""

from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import urlsplit

from study_common import ARMS, contained, digest, file_hashes, read, verify_files
from memory_seed_schema import literal_catalog, validate_policy

MODEL = "openai/gpt-6.1-sol#high"
FORMAT_DESIGN = "format-only-development-v1"
FORMAT_CONDITIONS = (
    ("plain", "plain", "compact"),
    ("static_compact", "static", "compact"),
    ("cami_compact", "cami", "compact"),
    ("static_readable", "static", "readable"),
    ("cami_readable", "cami", "readable"),
)


def format_conditions():
    return [dict(id=name, arm=arm, response_format=fmt) for name, arm, fmt in FORMAT_CONDITIONS]


RANKING_DESIGN = "identifier-ranking-development-v1"
LEXICAL_RANKING = "lexical-overlap/1"
IDENTIFIER_RANKING = "identifier-mentions/1"


def ranking_conditions():
    return [dict(id=name, arm=arm, response_format="readable", ranking_policy=policy)
            for name, arm, policy in (
                ("plain", "plain", LEXICAL_RANKING),
                ("cami_lexical", "cami", LEXICAL_RANKING),
                ("cami_identifier", "cami", IDENTIFIER_RANKING))]


def validate_design(study):
    if "memory_ranking_policy" in study or "ranking_policy" in study:
        raise ValueError("ranking is fixed per registered condition, not a study override")
    if study["schema_version"] == 1:
        if study["arms"] != list(ARMS) or study["repetitions"] != 3:
            raise ValueError("unsupported study design")
        if "conditions" in study or "design" in study:
            raise ValueError("legacy studies cannot carry a format-only design")
    elif study["schema_version"] == 2:
        if (
            study.get("design") != FORMAT_DESIGN
            or study["bundle_kind"] != "development"
            or study["arms"] != list(ARMS)
            or study["repetitions"] != 1
            or study.get("conditions") != format_conditions()
            or study.get("memory_response_format") != "compact"
        ):
            raise ValueError("unsupported format-only development design")
    elif study["schema_version"] == 3:
        if (study.get("design") != RANKING_DESIGN or study["bundle_kind"] != "development"
                or study["arms"] != ["plain", "cami"] or study["repetitions"] != 1
                or study.get("conditions") != ranking_conditions()
                or study.get("memory_response_format") != "readable"):
            raise ValueError("unsupported identifier-ranking development design")
    else:
        raise ValueError("unsupported study design")


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,100}", value):
        raise ValueError("invalid task/study identifier")
    return value


def normalize(bundle, kind):
    if kind == "development":
        fixtures = read(bundle / "fixture-manifest.json")["fixtures"]
        prompts = read(bundle / "task-prompts.json")
        evaluations = read(bundle / "task-evaluation.json")["tasks"]
        tasks = []
        for row in evaluations:
            task_id = safe_id(row["id"])
            (base,) = [f for f in fixtures if f["task"] == task_id and f["role"] == "base"]
            tasks.append(
                {
                    "id": task_id,
                    "archive": base["archive"],
                    "archive_sha256": base["sha256"],
                    "prompt": prompts[task_id],
                    "acceptance": row["acceptance"],
                    "pytest_selection": row.get("pytest_selection"),
                    "oracle_root": "oracles",
                    "replace_regression_tests": None,
                    "regression": "tests",
                }
            )
        seed = "memory-origin/seed-spec.json"
        sequence = [tasks[0]["id"], tasks[0]["id"], tasks[1]["id"], tasks[1]["id"]]
        assets = [
            "fixture-manifest.json",
            "task-prompts.json",
            "task-evaluation.json",
            seed,
            "seed_source_notes.py",
        ]
        assets += [t["archive"] for t in tasks]
        assets += [
            p.relative_to(bundle).as_posix() for p in (bundle / "oracles").rglob("*") if p.is_file()
        ]
    elif kind == "heldout":
        manifest = read(bundle / "tasks.json")
        if manifest["repetitions"] != 3 or manifest["arms"] != [
            "plain",
            "static_memory",
            "cami_memory",
        ]:
            raise ValueError("heldout bundle design differs from fixed v1")
        tasks = []
        for row in manifest["tasks"]:
            task_id = safe_id(row["task_id"])
            if (
                file_hashes(contained(bundle, row["private_evaluator_root"]))
                != row["oracle_hashes"]
            ):
                raise ValueError("heldout fixed oracle inventory changed")
            tasks.append(
                {
                    "id": task_id,
                    "archive": row["base_archive"]["path"],
                    "archive_sha256": row["base_archive"]["sha256"],
                    "prompt": contained(bundle, row["prompt_path"]).read_text(),
                    "acceptance": row["acceptance_node_ids"],
                    "pytest_selection": None,
                    "oracle_root": row["private_evaluator_root"],
                    "replace_regression_tests": row["private_evaluator_root"] + "/tests",
                    "regression": row["regression_test_path"],
                }
            )
        sequence = [r["task_id"] for r in manifest["sequence"]]
        seed = manifest["memory_origin_seed"]
        assets = ["tasks.json", seed, "seed_source_notes.py"]
        assets += [r["prompt_path"] for r in manifest["tasks"]]
        assets += [t["archive"] for t in tasks]
        for row in manifest["tasks"]:
            assets += [row["private_evaluator_root"] + "/" + name for name in row["oracle_hashes"]]
    else:
        raise ValueError("bundle kind must be development or heldout")
    if (
        len(tasks) != 2
        or len({t["id"] for t in tasks}) != 2
        or sequence != [tasks[0]["id"]] * 2 + [tasks[1]["id"]] * 2
    ):
        raise ValueError("v1 requires exactly two tasks and four canonical stages")
    for task in tasks:
        if digest(contained(bundle, task["archive"])) != task["archive_sha256"]:
            raise ValueError("base archive hash mismatch")
        for name in task["acceptance"]:
            if Path(name.split("::")[0]).is_absolute() or ".." in Path(name.split("::")[0]).parts:
                raise ValueError("unsafe fixed pytest node")
    memory_source = None
    metadata = bundle / "memory-source.json"
    if metadata.exists():
        memory_source = validate_policy(read(metadata))
        assets = [path for path in assets if path not in {seed, "seed_source_notes.py"}]
        seed = memory_source["seed"]
        assets += [
            "memory-source.json",
            seed,
            memory_source["generator"],
            *memory_source["helpers"],
        ]
    spec = read(contained(bundle, seed))
    if memory_source is not None:
        literal_catalog(spec)
    elif spec.get("schema_version") != 1:
        raise ValueError("nonlegacy seed requires explicit memory-source metadata")
    source_roots = spec["source_roots"]
    if not source_roots or any(
        not x.startswith("src/") or ".." in Path(x).parts for x in source_roots
    ):
        raise ValueError("v1 memory origin must be source-only under src/")
    result = {
        "tasks": tasks,
        "sequence": sequence,
        "seed": seed,
        "source_roots": source_roots,
        "asset_hashes": {x: digest(contained(bundle, x)) for x in sorted(set(assets))},
    }
    if memory_source is not None:
        result["memory_source"] = memory_source
    return result


def make_study(
    bundle,
    kind,
    harness,
    image,
    cami_source,
    adapter,
    controller,
    runtime_manifest=None,
    memory_response_format="full",
    service_tier=None,
    binary_path=Path("/root/.opencode/bin/opencode"),
    design=None,
    shared_server=None,
):
    if design is not None and (design not in {FORMAT_DESIGN, RANKING_DESIGN} or kind != "development"):
        raise ValueError("format-only design requires a development bundle")
    if design is not None and memory_response_format != "full":
        raise ValueError("format-only design fixes the response format per condition")
    service_tier_value({"service_tier": service_tier})
    shared_server_value({"shared_server": shared_server})
    if memory_response_format not in ("full", "compact", "readable"):
        raise ValueError("unsupported memory response format")
    data = normalize(bundle, kind)
    result = {
        "schema_version": 1,
        "execution_authorized": False,
        "bundle_kind": kind,
        "bundle_path": str(bundle),
        "normalized": data,
        "repetitions": 3,
        "arms": list(ARMS),
        "model": MODEL,
        "timeout_seconds": 900,
        "max_steps": 20,
        "memory_response_format": memory_response_format,
        "reported_token_budget": 1_000_000,
        "image": image,
        "binary_path": str(binary_path.resolve()),
        "binary_sha256": digest(binary_path),
        "runtime_manifest_path": str(runtime_manifest) if runtime_manifest else None,
        "runtime_manifest_sha256": digest(runtime_manifest) if runtime_manifest else None,
        "harness": str(harness),
        "cami_source": str(cami_source),
        "adapter": str(adapter),
        "pins": {
            "harness": {
                "root": str(harness.parent),
                "files": harness_files(harness.parent),
            },
            "controller": {
                "root": str(controller),
                "files": controller_files(controller),
            },
            "production": {"root": str(cami_source), "files": runtime_files(cami_source)},
            "adapter": {"root": str(adapter), "files": runtime_files(adapter)},
        },
    }
    if service_tier is not None:
        result["service_tier"] = service_tier
    if shared_server is not None:
        result["shared_server"] = shared_server
    if design == FORMAT_DESIGN:
        result.update(schema_version=2, design=design, repetitions=1,
                      conditions=format_conditions(), memory_response_format="compact")
    elif design == RANKING_DESIGN:
        result.update(schema_version=3, design=design, repetitions=1, arms=["plain", "cami"],
                      conditions=ranking_conditions(), memory_response_format="readable")
    return result


def controller_files(root):
    required = {
        "study_controller.py",
        "study_schema.py",
        "study_common.py",
        "study_workspace.py",
        "study_runtime.py",
        "study_ledger.py",
        "preparation_worker.py",
        "fixed_grader.py",
        "memory_seed_schema.py",
        "memory_format_evidence.py",
        "readable_receipts.py",
        "opencode_message_schema.py",
    }
    if not required <= {p.name for p in root.glob("*.py")}:
        raise ValueError("required controller/helper module missing")
    return {p.name: digest(p) for p in sorted(root.glob("*.py"))}


def harness_files(root):
    required = {
        "container_session.py",
        "container_worker.py",
        "container_common.py",
        "evidence_safety.py",
        "native_read_evidence.py",
        "trial_guards.py",
    }
    if not required <= {p.name for p in root.glob("*.py")}:
        raise ValueError("required final harness module missing")
    paths = sorted(root.glob("*.py")) + [root / "boundary-sentinel.txt"]
    return {p.name: digest(p) for p in paths}


def runtime_files(root):
    return {
        name: value
        for name, value in file_hashes(root).items()
        if not any(
            x in {"__pycache__", ".git", ".pytest_cache", ".ruff_cache"} for x in Path(name).parts
        )
        and not name.endswith((".pyc", ".pyo"))
    }


def memory_response_format(study):
    value = study.get("memory_response_format", "full")
    if value not in ("full", "compact", "readable"):
        raise ValueError("unsupported frozen memory response format")
    return value


def service_tier_value(study):
    value = study.get("service_tier")
    if value is not None and (not isinstance(value, str) or value not in ("auto", "priority")):
        raise ValueError("unsupported frozen service tier")
    return value


def shared_server_value(study):
    value = study.get("shared_server")
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("shared auth server must be a local HTTP endpoint")
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "host.docker.internal"}
            or parsed.username is not None or parsed.password is not None
            or parsed.path or parsed.query or parsed.fragment or parsed.port is None
            or not 1 <= parsed.port <= 65535
            or value != f"http://{parsed.hostname}:{parsed.port}"):
        raise ValueError("shared auth server must be a local HTTP endpoint")
    return value


def validate(study, *, execute=False):
    memory_response_format(study)
    service_tier_value(study)
    shared_server_value(study)
    validate_design(study)
    if study["model"] != MODEL or study["timeout_seconds"] != 900 or study["max_steps"] != 20:
        raise ValueError("frozen model/resource mismatch")
    if study.get("reported_token_budget") != 1_000_000:
        raise ValueError(
            "declared development v2 requires the frozen 1000000 reported-token threshold"
        )
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", study["image"]):
        raise ValueError("runtime requires an immutable image ID")
    if execute and study["execution_authorized"] is not True:
        raise ValueError("model execution requires explicit frozen authorization")
    if digest(Path(study["binary_path"])) != study["binary_sha256"]:
        raise ValueError("OpenCode executable changed")
    runtime_expected = {
        "image_id": study["image"],
        "binary_sha256": study["binary_sha256"],
        "cami_files": study["pins"]["production"]["files"],
        "adapter_files": study["pins"]["adapter"]["files"],
    }
    if study.get("runtime_manifest_path"):
        runtime = Path(study["runtime_manifest_path"])
        if digest(runtime) != study["runtime_manifest_sha256"] or read(runtime) != runtime_expected:
            raise ValueError("immutable runtime manifest mismatch")
    elif execute:
        raise ValueError("model execution requires pinned runtime manifest")
    bundle = Path(study["bundle_path"])
    verify_files(bundle, study["normalized"]["asset_hashes"])
    if normalize(bundle, study["bundle_kind"]) != study["normalized"]:
        raise ValueError("normalized bundle mismatch")
    for pin in study["pins"].values():
        verify_files(Path(pin["root"]), pin["files"])
    harness_pin = study["pins"]["harness"]
    if harness_files(Path(harness_pin["root"])) != harness_pin["files"]:
        raise ValueError("harness helper module inventory changed")
    controller_pin = study["pins"]["controller"]
    if controller_files(Path(controller_pin["root"])) != controller_pin["files"]:
        raise ValueError("controller module inventory changed")
    for name in ["production", "adapter"]:
        pin = study["pins"][name]
        if runtime_files(Path(pin["root"])) != pin["files"]:
            raise ValueError("runtime inventory changed")
    return study


def plan(study):
    if study.get("schema_version") in (2, 3):
        validate_design(study)
        result = []
        sequence = study["normalized"]["sequence"]
        if len(sequence) != 4 or sequence[0] != sequence[1] or sequence[2] != sequence[3] or sequence[0] == sequence[2]:
            raise ValueError("format-only design requires two tasks and four stages")
        conditions = format_conditions() if study["schema_version"] == 2 else ranking_conditions()
        for stage, task in enumerate(sequence, 1):
            offset = (stage - 1) % len(conditions)
            for condition in conditions[offset:] + conditions[:offset]:
                name, arm, fmt = (condition[k] for k in ("id", "arm", "response_format"))
                result.append(dict(
                    id=f"r1-{name}-s{stage}", repetition=1, arm=arm, condition=name,
                    response_format=fmt, stage=stage, task=task,
                    **({"ranking_policy": condition["ranking_policy"]} if "ranking_policy" in condition else {}),
                    predecessor=f"r1-{name}-s{stage - 1}" if stage > 1 else None,
                ))
        return result
    result = []
    for repetition in range(1, 4):
        for stage, task in enumerate(study["normalized"]["sequence"], 1):
            offset = (repetition - 1 + stage - 1) % 3
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


def trial_response_format(study, trial):
    if study.get("schema_version") in (2, 3):
        if trial not in plan(study):
            raise ValueError("trial differs from frozen format-only schedule")
        return trial["response_format"]
    return memory_response_format(study)


def trial_ranking_policy(study, trial):
    if study.get("schema_version") == 3:
        if trial not in plan(study):
            raise ValueError("trial differs from frozen ranking schedule")
        return trial["ranking_policy"]
    if "ranking_policy" in trial:
        raise ValueError("legacy trial cannot override ranking")
    return LEXICAL_RANKING
