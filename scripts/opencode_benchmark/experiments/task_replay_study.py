"""Prospective empty-cache repeated-task experiment; explicit --run only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'scripts/opencode_benchmark/controller'),
               str(ROOT / 'scripts/opencode_benchmark/analysis'), str(ROOT / 'integrations/opencode')]
from study_common import digest, read, write, file_hashes, inventory  # noqa: E402
from study_schema import normalize, runtime_files, harness_files, controller_files  # noqa: E402
from study_workspace import extract, capture, create_namespace, reset  # noqa: E402
from study_runtime import grade, regression_allowance  # noqa: E402
from aggregate_study import trial_tier  # noqa: E402
from aggregate_metrics import token_fields  # noqa: E402
from format_probe import read_projection  # noqa: E402
import task_replay  # noqa: E402

DESIGN = 'exact-task-replay-development-v1'
IMAGE = 'sha256:b0ac577d424f3ef181e3c4a5b188abf0ecf8a4fde0d544e55a3e825999826040'
RULES = {
    'design': DESIGN, 'maximum_model_sessions': 6, 'attempts': 8,
    'conditions': ['plain', 'exact_replay'], 'sequence': ['A', 'A', 'B', 'B'],
    'cache': 'Empty at start; only earlier successful same-condition source outputs may be recorded. Exact task, all workspace file bytes/modes, runtime context match. No historical solution import.',
    'success': 'All eight fixed quality gates pass; both four-stage total noncached token work and end-to-end charged wall strictly lower for exact_replay. Complete telemetry and uniform complete provider tier on all model calls required. Two expected hits and two expected misses; any deviation fails admission.',
    'wall': 'Within-run descriptive measured pipeline time including extraction, grading, capture, cache fingerprinting, recording and materialization. Shared baseline preflight split equally. No population speed claim; no independent host-quietness proof.',
    'limits': 'Fresh model session on misses, Sol high requested priority, 20 steps, 900 seconds, 1000000 token threshold. No retries/replacements/extensions. Heldout unopened.',
    'scope': 'Exact repeated development tasks only. Does not establish semantic reuse across changed repositories, real-world hit rate or general CAMI superiority.',
}


def runtime():
    bundle = ROOT / 'examples/opencode_benchmark_development_v2'
    return {'image': IMAGE, 'bundle_kind': 'development', 'bundle_path': str(bundle),
            'normalized': normalize(bundle, 'development'), 'cami_source': str(ROOT / 'src'),
            'adapter': str(ROOT / 'integrations/opencode'),
            'harness': str(ROOT / 'scripts/opencode_benchmark/harness/container_session.py')}


def pins():
    return {'production': runtime_files(ROOT / 'src'), 'adapter': runtime_files(ROOT / 'integrations/opencode'),
            'harness': harness_files(ROOT / 'scripts/opencode_benchmark/harness'),
            'controller': controller_files(ROOT / 'scripts/opencode_benchmark/controller'),
            'analysis': runtime_files(ROOT / 'scripts/opencode_benchmark/analysis'),
            'runner': digest(Path(__file__)), 'binary': digest(ROOT / 'bin/opencode')}


def schedule(spec):
    result = []
    for stage, task in enumerate(spec['normalized']['sequence'], 1):
        order = RULES['conditions'] if stage % 2 else list(reversed(RULES['conditions']))
        for condition in order:
            result.append({'id': f'{condition}-s{stage}', 'condition': condition, 'stage': stage, 'task': task,
                           'expected_cache_hit': condition == 'exact_replay' and stage in (2, 4)})
    return result


def model_session(spec, workspace, directory, prompt, manifest):
    (directory / 'memory').mkdir()
    prompt_file = directory / 'prompt.txt'
    prompt_file.write_text(prompt)
    argv = [sys.executable, spec['harness'], '--workspace', str(workspace), '--memory-dir', str(directory / 'memory'),
        '--state-dir', str(directory / 'private-state'), '--out', str(directory / 'session'), '--arm', 'plain',
        '--prompt-file', str(prompt_file), '--run-model', '--runtime-manifest', str(manifest),
        '--image', spec['image'], '--cami-source', spec['cami_source'], '--adapter-dir', spec['adapter'],
        '--opencode-binary', str(ROOT / 'bin/opencode'), '--opencode-sha256', digest(ROOT / 'bin/opencode'),
        '--memory-response-format', 'readable', '--service-tier', 'priority',
        '--shared-server', 'http://host.docker.internal:49374', '--timeout-seconds', '900',
        '--reported-token-budget', '1000000']
    with (directory / 'stdout.log').open('wb') as stdout, (directory / 'stderr.log').open('wb') as stderr:
        process = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=1200)
    if process.returncode:
        raise ValueError('model harness failed; no retry')
    result = read(directory / 'session/manifest.json')
    if result['status'] != 'passed' or (directory / 'private-state').exists():
        raise ValueError('model session incomplete or private state retained')
    for name, expected in result['artifact_hashes'].items():
        if digest(directory / 'session' / name) != expected:
            raise ValueError('session artifact hash mismatch')
    evidence = directory / 'session/evidence'
    if not read_projection(read(evidence / 'messages.json'), read(evidence / 'native-read-bytes.json'))['complete']:
        raise ValueError('native read telemetry incomplete')
    tokens = token_fields(read(evidence / 'usage.json'))
    if any(value is None for value in tokens.values()):
        raise ValueError('token telemetry incomplete')
    tier = trial_tier(directory, {'terminal_present': True})
    if not tier['configuration_valid'] or not tier['provider_reported_complete']:
        raise ValueError('model tier evidence incomplete')
    return tokens, tier['provider_reported_values']


def run(freeze, out):
    protocol = read(freeze / 'protocol.json')
    if protocol['rules'] != RULES or protocol['pins'] != pins() or protocol['runtime'] != runtime():
        raise ValueError('frozen code, inputs or rules changed')
    spec = protocol['runtime']
    if protocol['schedule'] != schedule(spec):
        raise ValueError('schedule differs from fixed design')
    if out.exists():
        raise ValueError('new output required; no retries')
    out.mkdir()
    shutil.copy2(freeze / 'protocol.json', out / 'protocol.json')
    cache = out / 'cache'
    cache.mkdir()
    context = json.dumps({'image': spec['image'], 'binary': protocol['pins']['binary'], 'source_scope': 'src/**'}, sort_keys=True)
    bases, allowances = {}, {}
    started = time.perf_counter()
    for task in spec['normalized']['tasks']:
        before = out / ('base-' + task['id'])
        extract(Path(spec['bundle_path']) / task['archive'], before)
        bases[task['id']] = before
        allowances[task['id']], _ = regression_allowance(spec, task, before, out)
    shared_wall = time.perf_counter() - started
    records = []
    for trial in protocol['schedule']:
        print(json.dumps({'event': 'starting', **trial}), flush=True)
        directory = out / trial['id']
        directory.mkdir()
        started = time.perf_counter()
        result = {'trial': trial, 'status': 'failed', 'model_calls': 0}
        try:
            task = next(t for t in spec['normalized']['tasks'] if t['id'] == trial['task'])
            before = bases[task['id']]
            candidate = directory / 'candidate'
            hit = False
            if trial['condition'] == 'exact_replay':
                lookup = task_replay.materialize(before, task['prompt'], context, cache, candidate)
                hit = lookup['status'] == 'candidate_requires_grading'
                write(directory / 'lookup.json', lookup)
                if hit != trial['expected_cache_hit']:
                    raise ValueError('unexpected hit/miss; frozen schedule not extended')
            result['cache_hit'] = hit
            if hit:
                tokens = dict.fromkeys(('input', 'cache_read', 'cache_write', 'output', 'reasoning'), 0)
            else:
                namespace = directory / 'namespace'
                create_namespace(namespace, digest(freeze / 'protocol.json'))
                reset(namespace, Path(spec['bundle_path']) / task['archive'], task['archive_sha256'], digest(freeze / 'protocol.json'))
                workspace = namespace / 'workspace'
                result['model_calls'] = 1
                tokens, result['provider_reported_tiers'] = model_session(spec, workspace, directory, task['prompt'], freeze / 'runtime-manifest.json')
                canonical = inventory(before)
                capture(workspace, canonical, candidate)
            result['tokens'] = tokens
            result['token_work'] = sum(tokens[k] for k in ('input', 'cache_write', 'output', 'reasoning'))
            quality = grade(spec, task, candidate, directory / 'evaluation', allowance=allowances[task['id']])
            result['quality'] = quality['status']
            if quality['status'] != 'pass':
                raise ValueError('fixed quality failed')
            if trial['condition'] == 'exact_replay' and not hit:
                write(directory / 'record.json', task_replay.record(before, candidate, task['prompt'], context, cache))
            result['status'] = 'passed'
        except Exception as error:
            result['error'] = type(error).__name__ + ': ' + str(error)
        result['wall_seconds'] = time.perf_counter() - started
        result['artifact_hashes'] = file_hashes(directory)
        write(directory / 'terminal.json', result)
        records.append(result)
        print(json.dumps({'event': 'terminal', 'trial': trial['id'], 'status': result['status'], 'error': result.get('error')}), flush=True)
        if result['status'] != 'passed':
            break  # preserve incomplete block; no dependent fallback or replacement
    summary = {'rules': RULES, 'shared_preflight_wall_seconds': shared_wall,
               'records': records, 'planned_attempts': 8, 'model_calls': sum(r['model_calls'] for r in records)}
    blocks = {}
    for condition in RULES['conditions']:
        members = [r for r in records if r['trial']['condition'] == condition]
        complete = len(members) == 4 and all(r['status'] == 'passed' for r in members)
        blocks[condition] = {'complete': complete,
            'token_work': sum(r.get('token_work', 0) for r in members) if complete else None,
            'charged_wall_seconds': shared_wall / 2 + sum(r['wall_seconds'] for r in members) if complete else None}
    summary['blocks'] = blocks
    tiers = {tier for r in records for tier in r.get('provider_reported_tiers', [])}
    summary['provider_reported_tiers'] = sorted(tiers)
    summary['direction_supported'] = len(tiers) == 1 and all(b['complete'] for b in blocks.values()) and all(
        blocks['exact_replay'][key] < blocks['plain'][key] for key in ('token_work', 'charged_wall_seconds'))
    write(out / 'summary.json', summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if args.run:
        if args.out is None:
            parser.error('--run requires --out')
        run(args.freeze, args.out)
    else:
        args.freeze.mkdir(exist_ok=False)
        spec = runtime()
        write(args.freeze / 'protocol.json', {'rules': RULES, 'runtime': spec, 'pins': pins(), 'schedule': schedule(spec)})
        write(args.freeze / 'runtime-manifest.json', {'image_id': IMAGE, 'binary_sha256': digest(ROOT / 'bin/opencode'),
            'cami_files': runtime_files(ROOT / 'src'), 'adapter_files': runtime_files(ROOT / 'integrations/opencode')})
        print('Frozen; zero model calls')


if __name__ == '__main__':
    main()
