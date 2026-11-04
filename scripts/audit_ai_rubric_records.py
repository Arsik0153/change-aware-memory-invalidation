"""Check required rubric facts and methodology without altering original AI decisions."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.validate_ai_review import audit_review, load_packet, require


def audit(packet: Path, directory: Path) -> dict:
    format_audit = audit_review(packet, directory/'review.json')
    cases, _, _, _ = load_packet(packet)
    review = json.loads((directory/'review.json').read_bytes())
    method_path = directory/'methodology.json'
    method = json.loads(method_path.read_bytes())
    require(isinstance(method, dict), 'methodology must be an object')
    for field in ('reviewer_kind', 'human', 'provider', 'model', 'reasoning_effort',
                  'agent_task', 'identity_basis', 'independence_disclosure'):
        require(method.get(field) == review[field], f'methodology identity differs: {field}')
    require(isinstance(method.get('tools'), list) and bool(method['tools']), 'tools must be recorded')
    require(isinstance(method.get('parser'), dict) and bool(method['parser']), 'parser must be recorded')
    for field in ('whole_module_inspection_method', 'signature_extraction_method'):
        require(isinstance(method.get(field), str) and bool(method[field].strip()), f'missing method: {field}')
    for item in review['items']:
        facts = item['extracted_facts']
        require(isinstance(facts, dict), 'rubric requires structured extracted facts')
        count = facts.get('definition_count')
        require('definition_count' in facts and (count is None or type(count) is int and count >= 0),
                'definition_count must be nonnegative integer or null')
        for field in ('unconditional', 'target_rebinding', 'type_parameters_present'):
            require(field in facts and (facts[field] is None or type(facts[field]) is bool),
                    f'{field} must be boolean or null')
        if cases[item['id']]['kind'] == 'signature_equals':
            require('actual_signature' in facts, 'missing actual_signature')
            signature = facts['actual_signature']
            require(signature is None or isinstance(signature, dict) and
                    {'parameters', 'returns_ast', 'decorators_ast', 'is_async'} <= set(signature),
                    'actual_signature must include all signature fields or be null')
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    return {'status': 'rubric_structure_verified', 'items': len(review['items']),
            'review_sha256': sha(directory/'review.json'), 'methodology_sha256': sha(method_path),
            'checker_sha256': sha(Path(__file__)), 'format_audit': format_audit,
            'limits': ['Checks presence and types of declared facts/methods, not their truth or actual tool access.',
                       'Post-hoc supplementary audit; original reviews and v1 analysis remain unchanged.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', type=Path, required=True)
    parser.add_argument('--review-dir', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.packet, args.review_dir)
    with args.out.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
