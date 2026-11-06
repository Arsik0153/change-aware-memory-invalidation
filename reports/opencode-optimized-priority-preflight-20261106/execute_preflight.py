"""Authorized post-quiet authored no-model correctness check, never a benchmark."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
STAGE = Path(__file__).resolve().parent
COMMIT = '10b81df84066990c466b410d69470caab90504c6'
IMAGE = 'sha256:3e5f5aee66022082251b8cc1fb5c3ea9399ec9589ab98ba3d190a8b0ab46b387'
DOCKER = ['docker', '--host=unix:///var/run/docker.sock']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')


def inventory(path):
    return {str(p.relative_to(path)): sha(p) for p in sorted(path.rglob('*')) if p.is_file()
            and not any(x in {'__pycache__','.git','.pytest_cache','.ruff_cache'} for x in p.relative_to(path).parts)
            and p.suffix not in {'.pyc','.pyo'}}


def run(argv, output, timeout=180):
    started = time.monotonic()
    env = {k:v for k,v in os.environ.items() if k not in {'DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'}}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    result = subprocess.run(argv, env=env, capture_output=True, timeout=timeout)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix('.stdout.txt').write_bytes(result.stdout)
    output.with_suffix('.stderr.txt').write_bytes(result.stderr)
    save(output, {'argv':[str(x) for x in argv], 'returncode':result.returncode,
                  'wall_seconds':time.monotonic()-started, 'model_calls':0,
                  'timing_scope':'correctness/setup only; no performance conclusion'})
    assert result.returncode == 0, str(output)
    return result.stdout


def chown(path):
    for p in [path,*path.rglob('*')]:
        assert not p.is_symlink()
        os.chown(p,65534,65534)


def docker(workspace, memory, source, adapter, extra, command):
    argv = [*DOCKER,'run','--rm','--pull=never','--network=none','--user','65534:65534','--cap-drop=ALL',
            '--security-opt=no-new-privileges','--read-only','--memory=2g','--cpus=2','--pids-limit=256',
            '--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--workdir','/',
            '--env','PYTHONPATH=/opt/memory-adapter:/opt/cami-src:/opt/cami-deps',
            '--env','PYTHONSAFEPATH=1','--env','PYTHONDONTWRITEBYTECODE=1']
    mounts = [(workspace,'/workspace',False),(memory,'/memory',False),(source,'/opt/cami-src',True),(adapter,'/opt/memory-adapter',True),*extra]
    for host,guest,readonly in mounts:
        argv += ['--mount',f'type=bind,src={host},dst={guest}' + (',readonly' if readonly else '')]
    return [*argv,'--entrypoint','python',IMAGE,*command]


def main():
    out = STAGE/'execution-v1'
    out.mkdir(exist_ok=False)
    status = {'status':'started','real_model_calls':0,'auth_reads_or_transfers':0,'commit':COMMIT,'image':IMAGE,'arms':[]}
    try:
        assert subprocess.check_output(['git','-C',str(ROOT),'rev-parse','10b81df^{commit}'],text=True).strip() == COMMIT
        raw = subprocess.check_output(['git','-C',str(ROOT),'archive','--format=tar',COMMIT,'src','integrations/opencode'])
        (out/'runtime-source.tar').write_bytes(raw)
        frozen = out/'frozen'
        frozen.mkdir()
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            for member in archive.getmembers():
                path = Path(member.name)
                assert not path.is_absolute() and '..' not in path.parts and (member.isdir() or member.isfile())
                target = frozen/path
                if member.isdir():
                    target.mkdir(parents=True,exist_ok=True)
                else:
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
                    target.chmod(member.mode)
        entries = subprocess.check_output(['git','-C',str(ROOT),'ls-tree','-rz',COMMIT,'--','src','integrations/opencode'])
        git_inventory = {}
        for entry in entries.split(b'\0'):
            if not entry:
                continue
            header,name = entry.split(b'\t',1)
            mode,kind,oid = header.decode().split()
            assert kind == 'blob' and mode in {'100644','100755'}
            name = name.decode()
            data = (frozen/name).read_bytes()
            assert hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest() == oid
            git_inventory[name] = {'mode':mode,'oid':oid,'sha256':sha(frozen/name)}
        save(out/'git-runtime-inventory.json',git_inventory)
        helper_pins = {}
        names = [p for p in (ROOT/'scripts/opencode_benchmark/harness').glob('*.py')]
        names += [ROOT/'scripts/opencode_benchmark/harness/boundary-sentinel.txt',
                  ROOT/'scripts/opencode_benchmark/controller/literal_stdio_worker.py']
        for path in names:
            name = str(path.relative_to(ROOT))
            expected = subprocess.check_output(['git','-C',str(ROOT),'show',COMMIT+':'+name])
            assert path.read_bytes() == expected
            helper_pins[name] = sha(path)
        save(out/'installed-helper-pins.json',helper_pins)
        source,adapter = frozen/'src',frozen/'integrations/opencode'
        runtime = {'image_id':IMAGE,'binary_sha256':sha(Path('/root/.opencode/bin/opencode')),
                   'cami_files':inventory(source),'adapter_files':inventory(adapter)}
        assert runtime['binary_sha256'] == '8d060e1d2fbb9bb44cf09ae6ed1f3f6a7cff070b5227e2f90970132b23a92050'
        save(out/'runtime-manifest.json',runtime)
        sys.path.insert(0,str(ROOT/'scripts/opencode_benchmark/harness'))
        from container_session import configuration
        catalogs = {}
        for arm in ['plain','static','cami']:
            directory = out/arm
            directory.mkdir()
            workspace,memory = directory/'workspace',directory/'memory'
            workspace.mkdir();memory.mkdir()
            target = workspace/'src/authored_fixture/core.py'
            target.parent.mkdir(parents=True)
            target.write_text('def stable_value():\n    """Authored structural literal."""\n    return 7\n')
            for argv in [['git','init','-q',str(workspace)],['git','-C',str(workspace),'add','src'],
                         ['git','-C',str(workspace),'-c','user.email=authored@example.invalid','-c','user.name=Authored','commit','-qm','Authored structural integration fixture']]:
                subprocess.run(argv,check=True,capture_output=True)
            chown(workspace);chown(memory)
            if arm != 'plain':
                commands = [(['/opt/memory-adapter/seed_source_literals_v2.py','--repo','/workspace','--source-root','src/authored_fixture','--out','/memory/seed'],'generate'),
                            (['/opt/memory-adapter/memory_adapter.py','prepare','--backend',arm,'--repo','/workspace','--seed-spec','/memory/seed/seed-spec.json','--out','/memory/prepared']+(['--state-home','/memory/cami-state'] if arm=='cami' else []),'prepare')]
                for command,label in commands:
                    run(docker(workspace,memory,source,adapter,[],command),directory/(label+'.json'))
                catalog_path = memory/'prepared/catalog.json'
                catalog = json.loads(catalog_path.read_bytes())
                assert catalog['schema_version']==2 and len(catalog['records'])==1
                assert catalog['records'][0]['payload']['type']=='source_excerpt_equals'
                catalogs[arm] = catalog_path.read_bytes()
                probe = directory/'actual-compact-mcp'
                probe.mkdir()
                proof_state = directory/'mcp-proof-state'
                (proof_state/'evidence').mkdir(parents=True)
                config = {'server':configuration(arm,'prepared/binding.json','compact','priority')['mcp']['servers']['research_memory'],
                          'expected':catalog['records'][0],'backend':arm,'format':'compact'}
                save(probe/'config.json',config)
                chown(probe);chown(proof_state)
                worker = ROOT/'scripts/opencode_benchmark/controller/literal_stdio_worker.py'
                extra = [(probe,'/check',False),(proof_state,'/state',False),(worker,'/opt/literal_stdio_worker.py',True)]
                run(docker(workspace,memory,source,adapter,extra,['/opt/literal_stdio_worker.py','--config','/check/config.json','--out','/check/result.json']),probe/'process.json')
                assert json.loads((probe/'result.json').read_bytes())['status']=='passed'
            argv = [sys.executable,str(ROOT/'scripts/opencode_benchmark/harness/container_session.py'),
                    '--workspace',str(workspace),'--memory-dir',str(memory),'--state-dir',str(directory/'private-state'),
                    '--out',str(directory/'session'),'--arm',arm,'--no-model','--service-tier','priority',
                    '--memory-response-format','compact','--image',IMAGE,'--cami-source',str(source),
                    '--adapter-dir',str(adapter),'--runtime-manifest',str(out/'runtime-manifest.json')]
            if arm!='plain':
                argv += ['--binding-relative','prepared/binding.json']
            run(argv,directory/'session-process.json',timeout=180)
            host = json.loads((directory/'session/manifest.json').read_bytes())
            worker = json.loads((directory/'session/evidence/manifest.json').read_bytes())
            tier = json.loads((directory/'session/evidence/service-tier.json').read_bytes())
            guard = json.loads((directory/'session/publication-guard.json').read_bytes())
            assert host['status']==worker['status']==guard['status']=='passed'
            assert host['state_removed'] and not (directory/'private-state').exists()
            assert not host['model_requested'] and worker['model_session_launches']==0
            assert not (directory/'session/credential-transfer.json').exists()
            assert tier['configured']==tier['requested']=='priority' and tier['reasoning_effort']=='high' and tier['actual_served'] is None
            assert json.loads((directory/'session/runtime-identity.json').read_bytes()) == runtime
            status['arms'].append({'arm':arm,'status':'passed','model_session_launches':0,'state_removed':True,
                'runtime_identity_match':True,'configured_tier':'priority','reasoning_effort':'high',
                'actual_served':None,'actual_compact_mcp':'not_applicable' if arm=='plain' else 'passed_exact_receipt_and_literal'})
            save(out/'progress.json',status)
        assert catalogs['static']==catalogs['cami']
        for name,expected in helper_pins.items():
            assert sha(ROOT/name)==expected
        assert inventory(source)==runtime['cami_files'] and inventory(adapter)==runtime['adapter_files']
        status.update(status='passed',catalog_raw_bytes_equal=True,source_before_after_equal=True,
                      installed_helpers_unchanged=True,source_snapshot_from_requested_commit=True,
                      current_mutable_core_mounted=False,auth_import_artifacts_absent=True,
                      caveat='No model/provider tier or latency/quality conclusion; preparation/configuration/actual stdio correctness only.')
    except BaseException as error:
        status.update(status='failed_preserved',error=type(error).__name__+': '+str(error))
        raise
    finally:
        save(out/'summary.json',status)
    print(json.dumps(status))


if __name__ == '__main__':
    main()
