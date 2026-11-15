"""Installed-package switching contract; local child process, no provider/model calls."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from cami.opencode import task_memory, task_session
from cami.product.service import ProductMemory

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'runs/cami-v2/installed-switch'
WORK = BASE / 'work'
(WORK / 'src').mkdir(parents=True, exist_ok=False)
subprocess.run(['git', 'init', '-q', str(WORK)], check=True)
os.environ['XDG_STATE_HOME'] = str(BASE / 'legacy-state')
source = 'def add(a,b):\n    return a-b\n'
(WORK / 'src/math.py').write_text(source)
ProductMemory(WORK).context('add')


def legacy_files():
    return {str(p.relative_to(BASE)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (BASE / 'legacy-state').rglob('*') if p.is_file()}


before = legacy_files()
agent = [sys.executable, '-B', '-c', "from pathlib import Path; Path('src/math.py').write_text('def add(a,b):\\n    return a+b\\n')"]
grade = [sys.executable, '-B', '-c', "exec(open('src/math.py').read()); assert add(4,2)==6"]
rows = []
for index, mode in enumerate(['legacy','v2','legacy']):
    (WORK / 'src/math.py').write_text(source)
    state = task_memory.namespace(BASE / 'new-memory', WORK) if mode == 'v2' else None
    result = task_session.run(BASE / str(index), WORK, 'Fix add sum', 'local contract, no provider', agent, grade, v2_state=state)
    assert result['quality'] == 'pass' and result['execution'] == 'success'
    assert not result['cache_eligible'] and not result['cache_recorded']
    assert legacy_files() == before
    rows.append({'mode':mode, 'result':result})
(ROOT / 'reports/cami-v2-20261115/installed-switch.json').write_text(json.dumps({
    'module':task_session.__file__, 'module_sha256':hashlib.sha256(Path(task_session.__file__).read_bytes()).hexdigest(),
    'model_requests':0, 'kind':'local child-process contract; not a live model measurement',
    'legacy_state_unchanged':True, 'runs':rows},indent=2))
print('legacy -> v2 -> legacy: installed package, quality pass, legacy state unchanged')
