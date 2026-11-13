"""Five-block four-condition full development experiment; explicit --run only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'scripts/opencode_benchmark/controller'),
               str(ROOT / 'scripts/opencode_benchmark/analysis'), str(ROOT / 'integrations/opencode')]
from study_common import digest, read, write, file_hashes, inventory  # noqa: E402
from study_schema import normalize, runtime_files, harness_files, controller_files  # noqa: E402
from study_workspace import extract, capture, create_namespace, reset  # noqa: E402
from study_runtime import grade, regression_allowance, origin_memory, verify_memory, session  # noqa: E402
from aggregate_study import trial_tier  # noqa: E402
from aggregate_metrics import token_fields  # noqa: E402
from format_probe import read_projection  # noqa: E402
import task_replay  # noqa: E402

DESIGN = 'full-cami-result-memory-development-v2'
CONDITIONS = ('plain', 'static', 'cami', 'cami_replay')
REPETITIONS = 5
IMAGE = 'sha256:b0ac577d424f3ef181e3c4a5b188abf0ecf8a4fde0d544e55a3e825999826040'
RULES = {
    'design': DESIGN, 'maximum_model_sessions': 70, 'attempts': 80,
    'conditions': list(CONDITIONS), 'repetitions': REPETITIONS, 'sequence': ['A', 'A', 'B', 'B'],
    'cache': 'Each block/condition isolated; source memory and result memory empty initially. Only prior successful same-condition source changes may be recorded. Exact task, all workspace files/modes and external context must match. No historical solutions.',
    'success': 'All 80 operational/quality trials and telemetry complete; all10 changed-input rejection probes with successful unchanged-input controls pass; uniform provider tier on all 70 model sessions; 10 expected exact-repeat hits with no model. Candidate strictly lower four-stage token work AND pipeline wall than EACH of three comparators in EACH of five blocks (15 comparisons per metric). Missing or failed attempts prevent support.',
    'wall': 'Includes canonical reset, independent source-memory construction, guards, model/auth/cleanup, cache lookup/record/materialization, capture and fresh grading. Shared fixed-baseline preflight divided equally across20 block-condition sequences. Interleaved order; host load recorded, not a guarantee of independent host quietness.',
    'limits': 'Sol high requested priority, readable source-memory display, legacy lexical ranking. Fresh model state per call; persistent isolated memory per block/condition. 900 seconds,20 steps,1000000 token threshold. No retry, replacement, extension, pooling, heldout exposure or implementation tuning during run.',
    'scope': 'Full development replication of exact-repeat result reuse added to CAMI, compared with original plain/static/CAMI. Still two historical development tasks, not80 independent tasks or proof for arbitrary new tasks. Canonical A-to-B source change; explicit same-task changed-input rejection probes separate from timed results.',
}



def runtime():
    bundle = ROOT / 'examples/opencode_benchmark_development_v2'
    return {'image': IMAGE, 'model': 'openai/gpt-6.1-sol#high', 'bundle_kind': 'development', 'bundle_path': str(bundle),
            'normalized': normalize(bundle, 'development'), 'cami_source': str(ROOT / 'src'),
            'adapter': str(ROOT / 'integrations/opencode'),
            'harness': str(ROOT / 'scripts/opencode_benchmark/harness/container_session.py'),
            'binary_path': str(ROOT / 'bin/opencode'), 'binary_sha256': digest(ROOT / 'bin/opencode'),
            'shared_server': 'http://host.docker.internal:49374', 'reported_token_budget': 1000000,
            'memory_response_format': 'readable', 'service_tier': 'priority'}


def pins():
    return {'production': runtime_files(ROOT / 'src'), 'adapter': runtime_files(ROOT / 'integrations/opencode'),
            'harness': harness_files(ROOT / 'scripts/opencode_benchmark/harness'),
            'controller': controller_files(ROOT / 'scripts/opencode_benchmark/controller'),
            'analysis': runtime_files(ROOT / 'scripts/opencode_benchmark/analysis'),
            'runner': digest(Path(__file__)), 'binary': digest(ROOT / 'bin/opencode')}


def schedule(spec):
    result = []
    for repetition in range(1, REPETITIONS + 1):
        for stage, task in enumerate(spec['normalized']['sequence'], 1):
            offset = (repetition + stage - 2) % len(CONDITIONS)
            for condition in CONDITIONS[offset:] + CONDITIONS[:offset]:
                result.append({'id': f'r{repetition}-{condition}-s{stage}', 'condition': condition,
                    'arm': 'cami' if condition == 'cami_replay' else condition,
                    'repetition': repetition, 'stage': stage, 'task': task,
                    'expected_cache_hit': condition == 'cami_replay' and stage in (2, 4)})
    return result


def model_session(spec, trial, workspace, memory, directory, prompt):
    prompt_file = directory / 'prompt.txt'
    prompt_file.write_text(prompt)
    result = session(spec, trial, workspace, memory, prompt_file, directory / 'session')
    if result['status'] != 'passed' or (directory / 'private-state').exists():
        raise ValueError('model session incomplete or private state retained')
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


def summarize(records, shared_wall):
    blocks = []
    for repetition in range(1, REPETITIONS + 1):
        for condition in CONDITIONS:
            members = [r for r in records if r['trial']['repetition'] == repetition and r['trial']['condition'] == condition]
            complete = len(members) == 4 and all(r['status'] == 'passed' for r in members)
            blocks.append({'repetition': repetition, 'condition': condition, 'complete': complete,
                'token_work': sum(r['token_work'] for r in members) if complete else None,
                'charged_wall_seconds': shared_wall / (REPETITIONS * len(CONDITIONS)) + sum(r['wall_seconds'] for r in members) if complete else None})
    tiers = sorted({tier for r in records for tier in r.get('provider_reported_tiers', [])})
    eligible = len(records) == 80 and all(b['complete'] for b in blocks) and len(tiers) == 1
    pairs = []
    for repetition in range(1, REPETITIONS + 1):
        lookup = {b['condition']: b for b in blocks if b['repetition'] == repetition}
        for comparator in CONDITIONS[:-1]:
            pairs.append({'repetition': repetition, 'comparator': comparator,
                **{key: (lookup['cami_replay'][key] < lookup[comparator][key]
                         if lookup['cami_replay'][key] is not None and lookup[comparator][key] is not None else None)
                   for key in ('token_work', 'charged_wall_seconds')}})
    return {'rules': RULES, 'planned_attempts': 80, 'terminal_attempts': len(records),
        'model_calls': sum(r['model_calls'] for r in records), 'shared_preflight_wall_seconds': shared_wall,
        'provider_reported_tiers': tiers, 'blocks': blocks, 'pairs': pairs, 'eligible': eligible,
        'direction_supported': eligible and all(p[k] is True for p in pairs for k in ('token_work', 'charged_wall_seconds'))}


def run(freeze, out):
    protocol = read(freeze / 'protocol.json')
    if protocol['rules'] != RULES or protocol['pins'] != pins() or protocol['runtime'] != runtime():
        raise ValueError('frozen code, inputs or rules changed')
    spec = {**protocol['runtime'], 'runtime_manifest_path': str(freeze / 'runtime-manifest.json')}
    if protocol['schedule'] != schedule(spec):
        raise ValueError('schedule differs from fixed design')
    if out.exists():
        raise ValueError('new output required; no retries')
    out.mkdir()
    shutil.copy2(freeze / 'protocol.json', out / 'protocol.json')
    (out / 'namespaces').mkdir()
    (out / 'trials').mkdir()
    memory_states = {}
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
        directory = out / 'trials' / trial['id']
        directory.mkdir()
        started = time.perf_counter()
        namespace = out / 'namespaces' / f"r{trial['repetition']}-{trial['condition']}"
        cache = namespace / 'result-cache'
        result = {'trial': trial, 'status': 'failed', 'model_calls': 0}
        try:
            if protocol['pins'] != pins():
                raise ValueError('frozen implementation changed during run')
            task = next(t for t in spec['normalized']['tasks'] if t['id'] == trial['task'])
            before = bases[task['id']]
            candidate = directory / 'candidate'
            if trial['stage'] == 1:
                create_namespace(namespace, digest(freeze / 'protocol.json'))
                cache.mkdir()
            workspace, memory = namespace / 'workspace', namespace / 'memory'
            previous = memory_states.get(str(namespace))
            if trial['stage'] != 1 and (previous is None or previous['files'] != file_hashes(memory)):
                raise ValueError('persistent memory changed or predecessor unavailable')
            canonical = reset(namespace, Path(spec['bundle_path']) / task['archive'], task['archive_sha256'], digest(freeze / 'protocol.json'))
            write(directory / 'canonical-reset.json', canonical)
            if trial['stage'] == 1 and trial['arm'] != 'plain':
                immutable = origin_memory(spec, workspace, memory, directory / 'construction', trial['arm'])
            else:
                immutable = verify_memory(spec, memory, trial['arm'], previous['immutable'] if previous else None)
            if inventory(workspace, omit_git=True) != canonical['canonical_files'] or inventory(before) != canonical['canonical_files']:
                raise ValueError('canonical inputs changed during preparation')
            result['immutable_memory'] = immutable
            hit = False
            if trial['condition'] == 'cami_replay':
                lookup = task_replay.materialize(workspace, task['prompt'], context, cache, candidate)
                hit = lookup['status'] == 'candidate_requires_grading'
                write(directory / 'lookup.json', lookup)
                if hit != trial['expected_cache_hit']:
                    raise ValueError('unexpected hit/miss; frozen schedule not extended')
            result['cache_hit'] = hit
            if hit:
                tokens = dict.fromkeys(('input', 'cache_read', 'cache_write', 'output', 'reasoning'), 0)
            else:
                result['model_calls'] = 1
                tokens, result['provider_reported_tiers'] = model_session(spec, trial, workspace, memory, directory, task['prompt'])
                capture(workspace, canonical['canonical_files'], candidate)
            result['tokens'] = tokens
            result['token_work'] = sum(tokens[k] for k in ('input', 'cache_write', 'output', 'reasoning'))
            quality = grade(spec, task, candidate, directory / 'evaluation', allowance=allowances[task['id']])
            result['quality'] = quality['status']
            if quality['status'] != 'pass':
                raise ValueError('fixed quality failed')
            if trial['condition'] == 'cami_replay' and not hit:
                write(directory / 'record.json', task_replay.record(before, candidate, task['prompt'], context, cache))
            verify_memory(spec, memory, trial['arm'], immutable)
            result['status'] = 'passed'
        except Exception as error:
            result['error'] = type(error).__name__ + ': ' + str(error)
        if (namespace / 'memory').exists() and 'immutable_memory' in result:
            result['memory_files_after'] = file_hashes(namespace / 'memory')
            memory_states[str(namespace)] = {'files': result['memory_files_after'], 'immutable': result['immutable_memory']}
        result['wall_seconds'] = time.perf_counter() - started
        result['artifact_hashes'] = file_hashes(directory)
        write(directory / 'terminal.json', result)
        records.append(result)
        print(json.dumps({'event': 'terminal', 'trial': trial['id'], 'status': result['status'], 'error': result.get('error')}), flush=True)
        write(out / f'summary-{len(records):03d}.json', summarize(records, shared_wall))
    probes = []
    for rep in range(1, REPETITIONS + 1):
        cache = out / 'namespaces' / f'r{rep}-cami_replay' / 'result-cache'
        for task in spec['normalized']['tasks']:
            directory = out / 'guard-probes' / f'r{rep}-{task["id"]}'
            directory.mkdir(parents=True)
            control = task_replay.materialize(bases[task['id']], task['prompt'], context, cache, directory / 'unchanged-control')
            changed = directory / 'changed-input'
            shutil.copytree(bases[task['id']], changed)
            source = next(iter(sorted((changed / 'src').rglob('*.py'))))
            source.write_bytes(source.read_bytes() + b'\n# explicit changed-input rejection probe\n')
            result = task_replay.materialize(changed, task['prompt'], context, cache, directory / 'must-not-exist')
            probes.append({'repetition': rep, 'task': task['id'], 'status': result['status'], 'control_status': control['status'],
                           'output_absent': not (directory / 'must-not-exist').exists()})
    probe_passed = all(p['status'] == 'miss' and p['output_absent'] and p['control_status'] == 'candidate_requires_grading' for p in probes)
    write(out / 'guard-probes.json', {'scope': 'Separate correctness probes after timed attempts; not counted as agent work or performance savings',
        'passed': probe_passed, 'probes': probes})
    final = summarize(records, shared_wall)
    final['guard_probes_passed'] = probe_passed
    final['eligible'] = final['eligible'] and probe_passed
    final['direction_supported'] = final['direction_supported'] and probe_passed
    write(out / 'summary.json', final)



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
