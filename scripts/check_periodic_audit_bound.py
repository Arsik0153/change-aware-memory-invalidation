"""Lift the frozen finite graph with a periodic audit; no production policy or probes."""
from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

from cami.artifacts import file_hash, read_json, reserve, write_json
from scripts.verify_cami import source_snapshot

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'examples/behavior_dependency/periodic_audit_protocol.json'
BASE = ROOT / 'reports/research-20261104/behavior-reachability-v1'


def state_id(base: str, age: int) -> str:
    return f'{base}@{age}'


def transition(edge: dict, age: int, interval: int | None, truth: bool, *,
               reset_on_change: bool = False, off_by_one: bool = False) -> dict:
    observed_age = 0 if reset_on_change and edge['changed_files'] else age
    due = (False if interval is None else observed_age + 1 > interval if off_by_one
           else observed_age + 1 >= interval)
    selected = edge['selected'] or due
    available = truth if selected else edge['next_available']
    next_base = f"p{edge['to_program']:02d}:{'available' if available else 'withheld'}"
    return {'next_base':next_base, 'next_available':available,
            'next_age':0 if selected else observed_age+1,
            'baseline_selected':edge['selected'], 'audit_due':due, 'selected':selected,
            'age_before':age, 'observed_age':observed_age}


def prefix(target: str, predecessors: dict) -> list[dict]:
    result = []
    while target in predecessors:
        edge = predecessors[target]
        result.append(edge)
        target = edge['from']
    return list(reversed(result))


def false_run_risk(states: list[dict], edges: list[dict]) -> dict:
    unsafe = {s['state_id'] for s in states if s['available'] and not s['truth']}
    adjacency = {s:[] for s in unsafe}
    indegree = {s:0 for s in unsafe}
    for edge in edges:
        if edge['from'] in unsafe and edge['to'] in unsafe:
            adjacency[edge['from']].append(edge)
            indegree[edge['to']] += 1
    queue = deque(sorted(s for s in unsafe if indegree[s] == 0))
    distance, predecessors = {s:1 for s in unsafe}, {}
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for edge in adjacency[current]:
            target = edge['to']
            if distance[current]+1 > distance[target]:
                distance[target] = distance[current]+1
                predecessors[target] = edge
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited == len(unsafe):
        endpoint = max(sorted(unsafe), key=lambda s:distance[s]) if unsafe else None
        path = prefix(endpoint, predecessors) if endpoint else []
        return {'unbounded':False, 'max_consecutive_false_available':distance[endpoint] if endpoint else 0,
                'false_run_start':path[0]['from'] if path else endpoint,
                'false_run_edges':path, 'cycle':None}
    for start in sorted(unsafe):
        search, seen = deque([(start,[])]), {start}
        while search:
            current, path = search.popleft()
            for edge in adjacency[current]:
                if edge['to'] == start:
                    return {'unbounded':True, 'max_consecutive_false_available':None,
                            'false_run_start':start, 'false_run_edges':[], 'cycle':path+[edge]}
                if edge['to'] not in seen:
                    seen.add(edge['to'])
                    search.append((edge['to'],path+[edge]))
    raise AssertionError('Non-acyclic graph must contain a cycle')


def lift(base: dict, interval: int, *, reset_on_change: bool = False,
         off_by_one: bool = False) -> dict:
    base_states = {s['state_id']:s for s in base['reachable_states']}
    adjacency = {s:[] for s in base_states}
    for edge in base['transitions']:
        adjacency[edge['from']].append(edge)
    initial = (base['initial_state'],0)
    queue, seen = deque([initial]), {initial}
    states, edges, predecessors = [], [], {}
    while queue:
        current, age = queue.popleft()
        sid = state_id(current,age)
        observed = base_states[current]
        states.append({'state_id':sid, 'base_state':current, 'age':age,
                       'available':observed['available'], 'truth':observed['truth']})
        for source_edge in adjacency[current]:
            truth = base_states[source_edge['to']]['truth']
            step = transition(source_edge,age,interval,truth,
                              reset_on_change=reset_on_change,off_by_one=off_by_one)
            assert step['next_base'] in base_states
            assert 0 <= step['next_age'] <= interval
            target = (step['next_base'],step['next_age'])
            edge = {'from':sid, 'to':state_id(*target), 'to_program':source_edge['to_program'],
                    'changed_files':source_edge['changed_files'], 'truth':truth, **step}
            edges.append(edge)
            if target not in seen:
                seen.add(target)
                predecessors[edge['to']] = edge
                queue.append(target)
    risk = false_run_risk(states,edges)
    risk['prefix'] = prefix(risk['false_run_start'],predecessors) if risk['false_run_start'] else []
    return {'interval':interval, 'state_count':len(states), 'transition_count':len(edges),
            'states':states, 'transitions':edges, 'risk':risk,
            'false_withholding_states':sum(not s['available'] and s['truth'] for s in states)}


