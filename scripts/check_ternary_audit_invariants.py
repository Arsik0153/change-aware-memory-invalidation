"""Finite audit invariants with nondeterministic exact, incomplete and unsound validators."""
from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

from cami.artifacts import file_hash,read_json,reserve,write_json
from scripts.check_periodic_audit_bound import false_run_risk,prefix
from scripts.verify_cami import source_snapshot

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'examples/behavior_dependency/ternary_audit_protocol.json'


def state_id(state):
    truth,available,age=state
    return f't{int(truth)}:a{int(available)}@{age}'


def successors(state,interval,outcomes,*,carry_on_insufficient=False):
    _,available,age=state
    for truth in (False,True):
        for baseline in (False,True):
            due=age+1>=interval
            selected=baseline or not available or due
            verdicts=outcomes[str(truth).lower()] if selected else [None]
            for verdict in verdicts:
                if selected:
                    next_available=(available if carry_on_insufficient and verdict=='insufficient_evidence'
                                    else verdict=='supported')
                    next_age=0
                else:
                    next_available=available
                    next_age=age+1
                target=(truth,next_available,next_age)
                yield target,{'from':state_id(state),'to':state_id(target),'baseline_trigger':baseline,
                    'audit_due':due,'selected':selected,'verdict':verdict,'next_truth':truth}


def explore(interval,outcomes,*,carry_on_insufficient=False):
    initial=(True,True,0)
    queue,seen=deque([initial]),{initial}
    states,edges,predecessors=[],[],{}
    while queue:
        current=queue.popleft()
        truth,available,age=current
        states.append({'state_id':state_id(current),'truth':truth,'available':available,'age':age})
        for target,edge in successors(current,interval,outcomes,
                                      carry_on_insufficient=carry_on_insufficient):
            edges.append(edge)
            if target not in seen:
                seen.add(target)
                predecessors[edge['to']]=edge
                queue.append(target)
    risk=false_run_risk(states,edges)
    risk['prefix']=prefix(risk['false_run_start'],predecessors) if risk['false_run_start'] else []
    withholding=[s for s in states if s['truth'] and not s['available']]
    if withholding:
        witness=withholding[0]['state_id']
        withholding_witness={'state':witness,'prefix':prefix(witness,predecessors)}
    else:
        withholding_witness=None
    return {'interval':interval,'initial_state':state_id(initial),'states':states,'transitions':edges,
            'state_count':len(states),'transition_count':len(edges),'risk':risk,
            'false_withholding_states':len(withholding),'false_withholding_witness':withholding_witness}


def verify_rank(result):
    interval=result['interval']
    states={s['state_id']:s for s in result['states']}
    unsafe={key for key,s in states.items() if s['available'] and not s['truth']}
    assert all(1<=states[key]['age']<interval for key in unsafe)
    for edge in result['transitions']:
        if edge['to'] in unsafe:
            assert not edge['selected']
        if edge['from'] in unsafe and edge['to'] in unsafe:
            assert states[edge['to']]['age']==states[edge['from']]['age']+1
    assert not result['risk']['unbounded']
    assert result['risk']['max_consecutive_false_available']==interval-1


def run(out):
    before=source_snapshot(ROOT)
    assert not before['source_status'], 'Commit source before model exploration'
    plan,plan_hash=read_json(PLAN),file_hash(PLAN)
    reserve(out)
    write_json(out/'protocol.json',plan)
    manifest={'status':'running','source_before':before,'protocol_sha256':plan_hash,
              'actual_probe_executions':0,'production_policy_changed':False}
    write_json(out/'manifest.json',manifest)
    summary={'models':{},'negative_controls':{},'scope':plan['scope'],'actual_probe_executions':0}
    try:
        for name,outcomes in plan['models'].items():
            for interval in plan['intervals']:
                key=f'{name}-K{interval}'
                result=explore(interval,outcomes)
                write_json(out/(key+'.json'),result)
                verify_rank(result)
                assert (result['false_withholding_states']==0)==(name=='exact_binary')
                summary['models'][key]={k:result[k] for k in ('interval','state_count','transition_count',
                    'risk','false_withholding_states','false_withholding_witness')}
        for control in plan['negative_controls']:
            name=control['id']
            outcomes=({'true':['supported','contradicted','insufficient_evidence'],
                       'false':['supported','contradicted','insufficient_evidence']}
                      if name=='false_positive_supported' else plan['models']['sound_positive_only'])
            result=explore(control['interval'],outcomes,carry_on_insufficient=name=='carry_on_insufficient')
            write_json(out/(name+'.json'),result)
            assert result['risk']['unbounded'] and result['risk']['cycle']
            detected=False
            try:
                verify_rank(result)
            except AssertionError:
                detected=True
            assert detected
            summary['negative_controls'][name]={'detected':detected,'risk':result['risk']}
        write_json(out/'summary.json',summary)
        assert file_hash(PLAN)==plan_hash
        after=source_snapshot(ROOT)
        assert after==before
        manifest.update(status='complete',source_after=after)
    except (Exception,KeyboardInterrupt) as exc:
        manifest.update(status='failed',failure={'type':type(exc).__name__,'message':str(exc)})
        raise
    finally:
        manifest['artifact_hashes']={p.name:file_hash(p) for p in out.iterdir()
                                    if p.is_file() and p.name!='manifest.json'}
        write_json(out/'manifest.json',manifest)


if __name__=='__main__':
    if not __debug__:
        raise SystemExit('Assertions required; do not use -O')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    run(parser.parse_args().out.resolve())
