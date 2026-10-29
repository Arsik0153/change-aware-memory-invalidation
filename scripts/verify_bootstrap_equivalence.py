"""Compare current bootstrap outputs with immutable synthetic study results."""
from __future__ import annotations

import argparse
from pathlib import Path

from cami.artifacts import file_hash, read_json, read_jsonl, reserve, write_json
from cami.evaluation import paired_cluster_bootstrap


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    manifest = read_json(args.study / 'manifest.json')
    source = args.study / 'trials.jsonl'
    if (manifest['status'] != 'complete'
            or file_hash(source) != manifest['artifact_hashes']['trials.jsonl']):
        raise ValueError('study is incomplete or trial hashes disagree')
    reserve(args.out)
    rows = read_jsonl(source)
    if not rows:
        raise ValueError('no trials to compare')
    for row in rows:
        old = row['interval']
        result = paired_cluster_bootstrap(
            {key: tuple(value) for key, value in row['left'].items()},
            {key: tuple(value) for key, value in row['right'].items()},
            repetitions=old['repetitions'], seed=old['seed'])
        expected = {key: value for key, value in old.items() if key != 'denominator_support'}
        if result.model_dump(mode='json', exclude={'denominator_support'}) != expected:
            raise ValueError(f"interval changed: {row['scenario']} trial {row['trial']}")
    write_json(args.out / 'equivalence.json', {
        'result': 'passed', 'compared_trials': len(rows), 'trials_sha256': file_hash(source),
        'evaluation_sha256': file_hash(Path(__file__).resolve().parents[1] / 'src/cami/evaluation.py'),
        'excluded_fields': ['denominator_support'],
    })
    print(f'{len(rows)} intervals match all previous fields exactly')


if __name__ == '__main__':
    main()
