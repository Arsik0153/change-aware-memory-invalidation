"""Exhaust finite projected availability states; validation is a finite-oracle boundary."""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import replace
import hashlib
from itertools import product
from pathlib import Path

from cami.artifacts import digest, file_hash, read_json, reserve, write_json
from cami.index import build_index, compare_indexes
from cami.models import Anchor, Behavior, Claim, MemoryState, PolicyConfig, Provenance, Subject, ValidationResult
from cami.policies import SelectionContext, advance_state, select_claims
from cami.repository import Blob, Snapshot
from cami.scenarios import edge_integer
from scripts.finite_behavior_oracle import value_of
from scripts.verify_cami import source_snapshot

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'examples/behavior_dependency/reachability_protocol.json'


def blob(path: str, source: str) -> Blob:
    content = source.encode()
    oid = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
    return Blob(path, oid, '100644', content, None)


def programs(plan: dict) -> list[dict]:
    space = plan['program_space']
    result = []
    for number, (f, g, unrelated) in enumerate(product(
            space['f_returns'], space['g_returns'], space['unrelated_values'])):
        source = space['module_template'].format(f=f, g=g)
        other = space['unrelated_template'].format(value=unrelated)
        snap = Snapshot(plan['mask']['repo_id'], f'constructed-program-{number:02d}',
                        (blob('module.py', source), blob('unrelated.py', other)))
        value = value_of(source)
        result.append({'program_id': number, 'f': f, 'g': g, 'unrelated': unrelated,
                       'module_source': source, 'unrelated_source': other,
                       'value': value, 'truth': value == 1, 'snapshot': snap,
                       'index': build_index(snap)})
    assert len(result) == space['expected_programs']
    return result


def state_id(state: tuple[int, bool]) -> str:
    return f"p{state[0]:02d}:{'available' if state[1] else 'withheld'}"


def prefix_to(target: str, predecessors: dict, transitions: list[dict]) -> list[dict]:
    path = []
    while target in predecessors:
        number = predecessors[target]
        edge = transitions[number]
        path.append(edge)
        target = edge['from']
    return list(reversed(path))


def changing_cycle(states: list[dict], transitions: list[dict]) -> list[dict] | None:
    unsafe = {s['state_id'] for s in states if s['false_availability']}
    adjacency = {s: [] for s in unsafe}
    for edge in transitions:
        if (edge['from'] in unsafe and edge['to'] in unsafe
                and not edge['selected'] and edge['changed_files']):
            adjacency[edge['from']].append(edge)
    candidates = []
    for start in sorted(unsafe):
        queue = deque([(start, [])])
        seen = {start}
        found = None
        while queue and found is None:
            current, path = queue.popleft()
            for edge in adjacency[current]:
                if edge['to'] == start:
                    found = path + [edge]
                    break
                if edge['to'] not in seen:
                    seen.add(edge['to'])
                    queue.append((edge['to'], path + [edge]))
        if found:
            candidates.append(found)
    return min(candidates, key=len) if candidates else None


def explore(plan: dict, universe: list[dict], variant: str, *,
            force_hidden: bool = False, suppress_previous: bool = False) -> dict:
    initial, = [p for p in universe if all(p[name] == plan['initial'][name]
                                          for name in ('f', 'g', 'unrelated'))]
    parent = initial['snapshot']
    claim = Claim(claim_id='f-returns-one', repo_id=parent.repo_id, origin_commit=parent.revision,
        kind='behavior_test', text='Finite authored predicate f() == 1.',
        subject=Subject(path='module.py', qualname='f', node_kind='function'),
        predicate=Behavior(type='behavior_test', probe_path='not-executed.py', probe_sha256='0'*64,
                           node_id='finite-oracle-boundary', environment_id='not-executed'),
        scope='Finite oracle boundary; no probe execution in this state-space check.')
    known = variant == 'known_missing' and not force_hidden
    masked = variant in {'known_missing', 'hidden_missing'} or force_hidden
    indices = []
    removed_edges = set()
    for p in universe:
        index = p['index']
        removed = tuple(e for e in index.edges if masked and edge_integer(
            parent.repo_id, e, plan['mask']['seed']) < int(plan['mask']['drop'] * 2**256))
        removed_edges.update(removed)
        indices.append(replace(index, edges=tuple(e for e in index.edges if e not in removed),
            unresolved=index.unresolved | ({e.source for e in removed} if known else set())))
    assert not masked or len(removed_edges) == 1
    prov = Provenance(claim_id=claim.claim_id, scenario_id=variant, known_incomplete=known,
        anchors=(Anchor(path='module.py', qualname='f', scope='symbol', observed_commit=parent.revision,
                        content_hash=parent.blobs[0].content_hash, origin='manual'),))
    policy = PolicyConfig(id='all_validate' if variant == 'all_validate' else 'symbol_validate',
                          dependency_depth=plan['dependency_depth'])
    initial_state = (initial['program_id'], plan['initial']['available'])
    assert initial['truth'] is True and initial_state[1] is True
    queue, seen = deque([initial_state]), {initial_state}
    states, transitions, predecessors = [], [], {}
    while queue:
        current, available = queue.popleft()
        old = universe[current]
        sid = state_id((current, available))
        states.append({'state_id': sid, 'program_id': current, 'available': available,
                       'truth': old['truth'], 'false_availability': available and not old['truth'],
                       'false_withholding': not available and old['truth']})
        previous = MemoryState(claim_id=claim.claim_id, revision=old['snapshot'].revision,
            state='valid' if available else 'stale', available=available, basis='validated',
            last_checked_commit=old['snapshot'].revision,
            last_supported_commit=parent.revision, last_verdict='supported' if available else 'contradicted',
            current_provenance=prov)
        for target in universe:
            snap = target['snapshot']
            changes = compare_indexes(indices[current], indices[target['program_id']], old['snapshot'], snap)
            selection_previous = previous.model_copy(update={'available': True}) if suppress_previous else previous
            decision, = select_claims(SelectionContext(snap.revision, (claim,), (prov,),
                (selection_previous,), changes, protocol_version=plan['protocol_version']), policy)
            result = None
            if decision.selected:
                result = ValidationResult(claim_id=claim.claim_id, commit=snap.revision,
                    validator='synthetic-finite-oracle-boundary',
                    verdict='supported' if target['truth'] else 'contradicted',
                    reason='test_passed' if target['truth'] else 'predicate_mismatch',
                    input_hash=digest({'program': target['program_id'], 'value': target['value']}),
                    duration_seconds=0, test_executions=0)
            advanced = advance_state(previous, decision, policy, result, structural=False)
            successor = (target['program_id'], advanced.available)
            edge = {'from': sid, 'to': state_id(successor),
                    'from_program': current, 'to_program': target['program_id'],
                    'selected': decision.selected, 'selection_reasons': list(decision.reasons),
                    'changed_files': sorted(changes.files),
                    'oracle_value': target['value'], 'next_available': advanced.available,
                    'validation_boundary_used': result is not None, 'actual_probe_executions': 0}
            transitions.append(edge)
            if successor not in seen:
                seen.add(successor)
                predecessors[edge['to']] = len(transitions)-1
                queue.append(successor)
    cycle = changing_cycle(states, transitions)
    errors = [s for s in states if s['false_availability'] or s['false_withholding']]
    return {'variant': variant, 'initial_state': state_id(initial_state),
        'reachable_states': states, 'transitions': transitions,
        'state_count': len(states), 'transition_count': len(transitions),
        'false_availability_states': sum(s['false_availability'] for s in states),
        'false_withholding_states': sum(s['false_withholding'] for s in states),
        'error_witnesses': {s['state_id']: prefix_to(s['state_id'], predecessors, transitions) for s in errors},
        'source_changing_unsafe_cycle': cycle,
        'cycle_prefix': prefix_to(cycle[0]['from'], predecessors, transitions) if cycle else None}


