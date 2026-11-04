"""Synthetic overlap-record denial matrix. No Git/corpus/outcome artifact access."""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'runs/real-structural-extension-runner-development-20261104'))
from real_structural_first_parent_support import compare_overlap

validation={'input_hash':'actual-bound-hash','verdict':'supported','reason':'predicate_matches','duration_seconds':1.0,'cpu_seconds':0.5}
provenance={'anchors':[{'content_hash':'original-anchor'}],'known_incomplete':False}
state={'last_checked_commit':'checked','available':True}
reference={'verdict':'supported','facts':{'signature':{'parameters':[{'name':'x'}]}}}
old={'group_id':'g','commit':'child','claim_id':'c','variant':'symbol_anchor','eligible':True,
 'provenance':provenance,'previous_state':{'revision':'parent'},'selection':{'selected':False},
 'state':state,'validation':validation,'full_production_validation':deepcopy(validation),'reference':reference}
parent={'group_id':'g','claim':{'claim_id':'c','predicate':{'expected_signature':{'is_async':False}}},
 'claim_sha256':'bound-claim','eligible':True,'exclusion_reasons':[],
 'ai_confirmation':{'reviews':[{'item_id':'actual-reviewed-case'}]},'reference':deepcopy(reference),
 'variants':{'symbol_anchor':{'provenance':deepcopy(provenance),'validation':deepcopy(validation),'state':deepcopy(state)}}}
record=deepcopy(old)
record['trajectory']={'coverage_stratum':'old_overlap'}
record['reference']['case_path']='/new/case.json'
for key in ['validation','full_production_validation']:
 record[key]['duration_seconds']=99.0;record[key]['cpu_seconds']=88.0
newparent=deepcopy(parent)
newparent['reference']['packet_path']='/new/packet'
newparent['variants']['symbol_anchor']['validation']['duration_seconds']=999.0
assert compare_overlap([record],[newparent],[old],[parent],OUT/'overlap-positive')['status']=='matched'
mutations=[
 ('observation','provenance.anchors.0.content_hash','different-anchor'),
 ('observation','validation.input_hash','different-validation-input'),
 ('observation','full_production_validation.input_hash','different-full-input'),
 ('observation','selection.selected',True),
 ('observation','state.last_checked_commit','different-check'),
 ('observation','previous_state.revision','different-parent'),
 ('observation','reference.facts.signature.parameters.0.name','different-parameter'),
 ('parent','claim.predicate.expected_signature.is_async',True),
 ('parent','claim_sha256','different-claim-hash'),
 ('parent','ai_confirmation.reviews.0.item_id','different-AI-case'),
 ('parent','variants.symbol_anchor.provenance.known_incomplete',True),
 ('parent','variants.symbol_anchor.validation.input_hash','different-parent-input'),
 ('parent','variants.symbol_anchor.state.available',False),
 ('parent','reference.facts.signature.parameters.0.name','different-parent-fact'),
 ('parent','eligible',False),
]
checks=[]
for number,(target,path,value) in enumerate(mutations):
 r,p=deepcopy(record),deepcopy(newparent)
 dest=r if target=='observation' else p
 parts=path.split('.')
 for part in parts[:-1]:dest=dest[int(part)] if isinstance(dest,list) else dest[part]
 dest[int(parts[-1]) if isinstance(dest,list) else parts[-1]]=value
 packet=OUT/'overlap-denials'/str(number)
 try:
  compare_overlap([r],[p],[old],[parent],packet)
 except ValueError as error:
  assert 'semantic mismatch' in str(error)
  assert json.loads((packet/'overlap-check.json').read_text())['status']=='mismatch'
  checks.append({'target':target,'field':path,'rejected':True})
 else:
  raise AssertionError((target,path,'semantic edit accepted'))
result={'synthetic_only':True,'explicit_volatile_fields_accepted':True,'semantic_edits_rejected':checks,'corpus_access':False}
(OUT/'overlap_denial_results.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'semantic_denials_passed':len(checks),'volatile_positive_passed':True,'corpus_access':False}))
