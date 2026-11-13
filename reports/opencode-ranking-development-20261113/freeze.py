import json
import subprocess
import sys
from pathlib import Path

root = Path("/var/lib/docker/volumes/cami-local-study-20261113/_data/runtime-v6")
controller = root / "scripts/opencode_benchmark/controller"
sys.path.insert(0, str(controller))
import study_schema as schema  # noqa: E402
import study_workspace as workspaces  # noqa: E402
from study_common import digest, read, write  # noqa: E402
from verify_literal_containers import execute  # noqa: E402

image = "sha256:b0ac577d424f3ef181e3c4a5b188abf0ecf8a4fde0d544e55a3e825999826040"
out = root / "runs/ranking-freeze"
out.mkdir(parents=True, exist_ok=False)
binary = root / "bin/opencode"
manifest = out / "runtime-manifest.json"
write(
    manifest,
    {
        "image_id": image,
        "binary_sha256": digest(binary),
        "cami_files": schema.runtime_files(root / "src"),
        "adapter_files": schema.runtime_files(root / "integrations/opencode"),
    },
)
study = schema.make_study(
    root / "examples/opencode_benchmark_development_v2",
    "development",
    root / "scripts/opencode_benchmark/harness/container_session.py",
    image,
    root / "src",
    root / "integrations/opencode",
    controller,
    manifest,
    service_tier="priority",
    binary_path=binary,
    design=schema.RANKING_DESIGN,
    shared_server="http://host.docker.internal:49374",
)
sys.path.insert(0, str(root / "scripts/opencode_benchmark/analysis"))
from ranking_probe import RULES  # noqa: E402

protocol = {
    "rules": RULES,
    "status": "frozen_authorized_development_execution",
    "source_commit": "19fb65e",
    "schedule": schema.plan(study),
    "analysis_files": schema.runtime_files(root / "scripts/opencode_benchmark/analysis"),
    "host": "macOS ARM64 with Docker Desktop; Linux named volume for all live state",
    "authorization": "User requested continued local implementation and execution until stopped; no heldout sessions.",
    "motivation": "Post-hoc replay found four omissions of one explicitly named function among seventeen dependent historical queries; no prior model utility evidence for this intervention.",
}
write(out / "protocol.json", protocol)
study.update(
    execution_authorized=True,
    protocol_sha256=digest(out / "protocol.json"),
    source_commit="19fb65e",
    analysis_files=protocol["analysis_files"],
)
write(out / "study.json", study)
schema.validate(study, execute=True)
write(out / "plan.json", {"trials": schema.plan(study), "maximum_model_sessions": 12})
# Independent preparations cover both display cohorts without sharing measured state.
for group, policy in (
    ("cami_lexical", schema.LEXICAL_RANKING),
    ("cami_identifier", schema.IDENTIFIER_RANKING),
):
    execute(out / "study.json", controller, out / ("stdio-" + group), ranking_policy=policy)
results = []
catalogs = []
for condition in schema.ranking_conditions():
    name, arm, fmt = condition["id"], condition["arm"], condition["response_format"]
    if arm == "plain":
        namespace = out / "plain-namespace"
        workspaces.create_namespace(namespace, digest(out / "study.json"))
        task = study["normalized"]["tasks"][0]
        workspaces.reset(
            namespace,
            Path(study["bundle_path"]) / task["archive"],
            task["archive_sha256"],
            digest(out / "study.json"),
        )
        workspace, memory = namespace / "workspace", namespace / "memory"
    else:
        namespace = out / ("stdio-" + name) / arm
        workspace, memory = namespace / "workspace", namespace / "memory"
        catalogs.append(digest(memory / "prepared/catalog.json"))
    case = out / ("session-" + name)
    case.mkdir()
    command = [
        sys.executable,
        study["harness"],
        "--no-model",
        "--workspace",
        str(workspace),
        "--memory-dir",
        str(memory),
        "--state-dir",
        str(case / "private-state"),
        "--out",
        str(case / "output"),
        "--arm",
        arm,
        "--opencode-binary",
        str(binary),
        "--opencode-sha256",
        digest(binary),
        "--runtime-manifest",
        str(manifest),
        "--image",
        image,
        "--cami-source",
        study["cami_source"],
        "--adapter-dir",
        study["adapter"],
        "--memory-response-format",
        fmt,
        "--memory-ranking-policy",
        condition["ranking_policy"],
        "--service-tier",
        "priority",
    ]
    if arm != "plain":
        command += ["--binding-relative", "prepared/binding.json"]
    with (case / "stdout.log").open("wb") as stdout, (case / "stderr.log").open("wb") as stderr:
        result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=240)
    record = {
        "condition": condition,
        "exit": result.returncode,
        "manifest": read(case / "output/manifest.json"),
    }
    write(case / "result.json", record)
    results.append(record)
    if result.returncode:
        raise RuntimeError("no-model admission failed: " + name)
    from study_runtime import validate_memory_command

    validate_memory_command(
        read(case / "output/effective-input-config.json"), arm, fmt, condition["ranking_policy"]
    )
    assert record["manifest"]["memory_ranking_policy"] == condition["ranking_policy"]
    receipt_path = case / "output/evidence/native-read-bytes.json"
    receipt = read(receipt_path)
    assert receipt["schema"] == "opencode-native-read-text/2" and receipt["complete"]
    assert receipt["utf8_bytes"] == 0 and receipt["read_calls"] == 0
    assert record["manifest"]["artifact_hashes"]["evidence/native-read-bytes.json"] == digest(
        receipt_path
    )
    assert not (case / "private-state").exists()
assert len(catalogs) == 2 and len(set(catalogs)) == 1
schema.validate(study, execute=True)
write(
    out / "admission.json",
    {
        "status": "passed",
        "model_calls": 0,
        "independent_cami_catalogs": 2,
        "catalog_sha256": catalogs[0],
        "stdio_cases": 12,
        "sessions": results,
        "study_sha256": digest(out / "study.json"),
    },
)
print(
    json.dumps(
        {
            "status": "passed",
            "study_sha256": digest(out / "study.json"),
            "model_calls": 0,
            "conditions": 3,
        }
    )
)
