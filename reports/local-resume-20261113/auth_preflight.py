import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

root = Path("/var/lib/docker/volumes/cami-local-study-20261113/_data/runtime-v3")
sys.path.insert(0, "/current-harness")
from container_session import credential_pipe  # noqa: E402

name = "cami-auth-preflight-" + uuid.uuid4().hex
state = root / "runs/auth-preflight-private"
state.mkdir(exist_ok=False)
image = "sha256:b0ac577d424f3ef181e3c4a5b188abf0ecf8a4fde0d544e55a3e825999826040"
result = {"model_calls": 0}
try:
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--name",
            name,
            "--label",
            "cami.research.owned=true",
            "--user",
            "65534:65534",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--tmpfs",
            "/state:rw,uid=65534,gid=65534,mode=700",
            "--tmpfs",
            "/tmp:rw",
            "--mount",
            f"type=bind,src={root}/bin/opencode,dst=/opt/opencode,readonly",
            "--env",
            "OPENCODE_DB=/state/opencode.db",
            "--env",
            "XDG_DATA_HOME=/state/data",
            "--env",
            "XDG_CONFIG_HOME=/state/config",
            "--env",
            "XDG_CACHE_HOME=/state/cache",
            "--env",
            "XDG_STATE_HOME=/state/state",
            "--env",
            "OPENCODE_TEST_HOME=/state/home",
            "--entrypoint",
            "python",
            image,
            "-c",
            "import time; time.sleep(300)",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    result["transfer"] = credential_pipe(
        name, state, "http://host.docker.internal:49374", binary=root / "bin/opencode"
    )
    assert result["transfer"]["status"] == "passed", "credential import failed"
finally:
    cleanup = subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    shutil.rmtree(state)
    result["private_state_removed"] = not state.exists()
    result["container_removed"] = cleanup.returncode == 0
    print(json.dumps(result, indent=2))
