"""Versioned, worktree-bound solution records. No model reasoning is retained."""
from __future__ import annotations

import difflib
import json
import sqlite3
from pathlib import Path

try:
    from . import task_replay as replay
except ImportError:
    import task_replay as replay


def namespace(root, workspace):
    return Path(root).resolve() / 'task-v2' / replay.digest(str(Path(workspace).resolve()).encode())


def hints(state, task, limit=2):
    words = set(task.casefold().split())
    found = []
    for path in (Path(state) / 'methods').glob('*.json'):
        value = json.loads(path.read_text())
        overlap = len(words & set(value['symptom'].casefold().split()))
        if overlap:
            found.append((-overlap, path.name, value))
    result = []
    for _, _, value in sorted(found)[:limit]:
        if len(value['patch'].encode()) > 4000:
            value = {**value, 'patch': None, 'patch_omitted': 'read verified artifact via provenance'}
        result.append(value)
    return result


def remember(directory, config, terminal):
    if not terminal['cache_eligible']:
        return False
    before, after = Path(directory) / 'before', Path(directory) / 'solution'
    patches, components = [], []
    for path in sorted(set(config['files']) | set(terminal['solution_files'])):
        if config['files'].get(path) == terminal['solution_files'].get(path):
            continue
        components.append(path)
        a = (before / path).read_text(errors='replace') if (before / path).exists() else ''
        b = (after / path).read_text(errors='replace') if (after / path).exists() else ''
        patches.extend(difflib.unified_diff(a.splitlines(True), b.splitlines(True), fromfile=path, tofile=path))
    receipt = Path(directory) / 'verified-grade.log'
    if not receipt.exists():
        replay.publish(receipt, (Path(directory) / 'grade.log').read_bytes())
    value = {'schema': 'cami-verified-method/1', 'symptom': config['task'],
             'cause': None, 'cause_status': 'not independently established',
             'components': components, 'patch': ''.join(patches),
             'verification': {'argv': config['grade'], 'quality': terminal['quality'],
                              'log_sha256': replay.digest(receipt.read_bytes())},
             'applicability': {'exact_input_key': config['key'], 'context': config['context'],
                               'similar_tasks': 'hint only; inspect current code and verify anew'},
             'provenance': str(Path(directory).resolve()),
             'replay_sha256': replay.digest((Path(config['cache']) / (config['key'] + '.json')).read_bytes())}
    target = Path(config['v2_state']) / 'methods'
    target.mkdir(parents=True, exist_ok=True)
    path = target / (config['key'] + '.json')
    if path.exists():
        old = json.loads(path.read_text())
        # Recovery may append a fresh grade to grade.log. Keep the first durable
        # verification receipt when patch, applicability and task provenance agree.
        comparable = {**value, 'verification': old['verification']}
        if comparable != old:
            raise ValueError('conflicting verified method for exact inputs')
        return True
    replay.publish(path, replay.canonical(value))
    return True


def reusable(state, key, context):
    """Low-level replay.record is not a quality certificate; require a committed admitted task."""
    method = Path(state) / 'methods' / (key + '.json')
    artifact = Path(state) / 'replay' / (key + '.json')
    if not method.is_file() or not artifact.is_file():
        return False
    value = json.loads(method.read_text())
    if value['applicability']['exact_input_key'] != key or value['applicability']['context'] != context:
        return False
    if replay.digest(artifact.read_bytes()) != value.get('replay_sha256'):
        return False
    receipt = Path(value['provenance']) / 'verified-grade.log'
    if not receipt.is_file() or replay.digest(receipt.read_bytes()) != value['verification']['log_sha256']:
        return False
    dbpath = Path(value['provenance']) / 'events.sqlite'
    if not dbpath.is_file():
        return False
    db = sqlite3.connect(f'file:{dbpath}?mode=ro', uri=True)
    try:
        events = [(k, json.loads(d)) for k, d in db.execute('select kind,data from events order by seq')]
    finally:
        db.close()
    terminal = [d for k, d in events if k == 'terminal']
    prepared = [d for k, d in events if k == 'prepared']
    return bool(terminal and prepared and terminal[-1]['cache_eligible']
                and terminal[-1]['cache_recorded'] and terminal[-1]['quality'] == 'pass'
                and terminal[-1]['execution'] == 'success' and terminal[-1]['telemetry']['complete']
                and terminal[-1]['input_key'] == key and prepared[-1]['context'] == context
                and prepared[-1]['request_coverage'] is True
                and Path(prepared[-1]['v2_state']).resolve() == Path(state).resolve())
