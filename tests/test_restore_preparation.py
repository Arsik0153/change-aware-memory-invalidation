from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from cami.artifacts import file_hash, read_json, read_jsonl, write_json, write_jsonl
from cami.errors import InputError

SPEC = importlib.util.spec_from_file_location(
    'restore_preparation', Path(__file__).resolve().parents[1] / 'scripts/restore_preparation.py')
assert SPEC and SPEC.loader
restore_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(restore_module)


def fixture(repo):
    parent = repo.commit({'a.py': 'x = 1\n'})
    child = repo.commit({'a.py': 'x = 2\n'})
    repo.git('remote', 'add', 'origin', 'https://example.invalid/project.git')
    repo.git('tag', 'fixed', child)
    selection = repo.root.parent / 'selection.json'
    parents = repo.root.parent / 'parents.jsonl'
    write_json(selection, {'seed': 42, 'repositories': [{
        'repo_id': repo.root.name, 'path': '/old/repo', 'url': 'https://example.invalid/project.git',
        'end_ref': 'fixed', 'end_commit': child, 'source_roots': ['.']}],
        'groups': [{'group_id': 'g', 'repo_id': repo.root.name, 'parent_commit': parent,
                    'child_commits': [child], 'stratum': 'heldout', 'cluster_id': 'episode'}]})
    write_jsonl(parents, [{'schema_version': 1, 'group_id': 'g', 'repo_id': repo.root.name,
                          'repo_path': '/old/repo', 'source_roots': ['.'],
                          'parent_commit': parent, 'seed': 42}])
    return selection, parents


def test_relocation_changes_only_paths_and_preserves_inputs(repo):
    selection, parents = fixture(repo)
    before = file_hash(selection), file_hash(parents)
    output = repo.root.parent / 'restored'
    restore_module.restore(selection, parents, repo.root.parent, output)
    expected_selection = read_json(selection)
    expected_selection['repositories'][0]['path'] = str(repo.root)
    expected_parents = read_jsonl(parents)
    expected_parents[0]['repo_path'] = str(repo.root)
    assert read_json(output / 'selection.json') == expected_selection
    assert read_jsonl(output / 'parent_inputs.jsonl') == expected_parents
    assert (file_hash(selection), file_hash(parents)) == before
    with pytest.raises(InputError, match='output already exists'):
        restore_module.restore(selection, parents, repo.root.parent, output)


@pytest.mark.parametrize('corruption', ['pin', 'parent', 'child', 'origin'])
def test_relocation_rejects_invalid_inputs_before_writing(repo, corruption):
    selection, parents = fixture(repo)
    data = read_json(selection)
    if corruption == 'pin':
        data['repositories'][0]['end_commit'] = '0' * 40
    elif corruption == 'parent':
        specs = read_jsonl(parents)
        specs[0]['seed'] = 99
        write_jsonl(parents, specs)
    elif corruption == 'child':
        data['groups'][0]['child_commits'] = ['0' * 40]
    else:
        data['repositories'][0]['url'] = 'https://example.invalid/other.git'
    write_json(selection, data)
    output = repo.root.parent / 'rejected'
    with pytest.raises(InputError):
        restore_module.restore(selection, parents, repo.root.parent, output)
    assert not output.exists()
