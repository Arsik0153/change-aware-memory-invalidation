"""Offline format screening only: exact generation JSON, zlib level 1, schema 1003."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time
import zlib

PREFIX = 'cami-json-zlib/1:'
MAX_BYTES = 256 * 1024 * 1024


def declared_size(value: str) -> int:
    if not value.startswith(PREFIX):
        raise ValueError('unknown generation encoding')
    length, separator, body = value[len(PREFIX):].partition(':')
    if (not separator or not length.isascii() or not length.isdecimal()
            or len(length) > 9 or length.startswith('0')):
        raise ValueError('invalid generation length')
    size = int(length)
    if not 0 < size <= MAX_BYTES or len(body) > ((size + size // 1000 + 1024) * 4 // 3 + 4):
        raise ValueError('generation exceeds encoding bounds')
    return size


def pack(raw: str) -> str:
    data = raw.encode('utf-8')
    if not 0 < len(data) <= MAX_BYTES:
        raise ValueError('generation exceeds decoded bound')
    return PREFIX + str(len(data)) + ':' + base64.b64encode(zlib.compress(data, level=1)).decode('ascii')


def unpack(value: str) -> str:
    size = declared_size(value)
    body = value.split(':', 2)[2]
    compressed = base64.b64decode(body, validate=True)
    if base64.b64encode(compressed).decode('ascii') != body:
        raise ValueError('noncanonical generation base64')
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, size + 1)
    if (len(raw) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail):
        raise ValueError('generation length or compressed stream differs')
    return raw.decode('utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tables(db):
    return {name: sorted(db.execute(f'SELECT * FROM {name}').fetchall())
            for (name,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def self_test():
    texts = ['{}', '{"path":"α/日本語.py"}', 'x' * 100000]
    for raw in texts:
        assert unpack(pack(raw)) == raw
    value = pack('x' * 100000)
    bad = [value.replace(':100000:', ':1:'), value[:-4], value + 'AAAA',
           value.replace('zlib/1', 'zlib/2'), value.replace(':100000:', ':0100000:'),
           value.replace(':100000:', ':999999999:'), value.replace(':100000:', ':0:'),
           value.replace(':100000:', ':100001:'), value.replace(':100000:', ':99999:'),
           PREFIX + '1:' + base64.b64encode(zlib.compress(b'\xff')).decode(),
           PREFIX + '1:' + base64.b64encode(zlib.compress(b'x') + zlib.compress(b'y')).decode()]
    for encoded in bad:
        try:
            unpack(encoded)
        except (ValueError, zlib.error, UnicodeError):
            pass
        else:
            raise AssertionError('malformed encoded generation accepted')
    print(json.dumps({'status': 'passed', 'roundtrips': len(texts), 'corruptions_rejected': len(bad)}))


def run(protocol_path, out):
    protocol = json.loads(protocol_path.read_text())
    out.mkdir(parents=True, exist_ok=False)
    frozen = {'design': 'generation-json-zlib1-screening-v1',
              'runner_sha256': sha(Path(__file__)), 'input_protocol_sha256': sha(protocol_path),
              'algorithm': 'zlib level1, canonical base64 TEXT, explicit decoded length',
              'maximum_total_decoded_generation_bytes': MAX_BYTES,
              'primary_target': 'at least50% smaller SQLite file in every case; exact reconstruction of every SQL row',
              'scope': 'Offline experimental schema1003 copies only. No production reader/migration, '
                       'no agent or MCP calls, no speed claim. Encoding elapsed time is one descriptive '
                       'observation, including updates and VACUUM. Originals must remain unchanged.'}
    write(out / 'protocol.json', frozen)
    results = []
    for case in protocol['cases']:
        original = Path(case['source']) / 'memory.sqlite3'
        assert sha(original) == case['files']['memory.sqlite3']
        with sqlite3.connect(original.as_uri() + '?mode=ro&immutable=1', uri=True) as db:
            assert db.execute('PRAGMA user_version').fetchone()[0] == 2
            before = tables(db)
            assert db.execute('PRAGMA freelist_count').fetchone()[0] == 0
        target = out / (case['id'] + '.sqlite3')
        shutil.copyfile(original, target)
        start = time.perf_counter()
        with sqlite3.connect(target) as db:
            total = 0
            for generation_id, _, _, raw in before['memory_generation']:
                encoded = pack(raw)
                assert unpack(encoded) == raw
                total += declared_size(encoded)
                db.execute('UPDATE memory_generation SET value=? WHERE id=?', (encoded, generation_id))
            assert total <= MAX_BYTES
            db.execute('PRAGMA user_version=1003')
            db.commit()
            db.execute('VACUUM')
        elapsed = time.perf_counter() - start
        with sqlite3.connect(target.as_uri() + '?mode=ro', uri=True) as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert db.execute('PRAGMA foreign_key_check').fetchone() is None
            after = tables(db)
            after['memory_generation'] = [(*row[:3], unpack(row[3])) for row in after['memory_generation']]
            assert before == after
        assert sha(original) == case['files']['memory.sqlite3']
        result = {'id': case['id'], 'status': 'verified', 'original_sha256': sha(original),
                  'prototype_sha256': sha(target), 'original_bytes': original.stat().st_size,
                  'prototype_bytes': target.stat().st_size, 'decoded_generation_bytes': total,
                  'all_tables_reconstruct_exactly': True, 'encode_and_vacuum_seconds': elapsed,
                  'size_reduction_percent': 100 * (1 - target.stat().st_size / original.stat().st_size)}
        write(out / (case['id'] + '.json'), result)
        results.append(result)
        print(json.dumps(result), flush=True)
    write(out / 'summary.json', {'status': 'verified', 'cases': results, 'scope': frozen['scope'],
          'storage_target_passed': all(r['size_reduction_percent'] >= 50 for r in results)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--protocol', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        run(args.protocol.resolve(), args.out.resolve())
