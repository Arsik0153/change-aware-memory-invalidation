"""Actual Linux MCP admission for schema3: fresh, both legacy versions, old-reader refusal."""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import zlib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, required=True)
    args = parser.parse_args()
    root = args.runtime_root.resolve()
    controller = root / 'scripts/opencode_benchmark/controller'
    sys.path[:0] = [str(controller), str(root / 'scripts/opencode_benchmark/harness')]
    import study_common as common
    import study_runtime as runtime
    import study_workspace as workspace
    from study_schema import make_study
    from verify_literal_containers import execute
    import container_session as harness

    out = root / 'runs/compression-admission'
    out.mkdir(exist_ok=False)
    study = make_study(root / 'examples/opencode_benchmark_development_v2', 'development',
        root / 'scripts/opencode_benchmark/harness/container_session.py',
        'sha256:b0ac577d424f3ef181e3c4a5b188abf0ecf8a4fde0d544e55a3e825999826040',
        root / 'src', root / 'integrations/opencode', controller, memory_response_format='readable',
        service_tier='priority', binary_path=root / 'bin/opencode')
    common.write(out / 'study.json', study)
    execute(out / 'study.json', controller, out / 'stdio')
    fresh = next((out / 'stdio/cami/memory').rglob('memory.sqlite3'))
    with sqlite3.connect(f'file:{fresh}?mode=ro', uri=True) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 3
    legacy = {
        1: root.parent / 'runtime-v9/runs/full-model/namespaces/r1-cami/memory',
        2: root.parent / 'runtime-v11/runs/path-mcp/r1-cami/candidate/memory',
    }
    checked = []
    for version, original in legacy.items():
        original_hashes = common.file_hashes(original)
        namespace = out / f'legacy-{version}'
        study_sha = common.digest(out / 'study.json')
        workspace.create_namespace(namespace, study_sha)
        task = study['normalized']['tasks'][1]
        workspace.reset(namespace, Path(study['bundle_path']) / task['archive'], task['archive_sha256'], study_sha)
        shutil.copytree(original, namespace / 'memory', dirs_exist_ok=True)
        copy_db = next((namespace / 'memory').rglob('memory.sqlite3'))
        with sqlite3.connect(f'file:{copy_db}?mode=ro', uri=True) as db:
            assert db.execute('PRAGMA user_version').fetchone()[0] == version
            generations = db.execute('SELECT id,value FROM memory_generation').fetchall()
        catalog = common.read(namespace / 'memory/prepared/catalog.json')
        expected = next(row for row in catalog['records']
            if row['source']['path'] not in ('src/click/core.py', 'src/click/decorators.py', 'src/click/__init__.py')
            and len(json.dumps(row, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()) <= 16384)
        case = namespace / 'probe'
        (case / 'evidence').mkdir(parents=True)
        server = harness.configuration('cami', 'prepared/binding.json', 'readable')['mcp']['servers']['research_memory']
        common.write(case / 'config.json', {'server': server, 'backend': 'cami', 'format': 'readable', 'expected': expected})
        common.chown(namespace)
        mounts = [(namespace / 'workspace', '/workspace', False), (namespace / 'memory', '/memory', False),
            (root / 'src', '/opt/cami-src', True), (root / 'integrations/opencode', '/opt/memory-adapter', True),
            (controller / 'literal_stdio_worker.py', '/opt/literal_stdio_worker.py', True),
            (controller / 'readable_receipts.py', '/opt/readable_receipts.py', True),
            (case, '/check', False), (case / 'evidence', '/state/evidence', False)]
        result = runtime.container(study, mounts, ['python', '-I', '/opt/literal_stdio_worker.py',
            '--config', '/check/config.json', '--out', '/check/result.json'], case / 'container', timeout=180)
        assert result['status'] == 'passed' and common.read(case / 'result.json')['status'] == 'passed'
        with sqlite3.connect(f'file:{copy_db}?mode=ro', uri=True) as db:
            assert db.execute('PRAGMA user_version').fetchone()[0] == 3
            for ident, original_raw in generations:
                stored = db.execute('SELECT value FROM memory_generation WHERE id=?', (ident,)).fetchone()[0]
                codec, length, body = stored.split(':', 2)
                assert codec == 'cami-json-zlib/1' and int(length) == len(original_raw.encode())
                decoder = zlib.decompressobj()
                raw = decoder.decompress(base64.b64decode(body, validate=True), int(length) + 1)
                assert raw == original_raw.encode() and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
        assert common.file_hashes(original) == original_hashes
        checked.append({'legacy_schema': version, 'schema': 3, 'status': 'passed',
                        'preserved_generations': len(generations), 'original_files_unchanged': True})
    rejection = out / 'old-reader'
    rejection.mkdir()
    code = '''import json,sys
from pathlib import Path
from cami.errors import IncompleteError
from cami.product.memory.store import MemoryStore
try:
    with MemoryStore(Path(sys.argv[1])).observation_connection():
        raise AssertionError('old reader accepted schema3')
except IncompleteError as error:
    assert 'memory_schema_error' in str(error), str(error)
    print(json.dumps({'status':'rejected','schema':3,'model_calls':0}))
'''
    relative = copy_db.parent.relative_to(namespace / 'memory')
    before_rejection = common.file_hashes(namespace / 'memory')
    result = runtime.container(study, [
        (namespace / 'memory', '/memory', False),
        (root.parent / 'runtime-v11/src', '/opt/cami-src', True)],
        ['python', '-c', code, '/memory/' + str(relative)], rejection / 'container', timeout=60)
    assert result['status'] == 'passed'
    assert json.loads(common.read(rejection / 'container/work.json')['stdout'])['status'] == 'rejected'
    assert common.file_hashes(namespace / 'memory') == before_rejection
    common.write(out / 'admission.json', {'status': 'passed', 'model_calls': 0, 'fresh_mcp_cases': 6,
        'legacy_mcp_cases': checked, 'old_reader_refused_schema3': True,
        'scope': 'Real Docker MCP fresh and migrated stores; exact historic JSON and original files preserved. '
                 'Actual prior schema2 reader refuses schema3. Correctness only, no timing claim.'})
    print(json.dumps(common.read(out / 'admission.json')))


if __name__ == '__main__':
    main()
