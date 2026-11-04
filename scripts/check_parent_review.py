"""Audit exported parent HTML links, blank assignments, and manifest hashes offline."""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from cami.artifacts import file_hash, read_json, read_jsonl, within, write_json


class Document(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.tags: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.add(tag)
        attributes = dict(attrs)
        if href := attributes.get('href'):
            self.links.append(href)
        if identity := attributes.get('id'):
            assert identity not in self.ids, f'duplicate HTML id: {identity}'
            self.ids.add(identity)


def check(root: Path) -> dict:
    documents = {}
    for path in root.rglob('*.html'):
        document = Document()
        document.feed(path.read_text(encoding='utf-8'))
        documents[path.resolve()] = document
        assert not {'script', 'iframe', 'img', 'form', 'input'} & document.tags
    links = 0
    for path, document in documents.items():
        for href in document.links:
            url = urlsplit(href)
            assert not url.scheme and not url.netloc, (path, href)
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            assert target.is_relative_to(root.resolve()) and target.is_file(), (path, href)
            if url.fragment:
                assert unquote(url.fragment) in documents[target].ids, (path, href)
            links += 1
    manifest = read_json(root / 'manifest.json')
    for relative, sha in manifest['artifact_hashes'].items():
        assert file_hash(within(root, relative)) == sha, relative
    packets = read_jsonl(root / 'packets.jsonl')
    claims = {i for i in documents[(root / 'review.html').resolve()].ids
              if i.startswith('claim-')}
    assert len(claims) == len(packets) == manifest['parent_items']
    population = {(p['claim']['claim_id'], p['parent_commit']) for p in packets}
    assert len(population) == len(packets)
    for packet in packets:
        assert set(packet['source_evidence']) == {packet['parent_commit']}
        assert 'child_commits' not in packet
    for form in ('primary_form.jsonl', 'second_form.jsonl'):
        rows = read_jsonl(root / form)
        identities = {(r['claim_id'], r['commit']) for r in rows}
        assert len(identities) == len(rows)
        assert identities <= population
        if form == 'primary_form.jsonl':
            assert identities == population
        else:
            assert len(rows) == manifest['second_parent_items']
        for row in rows:
            assert row['evidence'] == []
            assert all(row[key] is None for key in (
                'annotation_id', 'annotator_id', 'annotator_kind', 'independent',
                'label', 'confirmation_type', 'annotation_minutes'))
    return {'parent_items': len(packets), 'second_parent_items': manifest['second_parent_items'],
            'html_pages': len(documents), 'local_links_checked': links,
            'hashed_artifacts': len(manifest['artifact_hashes']),
            'manifest_sha256': file_hash(root / 'manifest.json'),
            'blank_answers_preserved': True,
            'checks': 'HTML parser, local targets/fragments, hashes and parent-only assignments; '
                      'no browser run; not independent truth evidence',
            'audit_script_sha256': file_hash(Path(__file__))}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('output already exists')
    if args.out.resolve().is_relative_to(args.package.resolve()):
        parser.error('audit output must be outside the package')
    write_json(args.out, check(args.package))
