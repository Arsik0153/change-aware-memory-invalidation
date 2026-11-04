"""Frozen Git/Docker experiment for the explicitly marked research selector adapter."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import subprocess
import sys

from cami.artifacts import digest, file_hash, read_json, reserve, write_json
from scripts.benchmark_behavior_histories import audit_probes
from scripts.check_behavior_history import create_fixture, git, prepare_inputs, verify_run
from scripts.verify_cami import source_snapshot

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'examples/behavior_dependency/periodic_docker_protocol.json'


def run(out: Path) -> None:
    before = source_snapshot(ROOT)
    assert not before['source_status'], 'Commit source before execution'
    plan, plan_hash = read_json(PLAN), file_hash(PLAN)
    reserve(out)
    write_json(out / 'protocol.json',plan)
    manifest = {'status':'running','source_before':before,'protocol_sha256':plan_hash,
                'completed_runs':[], 'production_policy_changed':False,
                'independent_human_labels':False, 'evaluation_eligible':False}
    write_json(out / 'manifest.json',manifest)
    results = []
    try:
        parent, children, observations = create_fixture(out,plan)
        configs = prepare_inputs(out,plan,parent,children,observations)
        inputs = {p.relative_to(out).as_posix():file_hash(p) for p in out.rglob('*')
                  if p.is_file() and 'repo' not in p.relative_to(out).parts and p != out / 'manifest.json'}
        manifest['input_hashes'] = inputs
        write_json(out / 'manifest.json',manifest)
        variants = {v['id']:v for v in plan['variants']}
        totals = Counter()
        for name in plan['schedule']:
            variant = variants[name]
            target = out / 'runs' / name
            command = [sys.executable,'-m','scripts.periodic_audit_adapter',
                       '--config',str(configs[name]),'--out',str(target)]
            if variant['interval'] is not None:
                command.extend(['--interval',str(variant['interval'])])
            write_json(out / f'{name}.command.json',command)
            try:
                process = subprocess.run(command,cwd=ROOT,capture_output=True,timeout=600)
            except subprocess.TimeoutExpired as exc:
                (out / f'{name}.stdout.log').write_bytes(exc.stdout or b'')
                (out / f'{name}.stderr.log').write_bytes(exc.stderr or b'')
                raise
            (out / f'{name}.stdout.log').write_bytes(process.stdout)
            (out / f'{name}.stderr.log').write_bytes(process.stderr)
            assert process.returncode == 0, name
            record = read_json(target / 'manifest.json')
            adapter = record['research_adapter']
            assert not record['evaluation_eligible']
            assert adapter['history_sha256'] == digest((parent,*children))
            assert adapter['interval'] == variant['interval']
            assert adapter['override_applied'] == (variant['interval'] is not None)
            assert adapter['adapter_sha256'] == file_hash(ROOT / 'scripts/periodic_audit_adapter.py')
            verified = verify_run(target,variant,children,observations,parent,plan)
            probes = audit_probes(target,plan['environment']['python_version'])
            totals.update(probes['outcomes'])
            results.append({**verified,'interval':variant['interval'],'probe_audit':probes})
            manifest['completed_runs'].append(name)
            write_json(out / 'results.json',results)
            write_json(out / 'manifest.json',manifest)
        assert dict(totals) == plan['expected_probe_outcomes']
        assert sum(totals.values()) == plan['expected_total_probe_executions']
        assert all(file_hash(out / name) == expected for name,expected in inputs.items())
        assert file_hash(PLAN) == plan_hash
        assert not git(out / 'repo','status','--porcelain')
        assert source_snapshot(ROOT) == before
        manifest.update(status='complete',source_after=before,
                        probe_outcomes=dict(totals),probe_executions=sum(totals.values()))
    except (Exception,KeyboardInterrupt) as exc:
        manifest.update(status='failed',failure={'type':type(exc).__name__,'message':str(exc)})
        raise
    finally:
        manifest['artifact_hashes'] = {p.relative_to(out).as_posix():file_hash(p)
            for p in sorted(out.rglob('*')) if p.is_file()
            and 'repo' not in p.relative_to(out).parts and p != out / 'manifest.json'}
        write_json(out / 'manifest.json',manifest)
    print({'status':manifest['status'],'probe_executions':manifest['probe_executions']})


if __name__ == '__main__':
    if not __debug__:
        raise SystemExit('Assertions required; do not use -O')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    run(parser.parse_args().out.resolve())
