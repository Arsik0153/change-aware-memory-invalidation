from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from cami.artifacts import digest, file_hash, read_json, read_jsonl, write_json, write_jsonl
from cami.errors import InputError
from cami.models import Claim

SPEC = importlib.util.spec_from_file_location(
    'export_parent_review', Path(__file__).resolve().parents[1] / 'scripts/export_parent_review.py')
assert SPEC and SPEC.loader
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def prepared(tmp_path):
    root = tmp_path / 'prepared'
    annotation = root / 'annotation'
    (annotation / 'sources').mkdir(parents=True)
    for revision in ('parent', 'child'):
        (annotation / f'sources/{revision}.py').write_text(f'# {revision} source\n')
    claim = Claim(claim_id='c', repo_id='repo', origin_commit='parent',
                  kind='symbol_exists', text='parent-only candidate', scope='exact',
                  subject={'path': 'module.py', 'qualname': 'f', 'node_kind': 'function'},
                  predicate={'type': 'symbol_exists', 'expected': True}).model_dump(mode='json')
    packet = {'schema_version': 1, 'repo_id': 'repo', 'run_id': 'run', 'claim': claim,
              'claim_sha256': digest(claim), 'parent_commit': 'parent', 'child_commits': ['child'],
              'probe': None, 'source_evidence': {revision: [{
                  'commit': revision, 'path': 'module.py', 'object_id': None, 'limitation': None,
                  'evidence_path': f'sources/{revision}.py',
                  'sha256': file_hash(annotation / f'sources/{revision}.py')
              }] for revision in ('parent', 'child')}}
    form = {'schema_version': 1, 'claim_id': 'c', 'commit': 'parent', 'evidence': [],
            **dict.fromkeys(exporter.ANSWER_FIELDS)}
    write_jsonl(annotation / 'packets.jsonl', [packet])
    write_jsonl(annotation / 'parent_confirmation_form.jsonl', [form])
    write_jsonl(annotation / 'second_form.jsonl', [form, {**form, 'commit': 'child'}])
    seal(root)
    return root


def seal(root):
    write_json(root / 'preparation_hashes.json', {
        f'annotation/{name}': file_hash(root / 'annotation' / name)
        for name in ('packets.jsonl', 'parent_confirmation_form.jsonl', 'second_form.jsonl')})


def test_parent_export_omits_child_files_metadata_and_assignments(tmp_path):
    source = prepared(tmp_path)
    output = tmp_path / 'parent-review'
    exporter.export(source, output)
    packet = read_jsonl(output / 'packets.jsonl')[0]
    assert 'child_commits' not in packet
    assert set(packet['source_evidence']) == {'parent'}
    assert not (output / 'sources/child.py').exists()
    assert (output / 'sources/parent.py').read_bytes() == (
        source / 'annotation/sources/parent.py').read_bytes()
    assert len(read_jsonl(output / 'primary_form.jsonl')) == 1
    assert len(read_jsonl(output / 'second_form.jsonl')) == 1
    manifest = read_json(output / 'manifest.json')
    for relative, expected in manifest['artifact_hashes'].items():
        assert file_hash(output / relative) == expected
    with pytest.raises(InputError, match='output already exists'):
        exporter.export(source, output)


@pytest.mark.parametrize('corruption', ['answer', 'source', 'packet_hash', 'population'])
def test_invalid_parent_materials_fail_before_output(tmp_path, corruption):
    source = prepared(tmp_path)
    if corruption == 'source':
        (source / 'annotation/sources/parent.py').write_text('changed source')
    elif corruption == 'packet_hash':
        (source / 'annotation/packets.jsonl').write_text('changed packet')
    else:
        form = read_jsonl(source / 'annotation/parent_confirmation_form.jsonl')[0]
        if corruption == 'answer':
            form['label'] = 'supported'
        else:
            form['commit'] = 'child'
        write_jsonl(source / 'annotation/parent_confirmation_form.jsonl', [form])
        seal(source)
    output = tmp_path / 'rejected'
    with pytest.raises(InputError):
        exporter.export(source, output)
    assert not output.exists()


@pytest.mark.parametrize('target', ['primary_form', 'secondary_form', 'source'])
def test_unknown_fields_cannot_leak_child_or_policy_metadata(tmp_path, target):
    source = prepared(tmp_path)
    if target == 'source':
        path = source / 'annotation/packets.jsonl'
        rows = read_jsonl(path)
        rows[0]['source_evidence']['parent'][0]['child_commits'] = ['child']
    else:
        name = 'parent_confirmation_form' if target == 'primary_form' else 'second_form'
        path = source / f'annotation/{name}.jsonl'
        rows = read_jsonl(path)
        rows[0]['policy_outcome'] = 'supported'
    write_jsonl(path, rows)
    seal(source)
    output = tmp_path / 'rejected'
    with pytest.raises(InputError, match='unexpected parent'):
        exporter.export(source, output)
    assert not output.exists()


def test_signature_claim_json_arrays_are_accepted(tmp_path):
    source = prepared(tmp_path)
    path = source / 'annotation/packets.jsonl'
    rows = read_jsonl(path)
    claim = rows[0]['claim']
    claim['kind'] = 'signature_equals'
    claim['predicate'] = {'type': 'signature_equals', 'expected_signature': {
        'parameters': [], 'decorators_ast': [], 'returns_ast': None, 'is_async': False}}
    rows[0]['claim_sha256'] = digest(claim)
    write_jsonl(path, rows)
    seal(source)
    output = tmp_path / 'review'
    exporter.export(source, output)
    assert read_jsonl(output / 'packets.jsonl')[0]['claim'] == claim
