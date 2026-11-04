from cami.models import Anchor, Provenance
from cami.structural_closure import DRAFT_REASON
from scripts.check_structural_carry import claims, snapshot
from scripts.check_structural_prerequisites import profile


def inputs(source):
    snap = snapshot(source)
    claim = claims(snap, 'profile')[0].model_copy(update={
        'text': 'module.py contains the exact top-level function definition f.',
        'scope': 'Exact syntactic definition identity only.'})
    provenance = Provenance(claim_id=claim.claim_id, scenario_id='intact',
        known_incomplete=True, unresolved_reasons=(DRAFT_REASON,),
        anchors=(Anchor(path='module.py', qualname='f', scope='symbol', origin='static',
                        observed_commit=snap.revision, content_hash=snap.blobs[0].content_hash),))
    return claim, provenance, snap


def test_unrelated_body_write_is_only_binding_failure():
    claim, prov, snap = inputs('def f(x): return x\ndef g(obj): obj.value = 1\n')
    row = profile(claim, prov, snap, ('.',), {})
    assert row['all_except_binding_gate_pass']
    assert not row['all_observed_conditions_pass']
    assert row['binding_first_reasons'][0]['reason'] == 'indirect namespace write uncertainty'
    assert prov.known_incomplete and prov.unresolved_reasons == (DRAFT_REASON,)


def test_bad_anchor_does_not_hide_other_conditions():
    claim, prov, snap = inputs('def f(x): return x\n')
    bad = prov.model_copy(update={'anchors': (prov.anchors[0].model_copy(update={'content_hash': '0'*64}),)})
    row = profile(claim, bad, snap, ('.',), {})
    assert row['conditions']['whole_module_binding_gate']
    assert not row['conditions']['anchor_identity_and_bounds']
    assert not row['all_except_binding_gate_pass']


def test_missing_blob_is_unavailable_for_signature():
    claim, prov, snap = inputs('def f(x): return x\n')
    claim = claims(snap, 'profile')[1]
    row = profile(claim, prov, snapshot(None), ('.',), {})
    assert not row['conditions']['readable_regular_support_in_roots']
    assert row['conditions']['signature_matches'] is None
    assert row['conditions']['whole_module_binding_gate'] is None
    assert not row['all_observed_conditions_pass']
