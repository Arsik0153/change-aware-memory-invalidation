"""Independent base-fails/gold-passes checks, without calling any model."""
import json
import subprocess
from study import REPORT, RUN, save

p = json.loads((REPORT / 'protocol.json').read_text())
golds = {
 'labels': '''def normalize_labels(values):
    if isinstance(values, str) and 'DEFAULT_SEPARATOR' in globals(): values = values.split(DEFAULT_SEPARATOR)
    result = []
    for value in values:
        if not isinstance(value, str): raise TypeError(value)
        value = value.strip().casefold()
        if value and value not in result: result.append(value)
    return result
''',
 'duration': '''import re
def duration_seconds(text):
    if not isinstance(text, str): raise TypeError(text)
    match = re.fullmatch(r'\\s*(\\d+(?:\\.\\d*)?|\\.\\d+)\\s*(ms|s|m)?\\s*',text)
    if not match: raise ValueError(text)
    unit = match[2] or globals().get('DEFAULT_UNIT')
    if unit is None: raise ValueError(text)
    return float(match[1]) * {'ms': .001,'s':1.,'m':60.}[unit]
'''}
results = []
for fixture in p['fixtures']:
    directory = RUN.parent / 'quality-admission' / fixture['id']
    (directory / 'src').mkdir(parents=True, exist_ok=False)
    command = ['/usr/bin/python3.12','-B',str(RUN / 'grader.py'), 'changed' if 'changed' in fixture['id'] else 'base']
    for arm in ['base','gold']:
        source = fixture['source'] if arm == 'base' else golds[fixture['id'].split('-')[0]]
        if arm == 'gold' and 'changed' in fixture['id']:
            source += '\n' + fixture['source'].split('\n')[-2] + '\n'
        (directory / 'src/solution.py').write_text(source)
        result = subprocess.run(command, cwd=directory, capture_output=True, text=True)
        (directory / (arm+'.log')).write_text(result.stdout+result.stderr)
        results.append({'fixture':fixture['id'],'arm':arm,'returncode':result.returncode})
        assert (result.returncode == 0) == (arm == 'gold'), results[-1]
save(REPORT / 'quality-admission.json', results)
