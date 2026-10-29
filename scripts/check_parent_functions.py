"""Supplementary parent-only observations; never produces validation receipts or labels."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from cami.artifacts import digest, file_hash, load_jsonl, read_json, reserve, within, write_json
from cami.behavior import check_docker
from cami.errors import InputError, ResourceError
from cami.models import Behavior, Claim, EnvironmentProfile, RepoLocation
from cami.repository import materialize, read_snapshot
from scripts.check_parent_environments import ParentInput
from scripts.parent_function_runner import PROBE_SHA256
from scripts.verify_cami import source_snapshot

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / 'examples/parent_function_diagnostics/pytest_protocol.json'
RUNNER = ROOT / 'scripts/parent_function_runner.py'
BASE_DEPENDENCIES = {'attrs': '23.2.0', 'py': '1.11.0'}
SUPPORTED_DEPENDENCIES = (BASE_DEPENDENCIES, {**BASE_DEPENDENCIES, 'packaging': '26.0'})


def prepare(parents_path, candidates, protocol):
    plan = read_json(protocol)
    if (plan['parent_inputs_sha256'] != file_hash(parents_path)
            or plan['probe_sha256'] != PROBE_SHA256 or plan['entry_point'] != 'test_frozen_case'
            or plan['target_module'] != '_pytest.compat' or plan['target_function'] != 'safe_getattr'
            or plan['python_version'] != '3.9.25' or plan['dependencies'] not in SUPPORTED_DEPENDENCIES
            or type(plan['repetitions']) is not int or plan['repetitions'] != 3):
        raise InputError('Diagnostic plan differs from frozen inputs or execution contract')
    parents = load_jsonl(parents_path, ParentInput, unique='group_id')
    selected = [p for p in parents if p.repo_id == 'pytest']
    if not selected or [p.group_id for p in selected] != plan['groups']:
        raise InputError('Plan must include exactly the selected pytest parent groups')
    prepared = []
    for parent in selected:
        base = within(candidates, parent.group_id)
        draft = read_json(base / 'draft.json')
        if draft['parent_input'] != parent.model_dump(mode='json') or draft['claims_sha256'] != file_hash(base / 'claims.jsonl'):
            raise InputError('Candidate parent or claim bytes changed')
        claims = load_jsonl(base / 'claims.jsonl', Claim, unique='claim_id')
        behavior = [c for c in claims if isinstance(c.predicate, Behavior)]
        if len(behavior) != 1:
            raise InputError('Exactly one frozen behavior candidate is required')
        claim = behavior[0]
        if (claim.origin_commit != parent.parent_commit or claim.repo_id != 'pytest'
                or claim.subject.path != 'src/_pytest/compat.py' or claim.subject.qualname != 'safe_getattr'
                or claim.predicate.probe_sha256 != PROBE_SHA256
                or claim.predicate.node_id != 'test_frozen_probe.py::test_frozen_case'
                or file_hash(within(base, claim.predicate.probe_path)) != PROBE_SHA256):
            raise InputError('Frozen claim/probe binding changed')
        prepared.append((parent, claim, base))
    return plan, prepared


def classify(process, expected_source_hash, expected_origins, dependencies=None):
    dependencies = BASE_DEPENDENCIES if dependencies is None else dependencies
    markers = [line.removeprefix(b'CAMI_FUNCTION_RESULT=') for line in process.stdout.splitlines()
               if line.startswith(b'CAMI_FUNCTION_RESULT=')]
    if process.returncode != 0 or len(markers) != 1:
        return {'status': 'technical_error', 'reason': 'container_or_payload_error'}
    try:
        result = json.loads(markers[0])
        if not isinstance(result, dict):
            raise ValueError('Payload must be an object')
        if (type(result.get('schema_version')) is not int or result['schema_version'] != 1
                or result['execution_mode'] != 'direct_frozen_function' or result['python_version'] != '3.9.25'
                or result['python_flags'] != {'isolated': 1, 'optimize': 0, 'dont_write_bytecode': 1}
                or result['dependencies'] != dependencies
                or result['probe_sha256'] != PROBE_SHA256 or result['preloaded_framework_modules'] != []):
            raise ValueError('Execution contract mismatch')
        if result['status'] == 'technical_error':
            return {'status': 'technical_error', 'reason': 'target_import_or_execution_error', 'payload': result}
        target = result['target']
        if not isinstance(result['module_origins'], dict):
            raise ValueError('Module origins must be an object')
        if (target['path'] != '/repo/src/_pytest/compat.py' or target['sha256'] != expected_source_hash
                or target['function_filename'] != target['path']
                or not {'_pytest', '_pytest.compat'} <= set(result['module_origins'])
                or result['module_origins']['_pytest.compat'] != {'path': target['path'], 'sha256': target['sha256']}):
            raise ValueError('Target source mismatch')
        for name, origin in result['module_origins'].items():
            if (not isinstance(origin, dict) or (name != '_pytest' and not name.startswith('_pytest.'))
                    or expected_origins.get(origin['path']) != origin['sha256']):
                raise ValueError('Module origin does not match parent Git blob')
        if result['status'] not in ('returned', 'assertion_failed'):
            raise ValueError('Unknown function outcome')
        return {'status': result['status'], 'reason': 'direct_frozen_function_observed', 'payload': result}
    except (ValueError, KeyError, TypeError) as error:
        return {'status': 'technical_error', 'reason': 'invalid_attestation', 'error': str(error)}


def observe(snapshot, profile, probe, output, *, dependencies=None):
    blobs = snapshot.by_path()
    expected_source = blobs['src/_pytest/compat.py'].content_hash
    origins = {'/repo/' + b.path: b.content_hash for b in snapshot.blobs if b.content is not None}
    attempts = []
    with tempfile.TemporaryDirectory(prefix='cami-parent-function-') as temp:
        root = Path(temp)
        materialize(snapshot, root / 'repo')
        (root / 'probe').mkdir()
        shutil.copyfile(probe, root / 'probe/test_frozen_probe.py')
        shutil.copyfile(RUNNER, root / 'runner.py')
        for repeat in range(3):
            name = 'cami-function-' + uuid.uuid4().hex
            command = ['docker', 'run', '--rm', '--pull', 'never', '--name', name, '--network', 'none',
                '--read-only', '--user', profile.user, '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                '--cpus', str(profile.cpus), '--memory', f'{profile.memory_mib}m', '--memory-swap', f'{profile.memory_mib}m',
                '--pids-limit', str(profile.pids_limit), '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m', '--workdir', '/tmp',
                '--env', 'PYTHONDONTWRITEBYTECODE=1', '--env', 'PYTHONNOUSERSITE=1',
                '--mount', f'type=bind,src={root / "repo"},dst=/repo,readonly',
                '--mount', f'type=bind,src={root / "probe"},dst=/probe,readonly',
                '--mount', f'type=bind,src={root / "runner.py"},dst=/runner.py,readonly',
                profile.image, 'python', '-I', '-B', '/runner.py']
            try:
                process = subprocess.run(command, capture_output=True, timeout=profile.timeout_seconds)
                stdout, stderr = process.stdout, process.stderr
                outcome = classify(process, expected_source, origins, dependencies)
                outcome['exit_code'] = process.returncode
            except subprocess.TimeoutExpired as error:
                stdout, stderr = error.stdout or b'', error.stderr or b''
                outcome = {'status': 'technical_error', 'reason': 'timeout', 'exit_code': None}
                try:
                    cleanup = subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=15)
                    if cleanup.returncode:
                        outcome['cleanup_error'] = cleanup.stderr.decode(errors='replace')
                except (subprocess.SubprocessError, OSError) as cleanup_error:
                    outcome['cleanup_error'] = str(cleanup_error)
            (output / f'repeat-{repeat}.stdout.log').write_bytes(stdout)
            (output / f'repeat-{repeat}.stderr.log').write_bytes(stderr)
            outcome.update(repeat=repeat, command=command,
                stdout_sha256=file_hash(output / f'repeat-{repeat}.stdout.log'),
                stderr_sha256=file_hash(output / f'repeat-{repeat}.stderr.log'))
            attempts.append(outcome)
            write_json(output / 'attempts.json', attempts)
    return attempts


def check(parents, candidates, image, output, protocol=PROTOCOL):
    plan, prepared = prepare(parents, candidates, protocol)
    if output.resolve().is_relative_to(candidates.resolve()) or output.resolve().is_relative_to(parents.resolve().parent):
        raise InputError('Diagnostic output must be outside source inputs')
    if any(output.resolve().is_relative_to(Path(parent.repo_path).resolve()) for parent, _, _ in prepared):
        raise InputError('Diagnostic output must be outside parent repositories')
    profile = EnvironmentProfile(image=image, python_version=plan['python_version'], source_paths=('src', '.'))
    check_docker(profile)
    before = source_snapshot(ROOT)
    reserve(output)
    hashes = {str(parents.resolve()): file_hash(parents), str(protocol.resolve()): file_hash(protocol)}
    for _, claim, base in prepared:
        for path in [base / 'draft.json', base / 'claims.jsonl', within(base, claim.predicate.probe_path)]:
            hashes[str(path.resolve())] = file_hash(path)
    manifest = {'schema_version': 1, 'status': 'running', 'scope': plan['purpose'],
                'profile': profile.model_dump(mode='json'), 'plan': plan, 'input_hashes': hashes,
                'source_before': before, 'groups': [], 'child_data_used': False,
                'produces_independent_receipts': False, 'real_experiment_eligible': False}

    def save():
        manifest['artifact_hashes'] = {str(p.relative_to(output)): file_hash(p)
            for p in output.rglob('*') if p.is_file() and p != output / 'manifest.json'}
        write_json(output / 'manifest.json', manifest)

    save()
    try:
        for parent, claim, base in prepared:
            target = output / parent.group_id
            target.mkdir()
            row = {'group_id': parent.group_id, 'parent_commit': parent.parent_commit,
                   'claim_id': claim.claim_id, 'claim_sha256': digest(claim), 'attempts': 0}
            manifest['groups'].append(row)
            try:
                snapshot = read_snapshot(RepoLocation(repo_id='pytest', path=parent.repo_path,
                                         source_roots=parent.source_roots), parent.parent_commit)
                attempts = observe(snapshot, profile, within(base, claim.predicate.probe_path), target,
                                   dependencies=plan['dependencies'])
                row.update(status='attempts_recorded', attempts=len(attempts),
                           outcomes=dict(Counter(a['status'] for a in attempts)))
            except (ResourceError, InputError, OSError, KeyError, subprocess.SubprocessError) as error:
                row.update(status='technical_error', error=f'{type(error).__name__}: {error}')
                if (target / 'attempts.json').exists():
                    completed = read_json(target / 'attempts.json')
                    row.update(attempts=len(completed), outcomes=dict(Counter(a['status'] for a in completed)))
            save()
            print(f"{parent.group_id}: {row['status']} {row.get('outcomes', {})}", flush=True)
        manifest['source_after'] = source_snapshot(ROOT)
        manifest['source_snapshots_match'] = before == manifest['source_after']
        manifest['source_inputs_unchanged'] = all(file_hash(Path(p)) == h for p, h in hashes.items())
        if not manifest['source_snapshots_match'] or not manifest['source_inputs_unchanged']:
            raise InputError('Implementation or source inputs changed during diagnostic')
        manifest['status'] = 'complete'
        manifest['summary'] = {'groups': len(manifest['groups']),
            'container_attempts': sum(r['attempts'] for r in manifest['groups']),
            'outcomes': dict(sum((Counter(r.get('outcomes', {})) for r in manifest['groups']), Counter())),
            'groups_with_orchestration_error': sum(r['status'] != 'attempts_recorded' for r in manifest['groups']),
            'groups_with_all_calls_returned': sum(r.get('outcomes', {}).get('returned', 0) == 3 for r in manifest['groups']),
            'groups_with_no_function_observation': sum(not any(r.get('outcomes', {}).get(s, 0)
                for s in ('returned', 'assertion_failed')) for r in manifest['groups']),
            'groups_with_incomplete_attempt_schedule': sum(r['attempts'] != 3 for r in manifest['groups'])}
    except Exception as error:
        manifest.update(status='failed', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        save()
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parents', type=Path, required=True)
    parser.add_argument('--candidates', type=Path, required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, default=PROTOCOL)
    args = parser.parse_args()
    check(args.parents.resolve(), args.candidates.resolve(), args.image, args.out.resolve(), args.protocol.resolve())
