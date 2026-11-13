"""Compare observable validation behavior against the frozen original code."""
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import sys


def worker(source):
    sys.path.insert(0, str(source))
    from cami.models import safe_path

    values = [''.join(chars) for n in range(6)
              for chars in itertools.product(('a', '.', '/', '\\', '\x00', 'α', ' ', ':'), repeat=n)]
    values += [prefix + suffix for prefix in ('a' * 512, 'a' * 513, 'a/' * 300 + 'b')
               for suffix in ('', '/', '/..', '//b', '/./b', '\\x', '\x00')]
    digest = hashlib.sha256()
    accepted = rejected = 0
    for value in values:
        for _ in range(2):
            try:
                result = safe_path(value)
                assert result is value
                outcome = ['ok', result]
                accepted += 1
            except ValueError as error:
                outcome = [type(error).__name__, str(error)]
                rejected += 1
            digest.update(json.dumps(outcome, ensure_ascii=True).encode() + b'\n')
    print(json.dumps({'inputs': len(values), 'calls': len(values) * 2,
                      'accepted': accepted, 'rejected': rejected,
                      'observable_outcomes_sha256': digest.hexdigest()}))


if __name__ == '__main__':
    if sys.argv[1] == '--worker':
        worker(Path(sys.argv[2]).resolve())
    else:
        protocol = json.loads(Path(sys.argv[1]).read_text())
        results = {}
        for side in ('baseline', 'candidate'):
            run = subprocess.run([sys.executable, '-I', '-B', __file__, '--worker', protocol[side]],
                                 capture_output=True, text=True, check=True)
            assert not run.stderr
            results[side] = json.loads(run.stdout)
        assert results['baseline'] == results['candidate']
        result = {'status': 'verified', **results,
                  'scope': 'Exhaustive strings of length 0–5 over eight path-relevant characters, '
                           'plus long-path boundaries; repeated calls preserve exact errors and input identity.'}
        Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))
