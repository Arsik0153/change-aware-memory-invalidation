import json, subprocess, sys
from pathlib import Path
root=Path('/var/lib/docker/volumes/cami-local-study-20261113/_data/runtime-v4')
controller=root/'scripts/opencode_benchmark/controller'
sys.path.insert(0,str(controller))
from study_common import digest, read, write
from study_schema import plan, validate
freeze=root/'runs/format-freeze'
study_path=freeze/'study.json'
study=validate(read(study_path),execute=True)
admission=read(freeze/'admission.json')
assert admission['status']=='passed' and admission['study_sha256']==digest(study_path)
assert admission['model_calls']==0 and len(admission['sessions'])==5
assert digest(freeze/'protocol.json')==study['protocol_sha256']
output=root/'runs/format-model'
driver=root/'runs/format-driver';driver.mkdir(exist_ok=False)
for index,trial in enumerate(plan(study)):
    print(json.dumps({'event':'starting','trial':trial['id'],'position':index+1,'maximum':20}),flush=True)
    argv=[sys.executable,str(controller/'study_controller.py'),'--study',str(study_path),
        '--study-sha256',digest(study_path),'--out',str(output),'--run-model','--one-trial',trial['id']]
    if index:argv+=['--resume']
    with (driver/(trial['id']+'.stdout')).open('wb') as stdout,(driver/(trial['id']+'.stderr')).open('wb') as stderr:
        result=subprocess.run(argv,stdout=stdout,stderr=stderr)
    if result.returncode:raise RuntimeError('controller stopped; no retry: '+trial['id'])
    record=read(output/'trials'/trial['id']/'terminal.json')
    print(json.dumps({'event':'terminal','trial':trial['id'],'status':record['status'],
        'quality':record['quality'],'session_status':record['session_status'],
        'failures':record.get('failures',[])}),flush=True)
print(json.dumps({'event':'finished','terminal_trials':20,'retries':0}),flush=True)