def check_invariants(result: dict) -> None:
    assert result['false_withholding_states'] == 0
    if result['variant'] == 'hidden_missing':
        assert result['false_availability_states'] > 0 and result['source_changing_unsafe_cycle']
    else:
        assert result['false_availability_states'] == 0


def run(out: Path) -> None:
    before = source_snapshot(ROOT)
    assert not before['source_status'], 'Commit source before execution'
    plan, plan_hash = read_json(PLAN), file_hash(PLAN)
    assert all(file_hash(ROOT / name) == h for name, h in plan['source_dependencies_sha256'].items())
    reserve(out)
    write_json(out / 'protocol.json', plan)
    manifest = {'status': 'running', 'source_before': before, 'protocol_sha256': plan_hash,
                'actual_probe_executions': 0, 'produces_real_labels_or_admission': False}
    write_json(out / 'manifest.json', manifest)
    try:
        universe = programs(plan)
        write_json(out / 'programs.json', [{**{k:v for k,v in p.items() if k not in {'index','snapshot'}},
            'revision': p['snapshot'].revision,
            'blobs': [{'path': b.path, 'oid': b.object_id, 'sha256': b.content_hash} for b in p['snapshot'].blobs]}
            for p in universe])
        summaries = {}
        for variant in plan['variants']:
            result = explore(plan, universe, variant)
            write_json(out / (variant + '.json'), result)
            check_invariants(result)
            summaries[variant] = {k:result[k] for k in ('state_count', 'transition_count',
                'false_availability_states', 'false_withholding_states', 'cycle_prefix', 'source_changing_unsafe_cycle')}
        controls = []
        for name, variant, options in [('hide_intact_edge','intact',{'force_hidden':True}),
                                      ('suppress_recovery_trigger','hidden_missing',{'suppress_previous':True})]:
            result = explore(plan, universe, variant, **options)
            write_json(out / (name + '.json'), result)
            detected = False
            try:
                check_invariants(result)
            except AssertionError:
                detected = True
            assert detected
            controls.append({'control':name, 'detected':detected,
                'false_availability_states':result['false_availability_states'],
                'false_withholding_states':result['false_withholding_states']})
        write_json(out / 'summary.json', {'programs':len(universe), 'variants':summaries,
            'negative_controls':controls, 'actual_probe_executions':0, 'limits':plan['limits']})
        assert file_hash(PLAN) == plan_hash
        after = source_snapshot(ROOT)
        assert before == after
        manifest.update(status='complete', source_after=after)
    except (Exception, KeyboardInterrupt) as exc:
        manifest.update(status='failed', failure={'type':type(exc).__name__,'message':str(exc)})
        raise
    finally:
        manifest['artifact_hashes'] = {p.name:file_hash(p) for p in out.iterdir()
                                      if p.is_file() and p.name != 'manifest.json'}
        write_json(out / 'manifest.json', manifest)


if __name__ == '__main__':
    if not __debug__:
        raise SystemExit('Assertions required; do not use -O')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    run(parser.parse_args().out.resolve())
