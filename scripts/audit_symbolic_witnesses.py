"""Check SMT output hashes and independently evaluate every saved SAT transition."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


def require(condition,message):
    if not condition:
        raise ValueError(message)


def values(stdout):
    tokens=re.findall(r'[()]|[^\s()]+',stdout.split('\n',1)[1])
    offset=0

    def expression():
        nonlocal offset
        require(offset<len(tokens),'Incomplete S-expression')
        token=tokens[offset]
        offset+=1
        if token!='(':
            require(token!=')','Unexpected closing bracket')
            return token
        result=[]
        while offset<len(tokens) and tokens[offset]!=')':
            result.append(expression())
        require(offset<len(tokens),'Unclosed S-expression')
        offset+=1
        return result

    pairs=expression()
    require(offset==len(tokens) and isinstance(pairs,list),'Expected one value list')
    result={}
    for pair in pairs:
        require(isinstance(pair,list) and len(pair)==2,'Expected value pair')
        name,value=pair
        require(isinstance(name,str) and name not in result,'Duplicate or invalid model name')
        if value in ('true','false'):
            parsed=value=='true'
        elif isinstance(value,list):
            require(len(value)==2 and value[0]=='-','Unsupported arithmetic value')
            parsed=-int(value[1])
        else:
            parsed=int(value)
        result[name]=parsed
    require(set(result)=={'K','b0','t0','a0','hint','t1','v','changed','step','selected','a1','b1'},
            'Unexpected model projection')
    integers={'K','b0','v','step','b1'}
    require(all(type(value) is (int if name in integers else bool) for name,value in result.items()),
            'Model projection has incorrect types')
    return result


def check_transition(model,variant):
    m=model
    observed=0 if variant=='reset_on_change' and m['changed'] else m['b0']
    due=observed+1>m['K'] if variant=='deadline_off_by_one' else observed+1>=m['K']
    selected=m['hint'] or due or (not m['a0'] and variant!='missing_unavailable_retry')
    available=(m['a0'] if variant=='carry_on_insufficient' and m['v']==2 else m['v']==0) if selected else m['a0']
    age=0 if selected else observed+1
    require((selected,available,age)==(m['selected'],m['a1'],m['b1']),'SAT transition disagrees with ordinary evaluation')
    require(m['K']>=1 and m['v'] in (0,1,2),'Invalid symbolic domain')
    if variant!='false_positive_supported':
        require(not (selected and m['v']==0) or m['t1'],'Positive soundness violated')


def audit(root):
    manifest=json.loads((root/'manifest.json').read_text())
    require(manifest['status']=='complete','Incomplete symbolic run')
    require(manifest['source_before']==manifest['source_after'],'Changed runtime source')
    for name,expected in manifest['artifact_hashes'].items():
        require(hashlib.sha256((root/name).read_bytes()).hexdigest()==expected,'Changed artifact: '+name)
    rows=json.loads((root/'results.json').read_text())
    models=[]
    for row in rows:
        stdout=(root/(row['id']+'.stdout')).read_text()
        require(stdout.splitlines()[0]==row['actual']==row['expected'],'Unexpected solver status')
        if row['actual']=='unsat':
            require('(proof' in stdout,'Missing solver proof object')
            continue
        model=values(stdout)
        variant=row['id'] if row['kind']=='witness' else 'normal'
        check_transition(model,variant)
        if row['kind']=='witness':
            unsafe=model['a1'] and not model['t1']
            if variant=='incomplete_can_withhold':
                require(model['t1'] and not model['a1'] and model['v']==2,'Missing inconclusive withholding witness')
            elif variant in ('false_positive_supported','carry_on_insufficient'):
                require(unsafe and model['b1']==0,'Missing unsafe age-zero witness')
            elif variant=='deadline_off_by_one':
                require(unsafe and model['b1']>=model['K'],'Missing deadline witness')
            elif variant=='reset_on_change':
                require(unsafe and model['a0'] and not model['t0'] and model['b1']!=model['b0']+1,'Missing rank witness')
            elif variant=='missing_unavailable_retry':
                require(not model['a0'] and model['t1'] and not model['a1'] and not model['selected'],'Missing retry witness')
        models.append({'id':row['id'],'kind':row['kind'],'values':model})
    return {'status':'passed','artifact_hashes_verified':len(manifest['artifact_hashes']),
            'sat_transitions_evaluated':len(models),'unsat_proof_objects_present':sum(r['actual']=='unsat' for r in rows),
            'proof_kernel_checked':False,'models':models,
            'auditor_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    result=audit(args.run)
    with args.out.open('x') as stream:
        json.dump(result,stream,indent=2)
        stream.write('\n')
    print({k:v for k,v in result.items() if k!='models'})
