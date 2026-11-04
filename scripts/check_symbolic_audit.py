"""Check symbolic availability transition obligations with a pinned external Z3 binary."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

from cami.artifacts import file_hash,read_json,reserve,write_json
from scripts.verify_cami import source_snapshot

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'examples/behavior_dependency/symbolic_audit_protocol.json'
ENVIRONMENT=ROOT/'reports/research-20261104/smt-environment.json'


def transition(variant='normal'):
    observed='(ite changed 0 b0)' if variant=='reset_on_change' else 'b0'
    due=f'({">" if variant=="deadline_off_by_one" else ">="} (+ {observed} 1) K)'
    selected=f'(or hint {due})' if variant=='missing_unavailable_retry' else f'(or hint (not a0) {due})'
    validated='(ite (= v 2) a0 (= v 0))' if variant=='carry_on_insufficient' else '(= v 0)'
    sound='' if variant=='false_positive_supported' else '(assert (=> (and selected (= v 0)) t1))'
    return f'''(set-option :produce-proofs true)
(set-option :timeout 10000)
(set-logic QF_LIA)
(declare-const K Int)
(declare-const b0 Int)
(declare-const t0 Bool)
(declare-const a0 Bool)
(declare-const hint Bool)
(declare-const t1 Bool)
(declare-const v Int)
(declare-const changed Bool)
(declare-const step Int)
(define-fun selected () Bool {selected})
(define-fun a1 () Bool (ite selected {validated} a0))
(define-fun b1 () Int (ite selected 0 (+ {observed} 1)))
(define-fun unsafe0 () Bool (and a0 (not t0)))
(define-fun unsafe1 () Bool (and a1 (not t1)))
(define-fun inv0 () Bool (and (>= b0 0) (< b0 K) (=> unsafe0 (> b0 0))))
(define-fun inv1 () Bool (and (>= b1 0) (< b1 K) (=> unsafe1 (> b1 0))))
(assert (>= K 1))
(assert (and (>= v 0) (<= v 2)))
{sound}
'''


def queries():
    obligations=[
        ('initial_invariant',['a0','t0','(= b0 0)'],'inv0'),
        ('transition_invariant',['inv0'],'inv1'),
        ('false_availability_requires_skip',['inv0','unsafe1'],'(not selected)'),
        ('unsafe_rank_increases',['inv0','unsafe0','unsafe1'],'(= b1 (+ b0 1))'),
        ('exact_no_false_withholding',['inv0','t1','(=> selected (= v (ite t1 0 1)))'],'a1'),
        ('tight_carry_template',['inv0','(>= K 2)','(>= step 1)','(< step K)',
            'a0','(= b0 (- step 1))','(= t0 (= step 1))','(not hint)','(not t1)'],
            '(and (not selected) a1 (= b1 step))'),
    ]
    result=[]
    for name,premises,goal in obligations:
        base=transition()+''.join(f'(assert {p})\n' for p in premises)
        result.append({'id':name+'.premises','expected':'sat','kind':'nonvacuity',
                       'input':base,'obligation':name})
        result.append({'id':name+'.refutation','expected':'unsat','kind':'obligation',
                       'input':base+f'(assert (not {goal}))\n','obligation':name})
    witnesses=[
        ('incomplete_can_withhold','normal',['inv0','(= K 4)','(= b0 0)','a0','t0','hint','t1','(= v 2)','(not a1)']),
        ('false_positive_supported','false_positive_supported',
            ['inv0','(= K 4)','(= b0 3)','a0','t0','(not t1)','(= v 0)','(not inv1)']),
        ('carry_on_insufficient','carry_on_insufficient',
            ['inv0','(= K 4)','(= b0 3)','a0','t0','(not t1)','(= v 2)','(not inv1)']),
        ('deadline_off_by_one','deadline_off_by_one',
            ['inv0','(= K 4)','(= b0 3)','unsafe0','(not hint)','(not t1)','(not inv1)']),
        ('reset_on_change','reset_on_change',
            ['inv0','(= K 4)','(= b0 2)','unsafe0','changed','(not hint)','unsafe1','(not (= b1 (+ b0 1)))']),
        ('missing_unavailable_retry','missing_unavailable_retry',
            ['inv0','(= K 4)','(= b0 0)','(not a0)','(not t0)','(not hint)','t1','(not a1)']),
    ]
    for name,variant,premises in witnesses:
        result.append({'id':name,'expected':'sat','kind':'witness',
            'input':transition(variant)+''.join(f'(assert {p})\n' for p in premises)})
    for query in result:
        query['input']+='(check-sat)\n'+('(get-proof)\n' if query['expected']=='unsat' else
            '(get-value (K b0 t0 a0 hint t1 v changed step selected a1 b1))\n')
    return result


def run(out, solver):
    before=source_snapshot(ROOT)
    assert not before['source_status'], 'Commit source before symbolic verification'
    plan,plan_hash=read_json(PLAN),file_hash(PLAN)
    environment,environment_hash=read_json(ENVIRONMENT),file_hash(ENVIRONMENT)
    solver=solver.resolve()
    assert file_hash(solver)==environment['binary_sha256']
    version=subprocess.check_output([str(solver),'-version'],text=True).strip()
    assert version==environment['version_output'] and plan['solver_version']==environment['version']
    jobs=queries()
    assert len(jobs)==plan['expected_checks']
    assert [q['obligation'] for q in jobs if q['kind']=='obligation']==plan['obligations']
    assert [q['id'] for q in jobs if q['kind']=='witness']==plan['sat_witnesses']
    reserve(out)
    write_json(out/'protocol.json',plan)
    write_json(out/'environment.json',environment)
    manifest={'status':'running','source_before':before,'protocol_sha256':plan_hash,
              'environment_sha256':environment_hash,'solver_version':version,
              'solver_sha256':file_hash(solver),'actual_probe_executions':0}
    write_json(out/'manifest.json',manifest)
    results=[]
    try:
        for query in jobs:
            path=out/(query['id']+'.smt2')
            path.write_text(query['input'])
            command=[str(solver),'-smt2',str(path)]
            process=subprocess.run(command,capture_output=True,timeout=15)
            (out/(query['id']+'.stdout')).write_bytes(process.stdout)
            (out/(query['id']+'.stderr')).write_bytes(process.stderr)
            lines=process.stdout.decode().splitlines()
            actual=lines[0].strip() if lines else None
            row={k:query[k] for k in ('id','kind','expected')}
            row.update(actual=actual,exit_code=process.returncode,input_sha256=file_hash(path),command=command)
            results.append(row)
            write_json(out/'results.json',results)
            assert process.returncode==0 and not process.stderr and actual==query['expected'],row
            assert len(lines)>1 and '(error' not in process.stdout.decode()
        assert file_hash(PLAN)==plan_hash and file_hash(ENVIRONMENT)==environment_hash
        assert file_hash(solver)==manifest['solver_sha256']
        after=source_snapshot(ROOT)
        assert before==after
        manifest.update(status='complete',source_after=after,checks=len(results),
            unsat_refutations=sum(r['kind']=='obligation' and r['actual']=='unsat' for r in results),
            sat_premises=sum(r['kind']=='nonvacuity' and r['actual']=='sat' for r in results),
            sat_witnesses=sum(r['kind']=='witness' and r['actual']=='sat' for r in results))
    except (Exception,KeyboardInterrupt) as exc:
        manifest.update(status='failed',failure={'type':type(exc).__name__,'message':str(exc)})
        raise
    finally:
        manifest['artifact_hashes']={p.name:file_hash(p) for p in out.iterdir()
                                    if p.is_file() and p.name!='manifest.json'}
        write_json(out/'manifest.json',manifest)
    print({k:manifest[k] for k in ('status','checks','unsat_refutations','sat_premises','sat_witnesses')})


if __name__=='__main__':
    if not __debug__:
        raise SystemExit('Assertions required; do not use -O')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--solver',type=Path,required=True)
    args=parser.parse_args()
    run(args.out.resolve(),args.solver)
