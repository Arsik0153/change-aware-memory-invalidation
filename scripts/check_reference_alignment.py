"""Research-only comparison and transition experiment against a frozen syntax reference."""
from __future__ import annotations

import argparse
import importlib.util
import sys
from collections import Counter
from pathlib import Path

from cami.artifacts import digest, file_hash, read_json, reserve, write_json, write_jsonl
from cami.index import build_index, compare_indexes
from cami.models import Anchor, MemoryState, PolicyConfig, Provenance, ValidationResult
from cami.policies import SelectionContext, advance_state, select_claims
from cami.validation import ValidationContext, validate_claim
from scripts.check_structural_carry import SUBJECT, claims, snapshot
from scripts.verify_cami import source_snapshot


def repository_root() -> Path:
    return next(parent for parent in Path(__file__).resolve().parents
                if (parent / 'pyproject.toml').is_file() and (parent / 'src/cami').is_dir())


ROOT = repository_root()
PROTOCOL = ROOT / 'examples/structural_closure/reference_alignment_protocol.json'
REFERENCE = ROOT / 'scripts/structural_checker.py'
VARIANTS = ('symbol_anchor', 'file_anchor', 'all_validate')


def load_reference(path: Path):
    spec = importlib.util.spec_from_file_location('alignment_frozen_reference', path)
    if spec is None or spec.loader is None:
        raise ValueError(f'Cannot load reference: {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_record(packet: Path, relative: str, source: str) -> dict:
    path = packet / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = source.encode('utf-8')
    with path.open('xb') as stream:
        stream.write(raw)
    return {'path': relative, 'encoding': 'utf-8', 'source': source,
            'byte_count': len(raw), 'sha256': file_hash(path)}


def reference_case(claim, source: dict, phase: str) -> dict:
    return {'id': f'{claim.claim_id}:{phase}', 'kind': claim.kind,
            'subject': claim.subject.model_dump(mode='json'),
            'predicate': claim.predicate.model_dump(mode='json'),
            'text': claim.text, 'scope': claim.scope,
            'source_path': source['path'], 'source_sha256': source['sha256']}


def adapt_reference(claim, revision: str, result: dict) -> ValidationResult:
    verdict = {'supported': 'supported', 'contradicted': 'contradicted',
               'uncertain': 'insufficient_evidence'}[result['verdict']]
    reason = ('reference_uncertain' if result['verdict'] == 'uncertain'
              else 'subject_absent' if result['facts'].get('exists') is False
              else 'reference_' + result['verdict'])
    return ValidationResult(claim_id=claim.claim_id, commit=revision,
        validator='research_independent_reference', verdict=verdict, reason=reason,
        evidence=(result['reason'],), input_hash=digest(result), duration_seconds=0.0)


def provenance_for(claim, parent, variant: str) -> Provenance:
    if variant not in VARIANTS:
        raise ValueError(f'Unknown selector variant: {variant}')
    return Provenance(claim_id=claim.claim_id, scenario_id='authored-synthetic',
        anchors=(Anchor(path=SUBJECT.path, qualname=SUBJECT.qualname,
            scope='file' if variant == 'file_anchor' else 'symbol',
            observed_commit=parent.revision, content_hash=parent.blobs[0].content_hash,
            origin='manual'),), known_incomplete=False)


def changes_record(changes) -> dict:
    def node_key(node):
        return node['path'], node['qualname'] or ''
    return {'files': sorted(changes.files),
            'symbols': sorted((n.model_dump(mode='json') for n in changes.symbols), key=node_key),
            'edges': sorted((e.model_dump(mode='json', by_alias=True) for e in changes.edges),
                            key=digest),
            'unresolved': sorted((n.model_dump(mode='json') for n in changes.unresolved), key=node_key),
            'limited_paths': sorted(changes.limited_paths),
            'global_unresolved': changes.global_unresolved}


def observe_pair(parent_source: str, mutation: dict, packet: Path, reference,
                 protocol_version: str = '1.1') -> tuple[dict, list[dict], list[dict]]:
    """Observe one full handwritten pair; does not read or collect the protocol."""
    pair_id = mutation['id']
    parent = snapshot(parent_source)
    child = snapshot(mutation['child_source'])
    sources = {'parent': source_record(packet, f'sources/{pair_id}/parent.py', parent_source),
               'child': source_record(packet, f'sources/{pair_id}/child.py', mutation['child_source'])}
    cache = {}
    before = build_index(parent, cache=cache)
    after = build_index(child, cache=cache)
    fresh = build_index(child)
    assert after == fresh, 'Warm and fresh child indexes differ'
    changes = compare_indexes(before, after, parent, child)
    cohort = claims(parent, pair_id)
    comparisons, states = [], []
    for claim in cohort:
        prov = provenance_for(claim, parent, 'symbol_anchor')
        cases = {phase: reference_case(claim, source, phase) for phase, source in sources.items()}
        independent = {phase: reference.check_case(packet, case) for phase, case in cases.items()}
        full = {'parent': validate_claim(claim, ValidationContext(parent, before, prov, ROOT, packet)),
                'child': validate_claim(claim, ValidationContext(child, fresh, prov, ROOT, packet))}
        assert independent['parent']['verdict'] == 'supported', 'Reference parent is not supported'
        assert full['parent'].verdict == 'supported', 'Production parent is not supported'
        for phase in sources:
            assert independent[phase]['source_sha256'] == sources[phase]['sha256']
        expected = mutation['authored_expected'][claim.kind]
        normalized = 'uncertain' if full['child'].verdict == 'insufficient_evidence' else full['child'].verdict
        common = {'mutation': pair_id, 'claim_id': claim.claim_id, 'claim_kind': claim.kind,
            'claim': claim.model_dump(mode='json'), 'sources': sources,
            'parent_revision': parent.revision, 'child_revision': child.revision,
            'changes': changes_record(changes), 'warm_index_equals_fresh': after == fresh,
            'reference_cases': cases, 'reference_results': independent,
            'full_validator_provenance': prov.model_dump(mode='json'),
            'full_validator_results': {phase: result.model_dump(mode='json') for phase, result in full.items()},
            'authored_expected': expected,
            'reference_authored_expected_mismatch': independent['child']['verdict'] != expected,
            'production_reference_child_mismatch': normalized != independent['child']['verdict'],
            'production_reference_parent_mismatch': full['parent'].verdict != independent['parent']['verdict']}
        comparisons.append(common)
        for variant in VARIANTS:
            provenance = provenance_for(claim, parent, variant)
            policy = PolicyConfig(id='all_validate' if variant == 'all_validate' else 'symbol_validate')
            previous = MemoryState(claim_id=claim.claim_id, revision=parent.revision,
                state='valid', available=True, basis='validated', current_provenance=provenance,
                last_checked_commit=parent.revision, last_supported_commit=parent.revision,
                last_verdict='supported')
            selection, = select_claims(SelectionContext(child.revision, (claim,), (provenance,),
                (previous,), changes, protocol_version=protocol_version), policy)
            validation = adapt_reference(claim, child.revision, independent['child']) if selection.selected else None
            state = advance_state(previous, selection, policy, validation, structural=True)
            verdict = independent['child']['verdict']
            states.append({**common, 'selector_variant': variant,
                'policy': policy.model_dump(mode='json'),
                'provenance': provenance.model_dump(mode='json'),
                'previous_state': previous.model_dump(mode='json'),
                'selection': selection.model_dump(mode='json'),
                'selected_validation_result': validation.model_dump(mode='json') if validation else None,
                'state': state.model_dump(mode='json'),
                'available_when_reference_not_supported': state.available and verdict != 'supported',
                'available_when_provably_contradicted': state.available and verdict == 'contradicted',
                'available_when_reference_uncertain': state.available and verdict == 'uncertain'})
    return {'mutation': pair_id, 'sources': sources,
            'parent_revision': parent.revision, 'child_revision': child.revision}, comparisons, states


def summary_for(comparisons: list[dict], states: list[dict], inputs: list[dict]) -> dict:
    def counts(rows):
        return {'states': len(rows), 'selected': sum(row['selection']['selected'] for row in rows),
            'available': sum(row['state']['available'] for row in rows),
            **{metric: sum(row[metric] for row in rows) for metric in (
                'available_when_reference_not_supported', 'available_when_provably_contradicted',
                'available_when_reference_uncertain')}}
    return {'input_pairs': len(inputs), 'claim_transitions': len(comparisons),
        'policy_states': len(states),
        'measurement_1_full_production_vs_reference': {
            'comparisons': len(comparisons),
            'parent_mismatches': sum(row['production_reference_parent_mismatch'] for row in comparisons),
            'child_mismatches': sum(row['production_reference_child_mismatch'] for row in comparisons),
            'reference_authored_expected_mismatches': sum(row['reference_authored_expected_mismatch'] for row in comparisons),
            'reference_child_verdicts': dict(Counter(row['reference_results']['child']['verdict'] for row in comparisons)),
            'production_child_verdicts': dict(Counter(row['full_validator_results']['child']['verdict'] for row in comparisons))},
        'measurement_2_research_reference_pipeline': {
            'overall': counts(states),
            'by_selector_variant': {variant: counts([r for r in states if r['selector_variant'] == variant]) for variant in VARIANTS}},
        'scope': 'Authored synthetic development challenge; no real records, labels, receipts, or real-data effect sizes.',
        'uncertainty_interpretation': 'Reference uncertain is not proof of a false claim; unavailable support and provable contradiction are separate metrics.'}


def check_protocol(plan: dict) -> None:
    assert plan['experiment'] == 'structural-reference-transition-alignment-v1'
    assert plan['known_incomplete'] is False
    assert plan['protocol_version'] == '1.1'
    assert plan['predicates'] == ['symbol_exists', 'signature_equals']
    assert plan['selector_variants'] == list(VARIANTS)
    assert len(plan['mutations']) == plan['expected_input_pairs'] == 21
    assert len({m['id'] for m in plan['mutations']}) == 21
    assert plan['expected_claim_transitions'] == 42
    assert plan['expected_policy_states'] == 126
    for mutation in plan['mutations']:
        assert set(mutation['authored_expected']) == set(plan['predicates'])
        assert set(mutation['authored_expected'].values()) <= {'supported', 'contradicted', 'uncertain'}


def run(out: Path, reference_path: Path = REFERENCE, *, explicit_reference: bool = False) -> None:
    reserve(out)
    manifest = {'status': 'running', 'produces_labels_or_receipts': False,
                'reference_override_explicit': explicit_reference,
                'python': sys.version, 'runner_path': str(Path(__file__).resolve()),
                'runner_sha256': file_hash(Path(__file__))}
    write_json(out / 'manifest.json', manifest)
    inputs, comparisons, states = [], [], []
    try:
        before = source_snapshot(ROOT)
        manifest['source_before'] = before
        assert not before['source_status'], 'Commit source before execution'
        protocol_hash = file_hash(PROTOCOL)
        reference_hash = file_hash(reference_path)
        plan = read_json(PROTOCOL)
        manifest.update(protocol_sha256=protocol_hash, reference_sha256=reference_hash,
                        reference_path=str(reference_path),
                        protocol_reference_sha256=plan['frozen_reference_sha256'])
        write_json(out / 'manifest.json', manifest)
        (out / 'protocol.json').write_bytes(PROTOCOL.read_bytes())
        (out / 'frozen-reference.py').write_bytes(reference_path.read_bytes())
        check_protocol(plan)
        if not explicit_reference:
            assert reference_hash == plan['frozen_reference_sha256'], 'Default frozen reference hash changed'
        reference = load_reference(out / 'frozen-reference.py')
        for mutation in plan['mutations']:
            input_row, pair_comparisons, pair_states = observe_pair(
                plan['parent_source'], mutation, out, reference, plan['protocol_version'])
            inputs.append(input_row)
            comparisons.extend(pair_comparisons)
            states.extend(pair_states)
            write_jsonl(out / 'inputs.jsonl', inputs)
            write_jsonl(out / 'comparisons.jsonl', comparisons)
            write_jsonl(out / 'states.jsonl', states)
        summary = summary_for(comparisons, states, inputs)
        summary['limits'] = plan['limits']
        write_json(out / 'summary.json', summary)
        assert len(inputs) == plan['expected_input_pairs']
        assert len(comparisons) == plan['expected_claim_transitions']
        assert len(states) == plan['expected_policy_states']
        assert len({(r['mutation'], r['claim_kind']) for r in comparisons}) == 42
        assert len({(r['mutation'], r['claim_kind'], r['selector_variant']) for r in states}) == 126
        for row in inputs:
            for source in row['sources'].values():
                assert file_hash(out / source['path']) == source['sha256']
        assert file_hash(PROTOCOL) == protocol_hash
        assert file_hash(reference_path) == reference_hash
        assert file_hash(out / 'protocol.json') == protocol_hash
        assert file_hash(out / 'frozen-reference.py') == reference_hash
        assert file_hash(Path(__file__)) == manifest['runner_sha256']
        after = source_snapshot(ROOT)
        manifest['source_after'] = after
        assert before == after, 'Source changed during execution'
        manifest['status'] = 'complete'
    except (Exception, KeyboardInterrupt) as exc:
        manifest.update(status='failed', failure={'type': type(exc).__name__, 'message': str(exc)})
        raise
    finally:
        manifest.setdefault('source_after', source_snapshot(ROOT))
        manifest['artifact_hashes'] = {
            p.relative_to(out).as_posix(): file_hash(p) for p in sorted(out.rglob('*'))
            if p.is_file() and p.name != 'manifest.json' and '__pycache__' not in p.parts}
        write_json(out / 'manifest.json', manifest)


def main() -> None:
    if not __debug__:
        raise SystemExit('Assertions are required; do not run with -O')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', type=Path,
                        help='Explicit separately identified reference override; hash is recorded')
    args = parser.parse_args()
    run(args.out.resolve(), args.reference.resolve() if args.reference else REFERENCE,
        explicit_reference=args.reference is not None)


if __name__ == '__main__':
    main()
