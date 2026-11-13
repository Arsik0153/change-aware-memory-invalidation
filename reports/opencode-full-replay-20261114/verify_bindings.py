"""Additional read-only artifact bindings; never changes run or success criteria."""
from pathlib import Path
import argparse
import json
import sys
repo = Path('/Users/zhanarys/Projects/change-aware-memory-invalidation')
sys.path[:0] = [str(repo / 'scripts/opencode_benchmark/analysis'), str(repo / 'integrations/opencode')]
from aggregate_study import sha, verify_terminal
from task_replay import inventory
from format_probe import read_projection

def audit(root):
    rows = []
    for directory in sorted((root / 'trials').iterdir()):
        record, terminal_sha, count = verify_terminal(directory)
        if record['status'] != 'passed':
            rows.append({'trial': directory.name, 'status': 'failed_attempt_preserved', 'terminal_sha256': terminal_sha})
            continue
        grade = json.loads((directory / 'evaluation/report.json').read_text())
        sources = {n: r['sha256'] for n,r in inventory(directory / 'candidate/src').items()}
        if sources != grade['source_files']:
            raise ValueError('graded source differs: ' + directory.name)
        if set(grade['outcomes']) != {'acceptance', 'regression'}:
            raise ValueError('both fixed quality gates required: ' + directory.name)
        row = {'trial': directory.name, 'status': 'verified', 'terminal_sha256': terminal_sha,
               'candidate_source_files': len(sources), 'verified_artifacts': count}
        if record['model_calls']:
            session = directory / 'session'
            manifest = json.loads((session / 'manifest.json').read_text())
            if manifest['status'] != 'passed' or not manifest['state_removed']:
                raise ValueError('incomplete session: ' + directory.name)
            for name, expected in manifest['artifact_hashes'].items():
                if sha(session / name) != expected:
                    raise ValueError('session hash differs: ' + directory.name)
            messages = json.loads((session / 'evidence/messages.json').read_text())
            receipt = json.loads((session / 'evidence/native-read-bytes.json').read_text())
            projection = read_projection(messages, receipt)
            if not projection['complete']:
                raise ValueError('incomplete native reads: ' + directory.name)
            row['native_reads'] = projection
        rows.append(row)
    if len(rows) != 80:
        raise ValueError('all80 attempts required')
    return {'status':'verified','trials':rows,'scope':'Supplemental source-to-grade, session-hash and native-read binding checks. No changed outcome criterion.'}

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('run',type=Path)
    p.add_argument('out',type=Path)
    args=p.parse_args()
    args.out.write_text(json.dumps(audit(args.run),indent=2)+'\n')
