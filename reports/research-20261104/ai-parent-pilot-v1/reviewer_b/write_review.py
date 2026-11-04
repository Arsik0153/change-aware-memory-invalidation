"""Serialize independently judged cases and verify strict packet/schema constraints."""
import ast
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

BASE = Path('/root/apps/change-aware-memory-invalidation/examples/ai_review_pilot/packet')
OUT = Path('/root/apps/change-aware-memory-invalidation/runs/blinded-ai-reviewer-b-20261104')

# These judgments were made after inspecting the source-derived extraction,
# full module-scope inventories, subject declarations, and exact predicates.
UNCERTAIN = {'case-05ba048b5794cf8f990f', 'case-42500e4d0e990a7fafe5', 'case-679aa00fdafa7e9a8520'}
ABSENT = {'case-40171ec6c75287dd3791', 'case-92fac7ba1b0e33c9f130', 'case-bf21190da236925a4ce3'}
MISMATCH = {
    'case-8810691b50960340f777': "The first parameter is named cls, whereas the predicate requires _case_85cedda1ed9a6eeda5e5de2f. Parameter names are part of exact signature equality.",
    'case-8f76208c55aa31b28f93': "The variadic positional parameter is named param_decls, whereas the predicate requires _case_8e35469b32bbd2ebc8600fc4. The remaining signature fields agree.",
    'case-97aa74864140fa4be270': "The first parameter is named ctx, whereas the predicate requires _case_8775f56b824ba2ed5a09a278. The remaining signature fields agree.",
    'case-f795a594f3c16a85b76b': "The first parameter is named cli, whereas the predicate requires _case_19fee5b73e98cf9990334ca9. The remaining signature fields agree.",
    'case-0b4b57db58e52db5eef8': "The function has no parameters, whereas the predicate requires one positional_or_keyword parameter named _case_b8ca6e06cf008794771e6376. The return annotation agrees.",
    'case-b773f7da706ed01a3d5e': "The first parameter is named help, whereas the predicate requires _case_0352818f05d75b1d7a7c406f. The remaining signature fields agree.",
}

def validate(value, schema, root, loc='$'):
    if '$ref' in schema:
        target = root
        for key in schema['$ref'].split('/')[1:]:
            target = target[key]
        validate(value, target, root, loc)
    if 'const' in schema:
        assert value == schema['const'] and type(value) is type(schema['const']), (loc, 'const')
    if 'type' in schema:
        kinds = {'object': dict, 'array': list, 'string': str, 'integer': int, 'boolean': bool, 'null': type(None)}
        assert type(value) is kinds[schema['type']], (loc, 'type', schema['type'])
    if 'enum' in schema:
        assert value in schema['enum'], (loc, 'enum')
    if isinstance(value, str) and 'pattern' in schema:
        assert re.search(schema['pattern'], value), (loc, 'pattern')
    if isinstance(value, dict):
        assert all(k in value for k in schema.get('required', [])), (loc, 'required')
        assert len(value) >= schema.get('minProperties', 0), (loc, 'minProperties')
        if schema.get('additionalProperties') is False:
            assert set(value) <= set(schema.get('properties', {})), (loc, 'additionalProperties')
        for k, child in schema.get('properties', {}).items():
            if k in value:
                validate(value[k], child, root, loc+'.'+k)
    if isinstance(value, list):
        assert len(value) >= schema.get('minItems', 0), (loc, 'minItems')
        for i, item in enumerate(value):
            if 'items' in schema:
                validate(item, schema['items'], root, f'{loc}[{i}]')
    if type(value) is int and 'minimum' in schema:
        assert value >= schema['minimum'], (loc, 'minimum')
    if 'oneOf' in schema:
        matches = 0
        for candidate in schema['oneOf']:
            try:
                validate(value, candidate, root, loc)
                matches += 1
            except AssertionError:
                pass
        assert matches == 1, (loc, 'oneOf', matches)
    for child in schema.get('allOf', []):
        validate(value, child, root, loc)
    if 'if' in schema:
        try:
            validate(value, schema['if'], root, loc)
            passed = True
        except AssertionError:
            passed = False
        if passed and 'then' in schema:
            validate(value, schema['then'], root, loc)

