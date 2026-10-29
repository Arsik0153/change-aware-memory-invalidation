"""Exhaustive small scorer algebra audit, not an experiment on policy effectiveness."""
from __future__ import annotations

import argparse
from itertools import product
from pathlib import Path

from cami.artifacts import file_hash, reserve, write_json, write_jsonl
from cami.evaluation import Label, Observation, compute_metrics
from cami.models import Claim, MemoryState, Provenance, Selection, ValidationResult
from scripts.verify_cami import source_snapshot

ROOT = Path(__file__).resolve().parents[1]
FIXED = {'stale_exposure', 'valid_retention', 'valid_withholding', 'selection_recall',
         'false_invalidation', 'invalidation_recall'}
VARIABLE = {'available_contamination', 'invalidation_precision', 'invalidation_f1'}
LABELS = ('supported', 'contradicted', 'uncertain')
STATES = ('valid', 'needs_validation', 'stale')


def observations(labels, states):
    rows = []
    for i, (label, state) in enumerate(zip(labels, states, strict=True)):
        claim = Claim(claim_id=f'fixture-{i}', repo_id='synthetic-algebra', origin_commit='parent',
                      kind='symbol_exists', text='Authored scorer fixture, no repository observation.',
                      scope='Synthetic metric algebra only',
                      subject={'path':'fixture.py','qualname':f'f{i}','node_kind':'function'},
                      predicate={'type':'symbol_exists','expected':True})
        checked = state != 'valid'
        verdict = {'valid':'supported','needs_validation':'insufficient_evidence','stale':'contradicted'}[state]
        validation = (ValidationResult(claim_id=claim.claim_id, commit='child', validator='structural',
                        verdict=verdict, reason='synthetic_authored_case', input_hash='fixture', duration_seconds=0)
                      if checked else None)
        rows.append(Observation(claim=claim,
            state=MemoryState(claim_id=claim.claim_id, revision='child', state=state,
                last_checked_commit='child' if checked else 'parent', last_supported_commit='parent',
                last_verdict=verdict, basis='validated' if checked else 'carried_forward',
                current_provenance=Provenance(claim_id=claim.claim_id, scenario_id='synthetic'),
                available=state == 'valid'),
            selection=Selection(claim_id=claim.claim_id, commit='child', selected=checked,
                                reasons=('synthetic_authored_case',)),
            label=Label(claim_id=claim.claim_id, commit='child', label=label,
                        annotator_id='synthetic_metric_algebra', evidence=('Authored combinatorial fixture',),
                        confirmation_type='synthetic_authored_oracle', adjudication_status='not_required'),
            validation=validation))
    return tuple(rows)


def expected_counts(labels, states):
    supported = {i for i, label in enumerate(labels) if label == 'supported'}
    contradicted = {i for i, label in enumerate(labels) if label == 'contradicted'}
    uncertain = set(range(len(labels))) - supported - contradicted
    available = {i for i, state in enumerate(states) if state == 'valid'}
    selected = set(range(len(states))) - available
    predicted = {i for i, state in enumerate(states) if state == 'stale'} - uncertain
    return {
        'stale_exposure': (len(available & contradicted), len(contradicted)),
        'valid_retention': (len(available & supported), len(supported)),
        'valid_withholding': (len(supported - available), len(supported)),
        'selection_recall': (len(selected & contradicted), len(contradicted)),
        'false_invalidation': (len(predicted & supported), len(supported)),
        'invalidation_recall': (len(predicted & contradicted), len(contradicted)),
        'available_contamination': (len(available & contradicted), len(available & (supported | contradicted))),
        'invalidation_precision': (len(predicted & contradicted), len(predicted)),
        'invalidation_f1': (2 * len(predicted & contradicted), len(predicted) + len(contradicted)),
        'uncertain_available': (len(available & uncertain), None),
    }


def run(out: Path):
    before = source_snapshot(ROOT)
    if before['source_status']:
        raise ValueError('Commit the audit before running it')
    reserve(out)
    manifest = {'status':'running','source_before':before,'scope':'synthetic scorer algebra',
                'policy_execution':False,'real_labels':False,'cases':0}
    write_json(out / 'manifest.json', manifest)
    cases = []
    invariants = []
    variable_support_seen = set()
    not_applicable_checks = 0
    try:
        for labels in product(LABELS, repeat=3):
            denominators = {name:set() for name in FIXED | VARIABLE}
            for states in product(STATES, repeat=3):
                rows = observations(labels, states)
                actual = compute_metrics(rows, 'all_validate', 'synthetic-algebra').metrics
                expected = expected_counts(labels, states)
                assert set(actual) == set(expected)
                for name, (numerator, denominator) in expected.items():
                    metric = actual[name]
                    assert (metric.numerator, metric.denominator) == (numerator, denominator)
                    if denominator is None:
                        assert metric.value == numerator and metric.reason is None
                    else:
                        assert metric.value == (numerator / denominator if denominator else None)
                        assert metric.reason == (None if denominator else 'zero_denominator')
                        denominators[name].add(denominator)
                for policy in ('keep_all','clear_all','file_invalidate','symbol_invalidate'):
                    baseline = compute_metrics(rows, policy, 'applicability-only').metrics
                    for name in ('selection_recall','false_invalidation','invalidation_precision',
                                 'invalidation_recall','invalidation_f1'):
                        metric = baseline[name]
                        assert metric.reason == 'not_applicable' and metric.value is None, (
                            labels, states, policy, name, metric)
                        assert (metric.numerator, metric.denominator) == expected[name]
                        not_applicable_checks += 1
                cases.append({'labels':labels,'states':states,
                              'metrics':{name:metric.model_dump(mode='json') for name,metric in actual.items()}})
            assert all(len(denominators[name]) == 1 for name in FIXED)
            variable_support_seen.update(name for name in VARIABLE
                                         if 0 in denominators[name] and max(denominators[name]) > 0)
            invariants.append({'labels':labels,'denominator_values':{
                name:sorted(values) for name,values in sorted(denominators.items())}})
        assert variable_support_seen == VARIABLE
        write_json(out / 'summary.json', {'status':'passed','cases':len(cases),
            'label_assignments':27,'state_assignments_per_label_set':27,
            'rate_metrics_per_case':9,'count_metrics_per_case':1,
            'not_applicable_checks':not_applicable_checks,
            'fixed_label_denominators':sorted(FIXED),
            'policy_state_dependent_support':sorted(variable_support_seen),
            'invariants_by_label_assignment':invariants,
            'limitations':['Small exhaustive scorer state space, not policy execution or historical data.',
                           'Baseline policy names test applicability only; supplied states are not claimed baseline outputs.',
                           'No coverage or interval estimates computed; synthetic authored labels never imply human review.']})
        manifest.update(status='passed',cases=len(cases),source_after=source_snapshot(ROOT))
        assert manifest['source_after'] == before
    except Exception as exc:
        manifest.update(status='failed',failure={'type':type(exc).__name__,'message':str(exc)})
        raise
    finally:
        write_jsonl(out / 'cases.jsonl', cases)
        manifest['completed_cases'] = len(cases)
        manifest['artifact_hashes'] = {p.name:file_hash(p) for p in out.iterdir()
                                      if p.is_file() and p.name != 'manifest.json'}
        write_json(out / 'manifest.json', manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    run(parser.parse_args().out)
