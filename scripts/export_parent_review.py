"""Export blank parent-review materials without child revisions or policy information."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from cami.artifacts import canonical, digest, file_hash, read_json, read_jsonl, reserve, within, write_json, write_jsonl
from cami.errors import InputError
from cami.models import Claim

ANSWER_FIELDS = ('annotation_id', 'annotator_id', 'annotator_kind', 'independent',
                 'label', 'confirmation_type', 'annotation_minutes')
FORM_FIELDS = {'schema_version', 'claim_id', 'commit', 'evidence', *ANSWER_FIELDS}
SOURCE_FIELDS = {'commit', 'path', 'object_id', 'sha256', 'limitation', 'evidence_path'}
PROBE_FIELDS = {'path', 'sha256', 'node_id'}


def export(prepared: Path, output: Path) -> None:
    if output.resolve().is_relative_to(prepared.resolve()):
        raise InputError('parent review output must be outside prepared inputs')
    annotation = prepared / 'annotation'
    hashes = read_json(prepared / 'preparation_hashes.json')
    names = ('packets.jsonl', 'parent_confirmation_form.jsonl', 'second_form.jsonl')
    for name in names:
        if file_hash(annotation / name) != hashes[f'annotation/{name}']:
            raise InputError(f'prepared annotation hash mismatch: {name}')
    packets = read_jsonl(annotation / 'packets.jsonl')
    expected = {(row['claim']['claim_id'], row['parent_commit']) for row in packets}
    if not packets or len(expected) != len(packets):
        raise InputError('empty or duplicate parent packet identities')
    parents = []
    sources: dict[str, Path] = {}
    for packet in packets:
        Claim.model_validate_json(canonical(packet['claim']))
        parent = packet['parent_commit']
        if (packet['claim']['origin_commit'] != parent
                or digest(packet['claim']) != packet['claim_sha256']):
            raise InputError('parent claim identity or hash mismatch')
        evidence = packet['source_evidence'][parent]
        for entry in evidence:
            if set(entry) != SOURCE_FIELDS:
                raise InputError('unexpected parent source fields')
            if entry['commit'] != parent:
                raise InputError('parent source entry names a different revision')
            if entry['evidence_path'] is not None:
                source = within(annotation, entry['evidence_path'])
                if file_hash(source) != entry['sha256']:
                    raise InputError('parent source hash mismatch')
                sources[entry['evidence_path']] = source
        probe = packet['probe']
        if probe:
            if set(probe) != PROBE_FIELDS:
                raise InputError('unexpected parent probe fields')
            source = within(annotation, probe['path'])
            if file_hash(source) != probe['sha256']:
                raise InputError('parent probe hash mismatch')
            sources[probe['path']] = source
        parents.append({key: packet[key] for key in (
            'schema_version', 'run_id', 'repo_id', 'claim', 'claim_sha256', 'parent_commit', 'probe')}
                       | {'source_evidence': {parent: evidence}})
    primary = read_jsonl(annotation / 'parent_confirmation_form.jsonl')
    secondary = [row for row in read_jsonl(annotation / 'second_form.jsonl')
                 if (row['claim_id'], row['commit']) in expected]
    if len(primary) != len(expected) or {(r['claim_id'], r['commit']) for r in primary} != expected:
        raise InputError('parent form differs from parent packet population')
    if len({(r['claim_id'], r['commit']) for r in secondary}) != len(secondary):
        raise InputError('duplicate secondary parent assignment')
    for row in primary + secondary:
        if set(row) != FORM_FIELDS:
            raise InputError('unexpected parent form fields')
        if any(row[field] is not None for field in ANSWER_FIELDS) or row['evidence'] != []:
            raise InputError('only blank forms may be exported for independent parent review')
    reserve(output)
    write_jsonl(output / 'packets.jsonl', parents)
    write_jsonl(output / 'primary_form.jsonl', primary)
    write_jsonl(output / 'second_form.jsonl', secondary)
    for relative, source in sources.items():
        target = within(output, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    write_json(output / 'manifest.json', {
        'scope': 'parent-only blank review material', 'parent_items': len(primary),
        'second_parent_items': len(secondary), 'copied_evidence_files': len(sources),
        'source_packet_sha256': hashes['annotation/packets.jsonl'],
        'child_revisions_exported': False, 'independent_answers_present': False,
        'limitations': ['Repository IDs and parent commit identities remain visible.',
                        'Candidate text and syntax are not independent truth evidence.'],
        'artifact_hashes': {p.relative_to(output).as_posix(): file_hash(p)
                            for p in sorted(output.rglob('*')) if p.is_file()},
    })


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    export(args.prepared, args.out)
