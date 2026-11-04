import hashlib
import json

import pytest

from scripts.check_research_facts import locate,verify


def registry(tmp_path):
    folder=tmp_path/'reports'
    folder.mkdir()
    data=b'{"behavior_claims":63,"ready":true}\n'
    (folder/'summary.json').write_bytes(data)
    fact={'id':'behavior.count','label':'Behavior candidates','source':'reports/summary.json',
          'source_sha256':hashlib.sha256(data).hexdigest(),
          'selector':{'format':'json_pointer','pointer':'/behavior_claims'},'expected':63,'unit':'claim'}
    return {'schema_version':1,'studies':[{'id':'parents','label':'Parents','scope':'Parent only',
            'limits':['Not labels'],'facts':[fact]}]},fact


def test_wrong_transcribed_count_is_rejected(tmp_path):
    data,fact=registry(tmp_path)
    rows,_=verify(data,tmp_path)
    assert rows[0]['value']==63
    fact['expected']=126
    with pytest.raises(ValueError,match='Fact value mismatch'):
        verify(data,tmp_path)


def test_changed_source_is_not_silently_accepted(tmp_path):
    data,_=registry(tmp_path)
    (tmp_path/'reports/summary.json').write_text('{"behavior_claims":126}')
    with pytest.raises(ValueError,match='Source changed'):
        verify(data,tmp_path)


def test_bool_is_not_the_integer_one(tmp_path):
    data,fact=registry(tmp_path)
    fact['selector']['pointer']='/ready'
    fact['expected']=1
    with pytest.raises(ValueError,match='Fact value mismatch'):
        verify(data,tmp_path)


def test_json_pointer_preserves_slashes_in_keys():
    data=json.dumps({'exposure/intact':{'median':1.25}}).encode()
    assert locate(data,{'format':'json_pointer','pointer':'/exposure~1intact/median'})==1.25


def test_ambiguous_test_log_is_rejected():
    data=b'3 passed in 0.1s\n4 passed in 0.2s\n'
    with pytest.raises(ValueError,match='one pytest'):
        locate(data,{'format':'pytest_summary'})


def test_limits_and_units_are_required(tmp_path):
    data,fact=registry(tmp_path)
    fact['unit']=''
    with pytest.raises(ValueError,match='explicit units'):
        verify(data,tmp_path)
    fact['unit']='claim'
    data['studies'][0]['limits']=[]
    with pytest.raises(ValueError,match='scope and limits'):
        verify(data,tmp_path)


def test_generated_ledger_keeps_registry_after_original_is_removed(tmp_path):
    from scripts.check_research_facts import run
    data,_=registry(tmp_path)
    source=tmp_path/'registry.json'
    source.write_text(json.dumps(data))
    out=tmp_path/'reports/ledger'
    run(source,out,tmp_path)
    source.unlink()
    rows,_=verify(json.loads((out/'registry.json').read_text()),tmp_path)
    assert rows[0]['value']==63
    manifest=json.loads((out/'manifest.json').read_text())
    assert manifest['artifact_hashes']['registry.json']==manifest['registry_sha256']
