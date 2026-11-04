"""Stdlib-only audit of the finite graph against an explicit semantic transition rule."""
from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
from pathlib import Path


def read(path: Path):
    return json.loads(path.read_text())


def expected_selection(variant: str, old: dict, new: dict, available: bool) -> bool:
    return (variant in {'all_validate', 'known_missing'} or not available
            or old['f'] != new['f']
            or (variant == 'intact' and old['f'] == 'g()' and old['g'] != new['g']))


def audit(root: Path, original_protocol: Path) -> dict:
    manifest, plan = read(root / 'manifest.json'), read(root / 'protocol.json')
    assert manifest['status'] == 'complete'
    assert manifest['source_before'] == manifest['source_after']
    for name, expected in manifest['artifact_hashes'].items():
        path = (root / name).resolve()
        assert path.is_relative_to(root.resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    assert hashlib.sha256(original_protocol.read_bytes()).hexdigest() == manifest['protocol_sha256']
    assert plan == read(original_protocol)
    programs = read(root / 'programs.json')
    assert len(programs) == 12
    assert {(p['f'], p['g'], p['unrelated']) for p in programs} == {
        (f, g, u) for f in ('1','2','g()') for g in (1,2) for u in (0,1)}
    assert [p['program_id'] for p in programs] == list(range(12))
    for p in programs:
        value = p['g'] if p['f'] == 'g()' else int(p['f'])
        assert p['value'] == value and p['truth'] is (value == 1)
        assert p['module_source'] == f"def f():\n    return {p['f']}\n\ndef g():\n    return {p['g']}\n"
        assert p['unrelated_source'] == f"VALUE = {p['unrelated']}\n"
        sources = {'module.py':p['module_source'], 'unrelated.py':p['unrelated_source']}
        assert {b['path'] for b in p['blobs']} == sources.keys()
        for b in p['blobs']:
            raw = sources[b['path']].encode()
            assert b['sha256'] == hashlib.sha256(raw).hexdigest()
            assert b['oid'] == hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    summary = read(root / 'summary.json')
    total_states = total_edges = 0
    for variant in plan['variants']:
        result = read(root / (variant + '.json'))
        states = {s['state_id']:s for s in result['reachable_states']}
        assert len(states) == len(result['reachable_states']) == result['state_count']
        initial, = [p for p in programs if (p['f'],p['g'],p['unrelated']) == ('g()',1,0)]
        assert result['initial_state'] == f"p{initial['program_id']:02d}:available"
        adjacency = {s:[] for s in states}
        for sid, state in states.items():
            p = programs[state['program_id']]
            assert sid == f"p{p['program_id']:02d}:{'available' if state['available'] else 'withheld'}"
            assert state['truth'] is p['truth']
            assert state['false_availability'] is (state['available'] and not p['truth'])
            assert state['false_withholding'] is (not state['available'] and p['truth'])
        for edge in result['transitions']:
            old_state, new_state = states[edge['from']], states[edge['to']]
            old, new = programs[old_state['program_id']], programs[new_state['program_id']]
            assert edge['from_program'] == old['program_id'] and edge['to_program'] == new['program_id']
            selected = expected_selection(variant, old, new, old_state['available'])
            assert edge['selected'] is selected
            available = new['truth'] if selected else old_state['available']
            assert edge['next_available'] is available and new_state['available'] is available
            assert edge['oracle_value'] == new['value']
            assert edge['validation_boundary_used'] is selected and edge['actual_probe_executions'] == 0
            changed = [path for path, field in [('module.py','module_source'), ('unrelated.py','unrelated_source')]
                       if old[field] != new[field]]
            assert edge['changed_files'] == changed
            adjacency[edge['from']].append(edge)
        for outgoing in adjacency.values():
            assert len(outgoing) == 12 and {e['to_program'] for e in outgoing} == set(range(12))
        seen, queue = {result['initial_state']}, deque([result['initial_state']])
        while queue:
            for edge in adjacency[queue.popleft()]:
                if edge['to'] not in seen:
                    seen.add(edge['to'])
                    queue.append(edge['to'])
        assert seen == states.keys()
        assert len(result['transitions']) == result['transition_count'] == 12*len(states)
        for field in ('false_availability', 'false_withholding'):
            assert result[field+'_states'] == sum(s[field] for s in states.values())
        assert summary['variants'][variant] == {k:result[k] for k in summary['variants'][variant]}
        for target, path in result['error_witnesses'].items():
            current = result['initial_state']
            for edge in path:
                assert edge in adjacency[current]
                current = edge['to']
            assert current == target
            assert states[target]['false_availability'] or states[target]['false_withholding']
        cycle = result['source_changing_unsafe_cycle']
        if cycle:
            current = result['initial_state']
            for edge in result['cycle_prefix']:
                assert edge in adjacency[current]
                current = edge['to']
            assert current == cycle[0]['from']
            for edge in cycle:
                assert edge in adjacency[current] and states[current]['false_availability']
                assert not edge['selected'] and edge['changed_files']
                current = edge['to']
            assert current == cycle[0]['from']
        total_states += len(states)
        total_edges += len(result['transitions'])
    return {'status':'passed', 'programs':12, 'reachable_states':total_states,
            'transitions_checked_against_explicit_rule':total_edges,
            'artifact_hashes_checked':len(manifest['artifact_hashes']),
            'uses_cami_imports':False, 'independent_human_review':False,
            'scope':'Finite semantic formula plus graph completeness and witness checks; not arbitrary Python or execution attestation.'}


if __name__ == '__main__':
    if not __debug__:
        raise SystemExit('Assertions required; do not use -O')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, default=Path(__file__).resolve().parents[1] /
                        'examples/behavior_dependency/reachability_protocol.json')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.input, args.protocol)
    with args.out.open('x') as handle:
        json.dump(result, handle, indent=2)
        handle.write('\n')
