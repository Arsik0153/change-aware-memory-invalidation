"""Describe parent-only structural prerequisites without producing closure or truth labels."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from pathlib import Path

from cami.artifacts import canonical, digest, file_hash, load_jsonl, read_json, reserve, within, write_json, write_jsonl
from cami.errors import InputError
from cami.index import parse_module
from cami.models import Claim, Equals, Node, Provenance, RepoLocation
from cami.repository import Snapshot, read_snapshot
from cami.structural_closure import DRAFT_REASON, SCOPES, _binding_check, _in_roots, _simple
from scripts.verify_cami import source_snapshot

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'examples/structural_closure/prerequisite_profile_protocol.json'


def conjunction(values: list[bool | None]) -> bool | None:
    if False in values:
        return False
    return None if None in values else True


def profile(claim: Claim, prov: Provenance, snapshot: Snapshot, roots: tuple[str, ...],
            modules: dict) -> dict:
    subject = Node(path=claim.subject.path, qualname=claim.subject.qualname)
    texts = {'Exact fixture syntax.',
             f'Exact {claim.kind} predicate for {subject.path}::{subject.qualname}.'}
    if isinstance(claim.predicate, Equals):
        texts.add(f'The exact definition {subject.path}:{subject.qualname} has normalized signature '
                  f'{canonical(claim.predicate.expected_signature).decode()}.')
    else:
        texts.add(f'{subject.path} contains the exact top-level function definition {subject.qualname}.')
    conditions = {
        'exact_scope_and_text': claim.scope in SCOPES.get(claim.kind, ()) and claim.text in texts,
        'simple_function_subject': claim.subject.node_kind == 'function' and _simple(claim.subject.qualname),
        'intact_incomplete_provenance': prov.scenario_id == 'intact' and prov.known_incomplete
            and not prov.dependencies and prov.unresolved_reasons == (DRAFT_REASON,),
        'exact_subject_anchor': any(a.scope == 'symbol' and a.path == subject.path
                                   and a.qualname == subject.qualname for a in prov.anchors),
    }
    blobs = snapshot.by_path()
    nodes = {subject, *(Node(path=a.path, qualname=a.qualname) for a in prov.anchors)}
    readable = all(_in_roots(n.path, roots) and n.path in blobs
                   and blobs[n.path].mode in {'100644', '100755'}
                   and blobs[n.path].content is not None and not blobs[n.path].limitation
                   for n in nodes)
    conditions['readable_regular_support_in_roots'] = readable
    observations = []
    definitions = {}
    unique, binding, binding_reasons = [], [], []
    if readable:
        for node in sorted(nodes, key=lambda n: (n.path, n.qualname or '')):
            blob = blobs[node.path]
            observation = {'node': node.model_dump(), 'blob_oid': blob.object_id,
                           'blob_sha256': blob.content_hash, 'mode': blob.mode}
            if node.path.endswith('.py'):
                if node.path not in modules:
                    module = parse_module(blob, node.path)
                    gate, reason = None, module.limitation
                    if not module.limitation:
                        try:
                            _binding_check(ast.parse(module.source))
                            gate = True
                        except InputError as exc:
                            gate, reason = False, str(exc)
                    modules[node.path] = module, gate, reason
                module, gate, reason = modules[node.path]
                if module.limitation:
                    unique.append(None)
                elif node.qualname is not None:
                    matches = [d for d in module.definitions if d.node == node]
                    valid = (_simple(node.qualname) and len(matches) == 1
                             and not matches[0].ambiguous and matches[0].node_kind == 'function')
                    unique.append(valid)
                    if valid:
                        definitions[node] = matches[0]
                    observation['matching_definitions'] = len(matches)
                    observation['unique_unambiguous'] = valid
                binding.append(gate)
                if gate is not True:
                    binding_reasons.append({'path': node.path, 'reason': reason})
            elif node.qualname is not None:
                unique.append(False)
            observations.append(observation)
        conditions['anchor_identity_and_bounds'] = all(
            not (a.scope == 'file' and a.qualname is not None)
            and a.observed_commit == snapshot.revision and a.content_hash == blobs[a.path].content_hash
            and all(line is None or line <= len(blobs[a.path].content.splitlines())
                    for line in (a.start_line, a.end_line)) for a in prov.anchors)
        conditions['unique_unambiguous_support'] = conjunction(unique)
        conditions['whole_module_binding_gate'] = conjunction(binding)
    else:
        conditions.update(anchor_identity_and_bounds=None, unique_unambiguous_support=None,
                          whole_module_binding_gate=None)
    definition = definitions.get(subject)
    conditions['signature_matches'] = (True if not isinstance(claim.predicate, Equals) else
        definition.signature == claim.predicate.expected_signature if definition is not None else None)
    return {'claim_id': claim.claim_id, 'claim_sha256': digest(claim),
            'provenance_sha256': digest(prov), 'conditions': conditions,
            'binding_first_reasons': binding_reasons, 'observations': observations,
            'signature_comparison_required': isinstance(claim.predicate, Equals),
            'all_observed_conditions_pass': all(value is True for value in conditions.values()),
            'all_except_binding_gate_pass': all(value is True for name, value in conditions.items()
                                                if name != 'whole_module_binding_gate')}


def run(out: Path) -> None:
    before = source_snapshot(ROOT)
    assert not before['source_status'], 'Commit source before execution'
    plan, plan_hash = read_json(PLAN), file_hash(PLAN)
    assert file_hash(ROOT / 'src/cami/structural_closure.py') == plan['closure_code_sha256']
    assert file_hash(ROOT / 'docs/protocol_1_1_structural_closure_v1.md') == plan['addendum_sha256']
    assert len(plan['parents']) == plan['expected_parent_groups']
    prepared, input_hashes = [], {}
    for parent in plan['parents']:
        base = within(ROOT / plan['candidate_root'], parent['group_id'])
        for name in ('claims', 'provenance', 'draft'):
            path = base / (name + ('.json' if name == 'draft' else '.jsonl'))
            assert file_hash(path) == parent[name + '_sha256']
            input_hashes[str(path)] = file_hash(path)
        draft = read_json(base / 'draft.json')
        assert draft['parent_input'] == {k: v for k, v in parent.items() if not k.endswith('_sha256')}
        claims = load_jsonl(base / 'claims.jsonl', Claim, 'claim_id')
        provenance = load_jsonl(base / 'provenance.jsonl', Provenance, 'claim_id')
        pmap = {p.claim_id: p for p in provenance}
        assert {c.claim_id for c in claims} == pmap.keys()
        assert all(c.origin_commit == parent['parent_commit'] and c.repo_id == parent['repo_id'] for c in claims)
        prepared.append((parent, [c for c in claims if c.kind in SCOPES], pmap))
    assert sum(len(c) for _, c, _ in prepared) == plan['expected_claims']
    reserve(out)
    write_json(out / 'protocol.json', plan)
    manifest = {'status': 'running', 'source_before': before, 'protocol_sha256': plan_hash,
                'input_hashes': input_hashes, 'parent_only': True,
                'creates_closure_or_admission': False, 'creates_labels_or_receipts': False}
    write_json(out / 'manifest.json', manifest)
    rows = []
    try:
        for parent, claims, pmap in prepared:
            repo = RepoLocation(repo_id=parent['repo_id'], path=parent['repo_path'],
                                source_roots=tuple(parent['source_roots']))
            snap = read_snapshot(repo, parent['parent_commit'])
            modules = {}
            for claim in claims:
                row = profile(claim, pmap[claim.claim_id], snap, repo.source_roots, modules)
                assert set(row['conditions']) == set(plan['conditions'])
                rows.append({'group_id': parent['group_id'], 'repo_id': parent['repo_id'],
                             'parent_commit': snap.revision, **row})
            write_jsonl(out / 'claims.jsonl', rows)
        summary = {'claims': len(rows), 'parent_groups': len(prepared),
            'per_condition': {name: dict(Counter(
                'pass' if r['conditions'][name] is True else
                'fail' if r['conditions'][name] is False else 'unavailable' for r in rows))
                for name in plan['conditions']},
            'all_observed_conditions_pass': sum(r['all_observed_conditions_pass'] for r in rows),
            'all_except_binding_gate_pass': sum(r['all_except_binding_gate_pass'] for r in rows),
            'signature_comparison_required': sum(r['signature_comparison_required'] for r in rows),
            'limits': ['Post-hoc descriptive profile; no independent truth determination.',
                       'Conditions reuse CAMI definitions; not an independent closure audit.',
                       'Real-data authority and independent review are absent even if all observations pass.',
                       'Shared parent modules and repeated parents across history are not independent samples.']}
        write_json(out / 'summary.json', summary)
        assert all(file_hash(Path(p)) == h for p, h in input_hashes.items())
        assert file_hash(PLAN) == plan_hash
        after = source_snapshot(ROOT)
        assert before == after
        manifest.update(status='complete', source_after=after)
    except (Exception, KeyboardInterrupt) as exc:
        manifest.update(status='failed', failure={'type': type(exc).__name__, 'message': str(exc)})
        raise
    finally:
        manifest['artifact_hashes'] = {p.name: file_hash(p) for p in out.iterdir()
                                      if p.is_file() and p.name != 'manifest.json'}
        write_json(out / 'manifest.json', manifest)


if __name__ == '__main__':
    if not __debug__:
        raise SystemExit('Assertions required; do not use -O')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    run(parser.parse_args().out.resolve())
