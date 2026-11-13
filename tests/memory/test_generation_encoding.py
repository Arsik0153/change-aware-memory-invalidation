import base64
import zlib

import pytest

from cami.errors import IncompleteError
from cami.product.memory.encoding import (
    MAX_CACHE_BYTES, check_decoded_budget, decode_generation, encode_generation,
)


def encoded(data, declared=None, trailing=b''):
    return 'cami-json-zlib/1:' + str(len(data) if declared is None else declared) + ':' + \
        base64.b64encode(zlib.compress(data) + trailing).decode('ascii')


@pytest.mark.parametrize('raw', ['{}', '{"path":"α/日本語.py"}', '{"states":[]}', 'x' * 100000])
def test_generation_json_roundtrip_preserves_exact_bytes(raw):
    value = encode_generation(raw)
    assert decode_generation(value) == raw
    assert zlib.decompress(base64.b64decode(value.split(':', 2)[2])) == raw.encode('utf-8')
    check_decoded_budget([value])


@pytest.mark.parametrize('value', [
    '{}', b'{}', None, 'cami-json-zlib/2:1:eA==', 'cami-json-zlib/1:01:eA==',
    'cami-json-zlib/1:0:eA==', 'cami-json-zlib/1:１:eA==', 'cami-json-zlib/1:1:',
    'cami-json-zlib/1:1:!!', 'cami-json-zlib/1:999999999:eA==',
    encoded(b'x' * 100000, declared=1), encoded(b'x', declared=2),
    encoded(b'\xff'), encoded(b'x', trailing=zlib.compress(b'y')),
    encoded(b'abc')[:-4],
])
def test_invalid_or_oversized_encoded_generation_is_rejected(value):
    with pytest.raises(IncompleteError, match='memory_generation_encoding_error'):
        decode_generation(value)


def test_noncanonical_base64_padding_is_rejected():
    value = encoded(b'xy')
    body = value.split(':', 2)[2]
    alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
    assert body.endswith('==')
    altered = body[:-3] + alphabet[alphabet.index(body[-3]) + 1] + '=='
    assert base64.b64decode(altered, validate=True) == base64.b64decode(body)
    with pytest.raises(IncompleteError, match='invalid payload'):
        decode_generation(value[:-len(body)] + altered)


def test_aggregate_declared_budget_rejects_before_any_expansion():
    # Each declared length is legal alone; together they bypass a per-value-only bound.
    value = encoded(b'x', declared=MAX_CACHE_BYTES // 2 + 1)
    with pytest.raises(IncompleteError, match='decoded generations exceed size limit'):
        check_decoded_budget([value, value])


def test_encoder_bounds_utf8_bytes_not_only_characters(monkeypatch):
    monkeypatch.setattr('cami.product.memory.encoding.MAX_CACHE_BYTES', 8)
    with pytest.raises(IncompleteError, match='JSON exceeds bound'):
        encode_generation('日本語')
