"""One sealed, sequential 12-attempt live comparison. Refuses to repeat attempts."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'runs/cami-v2/study'
REPORT = ROOT / 'reports/cami-v2-20261115'
PYTHON = ROOT / 'runs/cami-v2/installed/bin/python'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


def freeze():
    a = 'def normalize_labels(values):\n    return list(values)\n'
    b = 'def duration_seconds(text):\n    return float(text)\n'
    a2 = a + '\nDEFAULT_SEPARATOR = ","\n'
    b2 = b + '\nDEFAULT_UNIT = "s"\n'
    tasks = [
        ('labels', a, 'Implement normalize_labels(values): accept an iterable of strings, strip whitespace, casefold, omit empty labels, deduplicate preserving first-seen order. Raise TypeError for any non-string item. Keep the API.'),
        ('duration', b, 'Implement duration_seconds(text): parse a nonnegative decimal number followed by ms, s, or m, allow outer whitespace and whitespace between number and unit. Return float seconds. Reject missing/unknown unit, negatives, NaN, infinity and malformed numbers with ValueError. Raise TypeError for non-string input.'),
    ]
    fixtures = []
    for index, (name, source, task) in enumerate(tasks):
        for similar in (False, True):
            src = (a2 if index == 0 else b2) if similar else source
            prompt = task + (' Also support comma-delimited input strings using DEFAULT_SEPARATOR.' if index == 0 and similar else ' Also accept unitless decimals using DEFAULT_UNIT.' if similar else '')
            fixtures.append({'id': name + ('-changed' if similar else ''), 'source': src, 'task': prompt,
                             'test_source': ('from solution import normalize_labels\ndef test_labels():\n    assert normalize_labels([" A ", "a", "", "B"]) == ["a", "b"]\n' if index == 0 else 'from solution import duration_seconds\ndef test_duration():\n    assert duration_seconds("2m") == 120.0\n')})
    grader = '''import sys
sys.path.insert(0, 'src')
import solution as s
if hasattr(s, 'normalize_labels'):
    for values, expected in [([], []), ([" A ","a","", "B"], ["a","b"]), (["Straße","STRASSE"], ["strasse"]), ((x for x in [" b ","A","b"]), ["b","a"])]:
        assert s.normalize_labels(values) == expected
    for value in [None, 7, object()]:
        try: s.normalize_labels(["ok", value])
        except TypeError: pass
        else: raise AssertionError('non-string item')
    if sys.argv[1] == 'changed': assert s.normalize_labels(' A ,a, B,,') == ['a','b']
else:
    for text, expected in [('2m',120.), (' 250 ms ',.25), ('1.5s',1.5), ('0s',0.), (' .5 m ',30.)]:
        assert s.duration_seconds(text) == expected
    for text in ['-1s','NaNs','infs','1h','1','1.2.3s','s','']:
        if sys.argv[1] == 'changed' and text == '1': continue
        try: s.duration_seconds(text)
        except ValueError: pass
        else: raise AssertionError(text)
    for value in [None, 5]:
        try: s.duration_seconds(value)
        except TypeError: pass
        else: raise AssertionError('type')
    if sys.argv[1] == 'changed': assert s.duration_seconds(' 2.5 ') == 2.5
print('independent acceptance passed')
'''
    external = {'python': '3.12.3', 'dependencies': 'stdlib; optional pytest available via native tools',
                'grader_sha256': hashlib.sha256(grader.encode()).hexdigest(), 'model': 'openai/gpt-6.1-sol#high',
                'tool_access': 'native OpenCode tools unchanged', 'provider_usage': 'observed adapter requests; hidden retries not certified'}
    order = []
    for stage, fixture in enumerate(['labels','duration','labels','duration','labels-changed','duration-changed']):
        for arm in (['baseline','v2'] if stage % 2 == 0 else ['v2','baseline']):
            order.append({'id': f'{stage+1:02d}-{arm}', 'stage': stage+1, 'arm': arm, 'fixture': fixture})
    protocol = {'schema': 'cami-v2-small-study/1', 'baseline': '807285f', 'attempts': order,
                'fixtures': fixtures, 'grader': grader, 'external': external,
                'memory': 'separate empty-at-start per arm; only earlier eligible results; OpenCode request_coverage=false in both arms',
                'metric': 'ratio of summed full pipeline seconds and ratio of summed normalized token work (input+output+reasoning+cache_write); cache_read separate; unknown stays null',
                'time_boundary': 'before fixture restoration through fsync of result artifact, including all child capture/context/model/grade/replay/recording; analysis and the timing receipt itself excluded',
                'gate': 'all attempts operational, complete observed usage, all independent quality checks pass; both sums lower than baseline',
                'target_50': 'each ratio <=0.5, separately reported; no extrapolation to production repeat frequency',
                'retries': 'none; complete fixed volume once, preserve errors; admission excluded and reported separately',
                'interpretation': '6 logical stages, 12 arm attempts; two new, two exact repeat, two similar after code change per arm; one small dependent sequence, no confidence claim'}
    save(REPORT / 'protocol.json', protocol)
    raw = (REPORT / 'protocol.json').read_bytes()
    save(REPORT / 'protocol-seal.json', {'sha256': hashlib.sha256(raw).hexdigest(), 'sealed_ns': time.time_ns()})
    RUN.mkdir(parents=True, exist_ok=False)
    (RUN / 'grader.py').write_text(grader)
    (RUN / 'external.json').write_text(json.dumps(external, sort_keys=True))


def run():
    raw = (REPORT / 'protocol.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == json.loads((REPORT / 'protocol-seal.json').read_text())['sha256']
    protocol = json.loads(raw)
    fixtures = {f['id']: f for f in protocol['fixtures']}
    for item in protocol['attempts']:
        target = RUN / item['id']
        target.mkdir(exist_ok=False)  # Never rerun even an error.
        start = time.monotonic()
        fixture = fixtures[item['fixture']]
        work = RUN / (item['arm'] + '-work')
        work.mkdir(exist_ok=True)
        for path in list(work.iterdir()):
            if path.name != '.git':
                shutil.rmtree(path) if path.is_dir() else path.unlink()
        (work / 'src').mkdir()
        (work / 'tests').mkdir()
        (work / 'src/solution.py').write_text(fixture['source'])
        (work / 'tests/test_solution.py').write_text(fixture['test_source'])
        subprocess.run(['git','init','-q',str(work)], check=True)
        taskfile = target / 'task.txt'
        taskfile.write_text(fixture['task'])
        changed = 'changed' if 'changed' in item['fixture'] else 'base'
        grade = ['/usr/bin/python3.12','-B',str(RUN / 'grader.py'),changed]
        if item['arm'] == 'baseline':
            command = [str(PYTHON), str(ROOT / 'runs/cami-v2/baseline/integrations/opencode/run_task.py')]
        else:
            command = [str(PYTHON), '-m','cami.opencode.run_task','--mode','v2','--memory-root',str(RUN / 'memory')]
        command += ['--workspace',str(work),'--task-file',str(taskfile),'--context-file',str(RUN / 'external.json'),
                    '--journal-root',str(target / 'journals'),'--grade-json',json.dumps(grade),
                    '--origin','experiment','--opencode-binary','/root/.opencode/bin/opencode']
        save(target / 'start.json', {'attempt': item, 'command': command, 'loadavg': os.getloadavg(), 'start_ns': time.time_ns()})
        with (target / 'stdout.log').open('x') as out, (target / 'stderr.log').open('x') as err:
            result = subprocess.run(command, stdout=out, stderr=err, timeout=1100)
        save(target / 'result.json', {'returncode': result.returncode, 'finished_ns': time.time_ns()})
        save(target / 'timing.json', {'seconds': time.monotonic()-start})
        print(item['id'], 'finished', result.returncode, flush=True)


if __name__ == '__main__':
    import sys
    {'freeze': freeze, 'run': run}[sys.argv[1]]()
