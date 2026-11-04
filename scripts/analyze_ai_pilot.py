"""Compare preserved AI reviews with a frozen development reference; never emit labels."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from scripts.validate_ai_review import audit_review, load_packet

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'examples/ai_review_pilot'


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def keyed(records, ids):
    result = {r['id']: r for r in records}
    if len(result) != len(records) or set(result) != set(ids):
        raise ValueError('record identities do not match the complete packet')
    if any(r['verdict'] not in {'supported', 'contradicted', 'uncertain'} for r in records):
        raise ValueError('unknown verdict')
    return result


def compare(cases, origins, reference, reviews):
    """Keep disagreement and abstention visible; agreement is not a truth estimate."""
    sources = {'mechanical': keyed(reference, cases)}
    sources.update({name: keyed(records, cases) for name, records in reviews.items()})
    if set(sources) != {'mechanical', 'reviewer_a', 'reviewer_b'}:
        raise ValueError('exactly two distinct AI reviews are required')
    private = {r['id']: r for r in origins}
    if len(private) != len(origins) or set(private) != set(cases):
        raise ValueError('private map identities differ')
    rows = []
    for case_id, case in cases.items():
        origin = private[case_id]
        control = origin['transformation']
        verdicts = {name: records[case_id]['verdict'] for name, records in sources.items()}
        failures = ([name for name, verdict in verdicts.items()
                     if verdict != control['expected_verdict']] if control else [])
        disagreement = len(set(verdicts.values())) > 1
        rows.append({'id': case_id, 'group_id': origin['source_origin']['group_id'],
                     'kind': case['kind'], 'source_sha256': case['source_sha256'],
                     'origin_class': origin['origin_class'],
                     'control_type': control['type'] if control else None,
                     'control_expected': control['expected_verdict'] if control else None,
                     'verdicts': verdicts, 'control_failures': failures,
                     'disagreement': disagreement,
                     'unresolved': bool(failures) or disagreement or 'uncertain' in verdicts.values()})

    def summarize(subset):
        return {'cases': len(subset),
                'unique_source_hashes': len({r['source_sha256'] for r in subset}),
                'verdict_counts': {name: dict(Counter(r['verdicts'][name] for r in subset))
                                   for name in sources},
                'ai_pair_disagreements': sum(r['verdicts']['reviewer_a'] != r['verdicts']['reviewer_b'] for r in subset),
                'mechanical_disagreements': {name: sum(r['verdicts'][name] != r['verdicts']['mechanical'] for r in subset)
                                             for name in reviews},
                'control_failures': {name: sum(name in r['control_failures'] for r in subset) for name in sources},
                'unresolved': sum(r['unresolved'] for r in subset)}

    failed_controls = any(r['control_failures'] for r in rows)
    disagreement = any(r['disagreement'] for r in rows)
    summary = {'all': summarize(rows),
               'authentic': summarize([r for r in rows if r['control_type'] is None]),
               'controls': summarize([r for r in rows if r['control_type'] is not None]),
               'groups': {group: summarize([r for r in rows if r['group_id'] == group])
                          for group in sorted({r['group_id'] for r in rows})},
               'expansion_blocked_by_control_or_disagreement': failed_controls or disagreement,
               'human_review_count': 0, 'labels_created': 0, 'receipts_created': 0,
               'limits': ['Agreement is not independent truth or human annotation.',
                          'All methods may share CPython parser errors; AI models may share training and errors.',
                          'Cases share modules and parent groups; row counts are not independent observations.',
                          'Parent-only development syntax pilot; no behavioral or held-out conclusion.']}
    return summary, rows


def run(run_dir, review_a, review_b, out):
    out.mkdir(parents=True, exist_ok=False)
    manifest = {'status': 'running', 'evaluation_eligible': False,
                'analysis_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'analyzer_sha256': sha(Path(__file__))}
    write(out/'manifest.json', manifest)
    try:
        for relative, expected in read(BASE/'sealed_hashes.json').items():
            if sha(BASE/relative) != expected:
                raise ValueError(f'input seal mismatch: {relative}')
        protocol = read(BASE/'protocol.json')
        for relative, expected in protocol['artifact_sha256'].items():
            if sha(ROOT/relative) != expected:
                raise ValueError(f'frozen implementation/input changed: {relative}')
        runtime = read(run_dir/'manifest.json')
        for field, path in [('protocol_sha256', BASE/'protocol.json'),
                            ('sealed_hashes_sha256', BASE/'sealed_hashes.json'),
                            ('checker_sha256', ROOT/'scripts/structural_checker.py'),
                            ('mechanical_reference_sha256', run_dir/'mechanical-reference.json')]:
            if runtime[field] != sha(path):
                raise ValueError(f'reference identity mismatch: {field}')
        cases, _, packet_hash, _ = load_packet(BASE/'packet')
        if runtime['packet_sha256'] != packet_hash or protocol['packet_sha256'] != packet_hash:
            raise ValueError('packet identity mismatch')
        reviews = {}
        task_ids = []
        for name, directory in [('reviewer_a', review_a), ('reviewer_b', review_b)]:
            audit = audit_review(BASE/'packet', directory/'review.json')
            review = read(directory/'review.json')
            task_ids.append(review['agent_task'])
            shutil.copytree(directory, out/name, ignore=shutil.ignore_patterns('__pycache__'))
            write(out/(name+'-format-audit.json'), audit)
            reviews[name] = review['items']
        if len(set(task_ids)) != 2:
            raise ValueError('reviewer contexts are not distinct')
        reference = read(run_dir/'mechanical-reference.json')['records']
        for row in reference:
            if row['source_sha256'] != cases[row['id']]['source_sha256']:
                raise ValueError('reference source hash mismatch')
        summary, rows = compare(cases, read(BASE/'private/case_map.json'), reference, reviews)
        if summary['all']['cases'] != protocol['counts']['public_cases']:
            raise ValueError('protocol denominator mismatch')
        shutil.copyfile(run_dir/'manifest.json', out/'reference-run-manifest.json')
        shutil.copyfile(run_dir/'mechanical-reference.json', out/'mechanical-reference.json')
        write(out/'summary.json', summary)
        write(out/'comparisons.json', rows)
        manifest.update(status='complete', packet_sha256=packet_hash,
                        protocol_sha256=sha(BASE/'protocol.json'), reviewer_tasks=task_ids)
    except Exception as error:
        manifest.update(status='failed', failure={'type': type(error).__name__, 'message': str(error)})
        raise
    finally:
        manifest['artifact_sha256'] = {p.relative_to(out).as_posix(): sha(p)
                                      for p in sorted(out.rglob('*')) if p.is_file() and p != out/'manifest.json'}
        write(out/'manifest.json', manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('run', 'review-a', 'review-b', 'out'):
        parser.add_argument('--'+argument, type=Path, required=True)
    args = parser.parse_args()
    run(args.run, args.review_a, args.review_b, args.out)
