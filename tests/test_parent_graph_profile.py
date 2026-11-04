import hashlib

from cami.index import build_index
from cami.models import Anchor, Provenance
from cami.repository import Blob, Snapshot
from scripts.check_parent_graph_profile import claim_facts, module_facts
from scripts.check_structural_carry import claims


def snapshot(files):
    blobs=[]
    for name,text in files.items():
        data=text.encode()
        oid=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        blobs.append(Blob(name,oid,'100644',data,None))
    return Snapshot('fixture','parent',tuple(blobs))


def test_other_module_import_is_global_without_marking_clean_subject():
    source=snapshot({'module.py':'def f(x):\n    return x\n', 'other.py':'import math\n'})
    index=build_index(source)
    facts={m['path']:m for m in module_facts(index,source)}
    assert facts['other.py']['module_unresolved_added_by_linking']
    assert not facts['other.py']['module_unresolved_after_parse']
    claim=claims(source,'clean')[0]
    prov=Provenance(claim_id=claim.claim_id,scenario_id='intact',known_incomplete=True,
        anchors=(Anchor(path='module.py',qualname='f',scope='symbol',observed_commit='parent',
                        content_hash=source.blobs[0].content_hash,origin='manual'),))
    row=claim_facts(claim,prov,index)
    assert row['global_unresolved'] and row['known_incomplete']
    assert not row['subject_direct_unresolved'] and not row['subject_module_unresolved']
    assert row['matching_definitions']==1 and not row['any_ambiguous']


def test_parser_wildcard_flag_is_distinguished_from_linking_addition():
    source=snapshot({'module.py':'from absent import *\n'})
    row,=module_facts(build_index(source),source)
    assert row['module_unresolved_after_parse'] and row['module_unresolved_after_linking']
    assert not row['module_unresolved_added_by_linking']


def test_closed_literal_fixture_has_no_global_unresolved_flag():
    source=snapshot({'module.py':'def f():\n    return 1\n'})
    index=build_index(source)
    assert not index.global_unresolved
    row,=module_facts(index,source)
    assert not row['module_unresolved_after_linking'] and row['limitation'] is None
