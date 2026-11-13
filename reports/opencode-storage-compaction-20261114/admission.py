from pathlib import Path
import sys,shutil,json,sqlite3
root=Path('/var/lib/docker/volumes/cami-local-study-20261113/_data/runtime-v10')
controller=root/'scripts/opencode_benchmark/controller'
sys.path[:0]=[str(controller),str(root/'scripts/opencode_benchmark/harness')]
import study_common as common
import study_runtime as runtime
import study_workspace as workspace
from study_schema import make_study
from verify_literal_containers import execute
import container_session as harness
out=root/'runs/storage-admission'
out.mkdir()
study=make_study(root/'examples/opencode_benchmark_development_v2','development',root/'scripts/opencode_benchmark/harness/container_session.py','sha256:b0ac577d424f3ef181e3c4a5b188abf0ecf8a4fde0d544e55a3e825999826040',root/'src',root/'integrations/opencode',controller,memory_response_format='readable',service_tier='priority',binary_path=root/'bin/opencode')
common.write(out/'study.json',study)
execute(out/'study.json',controller,out/'stdio')
fresh=next((out/'stdio/cami/memory').rglob('memory.sqlite3'))
with sqlite3.connect(f'file:{fresh}?mode=ro',uri=True) as db:
    assert db.execute('PRAGMA user_version').fetchone()[0]==2
namespace=out/'legacy'
study_sha=common.digest(out/'study.json')
workspace.create_namespace(namespace,study_sha)
task=study['normalized']['tasks'][1]
workspace.reset(namespace,Path(study['bundle_path'])/task['archive'],task['archive_sha256'],study_sha)
original=root.parent/'runtime-v9/runs/full-model/namespaces/r1-cami/memory'
original_db=next(original.rglob('memory.sqlite3'))
original_sha=common.digest(original_db)
shutil.copytree(original,namespace/'memory',dirs_exist_ok=True)
copy_db=next((namespace/'memory').rglob('memory.sqlite3'))
with sqlite3.connect(f'file:{copy_db}?mode=ro',uri=True) as db:
    assert db.execute('PRAGMA user_version').fetchone()[0]==1
catalog=common.read(namespace/'memory/prepared/catalog.json')
expected=next(row for row in catalog['records'] if row['source']['path'] not in ('src/click/core.py','src/click/decorators.py','src/click/__init__.py') and len(json.dumps(row,sort_keys=True,ensure_ascii=True,separators=(',',':')).encode())<=16384)
case=namespace/'probe'
(case/'evidence').mkdir(parents=True)
server=harness.configuration('cami','prepared/binding.json','readable')['mcp']['servers']['research_memory']
common.write(case/'config.json',{'server':server,'backend':'cami','format':'readable','expected':expected})
common.chown(namespace)
result=runtime.container(study,[(namespace/'workspace','/workspace',False),(namespace/'memory','/memory',False),(root/'src','/opt/cami-src',True),(root/'integrations/opencode','/opt/memory-adapter',True),(controller/'literal_stdio_worker.py','/opt/literal_stdio_worker.py',True),(controller/'readable_receipts.py','/opt/readable_receipts.py',True),(case,'/check',False),(case/'evidence','/state/evidence',False)],['python','-I','/opt/literal_stdio_worker.py','--config','/check/config.json','--out','/check/result.json'],case/'container',timeout=180)
assert result['status']=='passed' and common.read(case/'result.json')['status']=='passed'
with sqlite3.connect(f'file:{copy_db}?mode=ro',uri=True) as db:
    assert db.execute('PRAGMA user_version').fetchone()[0]==2
assert common.digest(original_db)==original_sha
common.write(out/'admission.json',{'status':'passed','model_calls':0,'fresh_stdio_cases':6,'actual_legacy_mcp_upgrade_cases':1,'fresh_schema':2,'migrated_schema':2,'legacy_original_sha256':original_sha,'original_unchanged':True,'scope':'Actual Docker MCP stdio, new schema2 stores and a copy of the completed full-study schema1 database. Correctness only, not timing evidence.'})
print(json.dumps(common.read(out/'admission.json')))
