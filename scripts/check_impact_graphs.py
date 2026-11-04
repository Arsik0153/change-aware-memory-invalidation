"""Bounded exhaustive impact checks against a shortest-path oracle."""
from __future__ import annotations

import argparse
from itertools import product
from pathlib import Path

from cami.artifacts import file_hash, read_json, reserve, write_json
from cami.index import ChangeSet, impacted
from cami.models import Dependency, Node
from scripts.verify_cami import source_snapshot

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'examples/behavior_dependency/graph_check_protocol.json'


def distances(size: int, edges: list[tuple[int, int]]) -> list[list[int]]:
    # A caller is affected when it can reach a changed dependency, not vice versa.
    matrix = [[0 if i == j else size + 1 for j in range(size)] for i in range(size)]
    for source, target in edges:
        matrix[source][target] = min(matrix[source][target], 1)
    for via in range(size):
        for source in range(size):
            for target in range(size):
                matrix[source][target] = min(matrix[source][target],
                                            matrix[source][via] + matrix[via][target])
    return matrix


def changes(nodes: list[Node], edges: list[tuple[int, int]], mask: int) -> ChangeSet:
    return ChangeSet(
        files=frozenset({'module.py'} if mask else ()),
        symbols=frozenset(node for i, node in enumerate(nodes) if mask & (1 << i)),
        edges=tuple(Dependency(**{'from': nodes[s], 'to': nodes[t],
                                 'relation': 'calls', 'origin': 'static'}) for s, t in edges),
        unresolved=frozenset(), limited_paths=frozenset(), global_unresolved=False)


def expected(nodes: list[Node], matrix: list[list[int]], mask: int, depth: int) -> frozenset[Node]:
    seeds = {i for i in range(len(nodes)) if mask & (1 << i)}
    if mask:
        seeds.add(0)  # Git reports the containing file alongside symbol changes.
    return frozenset(node for i, node in enumerate(nodes)
                     if any(matrix[i][seed] <= depth for seed in seeds))


def check(plan: dict) -> dict:
    families = []
    for family in plan['families']:
        size = family['nodes']
        nodes = [Node(path='module.py')] + [Node(path='module.py', qualname=f'f{i}')
                                          for i in range(1, size)]
        possible = [(s, t) for s, t in product(range(size), repeat=2)
                    if family['self_edges'] or s != t]
        assert 2 ** len(possible) == family['graphs']
        cases = 0
        for graph in range(1 << len(possible)):
            edges = [edge for i, edge in enumerate(possible) if graph & (1 << i)]
            matrix = distances(size, edges)
            for mask in range(1 << size):
                delta = changes(nodes, edges, mask)
                for depth in plan['depths']:
                    actual = impacted(delta, depth)
                    wanted = expected(nodes, matrix, mask, depth)
                    if actual != wanted:
                        raise AssertionError({'size': size, 'graph': graph, 'edges': edges,
                                              'changed_mask': mask, 'depth': depth,
                                              'actual': sorted(map(str, actual)),
                                              'expected': sorted(map(str, wanted))})
                    cases += 1
        families.append({**family, 'cases': cases, 'mismatches': 0})
    nodes = [Node(path='module.py'), Node(path='module.py', qualname='caller'),
             Node(path='module.py', qualname='dependency')]
    wanted = expected(nodes, distances(3, [(1, 2)]), 4, 1)
    assert impacted(changes(nodes, [(1, 2)], 4), 1) == wanted
    assert impacted(changes(nodes, [(2, 1)], 4), 1) != wanted
    total = sum(row['cases'] for row in families)
    assert total == plan['expected_cases']
    return {'families': families, 'cases': total, 'mismatches': 0,
            'reversed_edge_negative_control_detected': True,
            'limitations': plan['limitations']}


def run(out: Path) -> None:
    before = source_snapshot(ROOT)
    assert not before['source_status'], 'Commit source before the verification run'
    plan = read_json(PLAN)
    protocol_hash = file_hash(PLAN)
    reserve(out)
    write_json(out / 'protocol.json', plan)
    manifest = {'status': 'running', 'source_before': before, 'protocol_sha256': protocol_hash}
    write_json(out / 'manifest.json', manifest)
    try:
        result = check(plan)
        write_json(out / 'results.json', result)
        assert file_hash(PLAN) == protocol_hash
        after = source_snapshot(ROOT)
        assert after == before
        manifest.update(status='complete', source_after=after)
    except (Exception, KeyboardInterrupt) as exc:
        manifest.update(status='failed', failure={'type': type(exc).__name__, 'message': str(exc)})
        raise
    finally:
        manifest['artifact_hashes'] = {p.name: file_hash(p) for p in out.iterdir()
                                      if p.is_file() and p.name != 'manifest.json'}
        write_json(out / 'manifest.json', manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    run(parser.parse_args().out)
