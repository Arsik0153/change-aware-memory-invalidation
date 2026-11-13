"""Time one complete configured MCP process, then verify actual wire/trace output."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

sys.path.insert(0, '/opt/controller')
from literal_stdio_worker import canonical, validate_response  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_bytes())
    server = config['server']
    arguments = {'query': config['expected']['id'], 'limit': 1}
    requests = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-06-18', 'capabilities': {},
            'clientInfo': {'name': 'path-validation-measurement', 'version': '1'}}},
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
         'params': {'name': 'memory_lookup', 'arguments': arguments}},
    ]
    cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    completed = subprocess.run(server['command'],
        input=b''.join(canonical(row) + b'\n' for row in requests),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=server['cwd'],
        env=dict(os.environ, **server['environment']), timeout=120, check=False)
    elapsed = time.perf_counter() - started
    end_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    args.out.parent.joinpath('mcp.stdout.jsonl').write_bytes(completed.stdout)
    args.out.parent.joinpath('mcp.stderr.log').write_bytes(completed.stderr)
    report = {'status': 'failed', 'process_wall_seconds': elapsed,
              'process_cpu_seconds': end_cpu.ru_utime + end_cpu.ru_stime - cpu.ru_utime - cpu.ru_stime,
              'returncode': completed.returncode, 'model_calls': 0}
    try:
        assert completed.returncode == 0
        responses = [json.loads(line) for line in completed.stdout.splitlines() if line]
        by_id = {row.get('id'): row for row in responses}
        assert len(responses) == 3 and set(by_id) == {1, 2, 3}
        assert not any('error' in row for row in responses)
        assert [tool['name'] for tool in by_id[2]['result']['tools']] == ['memory_lookup']
        trace = [json.loads(line) for line in Path('/state/evidence/memory-backend-trace.jsonl').read_bytes().splitlines()]
        report.update(validate_response(by_id[3]['result'], config['expected'], 'cami',
                                        'readable', trace, arguments))
        lookup = [row for row in trace if row.get('event') == 'memory_lookup'][0]
        report['lookup_wall_seconds'] = lookup['wall_seconds']
        report['status'] = 'passed'
    finally:
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
