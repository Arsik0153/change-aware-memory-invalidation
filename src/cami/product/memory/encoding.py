"""Schema 3 generation JSON: bounded, exact UTF-8 reconstruction."""
from __future__ import annotations

import base64
from collections.abc import Iterable
import zlib

from cami.errors import IncompleteError
from cami.product.store import MAX_CACHE_BYTES

PREFIX = "cami-json-zlib/1:"


def _header(value: str) -> tuple[int, int]:
    if type(value) is not str or not value.startswith(PREFIX):
        raise IncompleteError("memory_generation_encoding_error: unknown encoding")
    separator = value.find(":", len(PREFIX))
    length = value[len(PREFIX):separator] if separator != -1 else ""
    if (not length.isascii() or not length.isdecimal() or len(length) > 9
            or length.startswith("0")):
        raise IncompleteError("memory_generation_encoding_error: invalid length")
    size = int(length)
    if (not 0 < size <= MAX_CACHE_BYTES
            or len(value) - separator - 1 > (size + size // 1000 + 1024) * 4 // 3 + 4):
        raise IncompleteError("memory_generation_encoding_error: length exceeds bound")
    return size, separator + 1


def check_decoded_budget(values: Iterable[str]) -> None:
    total = 0
    for value in values:
        total += _header(value)[0]
        if total > MAX_CACHE_BYTES:
            raise IncompleteError("memory_database_unavailable: decoded generations exceed size limit")


def encode_generation(raw: str) -> str:
    if type(raw) is not str or len(raw) > MAX_CACHE_BYTES:
        raise IncompleteError("memory_generation_encoding_error: JSON exceeds bound")
    data = raw.encode("utf-8")
    if not 0 < len(data) <= MAX_CACHE_BYTES:
        raise IncompleteError("memory_generation_encoding_error: JSON exceeds bound")
    body = base64.b64encode(zlib.compress(data, level=1)).decode("ascii")
    return PREFIX + str(len(data)) + ":" + body


def decode_generation(value: str) -> str:
    size, start = _header(value)
    try:
        body = value[start:]
        compressed = base64.b64decode(body, validate=True)
        if base64.b64encode(compressed).decode("ascii") != body:
            raise ValueError("noncanonical base64")
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, size + 1)
        if (len(raw) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail):
            raise ValueError("length or compressed stream differs")
        return raw.decode("utf-8")
    except (ValueError, zlib.error) as exc:
        raise IncompleteError("memory_generation_encoding_error: invalid payload") from exc
