"""Observe frozen Requests parent probes under an explicit package-only projection."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from cami.artifacts import canonical, file_hash, read_json, read_jsonl, reserve, within, write_json
from cami.behavior import ProbeContext, check_docker, execute_probe
from cami.errors import InputError
from cami.models import Behavior, Claim, EnvironmentProfile, RepoLocation
from cami.repository import Snapshot, read_snapshot
from scripts.verify_cami import source_snapshot

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'examples/behavior_dependency/requests_projection_protocol.json'


def project(snapshot: Snapshot, prefixes: tuple[str, ...]) -> Snapshot:
    if not prefixes or any(not prefix.endswith('/') for prefix in prefixes):
        raise InputError('package prefixes must end in /')
    blobs = tuple(blob for blob in snapshot.blobs if blob.path.startswith(prefixes))
    if not blobs:
        raise InputError('no package blobs in parent snapshot')
    return Snapshot(snapshot.repo_id, snapshot.revision, blobs)


def run(out: Path) -> None:
    before = source_snapshot(ROOT)
    assert not before['source_status'], 'Commit source before diagnostic execution'
    plan = read_json(PLAN)
    plan_hash = file_hash(PLAN)
    profile = EnvironmentProfile.model_validate_json(canonical(plan['profile']))
    prepared = []
    input_hashes = {}
    for parent in plan['parents']:
        base = within(ROOT / plan['candidate_root'], parent['group_id'])
        for name in ('claims', 'draft'):
            path = base / (name + ('.jsonl' if name == 'claims' else '.json'))
            sha = file_hash(path)
            if sha != parent[name + '_sha256']:
                raise InputError(f'changed frozen input: {path}')
            input_hashes[str(path)] = sha
        draft = read_json(base / 'draft.json')
        identity = {key: value for key, value in parent.items()
                    if key not in {'claims_sha256', 'draft_sha256'}}
        if draft['parent_input'] != identity:
            raise InputError('parent input differs from sealed candidate draft')
        claims = [Claim.model_validate_json(canonical(row))
                  for row in read_jsonl(base / 'claims.jsonl')]
        if any(c.origin_commit != parent['parent_commit'] or c.repo_id != 'requests' for c in claims):
            raise InputError('candidate origin mismatch')
        behavior = [c for c in claims if isinstance(c.predicate, Behavior)]
        if len(behavior) != 1:
            raise InputError('one frozen behavior candidate required')
        claim = behavior[0]
        assert isinstance(claim.predicate, Behavior)
        probe = within(base, claim.predicate.probe_path)
        if file_hash(probe) != claim.predicate.probe_sha256:
            raise InputError('changed frozen probe')
        input_hashes[str(probe)] = file_hash(probe)
        prepared.append((parent, base, claim))
    assert len(prepared) == plan['expected_groups']
    assert len({p['group_id'] for p, _, _ in prepared}) == len(prepared)
    check_docker(profile)
    reserve(out)
    write_json(out / 'protocol.json', plan)
    manifest = {'status': 'running', 'source_before': before, 'protocol_sha256': plan_hash,
                'input_hashes': input_hashes, 'produces_receipts': False, 'produces_labels': False}
    observations = []

    def save() -> None:
        write_json(out / 'observations.json', observations)
        write_json(out / 'summary.json', {
            'status': manifest['status'], 'completed_groups': len(observations),
            'completed_group_probe_executions': sum(r['test_executions'] for r in observations),
            'outcomes': dict(Counter(r['verdict'] + '/' + r['reason'] for r in observations)),
            'limitations': plan['limitations']})
        manifest['artifact_hashes'] = {p.relative_to(out).as_posix(): file_hash(p)
                                      for p in out.rglob('*')
                                      if p.is_file() and p != out / 'manifest.json'}
        write_json(out / 'manifest.json', manifest)

    save()
    current = ''
    try:
        for parent, base, claim in prepared:
            current = parent['group_id']
            snapshot = read_snapshot(RepoLocation(repo_id='requests', path=parent['repo_path'],
                                     source_roots=tuple(parent['source_roots'])),
                                     parent['parent_commit'], max_file_bytes=plan['max_file_bytes'])
            projected = project(snapshot, tuple(plan['source_prefixes']))
            included = {blob.path for blob in projected.blobs}
            target = out / current
            write_json(target / 'projection.json', {
                'parent_commit': snapshot.revision, 'scope': 'package-only projection',
                'blobs': [{'path': b.path, 'object_id': b.object_id, 'mode': b.mode,
                           'sha256': b.content_hash if b.content is not None else None,
                           'limitation': b.limitation, 'included': b.path in included}
                          for b in snapshot.blobs]})
            result = execute_probe(claim, ProbeContext(projected, profile, base, target, phase='preflight'))
            write_json(target / 'observation.json', result)
            observations.append({'group_id': current, 'parent_commit': snapshot.revision,
                'claim_id': claim.claim_id, 'verdict': result.verdict, 'reason': result.reason,
                'test_executions': result.test_executions, 'included_blobs': len(included),
                'excluded_blobs': len(snapshot.blobs) - len(included),
                'excluded_limitations': dict(Counter(b.limitation for b in snapshot.blobs
                                                    if b.path not in included and b.limitation))})
            save()
        assert file_hash(PLAN) == plan_hash
        assert all(file_hash(Path(path)) == sha for path, sha in input_hashes.items())
        after = source_snapshot(ROOT)
        assert after == before
        manifest.update(status='complete', source_after=after)
    except (Exception, KeyboardInterrupt) as exc:
        manifest.update(status='failed', failure={'group_id': current, 'type': type(exc).__name__,
                                                 'message': str(exc)})
        raise
    finally:
        save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    run(parser.parse_args().out.resolve())
