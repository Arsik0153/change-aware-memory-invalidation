"""No-model admission of sealed heldout assets, real fixed grading and original-note MCP."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import full_replay_study as full
from study_common import chown, digest, file_hashes, read, write
from study_runtime import container, grade, origin_memory
from study_workspace import create_namespace, extract, reset


def main():
    root = full.ROOT
    spec = full.runtime(full.HELDOUT_DESIGN)
    bundle = Path(spec['bundle_path'])
    out = root / 'runs/heldout-admission'
    out.mkdir(exist_ok=False)
    report = {'status': 'started', 'model_calls': 0, 'baseline_failure_allowances': {},
              'quality': [], 'mcp': [], 'environment_adaptation': 'Sealed Linux x86 CPython3.12.3 to pinned development-study Linux ARM CPython3.12.12 image, unchanged pytest8.4.2/pretend1.0.9, other package versions recorded.'}
    try:
        freeze = read(bundle / 'asset-freeze.json')
        for name, expected in freeze['asset_hashes'].items():
            if digest(bundle / name) != expected:
                raise ValueError('sealed asset differs: ' + name)
        original = read(bundle / 'tasks.json')
        old = read(bundle / 'preflight-v2/report.json')
        for task in spec['normalized']['tasks']:
            row = next(t for t in original['tasks'] if t['task_id'] == task['id'])
            directory = out / task['id']
            directory.mkdir()
            candidates = {}
            for state in ('base', 'gold'):
                archive = row[state + '_archive']
                if digest(bundle / archive['path']) != archive['sha256']:
                    raise ValueError('source archive differs')
                candidates[state] = directory / state
                extract(bundle / archive['path'], candidates[state])
            base = grade(spec, task, candidates['base'], directory / 'base-grade')
            expected_count = next(r['assertion_failure_count'] for r in old['results']
                                  if r['task_id'] == task['id'] and r['state'] == 'base')
            acceptance, regression = (base['outcomes'][k] for k in ('acceptance', 'regression'))
            for outcome in (acceptance, regression):
                if outcome['exit_code'] != 1 or outcome['counts']['errors'] or outcome['counts']['failed'] != expected_count:
                    raise ValueError('base did not reproduce sealed assertion failures')
            if set(acceptance['node_ids']['failed']) != set(regression['node_ids']['failed']):
                raise ValueError('unexpected extra base regression failures')
            report['baseline_failure_allowances'][task['id']] = regression['node_ids']['failed']
            gold = grade(spec, task, candidates['gold'], directory / 'gold-grade', allowance=regression)
            if gold['status'] != 'pass':
                raise ValueError('gold fixed acceptance/full regression failed')
            poisoned = directory / 'poisoned-base'
            shutil.copytree(candidates['base'], poisoned)
            shutil.rmtree(poisoned / 'tests')
            (poisoned / 'tests').mkdir()
            (poisoned / 'tests/test_fake.py').write_text('def test_fake(): pass\n')
            (poisoned / 'pytest.ini').write_text('[pytest]\naddopts = --ignore=tests\n')
            (poisoned / 'conftest.py').write_text('raise RuntimeError("must never load candidate hook")\n')
            (poisoned / 'src/pytest.py').write_text('raise RuntimeError("must never import candidate runner")\n')
            control = grade(spec, task, poisoned, directory / 'restoration-grade', allowance=regression)
            if control['outcomes'] != base['outcomes']:
                raise ValueError('candidate hooks/tests changed fixed grading')
            report['quality'].append({'task': task['id'], 'base_failure_count': expected_count,
                'gold': 'passed', 'restoration_control': 'passed', 'regression_collected': regression['collected']})
        sys.path.insert(0, str(root / 'scripts/opencode_benchmark/harness'))
        import container_session as harness
        controller = root / 'scripts/opencode_benchmark/controller'
        catalogs = {}
        task = spec['normalized']['tasks'][0]
        for backend in ('static', 'cami'):
            namespace = out / backend
            create_namespace(namespace, digest(bundle / 'tasks.json'))
            reset(namespace, bundle / task['archive'], task['archive_sha256'], digest(bundle / 'tasks.json'))
            workspace, memory = namespace / 'workspace', namespace / 'memory'
            origin_memory(spec, workspace, memory, namespace / 'construction', backend)
            catalogs[backend] = (memory / 'prepared/catalog.json').read_bytes()
            catalog = read(memory / 'prepared/catalog.json')
            if len(catalog['records']) != 75:
                raise ValueError('original75 note catalog differs')
            expected = next(r for r in catalog['records'] if len(json.dumps(r,sort_keys=True,ensure_ascii=True,separators=(',', ':')).encode()) <= 16384)
            for mode in ('full', 'compact', 'readable'):
                case = namespace / mode
                (case / 'evidence').mkdir(parents=True)
                server = harness.configuration(backend, 'prepared/binding.json', mode)['mcp']['servers']['research_memory']
                write(case / 'config.json', {'server': server, 'backend': backend, 'format': mode, 'expected': expected})
                chown(case)
                result = container(spec, [(workspace, '/workspace', False), (memory, '/memory', False),
                    (root / 'src', '/opt/cami-src', True), (root / 'integrations/opencode', '/opt/memory-adapter', True),
                    (controller / 'literal_stdio_worker.py', '/opt/literal_stdio_worker.py', True),
                    (controller / 'readable_receipts.py', '/opt/readable_receipts.py', True),
                    (case, '/check', False), (case / 'evidence', '/state/evidence', False)],
                    ['python', '-I', '/opt/literal_stdio_worker.py', '--config', '/check/config.json', '--out', '/check/result.json'],
                    case / 'container', timeout=180)
                if result['status'] != 'passed' or read(case / 'result.json')['status'] != 'passed':
                    raise ValueError('actual note MCP failed')
                report['mcp'].append(read(case / 'result.json'))
        if catalogs['static'] != catalogs['cami']:
            raise ValueError('static/CAMI catalogs differ')
        report['catalog_byte_parity'] = True
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        report['artifact_hashes'] = file_hashes(out)
        write(out / 'admission.json', report)
    print(json.dumps({k: report[k] for k in ('status','model_calls','quality','catalog_byte_parity')}))


if __name__ == '__main__':
    main()
