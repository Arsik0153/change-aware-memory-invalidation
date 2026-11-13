"""Launch the immutable run and record lightweight host-load observations."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

repo = Path('/Users/zhanarys/Projects/change-aware-memory-invalidation')
report = repo / 'reports/opencode-full-replay-20261114'
protocol = report / 'protocol.json'
admission = json.loads((report / 'admission.json').read_text())
assert admission['status'] == 'passed' and admission['model_calls'] == 0
assert admission['protocol_sha256'] == hashlib.sha256(protocol.read_bytes()).hexdigest()
volume = '/var/lib/docker/volumes/cami-local-study-20261113/_data'
root = volume + '/runtime-v9'
command = ['docker', 'run', '--rm', '--name', 'cami-full-study-20261113',
    '--mount', 'type=volume,src=cami-local-study-20261113,dst=' + volume,
    '--mount', 'type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock',
    '--mount', 'type=bind,src=/Users/zhanarys/.config/opencode/service.json,dst=/root/.config/opencode/service.json,readonly',
    'cami-controller:local-20261113', root + '/scripts/opencode_benchmark/experiments/full_replay_study.py',
    '--freeze', root + '/runs/full-freeze', '--run', '--out', root + '/runs/full-model']
with (repo / 'runs/local-resume-20261113/full-driver-v9.jsonl').open('xb') as log, (repo / 'runs/local-resume-20261113/full-host-load-v9.jsonl').open('x') as observations:
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    while True:
        observations.write(json.dumps({'utc': datetime.now(timezone.utc).isoformat(),
            'load_average': os.getloadavg(), 'logical_cpus': os.cpu_count(),
            'free_disk_bytes': shutil.disk_usage(repo).free, 'controller_returncode': process.poll()}) + '\n')
        observations.flush()
        if process.returncode is not None:
            break
        time.sleep(10)
raise SystemExit(process.returncode)
