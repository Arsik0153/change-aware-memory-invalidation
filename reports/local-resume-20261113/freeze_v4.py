import json, subprocess, sys
from pathlib import Path
root=Path('/var/lib/docker/volumes/cami-local-study-20261113/_data/runtime-v4')
controller=root/'scripts/opencode_benchmark/controller'
sys.path.insert(0,str(controller))
import study_schema as schema
import study_workspace as workspaces
from study_common import digest, read, write
from verify_literal_containers import execute
image='sha256:b0ac577d424f3ef181e3c4a5b188abf0ecf8a4fde0d544e55a3e825999826040'
out=root/'runs/format-freeze'
out.mkdir(parents=True,exist_ok=False)
binary=root/'bin/opencode'
manifest=out/'runtime-manifest.json'
write(manifest,{'image_id':image,'binary_sha256':digest(binary),
    'cami_files':schema.runtime_files(root/'src'),'adapter_files':schema.runtime_files(root/'integrations/opencode')})
study=schema.make_study(root/'examples/opencode_benchmark_development_v2','development',
    root/'scripts/opencode_benchmark/harness/container_session.py',image,root/'src',
    root/'integrations/opencode',controller,manifest,service_tier='priority',binary_path=binary,
    design=schema.FORMAT_DESIGN,shared_server='http://host.docker.internal:49374')
proposal=root/'reports/opencode-memory-utility-design-review-20261106/proposal.json'
protocol={**read(proposal),'status':'frozen_authorized_development_execution',
    'proposal_sha256':digest(proposal),'source_commit':'420730d',
    'condition_mapping':schema.format_conditions(),'schedule':schema.plan(study),
    'analysis_files':schema.runtime_files(root/'scripts/opencode_benchmark/analysis'),
    'host':'macOS ARM64 with Docker Desktop; Linux named volume for all live state',
    'wall_eligibility':'descriptive only; no independently established host quietness',
    'authorization':'User requested continued local implementation and execution until stopped; no heldout sessions.'}
write(out/'protocol.json',protocol)
study.update(execution_authorized=True,protocol_sha256=digest(out/'protocol.json'),
             source_commit='420730d',analysis_files=protocol['analysis_files'])
write(out/'study.json',study)
schema.validate(study,execute=True)
write(out/'plan.json',{'trials':schema.plan(study),'maximum_model_sessions':20})
# Independent preparations cover both display cohorts without sharing measured state.
for group in ('compact','readable'):
    execute(out/'study.json',controller,out/('stdio-'+group))
results=[]
catalogs=[]
for condition in schema.format_conditions():
    name,arm,fmt=condition['id'],condition['arm'],condition['response_format']
    if arm=='plain':
        namespace=out/'plain-namespace'
        workspaces.create_namespace(namespace,digest(out/'study.json'))
        task=study['normalized']['tasks'][0]
        workspaces.reset(namespace,Path(study['bundle_path'])/task['archive'],task['archive_sha256'],digest(out/'study.json'))
        workspace,memory=namespace/'workspace',namespace/'memory'
    else:
        namespace=out/('stdio-'+fmt)/arm
        workspace,memory=namespace/'workspace',namespace/'memory'
        catalogs.append(digest(memory/'prepared/catalog.json'))
    case=out/('session-'+name);case.mkdir()
    command=[sys.executable,study['harness'],'--no-model','--workspace',str(workspace),
        '--memory-dir',str(memory),'--state-dir',str(case/'private-state'),'--out',str(case/'output'),
        '--arm',arm,'--opencode-binary',str(binary),'--opencode-sha256',digest(binary),
        '--runtime-manifest',str(manifest),'--image',image,'--cami-source',study['cami_source'],
        '--adapter-dir',study['adapter'],'--memory-response-format',fmt,'--service-tier','priority']
    if arm!='plain':command+=['--binding-relative','prepared/binding.json']
    with (case/'stdout.log').open('wb') as stdout,(case/'stderr.log').open('wb') as stderr:
        result=subprocess.run(command,stdout=stdout,stderr=stderr,timeout=240)
    record={'condition':condition,'exit':result.returncode,'manifest':read(case/'output/manifest.json')}
    write(case/'result.json',record);results.append(record)
    if result.returncode:raise RuntimeError('no-model admission failed: '+name)
assert len(catalogs)==4 and len(set(catalogs))==1
schema.validate(study,execute=True)
write(out/'admission.json',{'status':'passed','model_calls':0,'independent_catalogs':4,
    'catalog_sha256':catalogs[0],'stdio_cases':12,'sessions':results,'study_sha256':digest(out/'study.json')})
print(json.dumps({'status':'passed','study_sha256':digest(out/'study.json'),'model_calls':0,'conditions':5}))
