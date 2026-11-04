import collections
import json
import pathlib
import sys

ROOT = pathlib.Path('/root/apps/change-aware-memory-invalidation/examples/ai_review_pilot/packet')
OUT = pathlib.Path('/root/apps/change-aware-memory-invalidation/runs/blinded-ai-reviewer-a-20261104')
cases = json.loads((ROOT / 'cases.json').read_text())
observations = json.loads((OUT / 'observations.json').read_text())
items = []
for c, o in zip(cases, observations['observations'], strict=True):
    assert c['id'] == o['id']
    defs = o['definitions']
    target = c['subject']['qualname']
    duplicate = len(defs) > 1
    rebindings = o['bindings'] + [dict(kind='repeated_function_definition', line_start=d['line_start'], line_end=d['line_end']) for d in defs[1:]]
    facts = dict(definition_count=len(defs), unconditional=all(d['unconditional'] for d in defs) if defs else None,
                 target_rebinding=bool(rebindings), type_parameters_present=any(d['type_parameters_present'] for d in defs) if defs else None)
    if rebindings:
        facts['binding_events'] = rebindings
    if duplicate:
        facts['observed_definitions'] = [dict(line_start=d['line_start'], line_end=d['line_end'], unconditional=d['unconditional'], signature=d['actual_signature']) for d in defs]
    if c['kind'] == 'signature_equals':
        facts['actual_signature'] = defs[0]['actual_signature'] if len(defs) == 1 else None
    evidence = [dict(source_path=c['source_path'], available=True, line_start=1, line_end=o['lines'])]
    for d in defs:
        evidence.append(dict(source_path=c['source_path'], available=True, line_start=d['line_start'], line_end=d['line_end']))
    for b in o['bindings'] + o['wildcards']:
        evidence.append(dict(source_path=c['source_path'], available=True, line_start=b['line_start'], line_end=b['line_end']))
    if duplicate:
        verdict = 'uncertain'
        ranges = ', '.join(f"{d['line_start']}-{d['line_end']}" for d in defs)
        reasoning = f"The full module contains {len(defs)} unconditional module-level definitions of {target} at lines {ranges}. The later definitions bind the same name again. The rubric requires uncertainty for duplicate definitions; a unique subject cannot be selected."
    elif o['bindings'] or o['wildcards'] or any(not d['unconditional'] or d['type_parameters_present'] for d in defs):
        verdict = 'uncertain'
        reasoning = 'Module-level binding, wildcard-import, conditional-definition, or type-parameter ambiguity prevents establishing a unique eligible subject.'
    elif not defs:
        verdict = 'contradicted'
        reasoning = f"Inspected the entire supplied module, lines 1-{o['lines']}, including all module-level compound statements. There is no exact top-level function definition named {target}, and no target binding or wildcard-import ambiguity."
    elif c['kind'] == 'symbol_exists':
        verdict = 'supported'
        reasoning = f"The full module contains exactly one unconditional top-level function definition named {target}, at lines {defs[0]['line_start']}-{defs[0]['line_end']}. Whole-module inspection found no other definition, module-scope rebinding, wildcard import, or subject type parameters."
    elif o['signature_matches']:
        verdict = 'supported'
        reasoning = f"The independently extracted signature of the unique unconditional top-level {target} matches every expected field: parameter names, order, kinds, defaults and annotations, return annotation, decorator order, and async status. Whole-module inspection found no target rebinding or other rubric ambiguity."
    else:
        verdict = 'contradicted'
        actual = defs[0]['actual_signature']
        expected = c['predicate']['expected_signature']
        diffs = []
        if len(actual['parameters']) != len(expected['parameters']):
            diffs.append(f"actual parameter count is {len(actual['parameters'])}, expected {len(expected['parameters'])}")
        for i,(a,e) in enumerate(zip(actual['parameters'], expected['parameters'])):
            for key in a:
                if a[key] != e[key]:
                    diffs.append(f"parameter {i+1} {key}: actual {a[key]!r}, expected {e[key]!r}")
        for key in ('returns_ast','decorators_ast','is_async'):
            if actual[key] != expected[key]:
                diffs.append(f"{key}: actual {actual[key]!r}, expected {expected[key]!r}")
        reasoning = f"The signature was extracted from the unique unconditional top-level {target} before comparison. It differs from the predicate: " + '; '.join(diffs) + '. Whole-module inspection found no ambiguity that would require an uncertain verdict.'
    items.append(dict(id=c['id'], source_sha256=c['source_sha256'], verdict=verdict, extracted_facts=facts, evidence=evidence, reasoning=reasoning,
                      scope_notes=f"Exact supplied source for {c['subject']['path']}:{target}. Entire module inspected syntactically; nested functions and methods are excluded. Decorators and expressions were not evaluated; no runtime binding or behavior is asserted."))
