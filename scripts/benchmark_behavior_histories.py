"""Measure the frozen synthetic histories, auditing actual probe work outside timing."""
from __future__ import annotations

import argparse
from collections import Counter
import os
from pathlib import Path
import platform
import pstats
import statistics
import subprocess
import sys
import time

from cami.artifacts import file_hash, read_json, read_jsonl, reserve, write_json
from scripts.check_behavior_history import create_fixture, git, prepare_inputs, verify_run
from scripts.verify_cami import source_snapshot

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'examples/behavior_dependency/timing_protocol.json'


def audit_probes(run: Path, python_version: str) -> dict:
    records = read_jsonl(run / 'preflight_validations.jsonl') + read_jsonl(run / 'validations.jsonl')
    counts, durations = Counter(), []
    for result in records:
        assert result['test_executions'] == len(result['logs']) == 3
        assert result['verdict'] in {'supported', 'contradicted'} and not result['cache_hit']
        wanted = 'passed' if result['verdict'] == 'supported' else 'assertion_failure'
        for log in result['logs']:
            path = run / log
            markers = [line.removeprefix('CAMI_RESULT=') for line in path.read_text().splitlines()
                       if line.startswith('CAMI_RESULT=')]
            assert len(markers) == 1
            import json
            payload = json.loads(markers[0])
            assert payload['python_version'] == python_version
            assert payload['collected'] == ['test_behavior.py::test_f']
            reports = payload['reports']
            assert len(reports) == 3 and {r['when'] for r in reports} == {'setup', 'call', 'teardown'}
            assert all(r['nodeid'] == 'test_behavior.py::test_f' for r in reports)
            assert all(r['outcome'] == 'passed' for r in reports if r['when'] != 'call')
            call, = [r for r in reports if r['when'] == 'call']
            if wanted == 'passed':
                assert payload['exit_code'] == 0 and call['outcome'] == 'passed'
            else:
                assert payload['exit_code'] == 1 and call['outcome'] == 'failed' and call['assertion']
            outcome = read_json(path.with_suffix('.json'))
            assert outcome['outcome'] == wanted
            assert outcome['fingerprint'] == call['fingerprint']
            counts[wanted] += 1
            durations.append(outcome['duration_seconds'])
    return {'outcomes': dict(counts), 'executions': sum(counts.values()),
            'docker_subprocess_seconds': sum(durations), 'per_probe_seconds': durations}


def distribution(values: list[float]) -> dict:
    return {'median': statistics.median(values), 'min': min(values), 'max': max(values),
            'values': values}


def summarize(rows: list[dict], plan: dict) -> dict:
    groups, paired = {}, {}
    for history in plan['histories']:
        name = history['id']
        baseline = {r['repeat']: r for r in rows if r['history'] == name and r['variant'] == 'all_validate'}
        for variant in plan['variants']:
            subset = sorted((r for r in rows if r['history'] == name and r['variant'] == variant),
                            key=lambda r: r['repeat'])
            key = f'{name}/{variant}'
            groups[key] = {'repetitions': len(subset),
                **{field: distribution([r[field] for r in subset]) for field in
                   ('cli_wall_seconds', 'maintenance_wall_seconds', 'validation_seconds',
                    'host_cpu_seconds', 'index_seconds', 'selection_seconds', 'probe_wall_fraction')},
                'executions': [r['probe_audit']['executions'] for r in subset],
                'availability_mismatches': [r['verified']['availability_mismatches'] for r in subset]}
            if variant != 'all_validate':
                paired[key] = {
                    'cli_seconds_variant_minus_all': distribution([
                        r['cli_wall_seconds'] - baseline[r['repeat']]['cli_wall_seconds'] for r in subset]),
                    'cli_ratio_variant_over_all': distribution([
                        r['cli_wall_seconds'] / baseline[r['repeat']]['cli_wall_seconds'] for r in subset])}
    counts = Counter()
    for row in rows:
        counts.update(row['probe_audit']['outcomes'])
    return {'measured_runs': len(rows), 'groups': groups, 'paired': paired,
            'measured_probe_outcomes': dict(counts), 'measured_probe_executions': sum(counts.values()),
            'limits': plan['limits']}


