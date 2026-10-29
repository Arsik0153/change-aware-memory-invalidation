"""Run the frozen synthetic development histories; no real data or human labels."""
from __future__ import annotations

import argparse
import copy
import os
from pathlib import Path
import random
import subprocess
import sys
import traceback

from cami.artifacts import canonical, digest, file_hash, read_json, read_jsonl, write_json, write_jsonl
from cami.models import Claim, Equals, Parameter, Provenance, RunConfig, Signature
from scripts.demo_structural_closure import prepare_closure
from scripts.structural_fixture_oracle import observe
from scripts.verify_cami import source_snapshot

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / 'examples/structural_stress/protocol.json'


def validate_protocol(spec):
    if (type(spec.get('schema_version')) is not int or spec['schema_version'] != 1
            or spec.get('dataset_kind') != 'synthetic'
            or spec.get('split') != 'development'
            or spec.get('variants') != ['all_validate', 'original_incomplete', 'closed_structural']
            or spec.get('predicates') != ['symbol_exists', 'signature_equals']):
        raise ValueError('Only the synthetic development structural variants are supported')
    seeds = spec.get('seeds')
    if (not isinstance(seeds, list) or not seeds
            or any(type(seed) is not int or seed < 0 for seed in seeds)
            or len(set(seeds)) != len(seeds)):
        raise ValueError('Seeds must be nonempty, unique nonnegative integers')
    for field, minimum in [('files', 1), ('functions_per_file', 1), ('random_events_per_history', 0)]:
        if type(spec.get(field)) is not int or spec[field] < minimum:
            raise ValueError(f'Invalid {field}')
    events = {'unrelated', 'body', 'signature', 'duplicate', 'restore', 'remove',
              'parse', 'file_delete', 'no_change'}
    for field in ('fixed_events', 'random_event_choices'):
        values = spec.get(field)
        if not isinstance(values, list) or not values or any(v not in events for v in values):
            raise ValueError(f'Invalid {field}')


def git(repo, *arguments):
    environment = {**os.environ, 'GIT_AUTHOR_DATE': '2026-10-29T00:00:00Z',
                   'GIT_COMMITTER_DATE': '2026-10-29T00:00:00Z'}
    return subprocess.check_output(['git', '--no-replace-objects', '-C', str(repo), *arguments],
                                   env=environment, stderr=subprocess.PIPE).decode().strip()


def render(functions, mode):
    if mode == 'deleted':
        return None
    definitions = []
    for number, state in enumerate(functions):
        if state == 'absent':
            continue
        header = f'def f{number}(x' + (', extra=None' if state == 'signature' else '') + '):\n'
        definition = header + ('    return x + 7\n' if state == 'body' else '    return x\n')
        definitions.append(definition)
        if state == 'duplicate':
            definitions.append(definition)
    return '\n'.join(definitions) + ('\ndef broken(:\n' if mode == 'parse' else '')


def generator_verdict(mode, state, kind):
    if mode == 'deleted':
        return 'contradicted'
    if mode == 'parse' or state == 'duplicate':
        return 'insufficient_evidence'
    if state == 'absent' or (state == 'signature' and kind == 'signature_equals'):
        return 'contradicted'
    return 'supported'


def history(spec, seed):
    rng = random.Random(seed)
    functions = [['original'] * spec['functions_per_file'] for _ in range(spec['files'])]
    modes = ['valid'] * spec['files']
    events = list(spec['fixed_events']) + [rng.choice(spec['random_event_choices'])
                                         for _ in range(spec['random_events_per_history'])]
    records = []
    unrelated = 0
    for index, event in enumerate(['parent', *events]):
        file_number = rng.randrange(spec['files'])
        function_number = rng.randrange(spec['functions_per_file'])
        if event in ('body', 'signature', 'duplicate', 'remove'):
            modes[file_number] = 'valid'
            functions[file_number][function_number] = 'absent' if event == 'remove' else event
        elif event == 'restore':
            modes[file_number] = 'valid'
            functions[file_number] = ['original'] * spec['functions_per_file']
        elif event in ('parse', 'file_delete'):
            modes[file_number] = 'parse' if event == 'parse' else 'deleted'
        elif event == 'unrelated':
            unrelated += 1
        elif event not in ('parent', 'no_change'):
            raise ValueError('Unknown event')
        records.append({'step': index, 'event': event, 'target_file': file_number,
                        'target_function': function_number, 'functions': copy.deepcopy(functions),
                        'modes': list(modes), 'unrelated': unrelated})
    return records


