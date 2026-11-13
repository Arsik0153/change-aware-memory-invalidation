"""Frozen Linux MCP comparison using fresh processes and copied development stores."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import statistics
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--baseline-runtime', type=Path)
    parser.add_argument('--design', default='lexical-path-real-mcp-v1')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    root = args.runtime_root.resolve()
    controller = root / 'scripts/opencode_benchmark/controller'
    sys.path[:0] = [str(controller), str(root / 'scripts/opencode_benchmark/harness')]
    import study_common as common
    import study_runtime as runtime
    import study_workspace as workspace
    import container_session as harness

    study_path = root.parent / 'runtime-v10/runs/storage-admission/study.json'
    study = common.read(study_path)
    protocol_path = root / 'runs/path-mcp-protocol.json'
    baseline = args.baseline_runtime.resolve() if args.baseline_runtime else root.parent / 'runtime-v10'
    sides = {'baseline': baseline / 'src', 'candidate': root / 'src'}
    adapter = baseline / 'integrations/opencode'
    worker = Path(__file__).with_name('path_mcp_worker.py')
    pins = {side: common.file_hashes(path) for side, path in sides.items()}
    pins.update(adapter=common.file_hashes(adapter), worker=common.digest(worker),
                runner=common.digest(Path(__file__)), study=common.digest(study_path),
                validation=common.digest(controller / 'literal_stdio_worker.py'),
                receipts=common.digest(controller / 'readable_receipts.py'))
    if not args.run:
        cases = []
        for repetition in range(1, 6):
            for condition in ('cami', 'cami_replay'):
                name = f'r{repetition}-{condition}'
                source = root.parent / 'runtime-v9/runs/full-model/namespaces' / name / 'memory'
                catalog = common.read(source / 'prepared/catalog.json')
                expected = next(row for row in catalog['records']
                    if row['source']['path'] not in ('src/click/core.py', 'src/click/decorators.py', 'src/click/__init__.py')
                    and len(json.dumps(row, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()) <= 16384)
                cases.append({'id': name, 'source': str(source),
                              'source_files': common.file_hashes(source), 'expected': expected})
        common.write(protocol_path, {'design': args.design, 'pins': pins,
            'image': study['image'], 'cases': cases, 'repetitions_per_side': 5,
            'scope': 'Ten copied source-memory stores from two development tasks. '
                     'One initial MCP process per side includes schema1 conversion and analyzer '
                     'fingerprint recertification. Then five alternating fresh MCP processes per side '
                     'and case. Each starts with empty in-process lexical cache; OS cache uncontrolled. '
                     'Primary time spans Python process startup, initialize, list tools, one readable '
                     'lookup of a fixed valid literal ID, wire serialization, shutdown and wait. '
                     'Docker launch/cleanup is separately recorded and excluded from MCP latency. '
                     'Every actual payload, supported status, source binding and numeric trace receipt '
                     'must pass the existing independent validator. Retain all attempts, no retries. '
                     'Report medians/ranges; consistent improvement requires separated ranges in all '
                     'ten cases. No model requests or whole-agent speed claim.'})
        print(str(protocol_path))
        return

    protocol = common.read(protocol_path)
    assert pins == protocol['pins'] and args.design == protocol['design']
    out = root / 'runs/path-mcp'
    out.mkdir(exist_ok=False)
    common.write(out / 'protocol.json', protocol)
    task = study['normalized']['tasks'][1]
    results = []
    for number, case in enumerate(protocol['cases']):
        source = Path(case['source'])
        assert common.file_hashes(source) == case['source_files']
        namespaces = {}
        for side in sides:
            namespace = out / case['id'] / side
            workspace.create_namespace(namespace, pins['study'])
            reset = workspace.reset(namespace, Path(study['bundle_path']) / task['archive'],
                                    task['archive_sha256'], pins['study'])
            common.write(namespace / 'reset.json', reset)
            shutil.copytree(source, namespace / 'memory', dirs_exist_ok=True)
            namespaces[side] = namespace
        row = {'id': case['id'], 'cold': {}, 'samples': {side: [] for side in sides},
               'load_start': os.getloadavg()}
        for repetition in range(-1, 5):
            order = ('baseline', 'candidate') if (number + repetition) % 2 == 0 else ('candidate', 'baseline')
            for side in order:
                namespace = namespaces[side]
                trial = namespace / ('cold' if repetition == -1 else f'warm-{repetition}')
                (trial / 'evidence').mkdir(parents=True)
                server = harness.configuration('cami', 'prepared/binding.json', 'readable')['mcp']['servers']['research_memory']
                common.write(trial / 'config.json', {'server': server, 'expected': case['expected']})
                common.chown(namespace)
                execution = runtime.container(study, [
                    (namespace / 'workspace', '/workspace', False),
                    (namespace / 'memory', '/memory', False),
                    (sides[side], '/opt/cami-src', True), (adapter, '/opt/memory-adapter', True),
                    (controller, '/opt/controller', True), (worker, '/opt/worker.py', True),
                    (trial, '/check', False), (trial / 'evidence', '/state/evidence', False)],
                    ['python', '-I', '/opt/worker.py', '--config', '/check/config.json', '--out', '/check/result.json'],
                    trial / 'container', timeout=180)
                result = common.read(trial / 'result.json')
                assert execution['status'] == 'passed' and result['status'] == 'passed'
                result['container_total_wall_seconds'] = execution['total_host_wall_seconds']
                if repetition == -1:
                    row['cold'][side] = result
                else:
                    row['samples'][side].append(result)
        row['summary'] = {side: {
            metric: {'median': statistics.median(sample[metric] for sample in samples),
                     'min': min(sample[metric] for sample in samples),
                     'max': max(sample[metric] for sample in samples)}
            for metric in ('process_wall_seconds', 'process_cpu_seconds', 'lookup_wall_seconds')}
            for side, samples in row['samples'].items()}
        row['ranges_separated'] = row['summary']['candidate']['process_wall_seconds']['max'] < row['summary']['baseline']['process_wall_seconds']['min']
        assert common.file_hashes(source) == case['source_files']
        row['status'] = 'verified'
        common.write(out / case['id'] / 'result.json', row)
        results.append(row)
        print(json.dumps({'id': case['id'], 'summary': row['summary'],
                          'ranges_separated': row['ranges_separated']}), flush=True)
    for side, path in sides.items():
        assert common.file_hashes(path) == pins[side]
    common.write(out / 'summary.json', {'status': 'verified', 'model_calls': 0,
        'errors': 0, 'cases': results, 'scope': protocol['scope'],
        'all_ranges_separated': all(row['ranges_separated'] for row in results)})


if __name__ == '__main__':
    main()
