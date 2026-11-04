"""Package only the closed v3 public record; no model, Docker or target execution."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import sqlite3
import stat
import subprocess
import tarfile
import time
import zlib

RUN = 'runs/opencode-development-v3-20261104'
ANALYSIS = 'runs/opencode-development-v3-final-analysis-20261104'
STALENESS = 'runs/opencode-development-v3-final-staleness-20261104'
PRIVATE = {'server-private', 'private-state', 'private-export-client', 'export-client', '.ssh', '.aws', '.codex'}
SENSITIVE = {'access_token', 'refresh_token', 'id_token', 'api_key', 'apikey', 'authorization', 'encrypted_content'}
JWT = re.compile(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')
AUTH = re.compile(r'(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._+/=-]{20,}')
EXPECTED_TABLES = {'record', 'record_revision', 'index_view', 'memory_generation', 'record_state',
                   'validation_event', 'operation_receipt', 'product_head', 'source_reference'}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_write(path, value):
    path.write_bytes(json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b'\n')


def relative(value):
    path = PurePosixPath(str(value))
    if path.is_absolute() or str(path) != str(value) or '..' in path.parts or not path.parts:
        raise ValueError('noncanonical archive path')
    if any(p in PRIVATE for p in path.parts) or path.name.endswith('.private') or path.name.startswith('session.db'):
        raise ValueError('private artifact path refused')
    return path.as_posix()


def signature(info):
    return tuple(getattr(info, key) for key in ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))


class Builder:
    def __init__(self, root, out, original_root):
        self.root, self.out, self.original_root = root, out, original_root
        self.source_paths, self.historical_sources = {}, []
        self.main, self.memory, self.identities = {}, {}, {}
        self.terminal_count = 0
        self.checked_hashes = 0
        self.final_memory_checks = []
        self.catalogs = []
        self.pins_checked = 0

    def path(self, value):
        path = Path(value)
        if path.is_absolute():
            path = path.relative_to(self.root) if path.is_relative_to(self.root) else path.relative_to(self.original_root)
        return relative(path.as_posix())

    @contextmanager
    def opened(self, value):
        name = self.path(value)
        parts = PurePosixPath(name).parts
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = child
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, 'rb') as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_mode & 0o7000:
                    raise ValueError('nonordinary, linked or privileged file refused: ' + name)
                yield stream, before
                if signature(before) != signature(os.fstat(stream.fileno())):
                    raise ValueError('source changed during read: ' + name)
                if signature(before) != signature(os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)):
                    raise ValueError('source path changed during read: ' + name)
        finally:
            os.close(directory)

    def read(self, value):
        with self.opened(value) as (stream, _):
            return stream.read()

    def load(self, value):
        return json.loads(self.read(value))

    def privacy(self, value, artifact, location='$', depth=0):
        if depth > 50:
            raise ValueError('privacy inspection nesting exceeded: ' + artifact)
        if isinstance(value, dict):
            for key, item in value.items():
                if key.casefold() in SENSITIVE and item not in (None, '', False, [], {}):
                    if not isinstance(item, str) or not item.startswith(('[REDACTED', '${', '$env:')):
                        raise ValueError('credential-valued field refused: ' + artifact + ':' + location + '.' + key)
                self.privacy(item, artifact, location + '.' + key, depth + 1)
        elif isinstance(value, list):
            for item in value:
                self.privacy(item, artifact, location + '[]', depth + 1)
        elif isinstance(value, str):
            if JWT.search(value) or AUTH.search(value):
                raise ValueError('credential-shaped string refused: ' + artifact + ':' + location)
            if value.lstrip().startswith(('{', '[')):
                try:
                    nested = json.loads(value)
                except ValueError:
                    return
                self.privacy(nested, artifact, location + '<json>', depth + 1)

    def admit(self, value, *, expected=None, memory=False, archive_name=None):
        source = self.path(value)
        name = relative(archive_name) if archive_name else source
        target = self.memory if memory else self.main
        if name in target:
            if expected is not None and target[name]['sha256'] != expected:
                raise ValueError('conflicting declared file hash: ' + name)
            return
        with self.opened(source) as (stream, info):
            hasher = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1048576), b''):
                hasher.update(chunk)
            checksum = hasher.hexdigest()
            if expected is not None and expected != checksum:
                raise ValueError('declared hash mismatch: ' + name)
            self.identities[name] = signature(info)
            self.source_paths[name] = source
            target[name] = {'sha256': checksum, 'size': info.st_size, 'mode': stat.S_IMODE(info.st_mode)}
        if name.endswith(('.json', '.jsonl')):
            raw = self.read(source)
            values = [json.loads(line) for line in raw.splitlines()] if name.endswith('.jsonl') else [json.loads(raw)]
            for value in values:
                self.privacy(value, name)
        elif name.endswith('.txt') or '/source-objects/' in name:
            text = self.read(source).decode('utf-8', errors='replace')
            self.privacy(text, name)

    def tree(self, value, *, skip=(), memory=False):
        name = self.path(value)
        path = self.root / name
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError('tree root must be an ordinary directory: ' + name)
        for entry in sorted(os.scandir(path), key=lambda entry: entry.name):
            if entry.name in skip:
                continue
            child = name + '/' + entry.name
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                self.tree(child, skip=skip, memory=memory)
            elif stat.S_ISREG(info.st_mode):
                self.admit(child, memory=memory)
            else:
                raise ValueError('symlink/special entry refused: ' + child)

    def inventory(self):
        run = self.load(RUN + '/run.json')
        study = self.load(RUN + '/frozen-study.json')
        plan = self.load(RUN + '/plan.json')
        assert digest(self.read(run['study_path'])) == run['study_sha256']
        assert self.load(run['study_path']) == study
        assert study['repetitions'] == 3 and len(plan['trials']) == 36
        expected_ids = {item['id'] for item in plan['trials']}
        assert {p.name for p in (self.root / RUN / 'trials').iterdir()} == expected_ids
        for path in sorted((self.root / RUN).iterdir()):
            if path.is_file() or path.is_symlink():
                self.admit(path)
        self.tree(RUN + '/summaries')
        self.tree(RUN + '/baselines', skip=('workspace',))
        self.admit(run['study_path'], expected=run['study_sha256'])
        self.admit(study['runtime_manifest_path'], expected=study['runtime_manifest_sha256'])
        for item in plan['trials']:
            prefix = RUN + '/trials/' + item['id']
            terminal = self.load(prefix + '/terminal.json')
            assert terminal['status'] == terminal['operational_status'] == terminal['session_status'] == 'passed'
            assert not terminal['failures']
            self.admit(prefix + '/terminal.json')
            for name, checksum in terminal['artifact_hashes'].items():
                self.admit(prefix + '/' + relative(name), expected=checksum)
                self.checked_hashes += 1
            session = self.load(prefix + '/session/manifest.json')
            guard = self.load(prefix + '/session/publication-guard.json')
            assert session['status'] == guard['status'] == 'passed' and session['state_removed']
            for name, checksum in session['artifact_hashes'].items():
                self.admit(prefix + '/session/' + relative(name), expected=checksum)
            self.terminal_count += 1
        # Frozen implementation/protocol identities and exact development bundle only.
        for section in study['pins'].values():
            for name, checksum in section['files'].items():
                source = self.path(Path(section['root']) / relative(name))
                if digest(self.read(source)) == checksum:
                    self.admit(source, expected=checksum)
                else:
                    # Only frozen implementation pins may use this exact historical
                    # source fallback. Outcomes/catalogs never receive replacements.
                    environment = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
                    environment.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
                    result = subprocess.run(['git', '--no-pager', '-c', 'core.hooksPath=/dev/null',
                        '-c', 'protocol.allow=never', '-C', str(self.root), 'show', '18188a7:' + source],
                        capture_output=True, check=True, env=environment)
                    assert digest(result.stdout) == checksum, 'Historical source does not match frozen pin'
                    saved = self.out / 'historical-source' / source
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    saved.write_bytes(result.stdout)
                    self.admit(saved, expected=checksum, archive_name=source)
                    self.historical_sources.append({'path': source, 'commit': '18188a7', 'sha256': checksum})
                self.pins_checked += 1
        for name, checksum in study['normalized']['asset_hashes'].items():
            self.admit(Path(study['bundle_path']) / relative(name), expected=checksum)
        for folder in (ANALYSIS, STALENESS, 'runs/opencode-development-v3-figures-20261104'):
            self.tree(folder)
        self.tree('scripts/opencode_benchmark/analysis', skip=('__pycache__', '.pytest_cache', '.ruff_cache'))
        self.admit('scripts/analyze_opencode_staleness.py')
        stale = self.load(STALENESS + '/report.json')
        assert self.main[self.path(stale['inputs']['analyzer_path'])]['sha256'] == stale['inputs']['analyzer_sha256']
        for folder in stale['inputs']['canonical_tree_sha256']:
            self.tree(folder)
        caveats = self.load(RUN + '/timing-caveats.json')
        for caveat in caveats['caveats']:
            self.admit(caveat['evidence_path'], expected=caveat['evidence_sha256'])
        # Only the caveat's exact referenced timing evidence is authorized here.
        # Other heldout-preflight approval/auth/account metadata is not admitted.
        # Immutable catalogs/preparation evidence and optional final ProductMemory state.
        for namespace in sorted((self.root / RUN / 'namespaces').iterdir()):
            self.admit(namespace / 'identity.json')
            memory = namespace / 'memory'
            self.tree(memory, skip=('cami-state',))
            if namespace.name.endswith(('-static', '-cami')):
                catalog_path = memory / 'prepared/catalog.json'
                catalog = self.load(catalog_path)
                self.catalogs.append({'namespace': namespace.name, 'path': self.path(catalog_path),
                                      'raw_sha256': digest(self.read(catalog_path)), 'semantic_sha256': digest(canonical(catalog)),
                                      'records': len(catalog['records'])})
            state = memory / 'cami-state'
            if state.exists():
                assert namespace.name.endswith('-cami')
                self.tree(state, memory=True)
                databases = list(state.rglob('memory.sqlite3'))
                assert len(databases) == 1
                with sqlite3.connect(databases[0].absolute().as_uri() + '?mode=ro', uri=True) as db:
                    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
                    assert tables == EXPECTED_TABLES, 'Non-ProductMemory database refused'
                    assert db.execute('PRAGMA user_version').fetchone()[0] == 1
                    by_key = {row['payload']['note_key']: row['payload'] for row in catalog['records']}
                    revisions = 0
                    for (raw,) in db.execute('SELECT value FROM record_revision'):
                        payload = json.loads(raw)['payload']
                        assert payload['type'] == 'note'
                        payload['sources'] = [{k: s[k] for k in ('path', 'sha256', 'size')} for s in payload['sources']]
                        assert payload == by_key[payload['note_key']], 'Unexpected memory content refused'
                        revisions += 1
                self.final_memory_checks.append({'namespace': namespace.name, 'database': self.path(databases[0]),
                                                 'tables': sorted(tables), 'catalog_matched_revisions': revisions})
            final = self.load(RUN + '/trials/' + namespace.name + '-s4/terminal.json')
            for name, checksum in final['memory_files_after'].items():
                full = self.path(memory / relative(name))
                present = self.memory if name.startswith('cami-state/') else self.main
                assert full in present and present[full]['sha256'] == checksum
        assert len({row['semantic_sha256'] for row in self.catalogs}) == 1
        assert len(self.catalogs) == 6 and all(row['records'] == 329 for row in self.catalogs)

    def create_archive(self, output, files, role):
        metadata = {'schema_version': 1, 'role': role, 'run': RUN,
                    'scope': 'Closed development v3 only. V1/v2 failed attempts remain separate; no pooling.',
                    'files': files, 'terminal_trials': self.terminal_count, 'terminal_hashes_verified': self.checked_hashes,
                    'not_included': ['namespace workspaces', 'OpenCode/private/auth state', 'final heldout task/source/gold',
                                     'OpenCode binary/Docker images/credentials'],
                    'encoding': 'USTAR regular files only; original safe file modes, uid/gid0, mtime0; gzip mtime0 filename empty'}
        manifest = canonical(metadata) + b'\n'
        with output.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=6) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.USTAR_FORMAT) as archive:
                for name in sorted(files):
                    record = files[name]
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = record['size'], record['mode']
                    info.uid = info.gid = info.mtime = 0
                    with self.opened(self.source_paths[name]) as (stream, observed):
                        assert signature(observed) == self.identities[name], 'Source changed before archive'
                        archive.addfile(info, stream)
                info = tarfile.TarInfo('PUBLICATION-MANIFEST.json')
                info.size, info.mode = len(manifest), 0o644
                import io
                archive.addfile(info, io.BytesIO(manifest))
        return {'path': str(output), 'sha256': digest(output.read_bytes()), 'size': output.stat().st_size,
                'manifest_sha256': digest(manifest), 'files': len(files), 'source_bytes': sum(r['size'] for r in files.values())}


def verify_archive(archive, destination):
    destination.mkdir()
    with tarfile.open(archive, 'r:gz') as stream:
        members = stream.getmembers()
        names = [member.name for member in members]
        assert len(names) == len(set(names))
        assert all(member.isfile() and not member.linkname for member in members)
        for member in members:
            relative(member.name)
        manifest = json.loads(stream.extractfile('PUBLICATION-MANIFEST.json').read())
        assert set(names) == set(manifest['files']) | {'PUBLICATION-MANIFEST.json'}
        for member in members:
            target = destination / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as output:
                data = stream.extractfile(member)
                hasher = hashlib.sha256()
                for chunk in iter(lambda: data.read(1048576), b''):
                    output.write(chunk)
                    hasher.update(chunk)
            target.chmod(member.mode)
            if member.name != 'PUBLICATION-MANIFEST.json':
                expected = manifest['files'][member.name]
                assert hasher.hexdigest() == expected['sha256'] and target.stat().st_size == expected['size']
                assert stat.S_IMODE(target.stat().st_mode) == expected['mode']
    return {'status': 'passed', 'files': len(manifest['files']), 'regular_files_only': True,
            'all_sha256_sizes_modes_verified': True, 'destination': str(destination)}


def cpu():
    values = [resource.getrusage(who) for who in (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN)]
    return sum(value.ru_utime + value.ru_stime for value in values)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--original-repo-root', type=Path, default=Path('/root/apps/change-aware-memory-invalidation'))
    args = parser.parse_args()
    started, started_cpu = time.monotonic(), cpu()
    out, root = args.out.absolute(), args.repo.absolute()
    builder = Builder(root, out, args.original_repo_root.absolute())
    out.mkdir(exist_ok=True)
    free_before = os.statvfs(out).f_bavail * os.statvfs(out).f_frsize
    try:
        builder.inventory()
        for name in ('build_publication.py', 'README.md', 'reproduce_analysis.py'):
            builder.admit(out / name)
        for failure in sorted(out.glob('packaging-failure*.json')):
            builder.admit(failure)
        json_write(out / 'admission.json', {'terminal_trials': builder.terminal_count,
            'terminal_hashes_verified': builder.checked_hashes, 'frozen_pins_verified': builder.pins_checked,
            'main_files': builder.main, 'final_memory_files': builder.memory,
            'catalogs': builder.catalogs, 'final_memory_schema_checks': builder.final_memory_checks,
            'source_signatures': builder.identities, 'source_paths': builder.source_paths,
            'historical_sources': builder.historical_sources, 'privacy_scope': 'Published sanitation guards pass; structured key/JWT/auth pattern checks. No private credential bodies read; no claim of identifying arbitrary opaque secrets from text alone.'})
        archives = []
        for name, files, role in [('public-evidence.tar.gz', builder.main, 'public-terminal-evidence'),
                                  ('final-memory-state.tar.gz', builder.memory, 'final-product-memory-state-only')]:
            path = out / name
            record = builder.create_archive(path, files, role)
            second = out / (name + '.rebuild')
            repeated = builder.create_archive(second, files, role)
            assert record['sha256'] == repeated['sha256'] and record['size'] == repeated['size']
            second.unlink()
            record['byte_reproducible_second_build'] = True
            record['extraction_verification'] = verify_archive(path, out / name.removesuffix('.tar.gz'))
            archives.append(record)
        for name, expected in {**builder.main, **builder.memory}.items():
            with builder.opened(builder.source_paths[name]) as (stream, info):
                assert signature(info) == builder.identities[name]
                assert digest(stream.read()) == expected['sha256']
        json_write(out / 'packaging-report.json', {'status': 'passed', 'archives': archives,
            'source_inputs_unchanged': True, 'historical_sources': builder.historical_sources, 'terminal_trials': builder.terminal_count,
            'terminal_hashes_verified': builder.checked_hashes, 'catalogs': builder.catalogs,
            'final_memory_scope': 'Three final CAMI namespaces only, including ProductMemory SQLite/index generations/source CAS. This is not OpenCode session/auth state and not a complete dataset/history backup.',
            'publication_overhead': {'wall_seconds': time.monotonic() - started, 'cpu_seconds_self_and_completed_children': cpu() - started_cpu,
                'free_disk_before_bytes': free_before, 'free_disk_after_bytes': os.statvfs(out).f_bavail * os.statvfs(out).f_frsize,
                'scope': 'Packaging/admission/hash checks/double compression/extraction/source recheck only; evaluation/publication overhead, never trial cost.'},
            'runtime': {'python': __import__('sys').version, 'zlib': zlib.ZLIB_VERSION},
            'model_calls': 0, 'docker_calls': 0, 'network_calls': 0, 'tracked_writes': False})
    except BaseException as error:
        failed = out / 'packaging-failure.json'
        index = 1
        while failed.exists():
            failed = out / f'packaging-failure-{index:04d}.json'
            index += 1
        json_write(failed, {'status': 'failed', 'error_type': type(error).__name__,
            'reason': str(error), 'raw_rejected_payload_quarantined': False,
            'wall_seconds': time.monotonic() - started, 'cpu_seconds': cpu() - started_cpu})
        raise
    print(json.dumps({'status': 'passed', 'trials': builder.terminal_count,
                      'terminal_hashes': builder.checked_hashes, 'archives': [{k: row[k] for k in ('path', 'sha256', 'size')} for row in archives]}))


if __name__ == '__main__':
    main()