def commit_record(repo, record):
    for number, (functions, mode) in enumerate(zip(record['functions'], record['modes'], strict=True)):
        target = repo / f'module{number}.py'
        source = render(functions, mode)
        if source is None:
            target.unlink(missing_ok=True)
        else:
            target.write_text(source)
    (repo / 'unrelated.txt').write_text(str(record['unrelated']) + '\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '--allow-empty', '-qm', f"step-{record['step']:02d}-{record['event']}")
    return git(repo, 'rev-parse', 'HEAD')


def fixture(base, spec, seed):
    base.mkdir(parents=True, exist_ok=False)
    repo = base / 'parent/repo'
    repo.mkdir(parents=True)
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.name', 'CAMI synthetic structural stress')
    git(repo, 'config', 'user.email', 'fixture@example.invalid')
    records = history(spec, seed)
    parent = commit_record(repo, records[0])
    claims = []
    signature = Signature(parameters=(Parameter(name='x', kind='positional_or_keyword'),))
    for file_number in range(spec['files']):
        for function in range(spec['functions_per_file']):
            for kind in spec['predicates']:
                path, name = f'module{file_number}.py', f'f{function}'
                predicate = {'type': 'symbol_exists', 'expected': True} if kind == 'symbol_exists' else (
                    Equals(type='signature_equals', expected_signature=signature).model_dump(mode='json'))
                claims.append(Claim.model_validate_json(canonical({
                    'claim_id': f's{seed:02d}-m{file_number}-{name}-{kind}',
                    'repo_id': 'structural-fixture', 'origin_commit': parent, 'kind': kind,
                    'subject': {'path': path, 'qualname': name, 'node_kind': 'function'},
                    'predicate': predicate, 'text': f'Exact {kind} predicate for {path}::{name}.',
                    'scope': 'Exact syntactic definition, no runtime semantics.'})))
    write_jsonl(base / 'parent/claims.jsonl', claims)
    write_jsonl(base / 'parent/provenance.jsonl', [{
        'schema_version': 1, 'claim_id': c.claim_id, 'scenario_id': 'intact',
        'anchors': [{'path': c.subject.path, 'qualname': c.subject.qualname, 'scope': 'symbol',
                     'observed_commit': parent, 'content_hash': file_hash(repo / c.subject.path),
                     'origin': 'static'}], 'dependencies': [], 'known_incomplete': True,
        'unresolved_reasons': ['Draft parent-only anchors; dependency extraction and review pending.']}
        for c in claims])
    prepare_closure(base / 'parent', parent, claims, base / 'derived')
    revisions = [parent, *[commit_record(repo, record) for record in records[1:]]]
    for index, (revision, record) in enumerate(zip(revisions, records, strict=True)):
        record['tree'] = git(repo, 'rev-parse', revision + '^{tree}')
        record['changed_paths'] = (git(repo, 'diff', '--name-only', revisions[index-1], revision).splitlines()
                                   if index else [])
    observations = []
    for revision, record in zip(revisions, records, strict=True):
        blobs = {}
        for number, (functions, mode) in enumerate(zip(record['functions'], record['modes'], strict=True)):
            path = f'module{number}.py'
            authored = render(functions, mode)
            exists = bool(git(repo, 'ls-tree', revision, '--', path))
            raw = subprocess.check_output(['git', '--no-replace-objects', '-C', str(repo),
                                           'show', f'{revision}:{path}']).decode() if exists else None
            if raw != authored:
                raise ValueError('Git blob differs from generated source')
            blobs[path] = raw
        for claim in claims:
            file_number = int(claim.subject.path.removeprefix('module').removesuffix('.py'))
            function = int(claim.subject.qualname.removeprefix('f'))
            expected = generator_verdict(record['modes'][file_number],
                                          record['functions'][file_number][function], claim.kind)
            observed = observe(blobs[claim.subject.path], claim.subject.qualname, claim.kind)
            if observed != expected:
                raise ValueError(f'Independent oracle mismatch: {revision}/{claim.claim_id}')
            observations.append({'commit': revision, 'claim_id': claim.claim_id,
                                 'generator': expected, 'oracle': observed})
    write_json(base / 'history.json', {'records': records, 'revisions': revisions})
    write_jsonl(base / 'oracle.jsonl', observations)
    write_json(base / 'parent_oracle.json', {'synthetic': True, 'independent_human_review': False,
        'observations': [r for r in observations if r['commit'] == parent]})
    write_jsonl(base / 'parent_receipts.jsonl', [{'schema_version': 1, 'claim_id': c.claim_id,
        'origin_commit': parent, 'status': 'supported',
        'confirmation_type': 'synthetic_authored_tokenizer_oracle',
        'evidence_path': 'parent_oracle.json', 'evidence_sha256': file_hash(base / 'parent_oracle.json')}
        for c in claims])
    for variant in spec['variants']:
        write_json(base / f'{variant}.json', {'schema_version': 1, 'protocol_version': '1.1',
            'repo': {'repo_id': 'structural-fixture', 'path': 'parent/repo', 'source_roots': ['.']},
            'parent_commit': parent, 'child_commits': revisions[1:], 'claims_path': 'parent/claims.jsonl',
            'provenance_path': 'derived/provenance.jsonl' if variant == 'closed_structural' else 'parent/provenance.jsonl',
            'parent_receipts_path': 'parent_receipts.jsonl', 'scenario_id': 'intact',
            'dataset_kind': 'synthetic', 'split': 'development', 'stratum': 'fixture',
            'policy': {'id': 'all_validate' if variant == 'all_validate' else 'symbol_validate', 'dependency_depth': 1},
            'cache_dir': None, 'seed': seed, 'validation': {'execution': 'disabled', 'llm': 'disabled'}})
    return claims, records, revisions, observations


def verify_run(base, variant, claims, records, revisions, observations):
    run = base / 'runs' / variant
    manifest = read_json(run / 'manifest.json')
    ids = {c.claim_id for c in claims}
    if manifest['status'] != 'complete' or set(manifest['cohort']) != ids or manifest['excluded']:
        raise ValueError('Incomplete run or changed cohort')
    expected_config = RunConfig.model_validate_json((base / f'{variant}.json').read_bytes())
    expected_config = expected_config.model_copy(update={'repo': expected_config.repo.model_copy(
        update={'path': str((base / expected_config.repo.path).resolve())})})
    expected_policy = 'all_validate' if variant == 'all_validate' else 'symbol_validate'
    provenance = 'derived/provenance.jsonl' if variant == 'closed_structural' else 'parent/provenance.jsonl'
    if (manifest['config'] != expected_config.model_dump(mode='json')
            or manifest.get('configuration_hash') != digest(expected_config)
            or expected_config.policy.id != expected_policy or expected_config.provenance_path != provenance
            or expected_config.dataset_kind != 'synthetic' or expected_config.split != 'development'
            or expected_config.validation.execution != 'disabled' or expected_config.validation.llm != 'disabled'):
        raise ValueError('Configuration does not attest the intended synthetic variant')
    expected_inputs = {'claims': file_hash(base / 'parent/claims.jsonl'),
                       'provenance': file_hash(base / provenance),
                       'parent_receipts': file_hash(base / 'parent_receipts.jsonl'),
                       **{f'parent_evidence/{c.claim_id}': file_hash(base / 'parent_oracle.json') for c in claims}}
    if manifest.get('input_hashes') != expected_inputs:
        raise ValueError('Input hash inventory mismatch')
    if manifest.get('claim_hashes') != {c.claim_id: digest(c) for c in claims}:
        raise ValueError('Claim hash inventory mismatch')
    inventory = {str(p.relative_to(run)) for p in run.rglob('*') if p.is_file() and p != run / 'manifest.json'}
    if set(manifest['artifact_hashes']) != inventory:
        raise ValueError('Artifact hash inventory mismatch')
    for path, sha in manifest['artifact_hashes'].items():
        if file_hash(run / path) != sha:
            raise ValueError(f'Artifact hash mismatch: {path}')
    expected_provenance = sorted((Provenance.model_validate_json(canonical(r)).model_dump(
        mode='json', by_alias=True) for r in read_jsonl(base / provenance)), key=lambda r: r['claim_id'])
    if (sorted(read_jsonl(run / 'provenance.jsonl'), key=lambda r: r['claim_id']) != expected_provenance
            or any(r['known_incomplete'] != (variant != 'closed_structural') for r in expected_provenance)):
        raise ValueError('Run provenance differs from the intended fixture variant')
    if sorted(read_jsonl(run / 'claims.jsonl'), key=lambda c: c['claim_id']) != [
            c.model_dump(mode='json') for c in sorted(claims, key=lambda c: c.claim_id)]:
        raise ValueError('Immutable claims changed')
    if manifest['config']['cache_dir'] is not None:
        raise ValueError('Verdict cache enabled')
    selections, validations, states, costs = [read_jsonl(run / name) for name in (
        'selections.jsonl', 'validations.jsonl', 'states.jsonl', 'costs.jsonl')]
    required = {(revision, claim_id) for revision in revisions[1:] for claim_id in ids}
    for label, rows, key in [('selections', selections, 'commit'), ('states', states, 'revision'),
                             ('validations', validations, 'commit')]:
        keys = [(row[key], row['claim_id']) for row in rows]
        if (len(keys) != len(set(keys)) or not set(keys) <= required
                or label != 'validations' and set(keys) != required):
            raise ValueError(f'Duplicate, unexpected or missing {label} rows')
    cost_keys = [(row['phase'], row['commit']) for row in costs]
    if (len(cost_keys) != len(set(cost_keys)) or set(cost_keys) != {
            ('preflight', revisions[0]), *[('maintenance', r) for r in revisions[1:]]}):
        raise ValueError('Duplicate, unexpected or missing cost rows')
    expected = {(r['commit'], r['claim_id']): r['oracle'] for r in observations}
    last_checked = dict.fromkeys(ids, revisions[0])
    last_supported = dict(last_checked)
    last_verdict = dict.fromkeys(ids, 'supported')
    rows, mismatches = [], []
    for revision, record in zip(revisions[1:], records[1:], strict=True):
        decisions = {r['claim_id']: r for r in selections if r['commit'] == revision}
        results = {r['claim_id']: r for r in validations if r['commit'] == revision}
        current = {r['claim_id']: r for r in states if r['revision'] == revision}
        selected = {key for key, r in decisions.items() if r['selected']}
        if set(decisions) != ids or set(current) != ids or set(results) != selected:
            raise ValueError('Selection/state/result coverage mismatch')
        if variant != 'closed_structural' and selected != ids:
            raise ValueError('Baseline or incomplete fallback failed to select all claims')
        if variant == 'original_incomplete' and any('known_incomplete' not in r['reasons'] for r in decisions.values()):
            raise ValueError('Incomplete provenance fallback reason missing')
        for claim_id in sorted(ids):
            wanted = expected[revision, claim_id]
            if claim_id in results:
                last_checked[claim_id] = revision
                last_verdict[claim_id] = wanted
                if wanted == 'supported':
                    last_supported[claim_id] = revision
                if results[claim_id]['verdict'] != wanted or results[claim_id]['cache_hit']:
                    mismatches.append({'commit': revision, 'claim_id': claim_id, 'field': 'verdict',
                                       'expected': wanted, 'actual': results[claim_id]['verdict']})
            state = current[claim_id]
            for field, value in [('available', wanted == 'supported'),
                                 ('last_checked_commit', last_checked[claim_id]),
                                 ('last_supported_commit', last_supported[claim_id]),
                                 ('last_verdict', last_verdict[claim_id]),
                                 ('basis', 'validated' if claim_id in selected else 'carried_forward')]:
                if state[field] != value:
                    mismatches.append({'commit': revision, 'claim_id': claim_id, 'field': field,
                                       'expected': value, 'actual': state[field]})
            if claim_id not in selected and state['basis'] != 'carried_forward':
                raise ValueError('Unselected claim lost carried state')
            allowed_states = {'supported': {'valid'}, 'contradicted': {'stale', 'retired'},
                              'insufficient_evidence': {'needs_validation'}}
            if state['state'] not in allowed_states[last_verdict[claim_id]]:
                mismatches.append({'commit': revision, 'claim_id': claim_id, 'field': 'state',
                    'expected': sorted(allowed_states[last_verdict[claim_id]]), 'actual': state['state']})
        cost = next(r for r in costs if r['commit'] == revision and r['phase'] == 'maintenance')
        if cost['actual_validations'] != len(selected) or cost['cache_hits']:
            raise ValueError('Actual validation accounting mismatch')
        rows.append({'step': record['step'], 'event': record['event'], 'commit': revision,
                     'changed_paths': record['changed_paths'], 'effective_change': bool(record['changed_paths']),
                     'selected': len(selected), 'carried': len(ids-selected),
                     'oracle_supported': sum(expected[revision, c] == 'supported' for c in ids),
                     'oracle_contradicted': sum(expected[revision, c] == 'contradicted' for c in ids),
                     'oracle_uncertain': sum(expected[revision, c] == 'insufficient_evidence' for c in ids)})
    return {'status': 'failed' if mismatches else 'passed', 'variant': variant,
            'states_checked': len(ids) * (len(revisions)-1), 'mismatches': mismatches,
            'actual_validations': sum(r['selected'] for r in rows), 'transitions': rows}


def run_study(output, protocol=PROTOCOL):
    spec = read_json(protocol)
    validate_protocol(spec)
    before = source_snapshot(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'protocol.json', spec)
    report = {'schema_version': 1, 'status': 'running', 'study_id': spec['study_id'],
              'protocol_sha256': file_hash(protocol), 'git_head': git(ROOT, 'rev-parse', 'HEAD'),
              'implementation_hashes': {str(p.relative_to(ROOT)): file_hash(p) for p in (
                  Path(__file__), ROOT / 'scripts/structural_fixture_oracle.py',
                  ROOT / 'scripts/demo_structural_closure.py')},
              'dataset_kind': 'synthetic', 'split': 'development',
              'source_before': before, 'independent_human_labels': False, 'seeds': []}
    report['python'] = sys.version
    report['git_version'] = git(ROOT, '--version')
    write_json(output / 'summary.json', report)
    for seed in spec['seeds']:
        base = output / f'seed-{seed:02d}'
        row = {'seed': seed, 'status': 'running',
               'variants': [{'variant': variant, 'status': 'not_run'} for variant in spec['variants']]}
        report['seeds'].append(row)
        try:
            claims, records, revisions, observations = fixture(base, spec, seed)
            input_files = [p for p in base.rglob('*') if p.is_file() and 'repo' not in p.relative_to(base).parts]
            hashes = {str(p.relative_to(base)): file_hash(p) for p in input_files}
            order = spec['variants'][seed % 3:] + spec['variants'][:seed % 3]
            row['run_order'] = order
            for variant in order:
                variant_result = next(r for r in row['variants'] if r['variant'] == variant)
                command = [sys.executable, '-m', 'cami.cli', 'run', '--config', str(base / f'{variant}.json'),
                           '--out', str(base / 'runs' / variant)]
                try:
                    result = subprocess.run(command, capture_output=True, cwd=ROOT)
                    (base / f'{variant}.stdout.log').write_bytes(result.stdout)
                    (base / f'{variant}.stderr.log').write_bytes(result.stderr)
                    variant_result['exit_code'] = result.returncode
                    if result.returncode:
                        variant_result['status'] = 'failed'
                    else:
                        variant_result.update(verify_run(base, variant, claims, records, revisions, observations))
                except Exception as error:
                    variant_result.update(status='failed', error=f'{type(error).__name__}: {error}')
                    (base / f'{variant}-error.log').write_text(traceback.format_exc())
                write_json(output / 'summary.json', report)
            if any(file_hash(base / name) != sha for name, sha in hashes.items()):
                raise ValueError('Fixture input changed during execution')
            row['input_hashes'] = hashes
            row['oracle_checks'] = len(observations)
            row['status'] = 'passed' if all(r['status'] == 'passed' for r in row['variants']) else 'failed'
        except Exception as error:
            row.update(status='failed', error=f'{type(error).__name__}: {error}')
            (output / f'seed-{seed:02d}-error.log').write_text(traceback.format_exc())
        write_json(output / 'summary.json', report)
        print(f"seed={seed}: {row['status']}", flush=True)
    report['status'] = 'passed' if all(r['status'] == 'passed' for r in report['seeds']) else 'failed'
    report['source_after'] = source_snapshot(ROOT)
    report['source_snapshots_match'] = before == report['source_after']
    if not report['source_snapshots_match'] or file_hash(protocol) != report['protocol_sha256']:
        report['status'] = 'failed'
        report['error'] = 'Implementation or protocol changed during the study'
    report['artifact_hashes'] = {str(p.relative_to(output)): file_hash(p) for p in output.rglob('*')
        if p.is_file() and '.git' not in p.parts and p != output / 'summary.json'}
    write_json(output / 'summary.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, default=PROTOCOL)
    args = parser.parse_args()
    summary = run_study(args.out.resolve(), args.protocol.resolve())
    raise SystemExit(0 if summary['status'] == 'passed' else 1)
