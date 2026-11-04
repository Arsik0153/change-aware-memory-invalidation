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


def test_viewer_shows_parent_evidence_without_executing_source_markup(tmp_path):
    source = prepared(tmp_path)
    payload = '<script>alert("source")</script>\n<a href="https://invalid">x</a>\n'
    (source / 'annotation/sources/parent.py').write_text(payload)
    path = source / 'annotation/packets.jsonl'
    rows = read_jsonl(path)
    rows[0]['source_evidence']['parent'][0]['sha256'] = file_hash(
        source / 'annotation/sources/parent.py')
    rows[0]['claim']['text'] = '<img src=x onerror=alert(1)>'
    rows[0]['claim_sha256'] = digest(rows[0]['claim'])
    write_jsonl(path, rows)
    seal(source)
    output = tmp_path / 'review'
    exporter.export(source, output)
    markup = (output / 'review.html').read_text()
    assert '&lt;img src=x onerror=alert(1)&gt;' in markup
    assert '<img' not in markup
    assert 'child' not in markup
    assert 'primary_form.jsonl' in markup and 'second_form.jsonl' in markup
    assert 'Второй разметчик назначен</dt><dd>Да' in markup
    evidence = next((output / 'review-assets').glob('*.html')).read_text()
    assert '<script>' not in evidence
    assert '&lt;script&gt;' in evidence
    assert 'id="L2"' in evidence
    assert "default-src 'none'" in evidence
    assert (output / 'sources/parent.py').read_text() == payload
    assert read_jsonl(output / 'primary_form.jsonl')[0]['label'] is None


@pytest.mark.parametrize('relative', ['review.html', 'review-assets/source.py', 'primary_form.jsonl'])
def test_evidence_cannot_overwrite_exported_artifacts(tmp_path, relative):
    source = prepared(tmp_path)
    path = source / 'annotation/packets.jsonl'
    rows = read_jsonl(path)
    target = source / 'annotation' / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('source')
    rows[0]['source_evidence']['parent'][0]['evidence_path'] = relative
    rows[0]['source_evidence']['parent'][0]['sha256'] = file_hash(target)
    write_jsonl(path, rows)
    seal(source)
    output = tmp_path / 'rejected'
    with pytest.raises(InputError, match='conflicts with exported review files'):
        exporter.export(source, output)
    assert not output.exists()


def test_viewer_retains_missing_evidence_limitation_and_probe(tmp_path):
    source = prepared(tmp_path)
    path = source / 'annotation/packets.jsonl'
    rows = read_jsonl(path)
    entry = rows[0]['source_evidence']['parent'][0]
    entry.update(evidence_path=None, sha256=None, limitation='not available <reason>')
    probe = source / 'annotation/probes/test_frozen.py'
    probe.parent.mkdir()
    probe.write_bytes(b'assert True\n# \xff\n')
    rows[0]['probe'] = {'path': 'probes/test_frozen.py', 'sha256': file_hash(probe),
                        'node_id': 'test_frozen.py::test_example'}
    write_jsonl(path, rows)
    seal(source)
    output = tmp_path / 'review'
    exporter.export(source, output)
    markup = (output / 'review.html').read_text()
    assert 'исходник отсутствует' in markup
    assert 'not available &lt;reason&gt;' in markup
    assert 'test_frozen.py::test_example' in markup
    assert (output / 'probes/test_frozen.py').read_bytes() == probe.read_bytes()
    assert '\ufffd' in next((output / 'review-assets').glob('*.html')).read_text()


@pytest.mark.parametrize('newline', ['\n', '\r\n', '\r'])
def test_source_line_numbers_match_python_with_form_feed(tmp_path, newline):
    import ast
    from html.parser import HTMLParser

    source = prepared(tmp_path)
    code = newline.join(['# comment\fstill same line', 'def f():', '    return 1', ''])
    (source / 'annotation/sources/parent.py').write_bytes(code.encode())
    path = source / 'annotation/packets.jsonl'
    rows = read_jsonl(path)
    rows[0]['source_evidence']['parent'][0]['sha256'] = file_hash(
        source / 'annotation/sources/parent.py')
    write_jsonl(path, rows)
    seal(source)
    output = tmp_path / 'review'
    exporter.export(source, output)

    class Lines(HTMLParser):
        def __init__(self):
            super().__init__()
            self.current = None
            self.definition_line = None

        def handle_starttag(self, tag, attrs):
            if tag == 'span':
                self.current = dict(attrs)['id']

        def handle_data(self, data):
            if 'def f():' in data:
                self.definition_line = self.current

    lines = Lines()
    lines.feed(next((output / 'review-assets').glob('*.html')).read_text())
    assert lines.definition_line == f'L{ast.parse(code).body[0].lineno}' == 'L2'
    assert (output / 'sources/parent.py').read_bytes() == code.encode()
