import collections
import hashlib
import json
import pathlib
import re

ROOT = pathlib.Path('/root/apps/change-aware-memory-invalidation/examples/ai_review_pilot/packet')
OUT = pathlib.Path('/root/apps/change-aware-memory-invalidation/runs/blinded-ai-reviewer-a-20261104')
schema = json.loads((ROOT / 'review.schema.json').read_text())
review = json.loads((OUT / 'review.json').read_text())
cases = json.loads((ROOT / 'cases.json').read_text())

def validate(value, rule, location='$'):
    if '$ref' in rule:
        resolved = schema
        for part in rule['$ref'].split('/')[1:]:
            resolved = resolved[part]
        validate(value, resolved, location)
    if 'const' in rule:
        assert type(value) is type(rule['const']) and value == rule['const'], (location, 'const')
    if 'enum' in rule:
        assert value in rule['enum'], (location, 'enum')
    if 'type' in rule:
        types = dict(object=dict, array=list, string=str, integer=int, boolean=bool)
        if rule['type'] == 'null':
            assert value is None, (location, 'null')
        else:
            assert type(value) is types[rule['type']], (location, 'type')
    if isinstance(value, str):
        if 'pattern' in rule:
            assert re.search(rule['pattern'], value), (location, 'pattern')
    if type(value) is int and 'minimum' in rule:
        assert value >= rule['minimum'], (location, 'minimum')
    if isinstance(value, dict):
        assert set(rule.get('required', [])) <= set(value), (location, 'required')
        assert len(value) >= rule.get('minProperties', 0), (location, 'minProperties')
        if rule.get('additionalProperties') is False:
            assert set(value) <= set(rule.get('properties', {})), (location, 'additionalProperties')
        for key, subrule in rule.get('properties', {}).items():
            if key in value:
                validate(value[key], subrule, location + '.' + key)
    if isinstance(value, list):
        assert len(value) >= rule.get('minItems', 0), (location, 'minItems')
        for i,item in enumerate(value):
            if 'items' in rule:
                validate(item, rule['items'], location + f'[{i}]')
    if 'oneOf' in rule:
        valid = 0
        for subrule in rule['oneOf']:
            try:
                validate(value, subrule, location)
            except AssertionError:
                pass
            else:
                valid += 1
        assert valid == 1, (location, 'oneOf', valid)
    for subrule in rule.get('allOf', []):
        validate(value, subrule, location)
    if 'if' in rule:
        try:
            validate(value, rule['if'], location)
        except AssertionError:
            if 'else' in rule:
                validate(value, rule['else'], location)
        else:
            if 'then' in rule:
                validate(value, rule['then'], location)

validate(review, schema)
assert len(review['items']) == len(cases) == 36
assert [i['id'] for i in review['items']] == [c['id'] for c in cases]
assert len({i['id'] for i in review['items']}) == 36
for item, case in zip(review['items'], cases, strict=True):
    assert item['source_sha256'] == case['source_sha256']
    data = (ROOT / case['source_path']).read_bytes()
    assert hashlib.sha256(data).hexdigest() == item['source_sha256']
    lines = len(data.decode('utf-8').splitlines())
    for ev in item['evidence']:
        assert ev['source_path'] == case['source_path']
        assert ev['available'] is True
        assert 1 <= ev['line_start'] <= ev['line_end'] <= lines
    facts = item['extracted_facts']
    assert {'definition_count','unconditional','target_rebinding','type_parameters_present'} <= set(facts)
    if case['kind'] == 'signature_equals':
        assert 'actual_signature' in facts
    if item['verdict'] == 'uncertain':
        assert facts['definition_count'] == 3
        assert len(facts['observed_definitions']) == 3
    else:
        assert facts['definition_count'] in (0,1)
methodology = json.loads((OUT / 'methodology.json').read_text())
assert methodology['verdict_counts'] == dict(collections.Counter(i['verdict'] for i in review['items']))
assert all((OUT / name).is_file() for name in methodology['preserved_helpers'])
result = dict(schema_validation='passed (stdlib validator for supplied schema keywords)', case_inventory='36 exact unique IDs', source_hashes='21 verified', evidence_bounds='passed', verdict_counts=methodology['verdict_counts'], review_sha256=hashlib.sha256((OUT/'review.json').read_bytes()).hexdigest())
(OUT / 'validation.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result,indent=2))
