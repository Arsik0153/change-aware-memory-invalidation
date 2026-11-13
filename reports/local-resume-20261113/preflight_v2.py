import json
import subprocess
import sys
from pathlib import Path

root = Path("/var/lib/docker/volumes/cami-local-study-20261113/_data/runtime-v2")
controller = root / "scripts/opencode_benchmark/controller"
sys.path.insert(0, str(controller))
import study_schema as schema  # noqa: E402
from study_common import digest, write  # noqa: E402
from verify_literal_containers import execute  # noqa: E402

image = "sha256:b0ac577d424f3ef181e3c4a5b188abf0ecf8a4fde0d544e55a3e825999826040"
out = root / "runs/local-preflight"
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
    memory_response_format="readable",
    service_tier="priority",
    binary_path=binary,
)
write(out / "study.json", study)
execute(out / "study.json", controller, out / "stdio")
results = []
for arm in ("plain", "static", "cami"):
    if arm == "plain":
        workspace, memory = out / "stdio/static/workspace", out / "plain-memory"
        memory.mkdir()
    else:
        workspace, memory = out / "stdio" / arm / "workspace", out / "stdio" / arm / "memory"
    case = out / ("session-" + arm)
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
        "readable",
        "--service-tier",
        "priority",
    ]
    if arm != "plain":
        command += ["--binding-relative", "prepared/binding.json"]
    with (case / "stdout.log").open("wb") as stdout, (case / "stderr.log").open("wb") as stderr:
        result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=240)
    results.append(
        {
            "arm": arm,
            "exit": result.returncode,
            "manifest": json.loads((case / "output/manifest.json").read_text()),
        }
    )
    write(case / "result.json", results[-1])
    if result.returncode:
        raise RuntimeError("no-model session failed: " + arm)
write(out / "summary.json", {"status": "passed", "model_calls": 0, "sessions": results})
print("six stdio cases and three no-model sessions passed")
