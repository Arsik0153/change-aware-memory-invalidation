"""Collect automated parent-only probe observations without admitting claims or creating labels."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from cami.artifacts import (
    digest, file_hash, load_jsonl, read_json, reserve, within, write_json, write_jsonl,
)
from cami.behavior import ProbeContext, check_docker, execute_probe
from cami.errors import InputError
from cami.models import Behavior, Claim, EnvironmentProfile, Record, RepoLocation
from cami.repository import MAX_FILE_BYTES, read_snapshot


class ParentInput(Record):
    group_id: str
    repo_id: str
    repo_path: str
    source_roots: tuple[str, ...]
    parent_commit: str
    seed: int


def check_parents(parents_path: Path, candidates: Path, image: str, output: Path, *,
                  max_file_bytes: int = MAX_FILE_BYTES) -> None:
    if max_file_bytes < 1:
        raise InputError('max_file_bytes must be positive')
    parents = load_jsonl(parents_path, ParentInput, unique='group_id')
    if not parents:
        raise InputError('no parent inputs')
    profile = EnvironmentProfile(image=image, python_version='3.12.12', source_paths=('.', 'src'))
    prepared = []
    for parent in parents:
        base = within(candidates, parent.group_id)
        draft = read_json(base / 'draft.json')
        if (draft['parent_input'] != parent.model_dump(mode='json')
                or draft['claims_sha256'] != file_hash(base / 'claims.jsonl')):
            raise InputError('candidate draft differs from parent inputs or claim hash')
        claims = load_jsonl(base / 'claims.jsonl', Claim, unique='claim_id')
        if any(claim.origin_commit != parent.parent_commit or claim.repo_id != parent.repo_id
               for claim in claims):
            raise InputError('claim origin differs from parent input')
        behavior = [claim for claim in claims if isinstance(claim.predicate, Behavior)]
        if len(behavior) != 1:
            raise InputError('exactly one frozen behavior candidate required per parent')
        claim = behavior[0]
        assert isinstance(claim.predicate, Behavior)
        probe = within(base, claim.predicate.probe_path)
        if file_hash(probe) != claim.predicate.probe_sha256:
            raise InputError('frozen parent probe differs from claim hash')
        prepared.append((parent, base, claim))
    check_docker(profile)
    reserve(output)
    manifest = {'status': 'running', 'scope': 'automated parent-only environment diagnostic',
                'parent_inputs_sha256': file_hash(parents_path), 'max_file_bytes': max_file_bytes,
                'profile': profile.model_dump(mode='json'), 'groups': len(prepared),
                'produces_independent_receipts': False, 'produces_child_labels': False,
                'claim_hashes': {claim.claim_id: digest(claim) for _, _, claim in prepared},
                'implementation_hashes': {str(path.relative_to(Path(__file__).resolve().parents[1])):
                    file_hash(path) for path in [Path(__file__).resolve(),
                    Path(__file__).resolve().parents[1] / 'src/cami/behavior.py',
                    Path(__file__).resolve().parents[1] / 'src/cami/repository.py',
                    Path(__file__).resolve().parents[1] / 'src/cami/probe_runner.py']}}
    write_json(output / 'manifest.json', manifest)
    observations = []
    for parent, base, claim in prepared:
        snapshot = read_snapshot(RepoLocation(repo_id=parent.repo_id, path=parent.repo_path,
                                  source_roots=parent.source_roots), parent.parent_commit,
                                 max_file_bytes=max_file_bytes)
        target = output / parent.group_id
        result = execute_probe(claim, ProbeContext(snapshot, profile, base, target, phase='preflight'))
        write_json(target / 'observation.json', result)
        observations.append({'group_id': parent.group_id, 'repo_id': parent.repo_id,
            'parent_commit': parent.parent_commit, 'claim_id': claim.claim_id,
            'verdict': result.verdict, 'reason': result.reason,
            'test_executions': result.test_executions,
            'observation_path': f'{parent.group_id}/observation.json'})
        print(f'{parent.group_id}: {result.verdict} ({result.reason})', flush=True)
    write_jsonl(output / 'observations.jsonl', observations)
    write_json(output / 'summary.json', {
        'groups': len(observations), 'test_executions': sum(o['test_executions'] for o in observations),
        'outcomes': dict(Counter(f"{o['repo_id']}/{o['verdict']}/{o['reason']}"
                                 for o in observations)),
        'limitation': 'Automated observations do not supply independent parent review or admission.',
    })
    manifest.update({'status': 'complete', 'artifact_hashes': {
        path.relative_to(output).as_posix(): file_hash(path)
        for path in sorted(output.rglob('*')) if path.is_file() and path.name != 'manifest.json'}})
    write_json(output / 'manifest.json', manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parents', type=Path, required=True)
    parser.add_argument('--candidates', type=Path, required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--max-file-bytes', type=int, default=MAX_FILE_BYTES)
    args = parser.parse_args()
    check_parents(args.parents, args.candidates, args.image, args.out,
                  max_file_bytes=args.max_file_bytes)
