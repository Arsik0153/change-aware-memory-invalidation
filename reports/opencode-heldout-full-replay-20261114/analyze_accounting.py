"""Supplemental accounting and physical guard checks; no changed success rule."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'integrations/opencode'))
from task_replay import inventory  # noqa: E402


def analyze(root, report):
    primary = json.loads((report / 'audit.json').read_text())
    bindings = {r['trial']: r for r in json.loads((report / 'binding-audit.json').read_text())['trials']}
    components = ('input', 'cache_read', 'cache_write', 'output', 'reasoning')
    totals = {c: {'tokens': dict.fromkeys(components, 0), 'model_calls': 0, 'native_read_bytes': 0,
        'memory_lookup_calls': 0, 'memory_lookup_errors': 0, 'no_lookup_model_trials': [],
        'backend_wall_seconds': 0, 'session_wall_seconds': 0, 'result_cache_bytes': 0, 'source_memory_bytes': 0}
        for c in ('plain', 'static', 'cami', 'cami_replay')}
    hit_times = []
    for directory in sorted((root / 'trials').iterdir()):
        r = json.loads((directory / 'terminal.json').read_text())
        if r['status'] != 'passed':
            raise ValueError('complete successful run required for supplemental accounting')
        condition = r['trial']['condition']
        t = totals[condition]
        t['model_calls'] += r['model_calls']
        for component in components:
            t['tokens'][component] += r['tokens'][component]
        if not r['model_calls']:
            hit_times.append(r['wall_seconds'])
            continue
        t['native_read_bytes'] += bindings[directory.name]['native_reads']['bytes']
        session = directory / 'session'
        t['session_wall_seconds'] += json.loads((session / 'manifest.json').read_text())['total_host_wall_seconds']
        trace = session / 'evidence/memory-backend-trace.jsonl'
        events = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
        lookups = [e for e in events if e.get('event') == 'memory_lookup']
        t['memory_lookup_calls'] += len(lookups)
        t['memory_lookup_errors'] += sum(e.get('error') is not None for e in lookups)
        if condition != 'plain' and not lookups:
            t['no_lookup_model_trials'].append(directory.name)
        t['backend_wall_seconds'] += sum(e['wall_seconds'] for e in events if e.get('event') in ('server_start', 'memory_lookup'))
    for namespace in (root / 'namespaces').iterdir():
        condition = namespace.name.split('-', 1)[1]
        for field, folder in [('result_cache_bytes', 'result-cache'), ('source_memory_bytes', 'memory')]:
            totals[condition][field] += sum(p.stat().st_size for p in (namespace / folder).rglob('*') if p.is_file())
    protocol = json.loads((root / 'protocol.json').read_text())
    sequence = protocol['runtime']['normalized']['sequence']
    physical_probes = []
    for rep in range(1, 6):
        for task in set(sequence):
            p = root / 'guard-probes' / f'r{rep}-{task}'
            base = root / ('base-' + task)
            original, changed = inventory(base), inventory(p / 'changed-input')
            source = next(iter(sorted((base / 'src').rglob('*.py'))))
            relative = str(source.relative_to(base))
            expected = {**original, relative: {**original[relative],
                'sha256': hashlib.sha256(source.read_bytes() + b'\n# explicit changed-input rejection probe\n').hexdigest()}}
            # inventory also records size, so compare the physical bytes and path/mode sets directly.
            assert (p / 'changed-input' / relative).read_bytes() == source.read_bytes() + b'\n# explicit changed-input rejection probe\n'
            assert original.keys() == changed.keys()
            assert all(changed[k] == original[k] for k in original if k != relative)
            assert changed[relative]['sha256'] == expected[relative]['sha256']
            assert changed[relative]['mode'] == original[relative]['mode']
            stage = sequence.index(task) + 1
            learned = root / 'trials' / f'r{rep}-cami_replay-s{stage}' / 'candidate/src'
            assert inventory(p / 'unchanged-control/src') == inventory(learned)
            assert not (p / 'must-not-exist').exists()
            physical_probes.append({'repetition': rep, 'task': task, 'status': 'verified'})
    comparisons = {}
    for comparator in ('plain', 'static', 'cami'):
        comparisons[comparator] = {}
        for metric in ('token_work', 'charged_wall_seconds'):
            before = primary['statistics'][comparator][metric]
            after = primary['statistics']['cami_replay'][metric]
            reductions = [100 * (1 - a / b) for a, b in zip(after['values'], before['values'])]
            comparisons[comparator][metric] = {'reduction_of_medians_percent': 100 * (1 - after['median'] / before['median']),
                'paired_reduction_percent': {'median': statistics.median(reductions), 'min': min(reductions), 'max': max(reductions), 'values': reductions}}
    return {'status': 'verified', 'totals': totals, 'comparisons': comparisons, 'physical_guard_probes': physical_probes,
        'hit_wall_seconds': {'median': statistics.median(hit_times), 'min': min(hit_times), 'max': max(hit_times), 'values': hit_times},
        'scope': 'Token components are not monetary billing. Backend spans exclude process imports/JSON-RPC/trace append, so their share is not a whole-adapter CPU profile. Timed trial wall ends before terminal hashing/publication and final analysis; shared baseline preflight is charged equally. Physical guards verify output absence, exact changed bytes, and positive-control source identity.'}

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('run', type=Path)
    p.add_argument('report', type=Path)
    a = p.parse_args()
    result = analyze(a.run, a.report)
    (a.report / 'accounting.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('status', 'comparisons', 'hit_wall_seconds')}))