def check_bound(result: dict) -> None:
    assert not result['risk']['unbounded']
    assert result['risk']['max_consecutive_false_available'] <= result['interval']-1
    assert result['false_withholding_states'] == 0


def workload(base: dict, programs: list[dict], spec: dict, interval: int | None) -> dict:
    lookup = {(e['from'],e['to_program']):e for e in base['transitions']}
    current, age, rows = base['initial_state'], 0, []
    for number in range(1,spec['steps']+1):
        g = 1 if spec['id'] == 'stable' or (spec['id'] == 'break_then_restore' and number >= 9) else 2
        target, = [p for p in programs if (p['f'],p['g'],p['unrelated']) == ('g()',g,number%2)]
        source_edge = lookup[current,target['program_id']]
        step = transition(source_edge,age,interval,target['truth'])
        rows.append({'step':number, 'program_id':target['program_id'], 'truth':target['truth'], **step})
        current, age = step['next_base'], step['next_age']
    return {'workload':spec['id'], 'interval':interval, 'steps':rows,
            'logical_validations':sum(r['selected'] for r in rows),
            'false_availability_items':sum(r['next_available'] and not r['truth'] for r in rows),
            'false_withholding_items':sum(not r['next_available'] and r['truth'] for r in rows),
            'actual_probe_executions':0}


def run(out: Path) -> None:
    before = source_snapshot(ROOT)
    assert not before['source_status'], 'Commit source before the model study'
    plan, plan_hash = read_json(PLAN), file_hash(PLAN)
    assert all(file_hash(ROOT / name) == expected for name, expected in plan['base_input_sha256'].items())
    base, programs = read_json(BASE / 'hidden_missing.json'), read_json(BASE / 'programs.json')
    reserve(out)
    write_json(out / 'protocol.json', plan)
    manifest = {'status':'running', 'source_before':before, 'protocol_sha256':plan_hash,
                'base_input_sha256':plan['base_input_sha256'], 'actual_probe_executions':0,
                'production_policy_changed':False}
    write_json(out / 'manifest.json', manifest)
    try:
        summaries, controls, workloads = {}, [], []
        for interval in plan['intervals']:
            result = lift(base,interval)
            write_json(out / f'interval-{interval}.json', result)
            check_bound(result)
            summaries[str(interval)] = {key:result[key] for key in
                ('state_count','transition_count','false_withholding_states','risk')}
        for control in plan['negative_controls']:
            options = ({'reset_on_change':True} if control['id'] == 'reset_on_source_change'
                       else {'off_by_one':True})
            result = lift(base,control['interval'],**options)
            write_json(out / (control['id'] + '.json'), result)
            detected = False
            try:
                check_bound(result)
            except AssertionError:
                detected = True
            assert detected
            if control['id'] == 'reset_on_source_change':
                assert result['risk']['cycle']
                assert all(e['changed_files'] for e in result['risk']['cycle'])
            controls.append({'id':control['id'], 'detected':detected, 'risk':result['risk']})
        for spec in plan['workloads']:
            for interval in (None,*plan['intervals']):
                workloads.append(workload(base,programs,spec,interval))
        write_json(out / 'workloads.json', workloads)
        write_json(out / 'summary.json', {'intervals':summaries, 'negative_controls':controls,
            'workloads':[{k:v for k,v in w.items() if k != 'steps'} for w in workloads],
            'actual_probe_executions':0, 'limits':plan['limits']})
        assert file_hash(PLAN) == plan_hash
        assert all(file_hash(ROOT / name) == h for name,h in plan['base_input_sha256'].items())
        after = source_snapshot(ROOT)
        assert before == after
        manifest.update(status='complete',source_after=after)
    except (Exception, KeyboardInterrupt) as exc:
        manifest.update(status='failed',failure={'type':type(exc).__name__,'message':str(exc)})
        raise
    finally:
        manifest['artifact_hashes'] = {p.name:file_hash(p) for p in out.iterdir()
                                      if p.is_file() and p.name != 'manifest.json'}
        write_json(out / 'manifest.json', manifest)


if __name__ == '__main__':
    if not __debug__:
        raise SystemExit('Assertions required; do not use -O')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    run(parser.parse_args().out.resolve())
