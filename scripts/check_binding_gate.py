"""Read-only feasibility of the fixture binding gate on frozen real parent modules."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from pathlib import Path

from cami.artifacts import canonical, digest, file_hash, read_json, read_jsonl, reserve, within, write_json, write_jsonl
from cami.errors import InputError
from cami.models import Claim, RepoLocation
from cami.repository import read_snapshot
from cami.structural_closure import _binding_check
from scripts.verify_cami import source_snapshot

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'examples/behavior_dependency/binding_gate_protocol.json'


def observe(content: bytes | None, limitation: str | None) -> tuple[str, str | None]:
    if content is None or limitation:
        return 'unreadable_or_unparseable', limitation or 'missing_blob'
    try:
        tree = ast.parse(content.decode('utf-8'))
    except (SyntaxError, UnicodeError, ValueError) as exc:
        return 'unreadable_or_unparseable', type(exc).__name__
    try:
        _binding_check(tree)
    except InputError as exc:
        return 'binding_gate_rejected', str(exc)
    return 'passes_binding_gate_only', None


def run(out: Path) -> None:
    before = source_snapshot(ROOT)
    assert not before['source_status'], 'Commit source before diagnostic execution'
    plan = read_json(PLAN)
    plan_hash = file_hash(PLAN)
    assert file_hash(ROOT / 'src/cami/structural_closure.py') == plan['gate_sha256']
    assert file_hash(ROOT / 'docs/protocol_1_1_structural_closure_v1.md') == plan['addendum_sha256']
    assert len(plan['parents']) == plan['expected_parent_groups']
    inputs, prepared = {}, []
    for parent in plan['parents']:
        base = within(ROOT / plan['candidate_root'], parent['group_id'])
        for name in ('claims', 'draft'):
            path = base / (name + ('.jsonl' if name == 'claims' else '.json'))
            assert file_hash(path) == parent[name + '_sha256']
            inputs[str(path)] = file_hash(path)
        expected = {k: v for k, v in parent.items() if k not in {'claims_sha256', 'draft_sha256'}}
        assert read_json(base / 'draft.json')['parent_input'] == expected
        claims = [Claim.model_validate_json(canonical(r)) for r in read_jsonl(base / 'claims.jsonl')]
        assert all(c.origin_commit == parent['parent_commit'] and c.repo_id == parent['repo_id']
                   for c in claims)
        prepared.append((parent, [c for c in claims if c.kind in plan['claim_kinds']]))
    assert sum(len(claims) for _, claims in prepared) == plan['expected_structural_candidates']
    reserve(out)
    write_json(out / 'protocol.json', plan)
    manifest = {'status': 'running', 'source_before': before, 'protocol_sha256': plan_hash,
                'input_hashes': inputs, 'parent_only': True, 'closes_provenance': False,
                'produces_receipts_or_labels': False}
    rows, modules = [], []

    def save() -> None:
        write_jsonl(out / 'claims.jsonl', rows)
        write_jsonl(out / 'modules.jsonl', modules)
        write_json(out / 'summary.json', {
            'status': manifest['status'], 'claim_observations': len(rows),
            'parent_module_observations': len(modules),
            'claim_outcomes': dict(Counter(r['outcome'] for r in rows)),
            'module_outcomes': dict(Counter(r['outcome'] for r in modules)),
            'claim_first_reasons': dict(Counter(r['first_reason'] or 'none' for r in rows)),
            'module_first_reasons': dict(Counter(r['first_reason'] or 'none' for r in modules)),
            'by_repository': {repo: dict(Counter(r['outcome'] for r in rows if r['repo_id'] == repo))
                              for repo in sorted({r['repo_id'] for r in rows})},
            'limitations': ['Only one necessary gate, not all closure conditions.',
                           'Gate is fixture-only; no real-data closure authority is created.',
                           'First failure only; causes overlap and depend on traversal order.',
                           'Claims sharing a module are not independent observations.']})
        manifest['artifact_hashes'] = {p.relative_to(out).as_posix(): file_hash(p)
                                      for p in out.rglob('*') if p.is_file() and p != out / 'manifest.json'}
        write_json(out / 'manifest.json', manifest)

    save()
    try:
        for parent, claims in prepared:
            repo = RepoLocation(repo_id=parent['repo_id'], path=parent['repo_path'],
                                source_roots=tuple(parent['source_roots']))
            snapshot = read_snapshot(repo, parent['parent_commit'])
            blobs = snapshot.by_path()
            observations = {}
            for path in sorted({c.subject.path for c in claims}):
                blob = blobs.get(path)
                content = blob.content if blob else None
                outcome, reason = observe(content, blob.limitation if blob else None)
                record = {'group_id': parent['group_id'], 'repo_id': repo.repo_id,
                    'parent_commit': snapshot.revision, 'path': path,
                    'blob_oid': blob.object_id if blob else None,
                    'blob_sha256': blob.content_hash if content is not None else None,
                    'outcome': outcome, 'first_reason': reason}
                if content is not None:
                    target = out / 'sources' / blob.content_hash
                    target.parent.mkdir(exist_ok=True)
                    target.write_bytes(content)
                modules.append(record)
                observations[path] = record
            for claim in claims:
                rows.append({**observations[claim.subject.path], 'claim_id': claim.claim_id,
                             'claim_sha256': digest(claim), 'claim_kind': claim.kind,
                             'subject_qualname': claim.subject.qualname})
            save()
        assert file_hash(PLAN) == plan_hash
        assert all(file_hash(Path(path)) == expected for path, expected in inputs.items())
        after = source_snapshot(ROOT)
        assert before == after
        manifest.update(status='complete', source_after=after)
    except (Exception, KeyboardInterrupt) as exc:
        manifest.update(status='failed', failure={'type': type(exc).__name__, 'message': str(exc)})
        raise
    finally:
        save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    run(parser.parse_args().out.resolve())
