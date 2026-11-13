"""Collect and audit a terminated80-attempt run; refuses incomplete runs and reused outputs."""
from pathlib import Path
import hashlib
import json
import lzma
import shutil
import subprocess
import tarfile

REPO = Path(__file__).resolve().parents[2]
REPORT = Path(__file__).resolve().parent
EXPORT = REPO / 'runs/local-resume-20261113/heldout-v1/export'
VOLUME = 'cami-local-study-20261113'


def run(argv):
    subprocess.run([str(value) for value in argv], check=True, cwd=REPO)


def main():
    if EXPORT.exists() or (REPORT / 'evidence.tar.xz').exists():
        raise ValueError('new export/archive required; existing evidence is never overwritten')
    code = '''from pathlib import Path
import hashlib,json,lzma,tarfile,shutil
root=Path('/data/runtime-v14/runs/full-model')
report=Path('/report')
summary=json.loads((root/'summary.json').read_bytes())
if summary['terminal_attempts']!=80 or len(list((root/'trials').glob('*/terminal.json')))!=80:
    raise ValueError('all80 terminal attempts required')
if list(root.rglob('private-state')):
    raise ValueError('private state retained; do not export')
if (root/'protocol.json').read_bytes()!=(report/'protocol.json').read_bytes():
    raise ValueError('frozen protocol differs')
raw=hashlib.sha256()
class Writer:
    size=0
    def __init__(self,stream):self.stream=stream
    def write(self,data):
        raw.update(data);self.size+=len(data);return self.stream.write(data)
with (report/'evidence.tar.xz').open('xb') as output:
    with lzma.LZMAFile(output,'w',preset=6) as compressed:
        writer=Writer(compressed)
        with tarfile.open(fileobj=writer,mode='w|') as tar:
            tar.add(root,arcname='full-model')
for name in ('summary.json','guard-probes.json'):shutil.copy2(root/name,report/name)
receipt={'source':'immutable runtime-v14/runs/full-model','raw_tar_sha256':raw.hexdigest(),'raw_tar_bytes':writer.size,'archive_sha256':hashlib.sha256((report/'evidence.tar.xz').read_bytes()).hexdigest(),'archive_bytes':(report/'evidence.tar.xz').stat().st_size}
(report/'archive-receipt.json').write_text(json.dumps(receipt,indent=2)+'\\n')
print(json.dumps(receipt))
'''
    run(['docker','run','--rm','--mount',f'type=volume,src={VOLUME},dst=/data',
         '--mount',f'type=bind,src={REPORT},dst=/report','cami-controller:local-20261113','-c',code])
    receipt = json.loads((REPORT / 'archive-receipt.json').read_text())
    raw = hashlib.sha256()
    with lzma.open(REPORT / 'evidence.tar.xz', 'rb') as stream:
        while data := stream.read(1024 * 1024):
            raw.update(data)
    if raw.hexdigest() != receipt['raw_tar_sha256']:
        raise ValueError('compressed archive does not reproduce original tar bytes')
    EXPORT.mkdir()
    with tarfile.open(REPORT / 'evidence.tar.xz') as archive:
        archive.extractall(EXPORT, filter='data')
    root = EXPORT / 'full-model'
    for source, target in [('heldout-driver-v14.jsonl','driver.jsonl'),('heldout-host-load-v14.jsonl','host-load.jsonl')]:
        shutil.copy2(REPO / 'runs/local-resume-20261113' / source, REPORT / target)
    python = REPO / '.venv-local/bin/python'
    run([python, REPO / 'scripts/opencode_benchmark/analysis/full_replay_audit.py', '--run', root, '--out', REPORT / 'audit.json'])
    run([python, REPORT / 'verify_bindings.py', root, REPORT / 'binding-audit.json'])
    run([python, REPORT / 'account_all_attempts.py', root, REPORT / 'all-attempt-accounting.json'])
    run([python, REPORT / 'audit_note_usage.py', root, REPORT / 'note-usage-audit.json'])
    run([python, REPO / 'reports/session-20261114/audit_physical_guards.py', root, REPORT / 'physical-guard-audit.json'])
    audit = json.loads((REPORT / 'audit.json').read_text())
    if audit['eligible']:
        run([python, REPORT / 'analyze_accounting.py', root, REPORT])
        run([python, REPO / 'reports/opencode-full-replay-20261114/audit_token_components.py', '--run', root, '--out', REPORT / 'token-components-audit.json'])
    run([python, REPORT / 'render_results.py', REPORT / 'audit.json', REPORT])
    print(json.dumps({key: audit[key] for key in ('status','eligible','direction_supported')}))


if __name__ == '__main__':
    main()
