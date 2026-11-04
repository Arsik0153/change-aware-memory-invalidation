"""Verify published scalar facts against hashed artifacts and render a source-linked ledger."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
REGISTRY=ROOT/'reports/research-20261104/fact-registry.json'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def locate(data, selector):
    if selector['format']=='pytest_summary':
        matches=re.findall(r'^([0-9]+) passed(?:, [^\n]+)? in [^\n]+$',data.decode(),re.MULTILINE)
        if len(matches)!=1:
            raise ValueError('Expected one pytest pass summary')
        return int(matches[0])
    if selector['format']!='json_pointer':
        raise ValueError('Unknown fact selector format')
    value=json.loads(data)
    pointer=selector['pointer']
    if not pointer.startswith('/'):
        raise ValueError('Expected an absolute JSON pointer')
    for key in pointer[1:].split('/'):
        key=key.replace('~1','/').replace('~0','~')
        value=value[int(key)] if isinstance(value,list) else value[key]
    if type(value) not in (int,float,bool,str) and value is not None:
        raise ValueError('Facts must select scalars')
    return value


def verify(registry, root=ROOT):
    if registry['schema_version'] != 1:
        raise ValueError('Unsupported fact registry schema')
    rows, seen, sources=[],set(),{}
    for study in registry['studies']:
        if not study['scope'] or not study['limits']:
            raise ValueError('Each study needs scope and limits')
        for fact in study['facts']:
            if fact['id'] in seen or not fact['unit']:
                raise ValueError('Facts need unique ids and explicit units')
            seen.add(fact['id'])
            path=(root/fact['source']).resolve()
            if not path.is_relative_to((root/'reports').resolve()):
                raise ValueError('Fact source must stay inside reports')
            data=path.read_bytes()
            if sha(data)!=fact['source_sha256']:
                raise ValueError(f"Source changed: {fact['id']}")
            value=locate(data,fact['selector'])
            if type(value) is not type(fact['expected']) or value!=fact['expected']:
                raise ValueError(f"Fact value mismatch: {fact['id']}")
            sources[fact['source']]=sha(data)
            rows.append({'study':study['id'],'study_label':study['label'],
                'id':fact['id'],'label':fact['label'],'value':value,'unit':fact['unit'],
                'source':fact['source'],'selector':fact['selector'],
                'scope':study['scope'],'limits':study['limits']})
    return rows,sources


def run(registry_path, out, root=ROOT):
    registry_bytes=registry_path.read_bytes()
    registry=json.loads(registry_bytes)
    rows,sources=verify(registry,root)
    out.mkdir(parents=True,exist_ok=False)
    (out/'registry.json').write_bytes(registry_bytes)
    (out/'facts.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False)+'\n')
    with (out/'facts.tsv').open('w',newline='') as stream:
        writer=csv.writer(stream,delimiter='\t')
        writer.writerow(['study','id','value','unit','source','selector'])
        for row in rows:
            writer.writerow([row['study'],row['id'],json.dumps(row['value'],ensure_ascii=False),
                             row['unit'],row['source'],json.dumps(row['selector'])])
    lines=['# Проверяемый реестр чисел исследования','',
           'Сгенерировано из закреплённых артефактов. Проверка предотвращает ошибки переноса чисел; она не подтверждает научную интерпретацию или независимость данных.','']
    for study in registry['studies']:
        lines.extend(['## '+study['label'],'',study['scope'],'',
                      '| Факт | Значение | Единица | Источник |','| --- | ---: | --- | --- |'])
        for row in [r for r in rows if r['study']==study['id']]:
            relative=Path(os.path.relpath(root/row['source'],out)).as_posix()
            label=Path(row['source']).relative_to('reports').as_posix()
            lines.append(f"| {row['label']} | {row['value']} | {row['unit']} | [{label}](<{relative}>) |")
        lines.extend(['','Ограничения: '+' '.join(study['limits']),''])
    (out/'verified-facts.md').write_text('\n'.join(lines))
    if registry_path.read_bytes()!=registry_bytes:
        raise ValueError('Registry changed during rendering')
    if any(sha((root/name).read_bytes())!=expected for name,expected in sources.items()):
        raise ValueError('Evidence changed during rendering')
    manifest={'status':'passed','registry_sha256':sha(registry_bytes),
              'registry_snapshot':'registry.json','script_sha256':sha(Path(__file__).read_bytes()),'facts':len(rows),
              'studies':len(registry['studies']),'source_hashes':sources,
              'artifact_hashes':{p.name:sha(p.read_bytes()) for p in out.iterdir() if p.is_file()}}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print({'facts':len(rows),'studies':len(registry['studies']),'sources':len(sources)})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry',type=Path,default=REGISTRY)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    run(args.registry,args.out)
