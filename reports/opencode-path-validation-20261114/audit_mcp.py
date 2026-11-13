"""Re-read all real MCP wire responses, numeric receipts and timing arithmetic."""
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import statistics
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'scripts/opencode_benchmark/controller'))
from literal_stdio_worker import validate_response  # noqa: E402


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


root = Path(sys.argv[1]).resolve()
original_run = Path(sys.argv[3]).resolve()
protocol, summary = read(root / 'protocol.json'), read(root / 'summary.json')
assert len(protocol['cases']) == len(summary['cases']) == 10
count = 0
for case, row in zip(protocol['cases'], summary['cases'], strict=True):
    assert case['id'] == row['id'] and row['status'] == 'verified'
    original = original_run / 'namespaces' / case['id'] / 'memory'
    for name, expected_hash in case['source_files'].items():
        assert sha(original / name) == expected_hash
    original_db = next(original.rglob('memory.sqlite3'))
    with sqlite3.connect(original_db.as_uri() + '?mode=ro', uri=True) as db:
        prior = db.execute('SELECT * FROM memory_generation ORDER BY sequence').fetchall()
    for side in ('baseline', 'candidate'):
        assert len(row['samples'][side]) == 5
        generation_id = None
        for repetition in range(-1, 5):
            trial = root / case['id'] / side / ('cold' if repetition == -1 else f'warm-{repetition}')
            result = read(trial / 'result.json')
            assert result['status'] == 'passed' and result['returncode'] == 0
            config = read(trial / 'config.json')
            assert config['expected'] == case['expected']
            responses = [json.loads(line) for line in (trial / 'mcp.stdout.jsonl').read_bytes().splitlines()]
            by_id = {message.get('id'): message for message in responses}
            assert len(responses) == 3 and set(by_id) == {1, 2, 3}
            assert not any('error' in message for message in responses)
            trace = [json.loads(line) for line in (trial / 'evidence/memory-backend-trace.jsonl').read_bytes().splitlines()]
            verified = validate_response(by_id[3]['result'], case['expected'], 'cami', 'readable',
                                         trace, {'query': case['expected']['id'], 'limit': 1})
            assert all(result[key] == value for key, value in verified.items())
            lookup = [event for event in trace if event['event'] == 'memory_lookup'][0]
            assert lookup['returned_records'] == lookup['selected_records'] == 1
            assert lookup['withheld_records'] == 0 and lookup['error'] is None
            assert result['lookup_wall_seconds'] == lookup['wall_seconds']
            # This flag compares against the process-local last_generation, initially None.
            assert lookup['generation_changed'] is True
            payload = json.loads(lookup['response_audit']['full_result']['content'][0]['text'])
            if repetition == -1:
                generation_id = payload['memory_generation_id']
                assert generation_id != prior[-1][0]
            assert payload['memory_generation_id'] == generation_id
            assert result['process_wall_seconds'] > lookup['wall_seconds'] > 0
            container = read(trial / 'container/report.json')
            work = read(trial / 'container/work.json')
            assert container['status'] == 'passed' and container['cleanup_passed']
            assert work['returncode'] == 0 and not work['timeout']
            expected = row['cold'][side] if repetition == -1 else row['samples'][side][repetition]
            assert expected == result | {'container_total_wall_seconds': container['total_host_wall_seconds']}
            count += 1
        final_db = next((root / case['id'] / side / 'memory').rglob('memory.sqlite3'))
        with sqlite3.connect(final_db.as_uri() + '?mode=ro', uri=True) as db:
            generations = db.execute('SELECT * FROM memory_generation ORDER BY sequence').fetchall()
            assert generations[:-1] == prior and generations[-1][0] == generation_id
        for metric, claim in row['summary'][side].items():
            values = [sample[metric] for sample in row['samples'][side]]
            assert all(math.isfinite(value) and value > 0 for value in values)
            assert claim == {'median': statistics.median(values), 'min': min(values), 'max': max(values)}
    assert row['ranges_separated'] == (row['summary']['candidate']['process_wall_seconds']['max'] < row['summary']['baseline']['process_wall_seconds']['min'])
assert count == 120
assert summary['all_ranges_separated'] == all(row['ranges_separated'] for row in summary['cases'])
result = {'status': 'verified', 'mcp_processes': count, 'model_calls': 0,
          'summary_sha256': sha(root / 'summary.json'), 'protocol_sha256': sha(root / 'protocol.json'),
          'scope': 'All120 actual successful MCP responses, exact payload/source/status and numeric '
                   'receipt validation, one new persistent generation per namespace and '
                   'identical generation IDs across all subsequent calls, '
                   'container success and cleanup, raw timing receipts and arithmetic.'}
Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
