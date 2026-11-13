"""Install a new immutable ablation runtime, admit and freeze it; zero model calls."""
from pathlib import Path
import hashlib
import json
import subprocess

REPO = Path(__file__).resolve().parents[2]
REPORT = Path(__file__).resolve().parent
LOCAL = REPO / 'runs/local-resume-20261113/ablation-v1'
VOLUME = '/var/lib/docker/volumes/cami-local-study-20261113/_data'
ROOT = VOLUME + '/runtime-v15'
IMAGE = 'cami-controller:local-20261113'


def run(argv, **kwargs):
    return subprocess.run([str(x) for x in argv], check=True, cwd=REPO, **kwargs)


def main():
    running = subprocess.check_output(['docker', 'ps', '--format', '{{.Names}}'], text=True)
    if 'cami-heldout-study-20261114' in running:
        raise ValueError('finish heldout study first; no concurrent admission')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO):
        raise ValueError('commit source and preparation tools before freezing')
    LOCAL.mkdir(parents=True, exist_ok=False)
    source = LOCAL / 'source.tar'
    with source.open('xb') as output:
        run(['git', 'archive', 'HEAD', 'src', 'integrations/opencode',
             'scripts/opencode_benchmark', 'examples/opencode_benchmark_development_v2'], stdout=output)
    source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()
    mounts = ['--mount', 'type=volume,src=cami-local-study-20261113,dst=' + VOLUME,
              '--mount', 'type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock']
    install = f'''from pathlib import Path
import shutil,tarfile
root=Path({ROOT!r})
root.mkdir(exist_ok=False)
with tarfile.open('/source.tar') as archive:archive.extractall(root,filter='data')
(root/'bin').mkdir()
shutil.copy2(root.parent/'runtime-v7/bin/opencode',root/'bin/opencode')
(root/'runs').mkdir()
print('Installed immutable runtime-v15')
'''
    run(['docker', 'run', '--rm', *mounts, '--mount',
         f'type=bind,src={source},dst=/source.tar,readonly', IMAGE, '-c', install])
    with (LOCAL / 'admission.log').open('xb') as log:
        run(['docker', 'run', '--rm', *mounts, IMAGE,
             ROOT + '/scripts/opencode_benchmark/experiments/replay_ablation_admission.py'],
            stdout=log, stderr=subprocess.STDOUT)
    run(['docker', 'run', '--rm', *mounts, IMAGE,
         ROOT + '/scripts/opencode_benchmark/experiments/full_replay_study.py',
         '--design', 'result-memory-ablation-development-v1', '--freeze', ROOT + '/runs/full-freeze'])
    export = f'''from pathlib import Path
import hashlib,json,shutil,tarfile
root=Path({ROOT!r})
out=Path('/report')
for name in ('protocol.json','runtime-manifest.json'):
    if (out/name).exists():raise ValueError('existing frozen report')
    shutil.copy2(root/'runs/full-freeze'/name,out/name)
admission=json.loads((root/'runs/ablation-admission/admission.json').read_text())
admission['protocol_sha256']=hashlib.sha256((out/'protocol.json').read_bytes()).hexdigest()
with (out/'admission.json').open('x') as stream:json.dump(admission,stream,indent=2,sort_keys=True)
with tarfile.open(out/'admission.tar.xz','x:xz',preset=6) as archive:
    archive.add(root/'runs/ablation-admission',arcname='ablation-admission')
print(json.dumps({{k:admission[k] for k in ('status','model_calls','protocol_sha256')}}))
'''
    run(['docker', 'run', '--rm', *mounts, '--mount',
         f'type=bind,src={REPORT},dst=/report', IMAGE, '-c', export])
    environment = json.loads((REPO / 'reports/opencode-heldout-full-replay-20261114/environment.json').read_text())
    environment.update(source_commit=source_commit, runtime_snapshot='runtime-v15',
                       adaptation='Same pinned ARM image and development_v2 inputs as earlier full development run; independent actual admission.')
    (REPORT / 'environment.json').write_text(json.dumps(environment, indent=2) + '\n')
    receipt = {'source_commit': source_commit,
               'source_archive_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'admission_archive_sha256': hashlib.sha256((REPORT / 'admission.tar.xz').read_bytes()).hexdigest(),
               'model_calls': 0}
    (REPORT / 'preparation.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('Admission and freeze completed; commit report before launching models.')


if __name__ == '__main__':
    main()
