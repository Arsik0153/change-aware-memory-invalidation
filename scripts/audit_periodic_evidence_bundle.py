"""Verify a periodic-audit raw evidence ZIP using only the Python standard library."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import PurePosixPath
import tarfile
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def audit(archive):
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
        require(len(names) == len(set(names)), 'Duplicate ZIP member')
        for name in names:
            path = PurePosixPath(name)
            require(not path.is_absolute() and '..' not in path.parts, 'Unsafe ZIP path')
        manifest = json.loads(zipped.read('bundle-manifest.json'))
        require(manifest['schema_version'] == 1, 'Unsupported bundle schema')
        require(set(names) == set(manifest['artifact_sha256']) | {'bundle-manifest.json'},
                'Bundle inventory mismatch')
        for name, expected in manifest['artifact_sha256'].items():
            require(digest(zipped.read(name)) == expected, f'Bundle hash mismatch: {name}')
        original_hashes = source_files = nested_hashes = 0
        for component in manifest['components']:
            prefix = component['prefix']
            original = json.loads(zipped.read(prefix + '/manifest.json'))
            require(original['status'] == 'complete', 'Incomplete original run')
            require(original['source_before'] == original['source_after'], 'Source snapshots differ')
            require(not original['source_before']['source_status'], 'Original source was dirty')
            require(original['source_before']['git_head'] == component['runtime_commit'],
                    'Original runtime commit mismatch')
            for field in ('artifact_hashes','input_hashes'):
                for name, expected in original.get(field,{}).items():
                    path = PurePosixPath(name)
                    require(not path.is_absolute() and '..' not in path.parts, 'Unsafe original path')
                    require(digest(zipped.read(prefix+'/'+name)) == expected,
                            f'Original artifact mismatch: {prefix}/{name}')
                    original_hashes += 1
            with tarfile.open(fileobj=io.BytesIO(zipped.read(component['source_archive'])),mode='r:gz') as source:
                require(source.pax_headers.get('comment') == component['runtime_commit'],
                        'Git source archive commit mismatch')
                for name, expected in original['source_before']['files'].items():
                    member = source.getmember(name)
                    require(member.isfile() and expected is not None, 'Unsupported source member')
                    require(digest(source.extractfile(member).read()) == expected,
                            f'Runtime source mismatch: {name}')
                    source_files += 1
                protocol = source.extractfile(component['protocol_path']).read()
                require(digest(protocol) == original['protocol_sha256'], 'Original protocol hash mismatch')
                require(json.loads(protocol) == json.loads(zipped.read(prefix+'/protocol.json')),
                        'Copied protocol mismatch')
                for name, expected in original.get('base_input_sha256',{}).items():
                    require(digest(source.extractfile(name).read()) == expected,
                            f'Frozen base input mismatch: {name}')
                    original_hashes += 1
            if component['kind'] == 'git_docker':
                require(original['probe_executions'] == 93, 'Unexpected probe execution count')
                require(not original['evaluation_eligible'], 'Research run must be ineligible')
                for variant in original['completed_runs']:
                    run_prefix = prefix+'/runs/'+variant
                    run = json.loads(zipped.read(run_prefix+'/manifest.json'))
                    require(run['status'] == 'complete' and not run['evaluation_eligible'],
                            'Nested research run is incomplete or eligible')
                    for name, expected in run['artifact_hashes'].items():
                        require(digest(zipped.read(run_prefix+'/'+name)) == expected,
                                f'Nested artifact mismatch: {variant}/{name}')
                        nested_hashes += 1
        return {'status':'passed','bundle_files':len(names)-1,
                'original_hashes_verified':original_hashes,'nested_hashes_verified':nested_hashes,
                'runtime_source_files_verified':source_files,
                'container_image_included':manifest['container_image_included']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive')
    print(json.dumps(audit(parser.parse_args().archive)))
