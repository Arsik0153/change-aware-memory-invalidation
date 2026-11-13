"""Audit legacy-note payload identity and response states without inferring source-time truth."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo / 'scripts/opencode_benchmark/analysis'))
from aggregate_study import verify_terminal  # noqa: E402


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode()


def analyze(root):
    summary = json.loads((root / 'summary.json').read_bytes())
    if summary['terminal_attempts'] != 80:
        raise ValueError('all80 completed attempts required')
    protocol = json.loads((root / 'protocol.json').read_bytes())
    if {p.name for p in (root / 'trials').iterdir()} != {t['id'] for t in protocol['schedule']}:
        raise ValueError('scheduled terminal coverage differs')
    rows, unavailable = [], []
    for path in sorted((root / 'trials').glob('*/terminal.json')):
        terminal, terminal_sha, _ = verify_terminal(path.parent)
        trial = terminal['trial']
        if trial['arm'] == 'plain' or terminal.get('cache_hit', False):
            continue
        namespace = root / 'namespaces' / f"r{trial['repetition']}-{trial['condition']}"
        trace = path.parent / 'session/evidence/memory-backend-trace.jsonl'
        if not trace.exists():
            unavailable.append({'trial': trial['id'], 'primary_status': terminal['status'],
                                'reason': 'trace_unavailable', 'terminal_sha256': terminal_sha})
            continue
        catalog = json.loads((namespace / 'memory/prepared/catalog.json').read_bytes())
        records = {r['id']: r for r in catalog['records']}
        if len(records) != 75:
            raise ValueError('original75 catalog required')
        catalog_sha = hashlib.sha256(canonical(catalog)).hexdigest()
        events = [json.loads(line) for line in trace.read_text().splitlines()]
        lookups = [e for e in events if e.get('event') == 'memory_lookup']
        counts, fallback = Counter(), Counter()
        for event in lookups:
            if event.get('error') is not None:
                counts['backend_errors'] += 1
                continue
            receipt = event['response_audit']
            full = receipt['full_result']
            value = json.loads(full['content'][0]['text'])
            if (value['catalog_sha256'] != catalog_sha or event['catalog_sha256'] != catalog_sha
                    or value['backend'] != trial['arm']):
                raise ValueError('note catalog/backend binding differs')
            # Metadata below belongs to the full response bound by the receipt.
            # Native-visible marker and receipt joining is checked separately by the controller.
            if hashlib.sha256(canonical(full)).hexdigest() != receipt['receipt_payload']['full_result_sha256']:
                raise ValueError('full note response receipt differs')
            seen = set()
            for entry in value['entries']:
                original = records[entry['id']]
                if entry['id'] in seen or entry['payload'] != original['payload'] or entry['origin_source'] != original['source']:
                    raise ValueError('returned original note payload/source differs')
                if entry['label'] != 'manual_assertion' or entry['availability'] != (
                        'unchecked_current' if trial['arm'] == 'static' else 'manual_assertion_source_unchanged'):
                    raise ValueError('manual note trust label differs')
                seen.add(entry['id'])
            for withheld in value['withheld']:
                if withheld['id'] in seen or withheld['id'] not in records:
                    raise ValueError('withheld note identity differs')
                seen.add(withheld['id'])
                counts['withheld_' + withheld['reason']] += 1
            if len(seen) != value['selected_records'] or len(value['entries']) != event['returned_records'] or len(value['withheld']) != event['withheld_records']:
                raise ValueError('returned/withheld selection counts differ')
            counts['returned'] += len(value['entries'])
            counts['withheld'] += len(value['withheld'])
            fallback[receipt['fallback_reason'] or 'none'] += 1
        rows.append({'trial': trial['id'], 'stage': trial['stage'], 'condition': trial['condition'],
                     'primary_status': terminal['status'], 'terminal_sha256': terminal_sha,
                     'lookups': len(lookups), 'counts': dict(counts), 'fallbacks': dict(fallback)})
    return {'status': 'verified_observed_traces', 'model_sessions_with_trace': len(rows),
            'unavailable': unavailable, 'sessions_without_lookup': [r['trial'] for r in rows if not r['lookups']],
            'rows': rows, 'scope': 'Original75 generic notes, backend trust labels and withheld identities verified against each immutable catalog and full-response receipt. Includes available traces from failed primary attempts without changing their status or primary eligibility. Missing traces are explicit. Counts reflect actual selected queries, which differ between agents. Not an independent reconstruction of filesystem state at each lookup and not a causal speed claim.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('out', type=Path)
    args = parser.parse_args()
    with args.out.open('x') as stream:
        json.dump(analyze(args.run), stream, indent=2, sort_keys=True)
        stream.write('\n')
