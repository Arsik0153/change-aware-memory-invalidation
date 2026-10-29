"""Container-only observation of the single frozen pytest parent function probe."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import runpy
import sys
import traceback

PROBE_SHA256 = '609844de252a2ed01c153c8862703c6d492376de668033f56cac82b4aaa820f8'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    result = {'schema_version': 1, 'execution_mode': 'direct_frozen_function',
              'python_version': sys.version.split()[0], 'status': 'technical_error',
              'python_flags': {'isolated': sys.flags.isolated, 'optimize': sys.flags.optimize,
                               'dont_write_bytecode': sys.flags.dont_write_bytecode},
              'module_origins': {}, 'target': None}
    try:
        if result['python_flags'] != {'isolated': 1, 'optimize': 0, 'dont_write_bytecode': 1}:
            raise RuntimeError('Requires isolated Python with assertions enabled and bytecode writes disabled')
        result['dependencies'] = {name: importlib.metadata.version(name) for name in ('attrs', 'py')}
        preloaded = [n for n in sys.modules if n in ('pytest', '_pytest') or n.startswith(('_pytest.', 'pytest.'))]
        result['preloaded_framework_modules'] = sorted(preloaded)
        if preloaded:
            raise RuntimeError('Framework was imported before target source paths')
        probe = Path('/probe/test_frozen_probe.py')
        result['probe_sha256'] = sha(probe)
        if result['probe_sha256'] != PROBE_SHA256:
            raise RuntimeError('Frozen probe bytes changed')
        sys.path[0:0] = ['/repo/src', '/repo']
        namespace = runpy.run_path(str(probe))
        target = namespace['safe_getattr']
        module = sys.modules['_pytest.compat']
        target_path = Path(module.__file__).resolve()
        result['target'] = {'path': str(target_path), 'sha256': sha(target_path),
                            'function_filename': str(Path(target.__code__.co_filename).resolve())}
        if target_path != Path('/repo/src/_pytest/compat.py') or result['target']['function_filename'] != str(target_path):
            raise RuntimeError('Target function did not load from the mounted parent')
        try:
            namespace['test_frozen_case']()
        except AssertionError:
            result['status'] = 'assertion_failed'
            result['traceback'] = traceback.format_exc()
        else:
            result['status'] = 'returned'
    except Exception as error:
        result.update(status='technical_error', error_type=type(error).__name__, error=str(error),
                      traceback=traceback.format_exc())
    try:
        for name, module in sorted(tuple(sys.modules.items())):
            if name == '_pytest' or name.startswith('_pytest.'):
                path = Path(module.__file__).resolve()
                if not path.is_relative_to('/repo'):
                    raise RuntimeError(f'Mixed target import: {name} from {path}')
                result['module_origins'][name] = {'path': str(path), 'sha256': sha(path)}
    except Exception as error:
        result.update(status='technical_error', error_type=type(error).__name__, error=str(error),
                      traceback=traceback.format_exc())
    print('CAMI_FUNCTION_RESULT=' + json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
