"""Relocate a fixed preparation manifest after local corpora have been restored."""
from __future__ import annotations

import argparse
from pathlib import Path

from cami.artifacts import file_hash, read_json, read_jsonl, reserve, within, write_json, write_jsonl
from cami.errors import InputError
from cami.repository import chain, git, resolve


def restore(selection_path: Path, parents_path: Path, corpora: Path, output: Path) -> None:
    selection = read_json(selection_path)
    parents = read_jsonl(parents_path)
    repositories = {row['repo_id']: row for row in selection['repositories']}
    groups = {row['group_id']: row for row in selection['groups']}
    specs = {row['group_id']: row for row in parents}
    if (len(repositories) != len(selection['repositories']) or len(groups) != len(selection['groups'])
            or len(specs) != len(parents) or set(groups) != set(specs)):
        raise InputError('duplicate or unmatched repository/group identities')
    mappings = {}
    for repo_id, repository in repositories.items():
        local = within(corpora.resolve(), repo_id)
        origin = git(local, 'remote', 'get-url', 'origin').decode().strip()
        if origin.removesuffix('.git') != repository['url'].removesuffix('.git'):
            raise InputError(f'origin differs for {repo_id}')
        if resolve(local, repository['end_ref']) != repository['end_commit']:
            raise InputError(f'pinned end commit differs for {repo_id}')
        mappings[repo_id] = {'original': repository['path'], 'local': str(local),
                             'end_commit': repository['end_commit']}
    for group_id, group in groups.items():
        repo_id = group['repo_id']
        if repo_id not in repositories:
            raise InputError(f'unknown repository for {group_id}')
        repository = repositories[repo_id]
        expected = {'schema_version': 1, 'group_id': group_id, 'repo_id': repo_id,
                    'repo_path': repository['path'], 'source_roots': repository['source_roots'],
                    'parent_commit': group['parent_commit'], 'seed': selection['seed']}
        if specs[group_id] != expected:
            raise InputError(f'parent inputs differ from selection for {group_id}')
        chain(Path(mappings[repo_id]['local']), group['parent_commit'], tuple(group['child_commits']))
    for repo_id, repository in repositories.items():
        repository['path'] = mappings[repo_id]['local']
    for spec in parents:
        spec['repo_path'] = mappings[spec['repo_id']]['local']
    reserve(output)
    write_json(output / 'selection.json', selection)
    write_jsonl(output / 'parent_inputs.jsonl', parents)
    write_json(output / 'relocation.json', {
        'source_hashes': {str(path): file_hash(path) for path in (selection_path, parents_path)},
        'repository_paths': mappings, 'verified_groups': len(groups), 'selection_repeated': False,
        'only_changed_fields': ['repositories[].path', 'parent_inputs[].repo_path'],
    })


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--parents', type=Path, required=True)
    parser.add_argument('--corpora', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    restore(args.selection, args.parents, args.corpora, args.out)