def main():
    cases = json.loads((BASE/'cases.json').read_bytes())
    extraction = json.loads((OUT/'independent_extraction.json').read_text())
    items = []
    for case in cases:
        rel = case['source_path']
        module = extraction['modules'][rel]
        name = case['subject']['qualname']
        target = module['targets'][name]
        defs = target['definitions']
        bindings = target['bindings']
        assert not bindings, (case['id'], bindings)
        facts = {
            'definition_count': len(defs),
            'unconditional': all(d['unconditional'] for d in defs) if defs else None,
            'target_rebinding': bool(bindings) or len(defs) > 1,
            'type_parameters_present': any(d['type_parameters_present'] for d in defs) if defs else None,
        }
        if case['kind'] == 'signature_equals':
            facts['actual_signature'] = defs[0]['signature'] if len(defs) == 1 else None
        evidence = [dict(source_path=rel, available=True, line_start=d['line_start'], line_end=d['line_end']) for d in defs]
        evidence.append(dict(source_path=rel, available=True, line_start=1, line_end=module['line_count']))
        identity = case['subject']['path'] + ':' + name
        if case['id'] in UNCERTAIN:
            verdict = 'uncertain'
            assert len(defs) > 1
            facts['observed_definitions'] = [dict(name=d['name'], line_start=d['line_start'], line_end=d['line_end'], unconditional=d['unconditional'], signature=d['signature']) for d in defs]
            locations = ', '.join(f"{d['line_start']}-{d['line_end']}" for d in defs)
            reasoning = f"The full module contains {len(defs)} unconditional top-level definitions of {identity}, at lines {locations}. The later definitions also bind the same name again. The rubric requires uncertainty for duplicate definitions, so no unique eligible subject can be selected. All duplicate declarations are listed in observed_definitions; no additional source is missing."
        elif case['id'] in ABSENT:
            verdict = 'contradicted'
            assert not defs
            reasoning = f"I inspected the whole supplied module, lines 1-{module['line_count']}, including all module-scope control-flow branches. It has no top-level function definition with the exact name {name} for {identity}. No matching conditional definition, competing binding, wildcard import, or parsing ambiguity was found. The required symbol_exists=true predicate is therefore contradicted."
        elif case['id'] in MISMATCH:
            verdict = 'contradicted'
            assert len(defs) == 1 and defs[0]['unconditional']
            assert facts['actual_signature'] != case['predicate']['expected_signature']
            reasoning = f"The full module has one unconditional top-level definition of {identity}, with no competing binding. The actual signature was extracted from its AST before comparison. " + MISMATCH[case['id']]
        else:
            verdict = 'supported'
            assert len(defs) == 1 and defs[0]['unconditional']
            reasoning = f"The full module has exactly one unconditional top-level function definition of {identity}, with no competing binding, wildcard import, or subject type parameters. "
            if case['kind'] == 'signature_equals':
                assert facts['actual_signature'] == case['predicate']['expected_signature']
                reasoning += "The independently extracted AST signature matches every expected parameter name, order, kind, default, annotation, return annotation, decorator order, and async flag."
            else:
                reasoning += "This supports the required symbol_exists=true predicate."
        scope_notes = f"Reviewed the source_path supplied for {identity}, across all {module['line_count']} lines, using full-module AST inspection. Nested functions and methods were excluded from top-level definition counts. This is syntactic identity only; no module import, execution, runtime binding guarantee, or behavioral inference was used."
        if len(defs) > 1:
            scope_notes += " target_rebinding=true includes the later duplicate function bindings; there are no additional non-function bindings of this target."
        items.append(dict(id=case['id'], source_sha256=case['source_sha256'], verdict=verdict, extracted_facts=facts, evidence=evidence, reasoning=reasoning, scope_notes=scope_notes))
    review = dict(schema_version=1, reviewer_kind='ai_reviewer', human=False, provider='codex', model='codex:gpt-6.1-sol', reasoning_effort='high', identity_basis='declared_invocation', agent_task='/root/blinded_ai_reviewer_b', packet_sha256=extraction['packet_sha256'], independence_disclosure='Model weights and training independence are unverified.', items=items)
    schema = json.loads((BASE/'review.schema.json').read_text())
    validate(review, schema, schema)
    assert len(items) == 36
    assert len({i['id'] for i in items}) == 36
    assert {i['id'] for i in items} == {c['id'] for c in cases}
    for item in items:
        case = next(c for c in cases if c['id'] == item['id'])
        assert item['source_sha256'] == hashlib.sha256((BASE/case['source_path']).read_bytes()).hexdigest()
        for e in item['evidence']:
            assert e['source_path'] == case['source_path']
            assert 1 <= e['line_start'] <= e['line_end'] <= extraction['modules'][e['source_path']]['line_count']
    (OUT/'review.json').write_text(json.dumps(review, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
    counts = dict(collections.Counter(i['verdict'] for i in items))
    methodology = {
        'reviewer_kind': 'ai_reviewer', 'human': False,
        'provider': 'codex', 'model': 'codex:gpt-6.1-sol', 'reasoning_effort': 'high',
        'identity_basis': 'declared_invocation', 'agent_task': '/root/blinded_ai_reviewer_b',
        'independence_disclosure': 'Model weights and training independence are unverified.',
        'tools': ['functions.exec', 'exec_command (bash, cat, mkdir, python3)', 'apply_patch'],
        'parser': {'name': 'CPython standard-library ast', 'python_version': sys.version, 'ast_dump_include_attributes': False, 'source_decoding': 'tokenize.open using declared Python source encoding'},
        'whole_module_inspection_method': 'Parsed all bytes of every supplied module, then scanned the whole module AST for module-scope definitions, conditional statement blocks, assignment/deletion targets, import bindings and wildcard imports, loop/with targets, exception bindings, match bindings, and evaluated enclosing-scope declaration expressions. Function bodies and methods are not counted as top-level definitions. AST walking also inspected global declarations; none named a case subject. Inspected the resulting full binding inventories and source declaration excerpts, including appended duplicate definitions at file ends. Nested class/function scopes were distinguished from module scope.',
        'signature_extraction_method': 'inspect_packet.py derives signatures solely from function AST nodes, without reading expected_signature. It right-aligns positional defaults, distinguishes positional-only and positional-or-keyword parameters, includes *args, keyword-only parameters and **kwargs, dumps expression ASTs without locations, and records decorators in source order plus return annotations and async status. Extraction was persisted before predicate comparison. Each case was then judged against its own exact predicate.',
        'fact_conventions': {'definition_count': 'All matching functions in module lexical scope, including conditional ones; nested methods/functions excluded.', 'unconditional': 'Whether all observed matching definitions are unconditional; null when there is no matching definition.', 'target_rebinding': 'Includes non-function competing module bindings and later duplicate function definitions.', 'type_parameters_present': 'Observed subject type parameters; null when there is no subject definition.'},
        'packet_verification': {'packet_sha256': extraction['packet_sha256'], 'cases_sha256': extraction['identity']['cases_sha256'], 'source_count': len(extraction['modules']), 'source_hashes_verified': True, 'packet_hash_verified': True, 'encoding': 'SHA256 over canonical UTF-8 JSON of cases_sha256 and unique sorted sources inventory, using sort_keys=True, separators=(comma, colon), ensure_ascii=False, allow_nan=False. cases_sha256 is the SHA256 of exact cases.json bytes.'},
        'validation': 'Standard-library recursive schema-keyword validator checked the supplied review schema, exact 36 unique case IDs, source hashes, and in-bounds evidence ranges. No external validator or repository code was read or invoked.',
        'access_limitations': ['Read only the authorized cases.json, rubric.md, review.schema.json, and source paths named by cases.json, plus self-authored files in this run directory.', 'No network, CAMI implementation, private mapping, original source checkout, mechanical answers, other reviewer answer, imported supplied module, or executed supplied code was used.', 'This is a syntax review; runtime effects and decorator execution are outside the rubric. No original-source authenticity is inferred.', 'The shell command python was unavailable; python3 (CPython 3.12.3) was used. All supplied sources parsed successfully; no decoding, missing-file, unsupported-syntax, or target-type-parameter issue was found.', 'Model weights and training independence are unverified.'],
        'helpers_preserved': ['inspect_packet.py', 'write_review.py'],
        'independent_extraction_artifact': 'independent_extraction.json',
        'case_count': len(items), 'declared_verdict_counts': counts,
    }
    (OUT/'methodology.json').write_text(json.dumps(methodology, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
    # Read back the serialized artifact, so serialization is included in validation.
    validate(json.loads((OUT/'review.json').read_text()), schema, schema)
    print(json.dumps(dict(review_path=str(OUT/'review.json'), methodology_path=str(OUT/'methodology.json'), case_count=len(items), source_count=len(extraction['modules']), verdict_counts=counts, strict_schema_validation='passed', evidence_bounds='passed'), indent=2))

if __name__ == '__main__':
    main()
