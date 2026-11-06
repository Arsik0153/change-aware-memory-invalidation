"""Exact, unfiltered terminal-message replay; no model or task execution."""
from pathlib import Path
import argparse
import importlib.util
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/opencode_benchmark/analysis'))
sys.path.insert(0, str(ROOT / 'scripts/opencode_benchmark/controller'))
from aggregate_study import sha, verify_terminal


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    old_path = Path(__file__).with_name('memory_format_evidence_before.py')
    new_path = ROOT / 'scripts/opencode_benchmark/controller/memory_format_evidence.py'
    old, new = load('old_format', old_path), load('new_format', new_path)
    rows = []
    for version, selected in [('v3', 'full'), ('v4', 'compact'), ('v5', 'compact')]:
        run = ROOT / f'runs/opencode-development-{version}-20261104'
        for path in sorted((run / 'trials').glob('*/terminal.json')):
            terminal, terminal_sha, count = verify_terminal(path.parent)
            arm = terminal['trial']['arm']
            messages_path = path.parent / 'session/evidence/messages.json'
            events_path = path.parent / 'session/evidence/memory-backend-trace.jsonl'
            messages = json.loads(messages_path.read_bytes())
            events = [json.loads(line) for line in events_path.read_text().splitlines()] if arm != 'plain' else []
            before = old.inspect_format(messages, events, arm, selected)
            after = new.inspect_format(messages, events, arm, selected)
            if version == 'v5' and path.parent.name == 'r3-static-s1':
                assert before['status'] == 'unsupported_or_mismatch'
            else:
                assert before['status'] in {'matched', 'not_observed', 'not_applicable'}, before
            assert after['status'] in {'matched', 'not_observed', 'not_applicable'}, after
            rows.append({'version': version, 'trial': path.parent.name, 'terminal_sha256': terminal_sha,
                         'terminal_artifacts_verified': count, 'messages_sha256': sha(messages_path),
                         'events_sha256': sha(events_path) if events_path.is_file() else None,
                         'input_message_count': len(messages), 'input_filtering': False,
                         'before': before, 'after': after,
                         'retrospective_observer_only': True, 'original_terminal_rewritten': False})
    assert len(rows) == 74
    result = {'status': 'passed', 'rows': rows, 'complete_unfiltered_message_arrays': len(rows),
              'before_source_sha256': sha(old_path), 'after_source_sha256': sha(new_path),
              'controller_helpers_sha256': {str(p.relative_to(ROOT)): sha(p) for p in sorted(new_path.parent.glob('*.py')) if not p.name.startswith('test_')},
              'model_calls': 0, 'task_execution': False,
              'limits': ['Replay of format inspection only; original quality/operational/cost outcomes remain unchanged.',
                         'The earlier three-response verification lacked source/input hash bindings and did not establish full-message admission. It is retained, not used as evidence of this boundary.']}
    with args.out.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print('74 exact unfiltered terminal arrays verified; original failures unchanged.')


if __name__ == '__main__':
    main()
