"""Seal a rendered report after PDF-specific visual review and build its portable ZIP."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def finalize(report: Path, review: Path, archive: Path, delivery: Path) -> dict:
    report, review, archive, delivery = (p.resolve() for p in (report, review, archive, delivery))
    if archive.exists() or archive.is_relative_to(report) or delivery.is_relative_to(report):
        raise ValueError('Use a new archive and delivery outside the report directory')
    manifest = json.loads((report / 'manifest.json').read_text())
    visual = json.loads(review.read_text())
    if manifest['status'] != 'rendered_pending_visual_review':
        raise ValueError('Expected a rendered report pending visual review')
    if manifest['source_before'] != manifest['source_after']:
        raise ValueError('Build source snapshots differ')
    files = {p.relative_to(report).as_posix(): p for p in report.rglob('*') if p.is_file()}
    if files.keys() != manifest['artifact_hashes'].keys() | {'manifest.json'}:
        raise ValueError('Unexpected or missing report files')
    for name, expected in manifest['artifact_hashes'].items():
        if files[name].is_symlink() or sha(files[name]) != expected:
            raise ValueError(f'Report artifact changed: {name}')
    stem = manifest['report_spec']['artifact_stem']
    pdf = report / (stem + '.pdf')
    if (visual.get('status') != 'passed' or visual.get('pdf_sha256') != sha(pdf)
            or not visual.get('reviewer') or type(visual.get('pages')) is not int
            or visual['pages'] < 1):
        raise ValueError('A passed visual review bound to this exact PDF is required')
    if json.loads((report / 'text-check.json').read_text())['status'] != 'passed':
        raise ValueError('PDF text verification did not pass')
    write(report / 'visual-review.json', visual)
    manifest.update(status='complete', visual_review='visual-review.json')
    manifest['artifact_hashes']['visual-review.json'] = sha(report / 'visual-review.json')
    write(report / 'manifest.json', manifest)
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as zipped:
        for name in sorted(manifest['artifact_hashes'].keys() | {'manifest.json'}):
            zipped.write(report / name, name)
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip() is not None:
            raise ValueError('ZIP integrity check failed')
        for name, expected in manifest['artifact_hashes'].items():
            if hashlib.sha256(zipped.read(name)).hexdigest() != expected:
                raise ValueError(f'ZIP artifact mismatch: {name}')
    delivery.mkdir(parents=True, exist_ok=True)
    for name in [stem+'.pdf', stem+'.docx', 'manifest.json', 'text-check.json', 'visual-review.json']:
        shutil.copyfile(report / name, delivery / name)
    record = {'archive_path': str(archive), 'archive_sha256': sha(archive),
        'archive_bytes': archive.stat().st_size, 'files_verified': len(manifest['artifact_hashes']),
        'status': 'complete', 'build_head': manifest['source_before']['git_head'],
        'compact_evidence_files': len(manifest['evidence_sources']), 'full_raw_runs_included': False,
        'finalizer_sha256': sha(Path(__file__))}
    write(delivery / 'delivery.json', record)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('report', 'review', 'archive', 'delivery'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(finalize(args.report, args.review, args.archive, args.delivery)))
