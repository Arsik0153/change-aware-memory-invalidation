"""Describe graph fallback flags on frozen real parents without reading child outcomes."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from cami.artifacts import digest, file_hash, load_jsonl, read_json, reserve, within, write_json, write_jsonl
from cami.index import IndexConfig, build_index
from cami.models import Claim, Node, Provenance, RepoLocation
from cami.repository import read_snapshot
from scripts.verify_cami import source_snapshot

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'examples/behavior_dependency/parent_graph_profile_protocol.json'


def module_facts(index, snapshot):
    blobs = snapshot.by_path()
    rows = []
    for module in index.modules:
        node = Node(path=module.path)
        parsed = node in module.unresolved
        linked = node in index.unresolved
        assert not parsed or linked
        blob = blobs[module.path]
        rows.append({'path':module.path,'module_name':module.module_name,
            'blob_oid':blob.object_id,'blob_sha256':blob.content_hash,'mode':blob.mode,
            'definitions':len(module.definitions),'imports':list(module.imports),
            'limitation':module.limitation,'module_unresolved_after_parse':parsed,
            'module_unresolved_after_linking':linked,
            'module_unresolved_added_by_linking':linked and not parsed})
    return rows


def claim_facts(claim, provenance, index):
    subject = Node(path=claim.subject.path,qualname=claim.subject.qualname)
    matches = [d for m in index.modules for d in m.definitions if d.node == subject]
    return {'claim_id':claim.claim_id,'claim_sha256':digest(claim),'claim_kind':claim.kind,
        'subject':claim.subject.model_dump(mode='json'),'provenance_sha256':digest(provenance),
        'known_incomplete':provenance.known_incomplete,
        'matching_definitions':len(matches),'any_ambiguous':any(d.ambiguous for d in matches),
        'subject_direct_unresolved':subject in index.unresolved,
        'subject_module_unresolved':Node(path=subject.path) in index.unresolved,
        'subject_analysis_limitation':index.limitations().get(subject.path),
        'global_unresolved':index.global_unresolved}


def aggregate(parents, modules, claims):
    behavior = [row for row in claims if row['claim_kind']=='behavior_test']
    return {'parent_groups':len(parents),'modules_across_parents':len(modules),
        'claims':len(claims),'behavior_claims':len(behavior),
        'parents_global_unresolved':sum(p['global_unresolved'] for p in parents),
        'parents_warm_fresh_mismatch':sum(not p['warm_index_equals_fresh'] for p in parents),
        'modules_unresolved_after_parse':sum(m['module_unresolved_after_parse'] for m in modules),
        'modules_unresolved_added_by_linking':sum(m['module_unresolved_added_by_linking'] for m in modules),
        'modules_with_limitation':sum(m['limitation'] is not None for m in modules),
        'behavior_global_unresolved':sum(c['global_unresolved'] for c in behavior),
        'behavior_subject_direct_unresolved':sum(c['subject_direct_unresolved'] for c in behavior),
        'behavior_subject_module_unresolved':sum(c['subject_module_unresolved'] for c in behavior),
        'behavior_global_but_subject_and_module_clear':sum(c['global_unresolved']
            and not c['subject_direct_unresolved'] and not c['subject_module_unresolved'] for c in behavior),
        'all_candidates_known_incomplete':all(c['known_incomplete'] for c in claims),
        'candidate_kinds':dict(Counter(c['claim_kind'] for c in claims))}


def run(out):
    before = source_snapshot(ROOT)
    assert not before['source_status'], 'Commit source before diagnostic'
    plan, plan_hash = read_json(PLAN), file_hash(PLAN)
    inventory_path = ROOT / plan['parent_inventory']
    assert file_hash(inventory_path) == plan['parent_inventory_sha256']
    inventory = read_json(inventory_path)
    prepared, inputs = [], {str(inventory_path):file_hash(inventory_path)}
    for parent in inventory['parents']:
        base = within(ROOT/inventory['candidate_root'],parent['group_id'])
        for name in ('claims','provenance','draft'):
            path = base/(name+('.json' if name=='draft' else '.jsonl'))
            assert file_hash(path) == parent[name+'_sha256']
            inputs[str(path)] = file_hash(path)
        assert read_json(base/'draft.json')['parent_input'] == {
            k:v for k,v in parent.items() if not k.endswith('_sha256')}
        claims = load_jsonl(base/'claims.jsonl',Claim,'claim_id')
        provenance = load_jsonl(base/'provenance.jsonl',Provenance,'claim_id')
        pmap = {p.claim_id:p for p in provenance}
        assert {c.claim_id for c in claims} == pmap.keys()
        assert all(c.origin_commit==parent['parent_commit'] and c.repo_id==parent['repo_id'] for c in claims)
        prepared.append((parent,claims,pmap))
    assert len(prepared) == plan['expected_parent_groups']
    assert sum(len(c) for _,c,_ in prepared) == plan['expected_claims']
    assert sum(c.kind=='behavior_test' for _,claims,_ in prepared for c in claims)==plan['expected_behavior_claims']
    reserve(out)
    write_json(out/'protocol.json',plan)
    manifest = {'status':'running','source_before':before,'protocol_sha256':plan_hash,
                'input_hashes':inputs,'parent_only':True,'creates_labels_receipts_or_provenance':False}
    write_json(out/'manifest.json',manifest)
    parent_rows, module_rows, claim_rows, cache = [], [], [], {}
    try:
        for parent,claims,pmap in prepared:
            repo = RepoLocation(repo_id=parent['repo_id'],path=parent['repo_path'],
                                source_roots=tuple(parent['source_roots']))
            snapshot = read_snapshot(repo,parent['parent_commit'])
            config = IndexConfig(repo.source_roots,True)
            index = build_index(snapshot,config,cache)
            fresh = build_index(snapshot,config)
            assert index == fresh
            common = {'group_id':parent['group_id'],'repo_id':parent['repo_id'],
                      'parent_commit':parent['parent_commit']}
            modules = module_facts(index,snapshot)
            module_rows.extend({**common,**m} for m in modules)
            claim_rows.extend({**common,**claim_facts(c,pmap[c.claim_id],index)} for c in claims)
            graph = {'revision':index.revision,'source_roots':list(repo.source_roots),
                'edges':[e.model_dump(mode='json') for e in index.edges],
                'unresolved':sorted((n.model_dump(mode='json') for n in index.unresolved),
                                    key=lambda n:(n['path'],n['qualname'] or '')),
                'global_unresolved':index.global_unresolved}
            path = out/'graphs'/(parent['group_id']+'.json')
            write_json(path,graph)
            parent_rows.append({**common,'graph_sha256':file_hash(path),
                'modules':len(index.modules),'definitions':sum(len(m.definitions) for m in index.modules),
                'edges':len(index.edges),'unresolved_nodes':len(index.unresolved),
                'global_unresolved':index.global_unresolved,'warm_index_equals_fresh':index==fresh})
            print(parent['group_id'],flush=True)
        write_jsonl(out/'parents.jsonl',parent_rows)
        write_jsonl(out/'modules.jsonl',module_rows)
        write_jsonl(out/'claims.jsonl',claim_rows)
        summary = aggregate(parent_rows,module_rows,claim_rows)
        summary['by_repo'] = {repo:aggregate([p for p in parent_rows if p['repo_id']==repo],
            [m for m in module_rows if m['repo_id']==repo],[c for c in claim_rows if c['repo_id']==repo])
            for repo in sorted({p['repo_id'] for p in parent_rows})}
        summary['limits'] = plan['limits']
        write_json(out/'summary.json',summary)
        assert all(file_hash(Path(p))==h for p,h in inputs.items()) and file_hash(PLAN)==plan_hash
        after = source_snapshot(ROOT)
        assert before == after
        manifest.update(status='complete',source_after=after)
    except (Exception,KeyboardInterrupt) as exc:
        manifest.update(status='failed',failure={'type':type(exc).__name__,'message':str(exc)})
        raise
    finally:
        manifest['artifact_hashes'] = {p.relative_to(out).as_posix():file_hash(p)
            for p in sorted(out.rglob('*')) if p.is_file() and p != out/'manifest.json'}
        write_json(out/'manifest.json',manifest)


if __name__ == '__main__':
    if not __debug__:
        raise SystemExit('Assertions required; do not use -O')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    run(parser.parse_args().out.resolve())
