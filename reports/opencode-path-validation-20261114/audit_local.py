"""Audit process receipts, frozen files, output hashes and sample arithmetic."""
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts}


root = Path(sys.argv[1]).resolve()
protocol = json.loads((root / 'protocol.json').read_text())
summary = json.loads((root / 'summary.json').read_text())
assert len(protocol['cases']) == len(summary['cases']) == 10
checked = []
for case, row in zip(protocol['cases'], summary['cases'], strict=True):
    assert case['id'] == row['id'] and row['status'] == 'verified'
    source = Path(case['source'])
    assert files(source) == case['files']
    for side in ('baseline', 'candidate'):
        assert files(Path(protocol[side])) == protocol['source_files'][side]
        assert files(root / case['id'] / side / source.name) == case['files']
        assert len(row['samples'][side]) == 5
        for repetition, sample in enumerate(row['samples'][side]):
            receipt = json.loads((root / case['id'] / f'{repetition}-{side}.json').read_text())
            assert receipt['returncode'] == 0 and receipt['stderr'] == ''
            measured = json.loads(receipt['stdout'])
            assert sample == measured | {'process_wall_seconds': receipt['process_wall_seconds']}
            assert sample['output_sha256'] == case['output_sha256']
            assert sample['records'] == 329 and sample['states'] == 329
            assert sample['source_sha256'] == protocol['source_files'][side]['cami/models.py']
            if side == 'candidate':
                cache = sample['lexical_cache']
                assert 0 < cache['currsize'] <= cache['maxsize'] == 1024
                assert cache['hits'] > cache['misses'] > 0
            for metric in ('wall_seconds', 'cpu_seconds', 'process_wall_seconds'):
                assert math.isfinite(sample[metric]) and sample[metric] > 0
            assert sample['process_wall_seconds'] >= sample['wall_seconds']
        for metric, claim in row['summary'][side].items():
            values = [sample[metric] for sample in row['samples'][side]]
            assert claim == {'median': statistics.median(values), 'min': min(values), 'max': max(values)}
    for metric, separated in row['ranges_separated'].items():
        assert separated == (row['summary']['candidate'][metric]['max'] < row['summary']['baseline'][metric]['min'])
    checked.append({'id': case['id'], 'result_sha256': sha(root / case['id'] / 'result.json'),
                    'ranges_separated': row['ranges_separated']})
result = {'status': 'verified', 'model_calls': 0, 'verified_processes': 100,
          'summary_sha256': sha(root / 'summary.json'), 'cases': checked,
          'scope': 'All physical inputs and copied stores unchanged, exact public output hashes, '
                   'successful process receipts, actual record counts and lexical-cache work, '
                   'sample arithmetic and source imports pinned to each isolated version.'}
Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
