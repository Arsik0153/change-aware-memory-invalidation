"""Real fixed-test/replay/MCP admission of the ablation, with zero model calls."""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import full_replay_study as full
from study_common import digest, file_hashes, read, write
from study_runtime import grade, origin_memory, regression_allowance, verify_memory
from study_schema import make_study
from study_workspace import create_namespace, extract, reset
from verify_literal_containers import execute


def main():
    root = full.ROOT
    out = root / 'runs/ablation-admission'
    out.mkdir(exist_ok=False)
    spec = full.runtime(full.ABLATION_DESIGN)
    bundle = Path(spec['bundle_path'])
    controller = root / 'scripts/opencode_benchmark/controller'
    report = {'status': 'started', 'model_calls': 0, 'trials': [], 'guards': [],
              'scope': 'Gold sources used by controller-only infrastructure admission; never model input, production result memory, or performance evidence.'}
    try:
        study = make_study(bundle, 'development', Path(spec['harness']), spec['image'],
            root / 'src', root / 'integrations/opencode', controller,
            memory_response_format='readable', service_tier='priority', binary_path=root / 'bin/opencode')
        write(out / 'stdio-study.json', study)
        stdio = execute(out / 'stdio-study.json', controller, out / 'stdio')
        report['stdio_cases'] = stdio['actual_configured_stdio_cases']
        bases, golds, allowances = {}, {}, {}
        fixtures = read(bundle / 'fixture-manifest.json')['fixtures']
        for task in spec['normalized']['tasks']:
            base = out / ('base-' + task['id'])
            extract(bundle / task['archive'], base)
            bases[task['id']] = base
            allowances[task['id']], _ = regression_allowance(spec, task, base, out)
            row, = [r for r in fixtures if r['task'] == task['id'] and r['role'] == 'gold']
            if digest(bundle / row['archive']) != row['sha256']:
                raise ValueError('gold admission asset differs')
            golds[task['id']] = out / ('gold-' + task['id'])
            extract(bundle / row['archive'], golds[task['id']])
        context = json.dumps({'image': spec['image'], 'binary': spec['binary_sha256'], 'source_scope': 'src/**'},sort_keys=True)
        admission_sha = digest(out / 'stdio-study.json')
        immutable = {}
        for trial in full.schedule(spec):
            if trial['repetition'] != 1:
                continue
            task = next(t for t in spec['normalized']['tasks'] if t['id'] == trial['task'])
            namespace = out / trial['condition']
            if trial['stage'] == 1:
                create_namespace(namespace, admission_sha)
                (namespace / 'result-cache').mkdir()
            reset(namespace, bundle / task['archive'], task['archive_sha256'], admission_sha)
            workspace, memory = namespace / 'workspace', namespace / 'memory'
            directory = out / 'trials' / trial['id']
            directory.mkdir(parents=True)
            if trial['stage'] == 1 and trial['arm'] != 'plain':
                immutable[trial['condition']] = origin_memory(spec, workspace, memory, directory / 'construction', trial['arm'])
            else:
                verify_memory(spec, memory, trial['arm'], immutable.get(trial['condition']))
            candidate = directory / 'candidate'
            lookup = full.task_replay.materialize(workspace, task['prompt'], context, namespace / 'result-cache', candidate)
            hit = lookup['status'] == 'candidate_requires_grading'
            if hit != trial['expected_cache_hit']:
                raise ValueError('ablation cache schedule differs')
            if not hit:
                shutil.copytree(bases[task['id']], candidate)
                shutil.rmtree(candidate / 'src')
                shutil.copytree(golds[task['id']] / 'src', candidate / 'src')
            result = grade(spec, task, candidate, directory / 'evaluation', allowance=allowances[task['id']])
            if result['status'] != 'pass':
                raise ValueError('actual ablation candidate quality failed')
            if not hit:
                full.task_replay.record(bases[task['id']], candidate, task['prompt'], context, namespace / 'result-cache')
            report['trials'].append({'id': trial['id'], 'hit': hit, 'quality': 'pass', 'model_calls': 0})
        for condition in full.conditions(full.ABLATION_DESIGN):
            for task in spec['normalized']['tasks']:
                directory = out / 'guards' / (condition + '-' + task['id'])
                directory.mkdir(parents=True)
                cache = out / condition / 'result-cache'
                control = full.task_replay.materialize(bases[task['id']], task['prompt'], context, cache, directory / 'control')
                changed = directory / 'changed'
                shutil.copytree(bases[task['id']], changed)
                source = next(iter(sorted((changed / 'src').rglob('*.py'))))
                source.write_bytes(source.read_bytes() + b'\n# changed-input admission probe\n')
                rejected = full.task_replay.materialize(changed, task['prompt'], context, cache, directory / 'must-not-exist')
                if control['status'] != 'candidate_requires_grading' or rejected['status'] != 'miss' or (directory / 'must-not-exist').exists():
                    raise ValueError('ablation exact-input guard failed')
                report['guards'].append({'condition': condition, 'task': task['id'], 'status': 'passed'})
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        report['artifact_hashes'] = file_hashes(out)
        write(out / 'admission.json', report)
    print(json.dumps({k: report[k] for k in ('status','model_calls','stdio_cases','trials','guards')}))


if __name__ == '__main__':
    main()