review = dict(schema_version=1, reviewer_kind='ai_reviewer', human=False, provider='codex', model='codex:gpt-6.1-sol', reasoning_effort='high', agent_task='/root/blinded_ai_reviewer_a', packet_sha256=observations['packet_sha256'], independence_disclosure='Model weights and training independence are unverified.', identity_basis='declared_invocation', items=items)
(OUT / 'review.json').write_text(json.dumps(review, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
methodology = dict(
    schema_version=1, reviewer_kind='ai_reviewer', human=False, provider='codex', model='codex:gpt-6.1-sol', reasoning_effort='high', identity_basis='declared_invocation', agent_task='/root/blinded_ai_reviewer_a',
    independence_disclosure='Model weights and training independence are unverified.',
    tools=['functions.exec with exec_command: Bash cat, mkdir, sed, and python3; initial python executable lookup failed', 'Python standard library: ast, collections, hashlib, io, json, pathlib, platform, re, sys, tokenize'],
    parser=dict(implementation='CPython ast.parse; ast.dump(include_attributes=False)', python_version=observations['python'], ast_feature_version='interpreter default (Python 3.12)', type_comments=True),
    authorized_inputs=['examples/ai_review_pilot/packet/rubric.md', 'examples/ai_review_pilot/packet/review.schema.json', 'examples/ai_review_pilot/packet/cases.json', '21 unique source files named by cases.json'],
    whole_module_inspection_method='Decoded and parsed every complete module. ModuleScan walks all module-level control-flow suites and checks exact function names, uniqueness, conditionality, type parameters, assignments/deletions, imports including wildcard imports, exception and match bindings, loop/with targets, and definition-expression bindings. Function and class scopes are excluded from module-definition matching. A second whole-AST audit enumerated target occurrences, all-scope target stores/deletes, global/nonlocal declarations, and dynamic namespace calls; reviewed module-level statement inventories, target source headers and module tails. No target store/delete nodes, target global declarations, wildcard imports, or non-definition module rebindings were found. Three cases have three repeated unconditional definitions each.',
    signature_extraction_method='For each signature case, constructed actual_signature from the parsed FunctionDef/AsyncFunctionDef before accessing its expected_signature. Aligned positional defaults from the right, preserved positional-only and keyword-only kinds, represented missing defaults/annotations as null, dumped literal None as Constant(value=None), and preserved decorators in source order and async status. Compared resulting structured objects by exact equality only after extraction.',
    identity_verification=dict(cases_sha256=observations['cases_sha256'], packet_sha256=observations['packet_sha256'], source_count=len(observations['sources']), case_count=len(items), all_declared_source_sha256_verified=True, sources=observations['sources'], recipe="SHA256 of UTF8 canonical JSON {cases_sha256: SHA256(exact cases bytes), sources: unique source_path/source_sha256 objects sorted lexicographically by source_path}; json.dumps(sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False). Encoding contract clarified by coordinator in-message; no case answers supplied."),
    access_limitations=['Read only authorized packet inputs and self-authored run artifacts; no other repository files, CAMI code, original origins, private maps, mechanical answers, or another reviewer outputs were accessed.', 'No network used. Supplied modules were neither imported nor executed. Source strings/comments were treated as data.', 'Review is limited to supplied full-module syntax; no evaluated decorators, imported dependencies, runtime bindings, or behavioral guarantees.', 'Parser supports Python 3.12 syntax. All 21 modules decoded and parsed successfully; no unsupported subject syntax encountered.', 'Model identity and reasoning effort are declared invocation metadata, not independently measured. Model weights and training independence are unverified.'],
    preserved_helpers=['inspect_packet.py','audit_sources.py','write_review.py','validate_review.py'],
    verdict_counts=dict(collections.Counter(i['verdict'] for i in items)), answers_finalized_without_other_reviews=True)
(OUT / 'methodology.json').write_text(json.dumps(methodology, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
print(json.dumps(dict(items=len(items), verdict_counts=methodology['verdict_counts']), indent=2))
