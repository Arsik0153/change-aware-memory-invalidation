"""Audit a completed Requests projection run using stdlib and immutable Git objects."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def audit(root: Path) -> dict:
    if not __debug__:
        raise RuntimeError('Audit requires assertions; run Python without -O')
    manifest = read(root / 'manifest.json')
    assert manifest['status'] == 'complete'
    assert manifest['source_before'] == manifest['source_after']
    artifacts = manifest['artifact_hashes']
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*')
              if p.is_file() and p != root / 'manifest.json'}
    assert set(artifacts) == actual, 'artifact file set differs from manifest'
    for relative, expected in artifacts.items():
        path = (root / relative).resolve()
        assert path.is_relative_to(root.resolve()) and sha(path) == expected, relative
    for path, expected in manifest['input_hashes'].items():
        assert sha(Path(path)) == expected, path
    plan = read(root / 'protocol.json')
    assert sha(root / 'protocol.json') == manifest['protocol_sha256']
    parents = {p['group_id']: p for p in plan['parents']}
    observations = read(root / 'observations.json')
    observed = {r['group_id']: r for r in observations}
    assert len(parents) == len(plan['parents']) == plan['expected_groups']
    assert len(observed) == len(observations) and set(observed) == set(parents)
    outcomes, limitations = Counter(), Counter()
    objects, included_count, payload_count = {}, 0, 0
    for name, parent in parents.items():
        projection = read(root / name / 'projection.json')
        assert projection['parent_commit'] == parent['parent_commit']
        blobs = {b['path']: b for b in projection['blobs']}
        assert len(blobs) == len(projection['blobs'])
        raw_tree = subprocess.check_output([
            'git', '--no-replace-objects', '-C', parent['repo_path'],
            'ls-tree', '-rz', '--full-tree', parent['parent_commit']])
        tree = {}
        for entry in raw_tree.split(b'\0'):
            if entry:
                metadata, path = entry.split(b'\t', 1)
                mode, _, oid = metadata.decode().split()
                tree[path.decode()] = (mode, oid)
        assert set(blobs) == set(tree), name
        included, excluded_limitations = 0, Counter()
        for path, blob in blobs.items():
            assert (blob['mode'], blob['object_id']) == tree[path], (name, path)
            assert blob['included'] == path.startswith(tuple(plan['source_prefixes']))
            if blob['included']:
                assert blob['limitation'] is None
                assert blob['mode'] in ('100644', '100755')
                key = (parent['repo_path'], blob['object_id'])
                if key in objects:
                    assert objects[key] == blob['sha256']
                objects[key] = blob['sha256']
                included += 1
            elif blob['limitation']:
                excluded_limitations[blob['limitation']] += 1
        row = observed[name]
        claim_paths = [Path(path) for path in manifest['input_hashes']
                       if Path(path).parent.name == name and Path(path).name == 'claims.jsonl']
        assert len(claim_paths) == 1
        assert sha(claim_paths[0]) == parent['claims_sha256']
        candidates = [json.loads(line) for line in claim_paths[0].read_text().splitlines()]
        claims = [claim for claim in candidates if claim['kind'] == 'behavior_test']
        assert len(claims) == 1
        claim = claims[0]
        assert row['claim_id'] == claim['claim_id']
        assert claim['origin_commit'] == parent['parent_commit']
        probe = claim_paths[0].parent / claim['predicate']['probe_path']
        assert sha(probe) == claim['predicate']['probe_sha256']
        assert row['parent_commit'] == parent['parent_commit']
        assert row['included_blobs'] == included
        assert row['excluded_blobs'] == len(blobs) - included
        assert row['excluded_limitations'] == dict(excluded_limitations)
        limitations.update(excluded_limitations)
        included_count += included
        payloads = [read(p) for p in (root / name / 'logs').glob('**/repeat-*.json')]
        assert len(payloads) == row['test_executions'] == 3
        assert all(p['outcome'] == 'passed' for p in payloads), 'audit scope is completed passing diagnostic'
        for payload in payloads:
            log = (root / name / payload['log_path']).resolve()
            assert log.is_relative_to((root / name).resolve())
            markers = [line.removeprefix('CAMI_RESULT=') for line in log.read_text().splitlines()
                       if line.startswith('CAMI_RESULT=')]
            assert len(markers) == 1
            raw = json.loads(markers[0])
            node = claim['predicate']['node_id']
            assert raw['exit_code'] == 0 and raw['python_version'] == plan['profile']['python_version']
            assert raw['collected'] == [node]
            assert len(raw['reports']) == 3
            assert {report['when'] for report in raw['reports']} == {'setup', 'call', 'teardown'}
            assert all(report['nodeid'] == node and report['outcome'] == 'passed'
                       for report in raw['reports'])
        observation = read(root / name / 'observation.json')
        assert observation['claim_id'] == row['claim_id']
        assert observation['commit'] == row['parent_commit']
        assert observation['verdict'] == row['verdict'] == 'supported'
        assert observation['reason'] == row['reason'] == 'test_passed'
        assert observation['test_executions'] == row['test_executions']
        outcomes.update(p['outcome'] for p in payloads)
        payload_count += len(payloads)
    for repo in {key[0] for key in objects}:
        keys = sorted(oid for repo_path, oid in objects if repo_path == repo)
        raw = subprocess.check_output(['git', '--no-replace-objects', '-C', repo,
                                       'cat-file', '--batch'], input=('\n'.join(keys) + '\n').encode())
        offset = 0
        for oid in keys:
            end = raw.index(b'\n', offset)
            header = raw[offset:end].decode().split()
            assert header[:2] == [oid, 'blob']
            size = int(header[2])
            assert hashlib.sha256(raw[end + 1:end + 1 + size]).hexdigest() == objects[repo, oid]
            offset = end + size + 2
        assert offset == len(raw)
    summary = read(root / 'summary.json')
    assert summary['status'] == 'complete' and summary['completed_groups'] == len(parents)
    assert summary['completed_group_probe_executions'] == payload_count
    assert summary['outcomes'] == {'supported/test_passed': len(parents)}
    return {'status': 'verified', 'groups': len(parents), 'probe_payloads': payload_count,
            'outcomes': dict(outcomes), 'included_blob_records': included_count,
            'distinct_git_blobs_verified': len(objects), 'excluded_limitations': dict(limitations),
            'artifact_hashes_checked': len(artifacts),
            'input_hashes_checked': len(manifest['input_hashes']),
            'audit_script_sha256': sha(Path(__file__)),
            'scope': 'Completed passing projection diagnostic only; not independent human review',
            'manifest_sha256': sha(root / 'manifest.json')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists() or args.out.resolve().is_relative_to(args.run.resolve()):
        parser.error('audit output must be new and outside the run')
    result = audit(args.run)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
