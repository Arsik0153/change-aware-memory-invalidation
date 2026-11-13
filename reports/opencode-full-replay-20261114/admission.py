from pathlib import Path
import sys
import subprocess
import json
root = Path('/var/lib/docker/volumes/cami-local-study-20261113/_data/runtime-v9')
controller = root / 'scripts/opencode_benchmark/controller'
sys.path.insert(0, str(controller))
from study_common import read, digest, write
from study_schema import make_study, validate
from study_workspace import create_namespace, reset
from study_runtime import validate_memory_command
from verify_literal_containers import execute
freeze = root / 'runs/full-freeze'
spec = read(freeze / 'protocol.json')['runtime']
assert spec['model'] == 'openai/gpt-6.1-sol#high'
out = root / 'runs/full-admission'
out.mkdir(exist_ok=False)
# Legacy-shaped study only supplies the established no-model verification helper.
# No model run uses this object or its legacy36-trial schedule.
study = make_study(Path(spec['bundle_path']), 'development', Path(spec['harness']), spec['image'],
    Path(spec['cami_source']), Path(spec['adapter']), controller, freeze / 'runtime-manifest.json',
    memory_response_format='readable', service_tier='priority', binary_path=root / 'bin/opencode')
write(out / 'verification-study.json', study)
validate(study, execute=False)
execute(out / 'verification-study.json', controller, out / 'stdio')
sessions = []
for arm in ('plain', 'static', 'cami'):
    if arm == 'plain':
        namespace = out / 'plain'
        create_namespace(namespace, digest(freeze / 'protocol.json'))
        task = spec['normalized']['tasks'][0]
        reset(namespace, Path(spec['bundle_path']) / task['archive'], task['archive_sha256'], digest(freeze / 'protocol.json'))
    else:
        namespace = out / 'stdio' / arm
    case = out / ('session-' + arm)
    case.mkdir()
    command = [sys.executable, spec['harness'], '--workspace', str(namespace / 'workspace'),
        '--memory-dir', str(namespace / 'memory'), '--state-dir', str(case / 'private-state'), '--out', str(case / 'session'),
        '--arm', arm, '--no-model', '--runtime-manifest', str(freeze / 'runtime-manifest.json'),
        '--image', spec['image'], '--cami-source', spec['cami_source'], '--adapter-dir', spec['adapter'],
        '--opencode-binary', str(root / 'bin/opencode'), '--opencode-sha256', digest(root / 'bin/opencode'),
        '--memory-response-format', 'readable', '--service-tier', 'priority']
    if arm != 'plain':
        command += ['--binding-relative', 'prepared/binding.json']
    with (case / 'stdout.log').open('wb') as stdout, (case / 'stderr.log').open('wb') as stderr:
        process = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=240)
    assert process.returncode == 0
    manifest = read(case / 'session/manifest.json')
    assert manifest['status'] == 'passed' and not manifest['model_requested']
    assert not (case / 'private-state').exists()
    config = read(case / 'session/effective-input-config.json')
    assert config['model'] == spec['model'] and config['agents']['research']['steps'] == 20
    validate_memory_command(config, arm, 'readable')
    receipt = read(case / 'session/evidence/native-read-bytes.json')
    assert receipt['complete'] and receipt['read_calls'] == 0 and receipt['utf8_bytes'] == 0
    sessions.append({'arm': arm, 'status': 'passed'})
write(out / 'admission.json', {'status': 'passed', 'model_calls': 0, 'sessions': sessions,
    'stdio_cases': 6, 'protocol_sha256': digest(freeze / 'protocol.json')})
print(json.dumps(read(out / 'admission.json')))