def run(out: Path) -> None:
    before = source_snapshot(ROOT)
    assert not before['source_status'], 'Commit source before benchmarking'
    plan, plan_hash = read_json(PLAN), file_hash(PLAN)
    for history in plan['histories']:
        assert file_hash(ROOT / history['protocol']) == history['protocol_sha256']
    reserve(out)
    write_json(out / 'protocol.json', plan)
    host = {'platform': platform.platform(), 'python': sys.version,
            'logical_cpus': os.cpu_count(), 'available_cpus': len(os.sched_getaffinity(0)),
            'load_before': os.getloadavg(),
            'docker_version': subprocess.check_output(['docker', 'version', '--format', '{{.Server.Version}}'], text=True).strip(),
            'running_containers_before': subprocess.check_output(
                ['docker', 'ps', '--format', '{{.ID}} {{.Image}} {{.Status}}'], text=True).splitlines()}
    write_json(out / 'host.json', host)
    manifest = {'status': 'preparing', 'source_before': before, 'protocol_sha256': plan_hash,
                'completed_runs': 0, 'includes_independent_human_labels': False}
    rows, prepared = [], {}

    def save() -> None:
        write_json(out / 'measurements.json', rows)
        write_json(out / 'manifest.json', manifest)

    save()
    try:
        for entry in plan['histories']:
            base = out / 'inputs' / entry['id']
            base.mkdir(parents=True)
            history = read_json(ROOT / entry['protocol'])
            write_json(base / 'protocol.json', history)
            parent, children, observations = create_fixture(base, history)
            configs = prepare_inputs(base, history, parent, children, observations)
            prepared[entry['id']] = history, parent, children, observations, configs
        manifest['input_hashes'] = {str(p.relative_to(out)): file_hash(p)
            for p in (out / 'inputs').rglob('*') if p.is_file() and 'repo' not in p.relative_to(out).parts}

        def execute(job: dict, *, profile: bool = False) -> dict:
            history, parent, children, observations, configs = prepared[job['history']]
            name = 'profile' if profile else f"{job['repeat']:02d}-{job['history']}-{job['variant']}"
            target = out / 'runs' / name
            command = [sys.executable]
            if profile:
                command += ['-m', 'cProfile', '-o', str(out / 'profile.pstats')]
            command += ['-m', 'cami.cli', 'run', '--config', str(configs[job['variant']]), '--out', str(target)]
            write_json(out / (name + '.command.json'), command)
            load_before = os.getloadavg()
            started = time.perf_counter()
            try:
                process = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=600)
            except subprocess.TimeoutExpired as exc:
                (out / (name + '.stdout.log')).write_bytes(exc.stdout or b'')
                (out / (name + '.stderr.log')).write_bytes(exc.stderr or b'')
                raise
            elapsed = time.perf_counter() - started
            (out / (name + '.stdout.log')).write_bytes(process.stdout)
            (out / (name + '.stderr.log')).write_bytes(process.stderr)
            assert process.returncode == 0, (name, process.returncode)
            variant, = [v for v in history['variants'] if v['id'] == job['variant']]
            verified = verify_run(target, variant, children, observations, parent, history)
            audit = audit_probes(target, history['environment']['python_version'])
            costs = read_jsonl(target / 'costs.jsonl')
            assert audit['executions'] == sum(c['test_executions'] for c in costs)
            assert 0 < audit['docker_subprocess_seconds'] <= elapsed
            return {**job, 'run': str(target.relative_to(out)), 'profiled': profile,
                'cli_wall_seconds': elapsed,
                'maintenance_wall_seconds': sum(c['wall_seconds'] for c in costs if c['phase'] == 'maintenance'),
                'validation_seconds': sum(c['actual_validation_seconds'] for c in costs),
                'host_cpu_seconds': sum(c['cpu_seconds'] for c in costs),
                'index_seconds': sum(c['index_seconds'] for c in costs),
                'selection_seconds': sum(c['selection_seconds'] for c in costs),
                'probe_wall_fraction': audit['docker_subprocess_seconds'] / elapsed,
                'load_before': load_before, 'load_after': os.getloadavg(),
                'probe_audit': audit, 'verified': verified}

        manifest['status'] = 'profiling'
        save()
        profiled = execute(plan['profile'], profile=True)
        assert profiled['probe_audit']['executions'] == plan['profile']['expected_probe_executions']
        write_json(out / 'profile-run.json', profiled)
        stats = pstats.Stats(str(out / 'profile.pstats'))
        functions = [{'file': key[0], 'line': key[1], 'function': key[2],
                      'calls': value[1], 'own_seconds': value[2], 'cumulative_seconds': value[3]}
                     for key, value in stats.stats.items()]
        write_json(out / 'profile-functions.json', sorted(functions, key=lambda r: r['cumulative_seconds'], reverse=True)[:40])
        manifest['status'] = 'measuring'
        save()
        for job in plan['schedule']:
            rows.append(execute(job))
            manifest['completed_runs'] = len(rows)
            save()
            print(f"Completed {len(rows)}/{plan['measured_runs']}: {job}", flush=True)
        summary = summarize(rows, plan)
        write_json(out / 'summary.json', summary)
        assert len(rows) == plan['measured_runs']
        assert summary['measured_probe_executions'] == plan['expected_measured_probe_executions']
        assert all(g['repetitions'] == plan['repetitions'] for g in summary['groups'].values())
        assert all(file_hash(out / name) == h for name, h in manifest['input_hashes'].items())
        assert file_hash(PLAN) == plan_hash
        for entry in plan['histories']:
            assert file_hash(ROOT / entry['protocol']) == entry['protocol_sha256']
            assert git(out / 'inputs' / entry['id'] / 'repo', 'status', '--porcelain') == ''
        after = source_snapshot(ROOT)
        assert before == after
        manifest.update(status='complete', source_after=after, load_after=os.getloadavg())
    except (Exception, KeyboardInterrupt) as exc:
        manifest.update(status='failed', failure={'type': type(exc).__name__, 'message': str(exc)})
        raise
    finally:
        manifest['artifact_hashes'] = {str(p.relative_to(out)): file_hash(p) for p in sorted(out.rglob('*'))
            if p.is_file() and 'repo' not in p.relative_to(out).parts and p != out / 'manifest.json'}
        save()


if __name__ == '__main__':
    if not __debug__:
        raise SystemExit('Assertions required; do not use -O')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    run(parser.parse_args().out.resolve())
