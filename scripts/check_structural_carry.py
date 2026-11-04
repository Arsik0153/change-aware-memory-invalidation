"""Bounded check of selective carry against the same fresh structural validator."""
from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from dataclasses import replace
from pathlib import Path

from cami.artifacts import digest, file_hash, read_json, reserve, write_json, write_jsonl
from cami.index import build_index, compare_indexes
from cami.models import (
    Anchor, Claim, Equals, Exists, MemoryState, Parameter, PolicyConfig, Provenance,
    Signature, Subject,
)
from cami.policies import SelectionContext, select_claims
from cami.repository import Blob, Snapshot
from cami.validation import ValidationContext, validate_claim
from scripts.verify_cami import source_snapshot

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'examples/structural_closure/carry_protocol.json'
SUBJECT = Subject(path='module.py', qualname='f', node_kind='function')


def snapshot(source: str | None, *, mode: str = '100644',
             limitation: str | None = None) -> Snapshot:
    identity = digest({'source': source, 'mode': mode, 'limitation': limitation})
    blobs = ()
    if source is not None:
        content = source.encode('utf-8')
        oid = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
        blobs = (Blob(SUBJECT.path, oid, mode, None if limitation else content, limitation),)
    return Snapshot('synthetic-carry', 'constructed-' + identity, blobs)


def claims(parent: Snapshot, context_id: str) -> tuple[Claim, ...]:
    predicates = (
        Exists(type='symbol_exists', expected=True),
        Equals(type='signature_equals', expected_signature=Signature(parameters=(
            Parameter(name='x', kind='positional_or_keyword'),))),
    )
    return tuple(Claim(claim_id=f'{context_id}:{p.type}', repo_id=parent.repo_id,
        origin_commit=parent.revision, kind=p.type, text=f'Exact syntax: {p.type} for f',
        subject=SUBJECT, predicate=p, scope='Exact syntactic definition; no runtime claim')
        for p in predicates)


def carry_violation(row: dict) -> bool:
    return (row['parent_verdict'] == 'supported' and not row['selected']
            and row['child_verdict'] != 'supported')


def observe(parent: Snapshot, child: Snapshot, claim: Claim, plan: dict,
            *, suppress_changed_symbols: bool = False) -> dict:
    cache = {}
    before = build_index(parent, cache=cache)
    after = build_index(child, cache=cache)
    fresh = build_index(child)
    changes = compare_indexes(before, after, parent, child)
    if suppress_changed_symbols:
        changes = replace(changes, symbols=frozenset())
    provenance = Provenance(claim_id=claim.claim_id, scenario_id='authored-synthetic',
        anchors=(Anchor(path=SUBJECT.path, qualname=SUBJECT.qualname, scope='symbol',
            observed_commit=parent.revision, content_hash=parent.blobs[0].content_hash,
            origin='manual'),), known_incomplete=plan['known_incomplete'])
    parent_result = validate_claim(claim, ValidationContext(
        parent, before, provenance, ROOT, ROOT))
    previous = MemoryState(claim_id=claim.claim_id, revision=parent.revision,
        state='valid', available=True, basis='validated', current_provenance=provenance,
        last_checked_commit=parent.revision, last_supported_commit=parent.revision,
        last_verdict=parent_result.verdict)
    selected, = select_claims(SelectionContext(child.revision, (claim,), (provenance,),
        (previous,), changes, protocol_version=plan['protocol_version']),
        PolicyConfig(id='symbol_validate', dependency_depth=plan['dependency_depth']))
    result = validate_claim(claim, ValidationContext(child, fresh, provenance, ROOT, ROOT))
    row = {'claim_id': claim.claim_id, 'claim_kind': claim.kind,
        'parent_revision': parent.revision, 'child_revision': child.revision,
        'parent_verdict': parent_result.verdict, 'parent_reason': parent_result.reason,
        'child_verdict': result.verdict, 'child_reason': result.reason,
        'selected': selected.selected, 'selection_reasons': list(selected.reasons),
        'warm_index_equals_fresh': after == fresh,
        'changed_symbols': sorted((n.model_dump() for n in changes.symbols),
                                  key=lambda n: (n['path'], n['qualname'] or '')),
        'changed_files': sorted(changes.files), 'limited_paths': sorted(changes.limited_paths)}
    row['carry_violation'] = carry_violation(row)
    return row


