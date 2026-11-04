"""Metadata/source-code audit only. No Git or corpus source/tree/outcome reads."""
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'runs/real-structural-extension-planning-20261104'
OUT=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text())
plan=read(BASE/'proposed_protocol.json')
meta=read(BASE/'metadata_manifest.json')
old=read(ROOT/plan['old_protocol']['path'])
oldseal=read(ROOT/plan['old_protocol']['seal_path'])
full=read(BASE/'candidate_population.json')
added=read(BASE/'new_candidate_population.json')
groups={g['group_id']:g for g in plan['groups']}
oldgroups={g['group_id']:g for g in old['groups']}
trajectories={t['group_id']:t for t in meta['trajectories']}
assert len(groups)==len(oldgroups)==len(trajectories)==3
summaries=[]
for group_id,group in groups.items():
    trajectory=trajectories[group_id]
    oldgroup=oldgroups[group_id]
    assert group['child_commits'][:len(oldgroup['child_commits'])]==oldgroup['child_commits']
    assert len(group['child_commits'])==len(trajectory['steps'])==12
    previous=group['parent_commit']
    for number,step in enumerate(trajectory['steps'],1):
        assert step['step']==number and step['commit']==group['child_commits'][number-1]
        assert step['previous_commit']==previous and step['parents'][0]==previous
        assert step['is_merge']==(len(step['parents'])>1)
        assert step['already_in_old_protocol']==(step['commit'] in oldgroup['child_commits'])
        previous=step['commit']
    rows=[r for r in full if r['group_id']==group_id]
    assert len(rows)==96
    summaries.append({'group_id':group_id,'full_per_variant':len(rows),'added_per_variant':sum(not r['already_in_old_protocol'] for r in rows),'old_overlap_per_variant':sum(r['already_in_old_protocol'] for r in rows),'merge_per_variant':sum(r['is_merge'] for r in rows),'nonmerge_per_variant':sum(not r['is_merge'] for r in rows)})
key=lambda r:(r['group_id'],r['child_commit'],r['claim_id'])
assert len(full)==len({key(r) for r in full})==288
assert len(added)==176 and added==[r for r in full if not r['already_in_old_protocol']]
assert sum(r['already_in_old_protocol'] for r in full)==112
assert sum(r['is_merge'] for r in full)==80
assert sum(not r['is_merge'] for r in full)==208
critical=['src/cami/repository.py','scripts/run_real_structural_replay.py','scripts/real_structural_replay_support.py','src/cami/index.py','src/cami/policies.py','src/cami/validation.py']
identity=[]
for name in critical:
    current=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    identity.append({'path':name,'old_sha256':oldseal['files'][name],'current_sha256':current,'unchanged':current==oldseal['files'][name]})
assert all(row['unchanged'] for row in identity)
result={'metadata_audit':'passed_without_Git_or_corpus_access','groups':summaries,'full_per_variant':288,'new_per_variant':176,'old_overlap_per_variant':112,'merge_per_variant':80,'nonmerge_per_variant':208,'full_four_variants':1152,'new_four_variants':704,'old_overlap_four_variants':448,'critical_old_sources':identity,'strata_note':'Coverage partition and topology partition are separate descriptions of the same dependent observations. They are not additive independent samples.'}
(OUT/'metadata_audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in {'critical_old_sources','groups'}}))
