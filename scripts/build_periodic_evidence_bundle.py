"""Package complete raw periodic model/Docker runs and their exact Git source versions."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

from scripts.audit_periodic_evidence_bundle import audit

ROOT = Path(__file__).resolve().parents[1]


def build(model: Path, docker: Path, archive: Path):
    if archive.exists():
        raise FileExistsError(archive)
    payloads, components = {}, []
    for kind, folder in [('finite_model',model),('git_docker',docker)]:
        folder = folder.resolve()
        prefix = 'raw/'+kind
        record = json.loads((folder/'manifest.json').read_text())
        if record['status'] != 'complete':
            raise ValueError('Only completed runs can be bundled')
        commit = record['source_before']['git_head']
        source = 'source/'+commit+'.tar.gz'
        payloads[source] = subprocess.check_output(['git','-C',str(ROOT),'archive','--format=tar.gz',commit])
        for path in sorted(folder.rglob('*')):
            if path.is_symlink():
                raise ValueError(f'Symlink in raw run: {path}')
            if path.is_file():
                payloads[prefix+'/'+path.relative_to(folder).as_posix()] = path.read_bytes()
        components.append({'kind':kind,'prefix':prefix,'runtime_commit':commit,'source_archive':source,
            'protocol_path':'examples/behavior_dependency/'+
                ('periodic_audit_protocol.json' if kind == 'finite_model' else 'periodic_docker_protocol.json')})
        if kind == 'git_docker':
            subprocess.run(['git','-C',str(folder/'repo'),'fsck','--full'],check=True,capture_output=True)
            for row in json.loads((folder/'oracle.json').read_text())['observations']:
                actual = subprocess.check_output(['git','-C',str(folder/'repo'),'rev-parse',
                                                 row['commit']+':module.py'],text=True).strip()
                if actual != row['source_blob']:
                    raise ValueError('Git source blob identity mismatch')
    payloads['audit_bundle.py'] = (ROOT/'scripts/audit_periodic_evidence_bundle.py').read_bytes()
    payloads['README.txt'] = b'''CAMI periodic-audit raw evidence bundle\n\nContains both complete raw run directories, including the synthetic Git repository,\nall Docker stdout/outcome logs, and exact Git source archives for each runtime.\nRun: python3 audit_bundle.py PATH_TO_THIS_ZIP\nThe auditor reads the ZIP directly and does not execute bundled code or Git hooks.\n\nDocker image bytes are NOT included. Original image reference and Python version\nare frozen in raw/git_docker/protocol.json. Re-running requires that environment.\nPersisted absolute paths describe the original host; regenerate fresh runs with\nthe archived runners instead of editing the original hashed artifacts.\n\nThis is synthetic development evidence, not human annotations or main held-out\nevaluation. Hash consistency is not independent scientific review or authenticity.\nCompare the ZIP SHA-256 against the separately published delivery record.\n'''
    manifest = {'schema_version':1,'kind':'periodic_audit_complete_raw_runs',
        'container_image_included':False,'includes_synthetic_git_repository':True,
        'builder_commit':subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip(),
        'components':components,
        'artifact_sha256':{name:hashlib.sha256(data).hexdigest() for name,data in payloads.items()}}
    archive.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as zipped:
        for name,data in sorted(payloads.items()):
            zipped.writestr(name,data)
        zipped.writestr('bundle-manifest.json',json.dumps(manifest,indent=2)+'\n')
    result = audit(archive)
    # Check the original files a second time; do not certify a concurrently changing run.
    for component,folder in zip(components,(model,docker),strict=True):
        prefix = component['prefix']+'/'
        actual = {prefix+p.relative_to(folder).as_posix():p.read_bytes()
                  for p in folder.rglob('*') if p.is_file()}
        expected = {name:data for name,data in payloads.items() if name.startswith(prefix)}
        if actual != expected:
            raise ValueError('Raw run changed during bundling')
    result.update(archive=str(archive.resolve()),archive_bytes=archive.stat().st_size,
                  archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('model','docker','archive'):
        parser.add_argument('--'+name,type=Path,required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.model,args.docker,args.archive)))