def collect(plan: dict) -> tuple[list[dict], list[dict], list[dict], dict]:
    rows, inputs, claim_rows = [], [], []
    control = None
    for context_id, context in plan['parent_contexts'].items():
        parent_source = plan['parent_prefix'] + plan['parent_function'] + context
        parent = snapshot(parent_source)
        cohort = claims(parent, context_id)
        assert [c.kind for c in cohort] == plan['predicates']
        claim_rows.extend(c.model_dump(mode='json') for c in cohort)
        for mutation in plan['mutations']:
            child_source = None
            if mutation['function'] is not None:
                prefix = plan['parent_prefix']
                if mutation.get('replace_context_value'):
                    assert 'VALUE = 1' in prefix
                    prefix = prefix.replace('VALUE = 1', 'VALUE = 2')
                child_source = prefix + mutation['function'] + context + mutation.get('suffix', '')
            child = snapshot(child_source, mode=mutation.get('mode', '100644'),
                             limitation=mutation.get('limitation'))
            inputs.append({'context': context_id, 'mutation': mutation['id'],
                'parent_source': parent_source, 'child_source': child_source,
                'parent_revision': parent.revision, 'child_revision': child.revision,
                'child_mode': mutation.get('mode', '100644'),
                'child_limitation': mutation.get('limitation'),
                'parent_blob_oid': parent.blobs[0].object_id,
                'child_blob_oid': child.blobs[0].object_id if child.blobs else None})
            for claim in cohort:
                row = observe(parent, child, claim, plan)
                rows.append({'context': context_id, 'mutation': mutation['id'], **row})
                if (context_id == 'ordinary_class' and mutation['id'] == 'signature'
                        and claim.kind == 'signature_equals'):
                    control = observe(parent, child, claim, plan, suppress_changed_symbols=True)
    assert control is not None
    return rows, inputs, claim_rows, control


def run(out: Path) -> None:
    before = source_snapshot(ROOT)
    assert not before['source_status'], 'Commit source before execution'
    plan = read_json(PLAN)
    plan_hash = file_hash(PLAN)
    reserve(out)
    write_json(out / 'protocol.json', plan)
    manifest = {'status': 'running', 'source_before': before,
                'protocol_sha256': plan_hash, 'produces_labels_or_receipts': False}
    write_json(out / 'manifest.json', manifest)
    try:
        rows, inputs, cohort, control = collect(plan)
        write_jsonl(out / 'cases.jsonl', rows)
        write_jsonl(out / 'inputs.jsonl', inputs)
        write_jsonl(out / 'claims.jsonl', cohort)
        write_json(out / 'negative-control.json', control)
        summary = {'cases': len(rows), 'unique_input_pairs': len(inputs),
            'parent_claims': len(cohort),
            'parent_not_supported': sum(r['parent_verdict'] != 'supported' for r in rows),
            'selected': sum(r['selected'] for r in rows),
            'carried': sum(not r['selected'] for r in rows),
            'carry_violations': sum(r['carry_violation'] for r in rows),
            'warm_index_mismatches': sum(not r['warm_index_equals_fresh'] for r in rows),
            'child_verdicts': dict(Counter(r['child_verdict'] for r in rows)),
            'by_mutation': {m['id']: dict(Counter(
                ('selected:' if r['selected'] else 'carried:') + r['child_verdict']
                for r in rows if r['mutation'] == m['id'])) for m in plan['mutations']},
            'negative_control_detected': control['carry_violation'],
            'limits': plan['limits'], 'scope': plan['scope'],
            'size_limit_scope': plan['size_limit_scope']}
        write_json(out / 'summary.json', summary)
        assert len(rows) == plan['expected_cases']
        assert not summary['parent_not_supported']
        assert not summary['carry_violations']
        assert not summary['warm_index_mismatches']
        assert summary['negative_control_detected']
        assert file_hash(PLAN) == plan_hash
        after = source_snapshot(ROOT)
        assert before == after
        manifest.update(status='complete', source_after=after)
    except (Exception, KeyboardInterrupt) as exc:
        manifest.update(status='failed', failure={'type': type(exc).__name__, 'message': str(exc)})
        raise
    finally:
        manifest['artifact_hashes'] = {p.name: file_hash(p) for p in sorted(out.iterdir())
                                      if p.is_file() and p.name != 'manifest.json'}
        write_json(out / 'manifest.json', manifest)


if __name__ == '__main__':
    if not __debug__:
        raise SystemExit('Assertions are required; do not run with -O')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    run(parser.parse_args().out.resolve())
